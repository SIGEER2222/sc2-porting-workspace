"""Runnable entrypoint for shared multi-map PPO training.

The simulator backend is the default so a user can start training without a
live SC2 process. The fake backend remains available for dependency smoke and
CI. Both paths use the same ``MultiMapSelfTrainer`` and action grounding.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Callable

try:
    import torch
except ModuleNotFoundError as exc:  # pragma: no cover - dependency gate
    raise RuntimeError("PyTorch is required for multi-map training") from exc

from .action_metrics import summarize_rollout_actions
from .backends import FakeBackend
from .commander_profile import (
    build_commander_profile,
    commander_report_fields,
    validate_commander_profile,
)
from .env import CmreRLEnv
from .map_aware import load_map_aware_checkpoint
from .map_profiles import MapProfileRegistry
from .self_training import MultiMapSelfTrainer, MultiMapTrainingConfig
from .simulator_backend import SimulatorRlBackend


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "artifacts" / "projects" / "cmre-rl-training" / "multi-map-training"
)
DEFAULT_MAPS = ("dead-of-night", "void-launch")


def parse_map_names(raw: str) -> tuple[str, ...]:
    names = tuple(part.strip() for part in str(raw).split(",") if part.strip())
    if not names:
        raise ValueError("--maps must contain at least one map name")
    if len(set(names)) != len(names):
        raise ValueError("--maps must not contain duplicates")
    return names


def resolve_device(raw: str) -> str:
    value = str(raw).strip().lower()
    if value == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if value not in {"cpu", "cuda"}:
        raise ValueError("--device must be cpu, cuda, or auto")
    if value == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but no CUDA device is available")
    return value


def resolve_repo_path(raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def parse_scenario_overrides(raw_values: list[str] | None) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    for raw in raw_values or []:
        if "=" not in raw:
            raise ValueError("--scenario-map values must use MAP=PATH")
        map_name, path = raw.split("=", 1)
        map_name = map_name.strip()
        path = path.strip()
        if not map_name or not path:
            raise ValueError("--scenario-map values must use MAP=PATH")
        if map_name in overrides:
            raise ValueError(f"duplicate_scenario_map:{map_name}")
        overrides[map_name] = resolve_repo_path(path).resolve()
    return overrides


def build_builtin_scenario(
    map_name: str,
    *,
    seed: int,
    max_loops: int,
) -> dict[str, Any]:
    """Build a small but real SimulatorSession scenario for training smoke."""

    profile = MapProfileRegistry().resolve(map_name)
    base_x, base_y = 85.0, 94.0
    if profile.family == "escort":
        base_x, base_y = 75.0, 88.0
    enemy_x, enemy_y = base_x + 14.0, base_y
    return {
        "schema_version": "m7",
        "name": f"cmre-rl-training-{profile.map_id}",
        "map_name": profile.map_id,
        "players": [
            {
                "id": 0,
                "name": "Neutral",
                "race": "neutral",
                "allies": [],
                "is_ai": True,
                "relation": "neutral",
            },
            {
                "id": 1,
                "name": "Terran Ally",
                "race": "terran",
                "allies": [],
                "is_ai": True,
                "relation": "ally",
            },
            {
                "id": 2,
                "name": "Training Enemy",
                "race": "zerg",
                "allies": [],
                "is_ai": True,
                "relation": "enemy",
            },
        ],
        "spawns": [
            {
                "unit_type_id": "CommandCenter",
                "owner_player_id": 1,
                "x": base_x,
                "y": base_y,
            },
            {
                "unit_type_id": "SCV",
                "owner_player_id": 1,
                "x": base_x + 1.0,
                "y": base_y - 1.0,
            },
            {
                "unit_type_id": "Marine",
                "owner_player_id": 1,
                "x": base_x + 2.0,
                "y": base_y - 2.0,
            },
            {
                "unit_type_id": "MineralField",
                "owner_player_id": 0,
                "x": base_x + 3.0,
                "y": base_y - 4.0,
                "resource_amount": 5000,
            },
            {
                "unit_type_id": "Zergling",
                "owner_player_id": 2,
                "x": enemy_x,
                "y": enemy_y,
            },
            {
                "unit_type_id": "Hydralisk",
                "owner_player_id": 2,
                "x": enemy_x + 2.0,
                "y": enemy_y + 1.0,
            },
        ],
        "commands": [],
        "max_loops": int(max_loops),
        "seed": int(seed),
        "strict": True,
        "win_condition": "survival",
    }


def make_env_factories(
    map_names: tuple[str, ...],
    *,
    backend_name: str,
    seed: int,
    max_episode_steps: int,
    scenario_path: Path | None = None,
    scenario_overrides: Mapping[str, Path] | None = None,
    step_loops: int = 1,
    start_minerals: int | None = None,
    start_vespene: int | None = None,
) -> dict[str, Callable[[], Any]]:
    if backend_name == "fake":
        return {
            map_name: (
                lambda map_name=map_name: CmreRLEnv(
                    FakeBackend(max_steps=max_episode_steps),
                    normalize_reward=False,
                )
            )
            for map_name in map_names
        }

    if backend_name != "simulator":
        raise ValueError(f"unsupported_backend:{backend_name}")

    # ``max_episode_steps`` counts RL steps while the scenario's ``max_loops``
    # counts game loops. With step_loops>1 the two units differ, so budget the
    # scenario in loops or the episode gets truncated long before the step
    # limit is reached.
    scenario_max_loops = int(max_episode_steps) * max(1, int(step_loops))

    def factory(map_name: str) -> CmreRLEnv:
        from vibe.simulator_session import SimulatorSession

        session = SimulatorSession()
        selected_path = (scenario_overrides or {}).get(map_name, scenario_path)
        if selected_path is None:
            scenario = build_builtin_scenario(
                map_name,
                seed=seed,
                max_loops=scenario_max_loops,
            )
        else:
            if not selected_path.exists():
                raise FileNotFoundError(f"scenario_not_found:{selected_path}")
            scenario = json.loads(selected_path.read_text(encoding="utf-8-sig"))
            if not isinstance(scenario, dict):
                raise ValueError(f"scenario_must_be_object:{selected_path}")
            if isinstance(scenario.get("scenario"), dict):
                scenario = scenario["scenario"]
            scenario = dict(scenario)
            scenario["seed"] = int(seed)
            scenario["max_loops"] = scenario_max_loops
        session.scenario_load(scenario_dict=scenario, catalog="m7")
        session.scenario_reset()
        if start_minerals is not None or start_vespene is not None:
            session.player_set_resource(
                1, minerals=start_minerals, vespene=start_vespene
            )
        backend = SimulatorRlBackend(
            session, map_name=map_name, step_loops=step_loops
        )
        return CmreRLEnv(backend, normalize_reward=False)

    return {
        map_name: (lambda map_name=map_name: factory(map_name))
        for map_name in map_names
    }


def _finite_training_report(report: dict[str, Any]) -> bool:
    if int(report.get("total_steps", 0)) < 1:
        return False
    for map_result in report.get("maps", {}).values():
        for iteration in map_result.get("iterations", []):
            for value in iteration.get("ppo", {}).values():
                if not math.isfinite(float(value)):
                    return False
    return math.isfinite(float(report.get("total_mean_reward", 0.0)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run shared map-conditioned PPO self-training",
    )
    parser.add_argument(
        "--backend",
        choices=("simulator", "fake"),
        default="simulator",
        help="Training backend; simulator is the default real SimulatorSession path",
    )
    parser.add_argument(
        "--maps",
        default=",".join(DEFAULT_MAPS),
        help="Comma-separated map names, for example dead-of-night,void-launch",
    )
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--rollout-steps", type=int, default=64)
    parser.add_argument("--max-episode-steps", type=int, default=64)
    parser.add_argument("--hidden-dim", type=int, default=128)
    parser.add_argument("--ppo-epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument(
        "--ent-coef",
        type=float,
        default=0.01,
        help="Entropy bonus weight. Raise (e.g. 0.05) to keep exploration "
             "alive and avoid premature mode collapse onto a suboptimal action.",
    )
    parser.add_argument(
        "--ent-floor",
        type=float,
        default=0.0,
        help="Minimum per-decision entropy the policy is pushed to keep "
             "(anti-collapse pressure). 0 disables; ~0.5 prevents locking a "
             "single action before army-building is discovered.",
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="auto", help="cpu, cuda, or auto")
    parser.add_argument("--commander", default="TerranRaynor", help="Commander used for ML evidence")
    parser.add_argument("--commander-level", type=int, default=15,
                        help="Declared commander level (default: max level 15)")
    parser.add_argument("--commander-mastery", default="full",
                        help="Declared mastery allocation (default: full)")
    parser.add_argument("--commander-evidence", default=None,
                        help="Path to bank/JSON evidence proving in-game commander level/mastery")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for training-report.json and map-aware-policy.pt",
    )
    parser.add_argument(
        "--checkpoint",
        default=None,
        help="Optional output checkpoint path; defaults to <output-dir>/map-aware-policy.pt",
    )
    parser.add_argument(
        "--resume",
        default=None,
        help="Existing map-aware checkpoint to load before continuing PPO",
    )
    parser.add_argument(
        "--bc-checkpoint",
        default=None,
        help="Optional existing BC checkpoint used to warm-start the shared trunk",
    )
    parser.add_argument(
        "--scenario",
        default=None,
        help="Optional simulator scenario JSON reused for every selected map",
    )
    parser.add_argument(
        "--scenario-map",
        action="append",
        default=[],
        metavar="MAP=PATH",
        help="Optional per-map simulator scenario override; repeatable",
    )
    parser.add_argument(
        "--step-loops",
        type=int,
        default=1,
        help=(
            "Game loops advanced per RL step (control interval). The economy "
            "state machine needs ~60 loops per worker mining trip, so the "
            "legacy value of 1 makes any economy-driven reward unreachable. "
            "Use 8-32 for scenarios where production matters."
        ),
    )
    parser.add_argument(
        "--start-minerals",
        type=int,
        default=None,
        help="Override player 1 starting minerals after scenario reset",
    )
    parser.add_argument(
        "--start-vespene",
        type=int,
        default=None,
        help="Override player 1 starting vespene after scenario reset",
    )
    return parser


def run_training(args: argparse.Namespace) -> dict[str, Any]:
    map_names = parse_map_names(args.maps)
    if args.iterations < 1:
        raise ValueError("--iterations must be >= 1")
    if args.rollout_steps < 1:
        raise ValueError("--rollout-steps must be >= 1")
    if args.max_episode_steps < args.rollout_steps:
        raise ValueError("--max-episode-steps must be >= --rollout-steps")
    device = resolve_device(args.device)
    output_dir = resolve_repo_path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = (
        resolve_repo_path(args.checkpoint).resolve()
        if args.checkpoint
        else output_dir / "map-aware-policy.pt"
    )
    report_path = output_dir / "training-report.json"

    # Validate the commander before constructing environments or collecting a
    # single rollout. A low-level profile must never consume training steps and
    # then get laundered into a successful simulator report.
    commander_profile = build_commander_profile(
        args.commander,
        level=args.commander_level,
        mastery=args.commander_mastery,
        evidence_path=args.commander_evidence,
    )
    commander_validation = validate_commander_profile(commander_profile)
    commander_fields = commander_report_fields(commander_profile, commander_validation)
    if not commander_validation["passed"]:
        blocked_report = {
            "schema": "cmre-multi-map-training.v1",
            "status": "blocked",
            "evidence_class": "static-config",
            "backend": args.backend,
            "map_order": list(map_names),
            "total_steps": 0,
            "commander": commander_fields,
            "config": {
                "commander": args.commander,
                "commander_level": args.commander_level,
                "commander_mastery": args.commander_mastery,
                "commander_evidence": args.commander_evidence,
            },
            "blocked_reason": "commander_max_level_gate_failed",
            "report_path": str(report_path),
        }
        report_path.write_text(
            json.dumps(blocked_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise RuntimeError(
            "commander_max_level_gate_failed: "
            + "; ".join(commander_validation["reasons"])
        )

    if args.resume and args.bc_checkpoint:
        raise ValueError("--resume and --bc-checkpoint cannot be combined")
    scenario_path = resolve_repo_path(args.scenario).resolve() if args.scenario else None
    scenario_overrides = parse_scenario_overrides(args.scenario_map)
    unknown_overrides = sorted(set(scenario_overrides) - set(map_names))
    if unknown_overrides:
        raise ValueError(f"scenario_map_not_selected:{','.join(unknown_overrides)}")
    if (scenario_path or scenario_overrides) and args.backend != "simulator":
        raise ValueError("--scenario/--scenario-map require --backend simulator")
    policy = (
        load_map_aware_checkpoint(resolve_repo_path(args.resume), device=device)
        if args.resume
        else None
    )
    step_loops = int(getattr(args, "step_loops", 1))
    if step_loops < 1:
        raise ValueError("--step-loops must be >= 1")
    start_minerals = getattr(args, "start_minerals", None)
    start_vespene = getattr(args, "start_vespene", None)
    factories = make_env_factories(
        map_names,
        backend_name=args.backend,
        seed=args.seed,
        max_episode_steps=args.max_episode_steps,
        scenario_path=scenario_path,
        scenario_overrides=scenario_overrides,
        step_loops=step_loops,
        start_minerals=start_minerals,
        start_vespene=start_vespene,
    )
    config = MultiMapTrainingConfig(
        map_names=map_names,
        iterations=args.iterations,
        rollout_steps=args.rollout_steps,
        hidden_dim=args.hidden_dim,
        seed=args.seed,
        learning_rate=args.learning_rate,
        ppo_epochs=args.ppo_epochs,
        batch_size=args.batch_size,
        ent_coef=getattr(args, "ent_coef", 0.01),
        ent_floor=getattr(args, "ent_floor", 0.0),
        device=device,
        checkpoint_path=checkpoint_path,
        bc_checkpoint_path=(
            resolve_repo_path(args.bc_checkpoint)
            if args.bc_checkpoint
            else None
        ),
    )
    trainer = MultiMapSelfTrainer(
        factories,
        config=config,
        policy=policy,
    )
    report = trainer.train()
    report.update({
        "backend": args.backend,
        "device": device,
        "commander": commander_fields,
        "config": {
            "iterations": args.iterations,
            "rollout_steps": args.rollout_steps,
            "max_episode_steps": args.max_episode_steps,
            "hidden_dim": args.hidden_dim,
            "ppo_epochs": args.ppo_epochs,
            "batch_size": args.batch_size,
            "learning_rate": args.learning_rate,
            "ent_coef": getattr(args, "ent_coef", 0.01),
            "ent_floor": getattr(args, "ent_floor", 0.0),
            "seed": args.seed,
            "step_loops": step_loops,
            "start_minerals": start_minerals,
            "start_vespene": start_vespene,
            "resumed_from": str(resolve_repo_path(args.resume).resolve()) if args.resume else None,
            "bc_checkpoint": str(resolve_repo_path(args.bc_checkpoint).resolve()) if args.bc_checkpoint else None,
            "scenario": str(scenario_path) if scenario_path else None,
            "scenario_map": {key: str(value) for key, value in scenario_overrides.items()},
        },
    })
    report["status"] = "passed" if _finite_training_report(report) else "failed"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["status"] != "passed":
        raise RuntimeError(f"training_report_failed:{report_path}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = run_training(args)
    except Exception as exc:  # CLI boundary must return a truthful non-zero status.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("Training completed")
    print(f"  backend: {report['backend']}")
    print(f"  maps: {', '.join(report['map_order'])}")
    print(f"  total steps: {report['total_steps']}")
    print(f"  checkpoint: {report['checkpoint_path']}")
    print(f"  report: {report['report_path']}")
    return 0


__all__ = [
    "DEFAULT_MAPS",
    "build_builtin_scenario",
    "build_parser",
    "main",
    "make_env_factories",
    "parse_map_names",
    "parse_scenario_overrides",
    "resolve_device",
    "resolve_repo_path",
    "run_training",
]
