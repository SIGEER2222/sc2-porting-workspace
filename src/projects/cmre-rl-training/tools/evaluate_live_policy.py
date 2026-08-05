"""Compare the map-aware policy variants on fresh approved-launcher sessions."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
RUNNER = REPO_ROOT / "src" / "projects" / "cmre-rl-training" / "tools" / "run_live_rl.py"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate map-aware PPO variants on fresh SC2 sessions")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument(
        "--map",
        dest="maps",
        action="append",
        required=True,
        metavar="MAP_ID|LAUNCHER_MAP|PACKED_PATH",
        help="Repeat at least twice for held-out map evaluation",
    )
    parser.add_argument("--max-steps", type=int, default=64)
    parser.add_argument("--step-mul", type=int, default=8)
    parser.add_argument("--port-start", type=int, default=5960)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def resolve_repo_path(raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def parse_map_spec(raw: str) -> dict[str, str]:
    parts = str(raw).split("|", 2)
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise ValueError(f"map_spec_must_be_MAP_ID|LAUNCHER_MAP|PACKED_PATH:{raw}")
    map_id, launcher_map_name, map_path = (part.strip() for part in parts)
    return {
        "map_id": map_id,
        "launcher_map_name": launcher_map_name,
        "map_path": str(resolve_repo_path(map_path)),
    }


def parse_maps(raw_maps: list[str]) -> list[dict[str, str]]:
    maps = [parse_map_spec(raw) for raw in raw_maps]
    if len(maps) < 2:
        raise ValueError("at_least_two_maps_required")
    map_ids = [item["map_id"] for item in maps]
    if len(set(map_ids)) != len(map_ids):
        raise ValueError("duplicate_map_id")
    return maps


def checkpoint_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_variant_args(variant: str) -> list[str]:
    if variant == "frozen-stochastic":
        return []
    if variant == "live-update":
        return ["--train"]
    if variant == "deterministic-baseline":
        return ["--deterministic"]
    raise ValueError(f"unknown_variant:{variant}")


def build_run_command(
    *,
    checkpoint: Path,
    map_spec: dict[str, str],
    variant: str,
    port: int,
    max_steps: int,
    step_mul: int,
    output: Path,
    launcher_suffix: str,
    python_executable: str,
) -> list[str]:
    command = [
        python_executable,
        str(RUNNER),
        "--checkpoint",
        str(checkpoint),
        "--map-name",
        map_spec["map_id"],
        "--launcher-map-name",
        map_spec["launcher_map_name"],
        "--map-path",
        map_spec["map_path"],
        "--port",
        str(port),
        "--max-steps",
        str(max_steps),
        "--step-mul",
        str(step_mul),
        "--launcher-suffix",
        launcher_suffix,
        "--output",
        str(output),
        "--stop-on-terminal",
        "--save-replay",
        "--variant",
        variant,
    ]
    return command + build_variant_args(variant)


def summarize_reports(
    reports: list[dict[str, Any]],
    *,
    checkpoint: Path,
    maps: list[dict[str, str]],
    variants: list[str],
) -> dict[str, Any]:
    terminal_reports = [report for report in reports if report.get("terminal_observed")]
    victories = sum(
        1
        for report in terminal_reports
        for result in report.get("terminal_results", [])
        if int(result.get("player_id", 0)) == 1 and result.get("result_name") == "victory"
    )
    defeats = sum(
        1
        for report in terminal_reports
        for result in report.get("terminal_results", [])
        if int(result.get("player_id", 0)) == 1 and result.get("result_name") == "defeat"
    )
    runtime_clean = all(
        report.get("runtime_gate")
        and report.get("status") == "passed"
        and not report.get("script_error_verdict", {}).get("has_new_errors", True)
        for report in reports
    )
    all_terminal = len(reports) == len(terminal_reports) and bool(reports)
    status = "passed" if runtime_clean and all_terminal else "blocked"
    return {
        "schema": "cmre-live-policy-eval.v1",
        "status": status,
        "evidence_class": "runtime" if reports else "blocked",
        "checkpoint": str(checkpoint.relative_to(REPO_ROOT) if checkpoint.is_relative_to(REPO_ROOT) else checkpoint),
        "checkpoint_sha256": checkpoint_sha256(checkpoint),
        "maps": maps,
        "variants": variants,
        "sample_count": len(reports),
        "terminal_count": len(terminal_reports),
        "victory_count": victories,
        "defeat_count": defeats,
        "win_rate": (victories / len(terminal_reports)) if terminal_reports else None,
        "runtime_clean": runtime_clean,
        "all_runs_reached_terminal": all_terminal,
        "reports": reports,
        "boundary": "P2 remains native Computer; no P2 external ML claim",
    }


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    checkpoint = resolve_repo_path(args.checkpoint).resolve()
    maps = parse_maps(args.maps)
    variants = ["frozen-stochastic", "live-update", "deterministic-baseline"]
    if not checkpoint.is_file():
        raise FileNotFoundError(f"checkpoint_not_found:{checkpoint}")
    for map_spec in maps:
        if not Path(map_spec["map_path"]).is_file():
            raise FileNotFoundError(f"packed_map_not_found:{map_spec['map_path']}")

    if args.output_dir:
        output_dir = resolve_repo_path(args.output_dir).resolve()
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_dir = REPO_ROOT / "src" / "projects" / "cmre-rl-training" / "artifacts" / "stage-10-runtime-policy-eval" / stamp
    output_dir.mkdir(parents=True, exist_ok=True)
    commands: list[list[str]] = []
    reports: list[dict[str, Any]] = []
    port = int(args.port_start)

    for map_spec in maps:
        for variant in variants:
            run_id = f"{map_spec['map_id']}-{variant}"
            run_dir = output_dir / run_id
            report_path = run_dir / "live-rl-report.json"
            command = build_run_command(
                checkpoint=checkpoint,
                map_spec=map_spec,
                variant=variant,
                port=port,
                max_steps=int(args.max_steps),
                step_mul=int(args.step_mul),
                output=report_path,
                launcher_suffix=f"stage10-{run_id}",
                python_executable=str(args.python),
            )
            commands.append(command)
            if not args.dry_run:
                run_dir.mkdir(parents=True, exist_ok=True)
                completed = subprocess.run(
                    command,
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                (run_dir / "runner.stdout.log").write_text(completed.stdout, encoding="utf-8")
                (run_dir / "runner.stderr.log").write_text(completed.stderr, encoding="utf-8")
                if report_path.is_file():
                    reports.append(json.loads(report_path.read_text(encoding="utf-8")))
                else:
                    reports.append({
                        "status": "failed",
                        "variant": variant,
                        "map_name": map_spec["map_id"],
                        "error": f"runner_report_missing:exit={completed.returncode}",
                    })
            port += 1

    summary = summarize_reports(reports, checkpoint=checkpoint, maps=maps, variants=variants)
    summary["commands"] = commands
    summary["dry_run"] = bool(args.dry_run)
    summary["output_dir"] = str(output_dir.relative_to(REPO_ROOT) if output_dir.is_relative_to(REPO_ROOT) else output_dir)
    summary_path = output_dir / "evaluation-report.json"
    summary["report_path"] = str(summary_path.relative_to(REPO_ROOT) if summary_path.is_relative_to(REPO_ROOT) else summary_path)
    if args.dry_run:
        summary["status"] = "dry-run"
        summary["evidence_class"] = "static"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = evaluate(args)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "status": summary["status"],
        "report": summary.get("report_path", ""),
        "sample_count": summary["sample_count"],
        "terminal_count": summary["terminal_count"],
        "win_rate": summary["win_rate"],
        "dry_run": summary["dry_run"],
    }, ensure_ascii=False))
    return 0 if summary["status"] in {"passed", "dry-run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
