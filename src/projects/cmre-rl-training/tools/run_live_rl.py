"""Run a bounded map-aware PPO rollout against real SC2.

This entrypoint owns only orchestration. SC2 is always started through the
registered launcher; the live session and RL environment stay reusable from
tests and other runners.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
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

import numpy as np  # noqa: E402
import torch  # noqa: E402

from cmre_rl_training.action_grounding import ActionGrounder  # noqa: E402
from cmre_rl_training.env import CmreRLEnv  # noqa: E402
from cmre_rl_training.live_sc2_session import LiveRawSc2Session  # noqa: E402
from cmre_rl_training.map_aware import (  # noqa: E402
    MapAwareEnv,
    load_map_aware_checkpoint,
    save_map_aware_checkpoint,
)
from cmre_rl_training.map_profiles import MapProfileRegistry  # noqa: E402
from cmre_rl_training.ppo import PPOTrainer  # noqa: E402
from cmre_rl_training.raw_sc2_backend import RawSc2Backend  # noqa: E402
from cmre_rl_training.rollout import collect_rollout  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run map-aware PPO on real SC2 through the approved launcher")
    parser.add_argument("--map-name", default="dead-of-night")
    parser.add_argument("--launcher-map-name", default="亡者之夜.SC2Map")
    parser.add_argument(
        "--map-path",
        default="artifacts/live-maps/亡者之夜_live_packed.SC2Map",
        help="Packed .SC2Map passed to CreateGame",
    )
    parser.add_argument(
        "--checkpoint",
        default="artifacts/projects/cmre-rl-training/multi-map-training/map-aware-policy.pt",
        help="Map-aware checkpoint produced by train_multi_map.py",
    )
    parser.add_argument("--port", type=int, default=5952)
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--step-mul", type=int, default=8)
    parser.add_argument("--commander", default="TerranRaynor")
    parser.add_argument("--launcher-suffix", default="rl-bridge")
    parser.add_argument("--output", default=None, help="Runtime report path")
    parser.add_argument("--protocol-root", default=str(PROTOCOL_ROOT))
    parser.add_argument("--skip-launch", action="store_true", help="Use an already running API")
    parser.add_argument("--deterministic", action="store_true")
    parser.add_argument("--train", action="store_true", help="Apply one PPO update to the live rollout")
    parser.add_argument("--ppo-epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=8)
    return parser


def resolve_repo_path(raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def wait_for_api(
    port: int,
    *,
    timeout_seconds: float = 180.0,
    launcher_process: subprocess.Popen[bytes] | None = None,
) -> bool:
    """Wait for a listening API socket without a blind startup sleep."""

    deadline = time.monotonic() + float(timeout_seconds)
    while time.monotonic() < deadline:
        if launcher_process is not None and launcher_process.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=2.0):
                return True
        except OSError:
            time.sleep(1.0)
    return False


def launch_approved_launcher(args: argparse.Namespace, output_dir: Path) -> tuple[subprocess.Popen[bytes], Any]:
    launcher = REPO_ROOT / "tools" / "launchers" / "launch-cmre-alenger.ps1"
    launcher_log = output_dir / "launcher.log"
    launcher_err = output_dir / "launcher.err.log"
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(launcher),
        "-MapName",
        args.launcher_map_name,
        "-Commander",
        args.commander,
        "-ListenPort",
        str(args.port),
        "-ApiMinimal",
        "-KeepAlive",
        "-MapCopySuffix",
        args.launcher_suffix,
    ]
    stdout = launcher_log.open("wb")
    stderr = launcher_err.open("wb")
    process = subprocess.Popen(command, cwd=REPO_ROOT, stdout=stdout, stderr=stderr)
    return process, (stdout, stderr)


def stop_launcher(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except OSError:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def script_error_verdict(start_epoch: float) -> dict[str, Any]:
    logs_dir = Path.home() / "Documents" / "StarCraft II" / "GameLogs"
    if not logs_dir.is_dir():
        return {"checked": False, "has_new_errors": False, "reason": "GameLogs directory not found"}
    errors: list[dict[str, Any]] = []
    for path in logs_dir.glob("*ScriptError*.txt"):
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime >= start_epoch:
            errors.append({"file": path.name, "size": stat.st_size, "mtime": stat.st_mtime})
    return {
        "checked": True,
        "has_new_errors": bool(errors),
        "count": len(errors),
        "errors": errors,
        "window_start_epoch": start_epoch,
    }


def default_output_path(map_name: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return PROJECT_ROOT / "artifacts" / "stage-09-live-rl-bridge" / f"{stamp}-{map_name}" / "live-rl-report.json"


def run_live(args: argparse.Namespace) -> dict[str, Any]:
    if args.max_steps < 1:
        raise ValueError("--max-steps must be >= 1")
    if args.step_mul < 1:
        raise ValueError("--step-mul must be >= 1")
    if args.ppo_epochs < 1 or args.batch_size < 1:
        raise ValueError("--ppo-epochs and --batch-size must be >= 1")

    report_path = resolve_repo_path(args.output) if args.output else default_output_path(args.map_name)
    report_path = report_path.resolve()
    output_dir = report_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = resolve_repo_path(args.checkpoint).resolve()
    map_path = resolve_repo_path(args.map_path).resolve()
    start_epoch = time.time()
    launcher_process: subprocess.Popen[bytes] | None = None
    launcher_handles: Any = None
    session: LiveRawSc2Session | None = None
    base_env: CmreRLEnv | None = None
    report: dict[str, Any] = {
        "schema": "cmre-live-rl-bridge.v1",
        "status": "failed",
        "evidence_class": "runtime",
        "map_name": args.map_name,
        "map_path": str(map_path.relative_to(REPO_ROOT) if map_path.is_relative_to(REPO_ROOT) else map_path.name),
        "checkpoint": str(checkpoint_path.relative_to(REPO_ROOT) if checkpoint_path.is_relative_to(REPO_ROOT) else checkpoint_path.name),
        "config": {
            "port": args.port,
            "max_steps": args.max_steps,
            "step_mul": args.step_mul,
            "deterministic": bool(args.deterministic),
            "train": bool(args.train),
        },
        "launcher_started": False,
        "api_ready": False,
        "create_game": False,
        "join_game": False,
        "frame_advancement": False,
        "action_results_observed": False,
        "training_update_applied": False,
        "reward_basis": "observation-derived runtime proxy; no mission terminal claim",
        "report_path": str(report_path.relative_to(REPO_ROOT) if report_path.is_relative_to(REPO_ROOT) else report_path),
    }

    try:
        if not checkpoint_path.is_file():
            raise FileNotFoundError(f"map_aware_checkpoint_not_found:{checkpoint_path}")
        if not map_path.is_file():
            raise FileNotFoundError(f"packed_map_not_found:{map_path}")

        if not args.skip_launch:
            try:
                with socket.create_connection(("127.0.0.1", int(args.port)), timeout=1.0):
                    raise RuntimeError(f"sc2_api_port_already_in_use:{args.port}")
            except OSError:
                pass
            launcher_process, launcher_handles = launch_approved_launcher(args, output_dir)
            report["launcher_started"] = True
            report["launcher_pid"] = launcher_process.pid
        report["api_ready"] = wait_for_api(args.port, launcher_process=launcher_process)
        if not report["api_ready"]:
            if launcher_process is not None and launcher_process.poll() is not None:
                report["launcher_exit_code"] = launcher_process.returncode
                raise RuntimeError(f"approved_launcher_exited:{launcher_process.returncode}")
            raise RuntimeError(f"sc2_api_not_ready:{args.port}")

        session = LiveRawSc2Session(
            map_path,
            port=args.port,
            protocol_root=resolve_repo_path(args.protocol_root),
            progress_loop_limit=max(args.max_steps * args.step_mul, 1),
        )
        backend = RawSc2Backend(session, map_name=args.map_name, player_id=1, step_mul=args.step_mul)
        base_env = CmreRLEnv(backend, normalize_reward=False)
        profile = MapProfileRegistry().resolve(args.map_name)
        env = MapAwareEnv(base_env, profile)
        policy = load_map_aware_checkpoint(checkpoint_path, device="cpu")
        policy.eval()
        grounder = ActionGrounder(profile, player_id=1)
        initial_observation = getattr(session, "_last_observation", None) or {}
        loop_start = int(initial_observation.get("loop", 0))

        buffer = collect_rollout(
            env,
            policy,
            n_steps=args.max_steps,
            deterministic=args.deterministic,
            device="cpu",
            action_builder=grounder.ground,
        )
        rewards = [float(step.reward) for step in getattr(buffer, "_steps", ())]
        actions = [int(step.action.flatten()[0]) for step in getattr(buffer, "_steps", ())]
        report.update({
            "player_id": session.player_id,
            "steps_collected": len(buffer),
            "loop_start": loop_start,
            "loop_end": int(getattr(session, "_last_observation", {}).get("loop", 0)),
            "reward_sum": float(sum(rewards)),
            "reward_mean": float(np.mean(rewards)) if rewards else 0.0,
            "action_indices": actions,
            "policy_config": policy.config(),
            "feature_dim": int(env.observation_dim),
        })
        if args.train:
            trainer = PPOTrainer(policy, epochs=args.ppo_epochs, batch_size=args.batch_size)
            metrics = trainer.train(buffer)
            live_checkpoint = output_dir / "live-map-aware-policy.pt"
            save_map_aware_checkpoint(
                policy,
                live_checkpoint,
                training={"source": "real-sc2-bounded-rollout", "steps": len(buffer), "ppo": metrics},
            )
            report["training_update_applied"] = True
            report["ppo_metrics"] = metrics
            report["live_checkpoint"] = str(live_checkpoint.relative_to(REPO_ROOT))
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if session is not None:
            report["runtime_stats"] = dict(session.runtime_stats)
            report["create_game"] = bool(session.runtime_stats.get("create_game"))
            report["join_game"] = bool(session.runtime_stats.get("join_game"))
            report["action_results_observed"] = bool(session.runtime_stats.get("action_results"))
            report["action_successes"] = int(session.runtime_stats.get("action_successes", 0))
            report["frame_advancement"] = bool(session.runtime_stats.get("requested_step_loops", 0) > 0)
            try:
                session.leave()
            except Exception as exc:
                report["leave_error"] = f"{type(exc).__name__}: {exc}"
        stop_launcher(launcher_process)
        if launcher_handles is not None:
            for handle in launcher_handles:
                handle.close()
        report["script_error_verdict"] = script_error_verdict(start_epoch)
        required_runtime = (
            report.get("api_ready")
            and report.get("create_game")
            and report.get("join_game")
            and report.get("frame_advancement")
            and report.get("action_results_observed")
            and int(report.get("action_successes", 0)) > 0
            and int(report.get("steps_collected", 0)) == int(args.max_steps)
        )
        report["runtime_gate"] = bool(required_runtime)
        if report.get("error"):
            report["status"] = "failed"
        elif report["script_error_verdict"].get("has_new_errors"):
            report["status"] = "blocked"
        elif not required_runtime:
            report["status"] = "blocked"
        else:
            report["status"] = "passed"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_live(args)
    print(json.dumps({
        "status": report.get("status"),
        "report": report.get("report_path"),
        "api_ready": report.get("api_ready"),
        "create_game": report.get("create_game"),
        "join_game": report.get("join_game"),
        "frame_advancement": report.get("frame_advancement"),
        "action_results_observed": report.get("action_results_observed"),
        "script_errors": report.get("script_error_verdict", {}).get("has_new_errors"),
    }, ensure_ascii=False))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
