#!/usr/bin/env python3
"""Run a resumable CMRE commander x map launcher matrix.

The matrix intentionally calls the approved PowerShell launcher for every
pair. It does not launch SC2 by itself; ``--runtime`` is reserved for a later
smoke tier and is kept separate from the cheap, exhaustive staging gate.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
SC2VIBE_ROOT = WORKSPACE_ROOT.parent
DEFAULT_LEGACY_ROOT = SC2VIBE_ROOT / "cmre-runtime"
LAUNCHER = WORKSPACE_ROOT / "tools" / "launchers" / "launch-cmre-alenger.ps1"
WEBUI_DIR = WORKSPACE_ROOT / "tools" / "cmre-webui"


@dataclass(frozen=True)
class Pair:
    commander_id: str
    commander_group: str
    race: str
    map_name: str

    @property
    def key(self) -> str:
        return f"{self.map_name}::{self.commander_id}"


def load_commanders() -> list[dict]:
    sys.path.insert(0, str(WEBUI_DIR))
    import server  # pylint: disable=import-outside-toplevel

    return [item for item in server.load_commanders() if item.get("group") in {"official", "alenger"}]


def load_maps(legacy_root: Path) -> list[str]:
    maps_root = legacy_root / "Maps" / "CMRE"
    if not maps_root.is_dir():
        raise FileNotFoundError(f"CMRE map root not found: {maps_root}")
    return sorted(item.name for item in maps_root.iterdir() if item.is_dir() and item.name.endswith(".SC2Map"))


def build_pairs(legacy_root: Path) -> list[Pair]:
    commanders = load_commanders()
    maps = load_maps(legacy_root)
    if not commanders:
        raise RuntimeError("no CMRE commanders exposed by the WebUI registry")
    if not maps:
        raise RuntimeError("no CMRE maps found")
    return [
        Pair(
            commander_id=item["id"],
            commander_group=item["group"],
            race=item["race"],
            map_name=map_name,
        )
        for map_name in maps
        for item in sorted(commanders, key=lambda value: value["id"])
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-root", type=Path, default=DEFAULT_LEGACY_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=WORKSPACE_ROOT / "artifacts" / "projects" / "cmre-porting" / "stage25-ai-ally-capability-completion" / "cmre-commander-map-matrix",
    )
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--limit", type=int, default=0, help="run at most N pairs after resume filtering")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--runtime", action="store_true", help="reserved runtime tier; not mixed into staging results")
    return parser.parse_args()


def read_completed(path: Path) -> set[str]:
    if not path.exists():
        return set()
    completed = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("status") == "pass" and row.get("pair_key"):
            completed.add(row["pair_key"])
    return completed


def classify_failure(stdout: str, stderr: str, returncode: int | None) -> str:
    combined = f"{stdout}\n{stderr}".lower()
    if "sc2_runtime_busy" in combined or "test lock" in combined and "already held" in combined:
        return "blocked"
    if returncode == 0:
        return "pass"
    return "fail"


def run_pair(pair: Pair, legacy_root: Path, timeout: int, runtime: bool) -> dict:
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(LAUNCHER),
        "-MapName",
        pair.map_name,
        "-Commander",
        pair.commander_id,
        "-LegacyRootOverride",
        str(legacy_root),
        "-Mode",
        "1",
        "-DifficultyBase",
        "0",
        "-DifficultyPlus",
        "0",
        "-PlayerMode",
    ]
    if not runtime:
        command.append("-NoLaunch")

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=WORKSPACE_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        returncode = completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        returncode = None
    duration = round(time.monotonic() - started, 3)
    status = classify_failure(stdout, stderr, returncode)
    return {
        "pair_key": pair.key,
        "commander_id": pair.commander_id,
        "commander_group": pair.commander_group,
        "race": pair.race,
        "map_name": pair.map_name,
        "tier": "runtime" if runtime else "staging",
        "status": status,
        "returncode": returncode,
        "duration_sec": duration,
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
        "command": command,
    }


def write_summary(output_dir: Path, pairs: list[Pair], rows: list[dict], runtime: bool) -> None:
    # A resumed repair run may append a newer verdict for a previous failure.
    # The summary is the acceptance view, so keep the latest row per pair while
    # preserving the full append-only JSONL audit trail.
    latest_by_pair: dict[str, dict] = {}
    for row in rows:
        if row.get("pair_key"):
            latest_by_pair[row["pair_key"]] = row
    rows = [
        latest_by_pair[pair.key]
        for pair in pairs
        if pair.key in latest_by_pair
    ]
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    summary = {
        "schemaVersion": 1,
        "tier": "runtime" if runtime else "staging",
        "pair_count": len(pairs),
        "completed_count": len(rows),
        "counts": counts,
        "commander_count": len({pair.commander_id for pair in pairs}),
        "map_count": len({pair.map_name for pair in pairs}),
        "pairs": [asdict(pair) | {"pair_key": pair.key} for pair in pairs],
        "results": rows,
    }
    (output_dir / ("runtime-summary.json" if runtime else "staging-summary.json")).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    args = parse_args()
    if args.runtime:
        raise SystemExit("--runtime is reserved until the staging matrix is complete")
    pairs = build_pairs(args.legacy_root)
    print(json.dumps({"pair_count": len(pairs), "commander_count": len({p.commander_id for p in pairs}), "map_count": len({p.map_name for p in pairs})}, ensure_ascii=False))
    if args.plan_only:
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    results_path = args.output_dir / "staging-results.jsonl"
    completed = read_completed(results_path) if args.resume else set()
    pending = [pair for pair in pairs if pair.key not in completed]
    if args.limit > 0:
        pending = pending[: args.limit]
    rows = []
    if results_path.exists() and args.resume:
        for line in results_path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    with results_path.open("a", encoding="utf-8") as stream:
        for index, pair in enumerate(pending, start=1):
            row = run_pair(pair, args.legacy_root, args.timeout, runtime=False)
            rows.append(row)
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            print(json.dumps({"index": index, "remaining": len(pending) - index, "pair_key": pair.key, "status": row["status"], "duration_sec": row["duration_sec"]}, ensure_ascii=False), flush=True)
    write_summary(args.output_dir, pairs, rows, runtime=False)
    return 0 if all(row["status"] == "pass" for row in rows if row.get("tier") == "staging") else 2


if __name__ == "__main__":
    raise SystemExit(main())
