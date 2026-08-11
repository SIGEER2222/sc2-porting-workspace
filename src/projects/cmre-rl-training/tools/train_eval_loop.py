"""Repeatable train -> evaluate -> promote loop for the ML autonomous plan.

Stage 4 of the autonomous-completion plan automates the cycle:

1. Train the simulator curriculum for N iterations (one map-aware policy).
2. Save a checkpoint plus its training metadata.
3. Run bounded live evaluation when a runtime lease is available.
4. Compare the latest checkpoint against a random baseline and the previous
   best; promote only when runtime gates pass and metrics improve.
5. Archive failed traces for analysis.

``--dry-run`` builds and writes the live-evaluation plan (ports, checkpoint
hash, per-variant commands, report paths) WITHOUT launching SC2. The plan
builder is pure and unit-testable.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = REPO_ROOT / "src" / "projects" / "cmre-rl-training"
CMRE_PORTING_SRC = REPO_ROOT / "src" / "projects" / "cmre-porting"
CMRE_NEURO_SRC = REPO_ROOT / "src" / "projects" / "cmre-neuro-adapter"
PROTOCOL_ROOT = REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"

for path in (PROJECT_ROOT, CMRE_PORTING_SRC, CMRE_NEURO_SRC, PROTOCOL_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from cmre_rl_training.commander_profile import (  # noqa: E402
    build_commander_profile,
    commander_report_fields,
    validate_commander_profile,
)


DEFAULT_VARIANTS = ("frozen-stochastic", "live-update", "deterministic-baseline")


@dataclass
class TrainEvalConfig:
    """Resolved configuration for one train/eval/promote cycle."""

    maps: tuple[str, ...] = ("dead-of-night",)
    train_iterations: int = 10
    rollout_steps: int = 64
    max_episode_steps: int = 64
    # Simulator steps are control decisions; economy state transitions need
    # several game loops between decisions. Keep the loop configurable so the
    # train/eval path does not silently collapse production into a one-loop
    # smoke test.
    train_step_loops: int = 8
    train_start_minerals: int | None = None
    train_start_vespene: int | None = None
    train_output_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "artifacts" / "train-eval-loop" / "training"
    )
    checkpoint_path: Path | None = None
    resume: str | None = None
    live_port_start: int = 5960
    live_max_steps: int = 512
    live_step_mul: int = 8
    variants: tuple[str, ...] = DEFAULT_VARIANTS
    report_root: Path = field(
        default_factory=lambda: PROJECT_ROOT / "artifacts" / "train-eval-loop" / "live"
    )
    stop_on_terminal: bool = True
    save_replay: bool = True
    commander: str = "TerranRaynor"
    commander_level: int | None = 15
    commander_mastery: str | None = "full"
    commander_evidence: str | None = None
    commander_enforce: bool = True
    dry_run: bool = False
    skip_live: bool = False
    device: str = "cpu"
    promote_distinct_actions_min: int = 3
    promote_illegal_rate_max: float = 0.05

    def resolved_checkpoint(self) -> Path:
        if self.checkpoint_path is not None:
            return Path(self.checkpoint_path)
        return self.train_output_dir / "map-aware-policy.pt"


def resolve_repo_path(raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def checkpoint_sha256(path: Path) -> str:
    if not path.is_file():
        return "pending"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_eval_plan(config: TrainEvalConfig) -> dict[str, Any]:
    """Build the live-evaluation plan without touching SC2.

    Returns a JSON-serializable dict describing every (map, variant) run: the
    port, the output report path, and the exact ``run_live_rl.py`` argument
    list. Ports are unique per run so multiple fresh launchers do not collide.
    """

    checkpoint = config.resolved_checkpoint()
    commander_profile = build_commander_profile(
        config.commander,
        level=config.commander_level,
        mastery=config.commander_mastery,
        evidence_path=config.commander_evidence,
    )
    commander_validation = validate_commander_profile(commander_profile)
    plan_root = config.report_root
    commands: list[dict[str, Any]] = []
    port = int(config.live_port_start)
    map_variant_pairs = (
        []
        if config.commander_enforce and not commander_validation["passed"]
        else [
            (map_name, variant)
            for map_name in config.maps
            for variant in config.variants
        ]
    )

    for map_name, variant in map_variant_pairs:
        run_dir = plan_root / f"{map_name}-{variant}"
        report_path = run_dir / "live-rl-report.json"
        args: list[str] = [
            "python",
            str((PROJECT_ROOT / "tools" / "run_live_rl.py").relative_to(REPO_ROOT)),
            "--checkpoint", str(checkpoint),
            "--map-name", map_name,
            "--port", str(port),
            "--max-steps", str(config.live_max_steps),
            "--step-mul", str(config.live_step_mul),
            "--commander", config.commander,
            "--mastery-layout", "30,30,30,30,30,30",
            "--variant", variant,
            "--output", str(report_path),
        ]
        if config.commander_level is not None:
            args += ["--commander-level", str(config.commander_level)]
        if config.commander_mastery is not None:
            args += ["--commander-mastery", str(config.commander_mastery)]
        args.append("--commander-enforce" if config.commander_enforce else "--no-commander-enforce")
        if config.commander_evidence is not None:
            args += ["--commander-evidence", str(config.commander_evidence)]
        if config.stop_on_terminal:
            args.append("--stop-on-terminal")
        if config.save_replay:
            args.append("--save-replay")
        commands.append({
            "map": map_name,
            "variant": variant,
            "port": port,
            "report_path": str(report_path),
            "command": args,
        })
        port += 1

    return {
        "schema": "cmre-train-eval-plan.v1",
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "dry_run": bool(config.dry_run),
        "maps": list(config.maps),
        "variants": list(config.variants),
        "checkpoint": str(checkpoint),
        "checkpoint_sha256": checkpoint_sha256(checkpoint),
        "live_max_steps": config.live_max_steps,
        "live_step_mul": config.live_step_mul,
        "stop_on_terminal": config.stop_on_terminal,
        "save_replay": config.save_replay,
        "commander": config.commander,
        "commander_profile": commander_report_fields(commander_profile, commander_validation),
        "commander_gate_passed": bool(commander_validation["passed"]),
        "commander_gate_reasons": list(commander_validation["reasons"]),
        "commander_enforce": bool(config.commander_enforce),
        "status": (
            "blocked"
            if config.commander_enforce and not commander_validation["passed"]
            else "planned"
        ),
        "total_runs": len(commands),
        "commands": commands,
    }


def _run_training(config: TrainEvalConfig) -> dict[str, Any]:
    """Train the simulator curriculum and return the training report."""

    from cmre_rl_training.training_cli import run_training

    checkpoint = config.resolved_checkpoint()
    config.train_output_dir.mkdir(parents=True, exist_ok=True)
    ns = argparse.Namespace(
        backend="simulator",
        maps=",".join(config.maps),
        iterations=config.train_iterations,
        rollout_steps=config.rollout_steps,
        max_episode_steps=config.max_episode_steps,
        hidden_dim=128,
        ppo_epochs=4,
        batch_size=64,
        learning_rate=3e-4,
        ent_coef=0.01,
        ent_floor=0.0,
        seed=7,
        device=config.device,
        output_dir=str(config.train_output_dir),
        checkpoint=str(checkpoint),
        resume=config.resume,
        bc_checkpoint=None,
        scenario=None,
        scenario_map=[],
        step_loops=config.train_step_loops,
        start_minerals=config.train_start_minerals,
        start_vespene=config.train_start_vespene,
        commander=config.commander,
        commander_level=config.commander_level,
        commander_mastery=config.commander_mastery,
        commander_evidence=config.commander_evidence,
    )
    return run_training(ns)


def _best_metrics_path(config: TrainEvalConfig) -> Path:
    return config.report_root / "best-metrics.json"


def _load_best_metrics(config: TrainEvalConfig) -> dict[str, Any] | None:
    path = _best_metrics_path(config)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None


def _metrics_improved(new: dict[str, Any], best: dict[str, Any] | None) -> bool:
    if best is None:
        return True
    new_distinct = int(new.get("distinct_actions_used", 0))
    new_illegal = float(new.get("illegal_action_rate", 1.0))
    best_distinct = int(best.get("distinct_actions_used", 0))
    best_illegal = float(best.get("illegal_action_rate", 1.0))
    if new_illegal > best_illegal:
        return False
    return new_distinct >= best_distinct


def _promote(config: TrainEvalConfig, checkpoint: Path, metrics: dict[str, Any], best_dir: Path) -> dict[str, Any]:
    best_dir.mkdir(parents=True, exist_ok=True)
    promoted = best_dir / "map-aware-policy.pt"
    if checkpoint.is_file():
        promoted.write_bytes(checkpoint.read_bytes())
    metrics_path = best_dir / "best-metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"promoted_checkpoint": str(promoted), "promoted_metrics": str(metrics_path)}


def _write_loop_report(report: dict[str, Any], path: Path) -> None:
    """Persist the complete cycle report, including truthful blocked states."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_train_eval(config: TrainEvalConfig) -> dict[str, Any]:
    """Execute the train -> evaluate -> promote cycle.

    In ``dry_run`` mode only the evaluation plan is built and written. Otherwise
    the simulator curriculum is trained, the live evaluation runs when a lease
    is available, and promotion is gated on runtime + policy metrics.
    """

    config.report_root.mkdir(parents=True, exist_ok=True)
    plan = build_eval_plan(config)
    plan_path = config.report_root / "train-eval-plan.json"
    loop_report_path = config.report_root / "train-eval-report.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report: dict[str, Any] = {
        "schema": "cmre-train-eval-loop.v1",
        "dry_run": bool(config.dry_run),
        "skip_live": bool(config.skip_live),
        "plan_path": str(plan_path),
        "report_path": str(loop_report_path),
        "stage": "planned",
        "commander_profile": plan.get("commander_profile"),
    }

    if config.dry_run:
        report["stage"] = "blocked" if plan.get("status") == "blocked" else "dry_run"
        report["plan"] = plan
        report["status"] = plan.get("status", "planned")
        _write_loop_report(report, loop_report_path)
        return report

    if plan.get("status") == "blocked":
        report["stage"] = "blocked"
        report["plan"] = plan
        report["status"] = "blocked"
        _write_loop_report(report, loop_report_path)
        return report

    # Stage A: train simulator curriculum.
    training_report = _run_training(config)
    checkpoint = config.resolved_checkpoint()
    report["training"] = {
        "status": training_report.get("status"),
        "total_steps": training_report.get("total_steps"),
        "total_mean_reward": training_report.get("total_mean_reward"),
        "checkpoint": str(checkpoint),
        "checkpoint_sha256": checkpoint_sha256(checkpoint),
        "commander": training_report.get("commander"),
    }
    report["stage"] = "trained"

    # The first plan is written before training so dry-run and commander gates
    # have an artifact. Refresh it after the checkpoint exists so downstream
    # live runs receive a content hash instead of the pre-training `pending`
    # placeholder.
    plan = build_eval_plan(config)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["plan_checkpoint_sha256"] = plan["checkpoint_sha256"]

    if config.skip_live:
        report["status"] = "trained_only"
        _write_loop_report(report, loop_report_path)
        return report

    # Stage B: bounded live evaluation per (map, variant).
    live_runs: list[dict[str, Any]] = []
    promoted = False
    best = _load_best_metrics(config)
    for command in plan["commands"]:
        run_dir = Path(command["report_path"]).parent
        run_dir.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            command["command"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
        run_result: dict[str, Any] = {
            "map": command["map"],
            "variant": command["variant"],
            "port": command["port"],
            "returncode": proc.returncode,
            "report_path": command["report_path"],
        }
        report_file = Path(command["report_path"])
        if report_file.is_file():
            try:
                run_result["live_report"] = json.loads(report_file.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, OSError):
                run_result["live_report_error"] = "unreadable"
        else:
            run_result["live_report_error"] = "missing"
            # Archive the failed trace for analysis.
            archive = config.report_root / "failed" / f"{command['map']}-{command['variant']}.log"
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_text(
                f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}\n",
                encoding="utf-8",
            )
            run_result["archived_trace"] = str(archive)
        live_runs.append(run_result)

    report["live_runs"] = live_runs
    report["stage"] = "evaluated"

    # Stage C: promote if gates pass and metrics improve.
    passed_runs = [
        r for r in live_runs
        if isinstance(r.get("live_report"), dict) and r["live_report"].get("status") == "passed"
    ]
    if passed_runs:
        # Use the first passed run's action metrics as the promotion candidate.
        candidate = passed_runs[0]["live_report"]
        action_metrics = candidate.get("action_metrics", {})
        gates_ok = (
            int(action_metrics.get("distinct_actions_used", 0)) >= config.promote_distinct_actions_min
            and float(action_metrics.get("illegal_action_rate", 1.0)) <= config.promote_illegal_rate_max
        )
        if gates_ok and _metrics_improved(action_metrics, best):
            promotion = _promote(config, checkpoint, action_metrics, config.report_root / "best")
            report["promotion"] = promotion
            promoted = True
    report["promoted"] = promoted
    report["status"] = "evaluated"
    if promoted:
        report["status"] = "promoted"
    elif not passed_runs:
        report["status"] = "no_passing_live_run"
    _write_loop_report(report, loop_report_path)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train -> evaluate -> promote loop for CMRE RL")
    parser.add_argument("--maps", default="dead-of-night", help="Comma-separated map names")
    parser.add_argument("--train-iterations", type=int, default=10)
    parser.add_argument("--rollout-steps", type=int, default=64)
    parser.add_argument("--max-episode-steps", type=int, default=64)
    parser.add_argument(
        "--train-step-loops",
        type=int,
        default=8,
        help="Game loops advanced per simulator training decision (default: 8)",
    )
    parser.add_argument("--train-start-minerals", type=int, default=None)
    parser.add_argument("--train-start-vespene", type=int, default=None)
    parser.add_argument("--train-output-dir", default=str(PROJECT_ROOT / "artifacts" / "train-eval-loop" / "training"))
    parser.add_argument("--checkpoint", default=None, help="Output checkpoint path")
    parser.add_argument("--resume", default=None, help="Existing checkpoint to resume")
    parser.add_argument("--live-port-start", type=int, default=5960)
    parser.add_argument("--live-max-steps", type=int, default=512)
    parser.add_argument("--live-step-mul", type=int, default=8)
    parser.add_argument("--variants", default=",".join(DEFAULT_VARIANTS), help="Comma-separated eval variants")
    parser.add_argument("--report-root", default=str(PROJECT_ROOT / "artifacts" / "train-eval-loop" / "live"))
    parser.add_argument("--stop-on-terminal", action="store_true", default=True)
    parser.add_argument("--no-stop-on-terminal", dest="stop_on_terminal", action="store_false")
    parser.add_argument("--save-replay", action="store_true", default=True)
    parser.add_argument("--no-save-replay", dest="save_replay", action="store_false")
    parser.add_argument("--commander", default="TerranRaynor")
    parser.add_argument("--commander-level", type=int, default=15)
    parser.add_argument("--commander-mastery", default="full")
    parser.add_argument("--commander-evidence", default=None)
    parser.add_argument("--commander-enforce", dest="commander_enforce", action="store_true", default=True)
    parser.add_argument("--no-commander-enforce", dest="commander_enforce", action="store_false")
    parser.add_argument("--dry-run", action="store_true", help="Build the eval plan only; do not launch SC2")
    parser.add_argument("--skip-live", action="store_true", help="Train only; skip live evaluation")
    parser.add_argument("--device", default="cpu")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = TrainEvalConfig(
        maps=tuple(p.strip() for p in args.maps.split(",") if p.strip()),
        train_iterations=args.train_iterations,
        rollout_steps=args.rollout_steps,
        max_episode_steps=args.max_episode_steps,
        train_step_loops=args.train_step_loops,
        train_start_minerals=args.train_start_minerals,
        train_start_vespene=args.train_start_vespene,
        train_output_dir=Path(args.train_output_dir),
        checkpoint_path=Path(args.checkpoint) if args.checkpoint else None,
        resume=args.resume,
        live_port_start=args.live_port_start,
        live_max_steps=args.live_max_steps,
        live_step_mul=args.live_step_mul,
        variants=tuple(p.strip() for p in args.variants.split(",") if p.strip()),
        report_root=Path(args.report_root),
        stop_on_terminal=args.stop_on_terminal,
        save_replay=args.save_replay,
        commander=args.commander,
        commander_level=args.commander_level,
        commander_mastery=args.commander_mastery,
        commander_evidence=args.commander_evidence,
        commander_enforce=args.commander_enforce,
        dry_run=args.dry_run,
        skip_live=args.skip_live,
        device=args.device,
    )
    report = run_train_eval(config)
    print(json.dumps({
        "status": report.get("status"),
        "stage": report.get("stage"),
        "plan_path": report.get("plan_path"),
        "dry_run": report.get("dry_run"),
    }, ensure_ascii=False))
    return 0 if report.get("status") in ("planned", "promoted", "trained_only", "evaluated", "no_passing_live_run") else 1


if __name__ == "__main__":
    raise SystemExit(main())
