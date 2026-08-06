#!/usr/bin/env python3
"""Run a resumable native CMRE commander x map runtime smoke matrix.

Each pair is staged and then exercised through the approved launcher and the
SC2 API.  This is intentionally a smoke gate: a pair passes when the real
game reaches a playable frame with P1 as Participant, P2 as native Computer
ally, native P2 initialization is observed, P1 actions are accepted, and the
same launch window has no new ScriptError.  Mission victory is not required
for this matrix and is reported separately.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
SC2_ROOT = Path(os.environ.get("SC2_ROOT", r"E:\SC2\SC2new\StarCraft II"))
LAUNCHER = WORKSPACE_ROOT / "tools" / "launchers" / "launch-cmre-alenger.ps1"
PACKER = WORKSPACE_ROOT / "tools" / "mpq" / "scripts" / "pack_stormlib.py"
LEGACY_ROOT = Path(os.environ.get("CMRE_LEGACY_ROOT", str(WORKSPACE_ROOT.parent / "cmre-runtime")))
WEBUI_DIR = WORKSPACE_ROOT / "tools" / "cmre-webui"
STAGE_BUSY_RETRIES = 12
STAGE_BUSY_RETRY_DELAY_SEC = 5


def _module_available(executable: str, module: str) -> bool:
    try:
        result = subprocess.run(
            [executable, "-c", f"import {module}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def resolve_runtime_python() -> str:
    """Select an interpreter with the live SC2 websocket dependency."""
    candidates: list[str] = []
    configured = os.environ.get("CMRE_RUNTIME_PYTHON", "").strip()
    if configured:
        candidates.append(configured)
    if os.name == "nt" and shutil.which("py"):
        try:
            launcher = subprocess.run(
                ["py", "-3.13", "-c", "import sys; print(sys.executable)"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if launcher.returncode == 0 and launcher.stdout.strip():
                candidates.append(launcher.stdout.strip().splitlines()[-1])
        except (OSError, subprocess.SubprocessError):
            pass
    candidates.append(sys.executable)
    for candidate in candidates:
        if _module_available(candidate, "aiohttp"):
            return candidate
    return sys.executable


PYTHON = resolve_runtime_python()


def _powershell_literal(value: str) -> str:
    """Quote one argument for a PowerShell command expression."""
    return "'" + str(value).replace("'", "''") + "'"


def powershell_command(command: list[str]) -> list[str]:
    """Use ``-Command`` for launcher scripts invoked from Python.

    On this host, ``powershell -File`` can terminate with unsigned ``-1``
    before returning the launcher output when it is started through
    ``subprocess``.  Building one explicit command expression preserves the
    launcher parameter names while quoting map paths and non-ASCII values.
    Existing ``-Command`` invocations are left untouched.
    """
    if not command or Path(command[0]).name.lower() not in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        return command
    try:
        file_index = next(index for index, value in enumerate(command) if value.lower() == "-file")
    except StopIteration:
        return command
    if file_index + 1 >= len(command):
        return command

    script = ["&", _powershell_literal(command[file_index + 1])]
    index = file_index + 2
    while index < len(command):
        token = command[index]
        script.append(token if token.startswith("-") else _powershell_literal(token))
        if token.startswith("-") and index + 1 < len(command) and not command[index + 1].startswith("-"):
            script.append(_powershell_literal(command[index + 1]))
            index += 1
        index += 1
    return [command[0], "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", " ".join(script)]


def load_commanders() -> list[dict]:
    sys.path.insert(0, str(WEBUI_DIR))
    import server  # pylint: disable=import-outside-toplevel

    return [
        item
        for item in server.load_commanders()
        if item.get("group") in {"official", "alenger"}
    ]


def load_maps(map_root: Path | None = None, map_set: str = "cmre") -> list[str]:
    root = map_root or (LEGACY_ROOT / "Maps" / "CMRE")
    if not root.is_dir():
        raise FileNotFoundError(f"map root not found: {root}")
    maps = sorted(
        item.name
        for item in root.iterdir()
        if item.is_dir() and item.name.endswith(".SC2Map")
    )
    if map_set == "reborn":
        story_maps = {
            "zstorychar.SC2Map",
            "zstoryexpedition.SC2Map",
            "zstoryhybrid.SC2Map",
            "zstorykorhal.SC2Map",
            "zstoryspace.SC2Map",
            "zstoryzerus.SC2Map",
        }
        maps = [
            name
            for name in maps
            if name in story_maps or fnmatch.fnmatch(name, "z*_reborn_port.SC2Map")
        ]
    elif map_set != "cmre":
        raise ValueError(f"unsupported map set: {map_set}")
    if not maps:
        raise FileNotFoundError(f"no {map_set} maps found under: {root}")
    return maps


def build_pairs(
    *,
    order: str = "map-first",
    focus_commander: str | None = None,
    focus_map: str | None = None,
    map_root: Path | None = None,
    map_set: str = "cmre",
    commander_id: str | None = None,
) -> list[dict]:
    commanders = sorted(load_commanders(), key=lambda item: item["id"])
    if commander_id is not None:
        commanders = [item for item in commanders if item["id"] == commander_id]
        if not commanders:
            raise ValueError(f"commander is not registered: {commander_id}")
    maps = load_maps() if map_root is None and map_set == "cmre" else load_maps(map_root, map_set)
    source_root = map_root or (LEGACY_ROOT / "Maps" / "CMRE")
    pairs = [
        {
            "pair_key": f"{map_name}::{commander['id']}",
            "commander_id": commander["id"],
            "commander_group": commander["group"],
            "race": commander["race"],
            "map_name": map_name,
            "map_source": str(source_root / map_name),
            "enable_reborn": map_set == "reborn",
        }
        for map_name in maps
        for commander in commanders
    ]
    if order == "map-first":
        return pairs
    if order == "commander-first":
        return [
            pair
            for commander in commanders
            for pair in pairs
            if pair["commander_id"] == commander["id"]
        ]
    if order != "commander-then-map":
        raise ValueError(f"unsupported matrix order: {order}")

    focus_commander = focus_commander or commanders[0]["id"]
    focus_map = focus_map or maps[0]
    if focus_commander not in {item["id"] for item in commanders}:
        raise ValueError(f"focus commander is not registered: {focus_commander}")
    if focus_map not in set(maps):
        raise ValueError(f"focus map is not registered: {focus_map}")
    first_commander = [
        pair for pair in pairs if pair["commander_id"] == focus_commander
    ]
    first_map = [
        pair
        for pair in pairs
        if pair["map_name"] == focus_map
        and pair["commander_id"] != focus_commander
    ]
    focused_keys = {pair["pair_key"] for pair in first_commander + first_map}
    remainder = [pair for pair in pairs if pair["pair_key"] not in focused_keys]
    return first_commander + first_map + remainder


def run_process(command: list[str], timeout: int, *, output: Path | None = None) -> dict:
    started = time.monotonic()
    environment = os.environ.copy()
    project_pythonpath = str(WORKSPACE_ROOT / "src" / "projects" / "cmre-porting")
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (project_pythonpath, existing_pythonpath) if item
    )
    kwargs: dict = {
        "cwd": WORKSPACE_ROOT,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
        "check": False,
        "env": environment,
    }
    effective_command = powershell_command(command)
    try:
        completed = subprocess.run(effective_command, **kwargs)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        returncode = completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        returncode = None
    result = {
        "returncode": returncode,
        "duration_sec": round(time.monotonic() - started, 3),
        "stdout_tail": stdout[-6000:],
        "stderr_tail": stderr[-6000:],
        "command": effective_command,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(stdout + ("\n--- STDERR ---\n" + stderr if stderr else ""), encoding="utf-8")
    return result


def is_runtime_busy(result: dict) -> bool:
    """Return true only for the launcher's transient global-runtime guard."""
    output = "\n".join(
        str(result.get(key) or "") for key in ("stdout_tail", "stderr_tail")
    )
    return "SC2_RUNTIME_BUSY" in output


def run_stage_with_retry(pair: dict, suffix: str, port: int, pair_dir: Path, timeout: int) -> dict:
    """Retry only the launcher-owned runtime lease collision.

    The approved launcher serializes the global SC2 runtime with a named mutex
    and a lease file.  The previous game's process can disappear a few seconds
    before the launcher releases that mutex, so treating the first busy result
    as a pair failure creates false staging failures in a serial matrix.
    """
    attempts: list[dict] = []
    for attempt in range(1, STAGE_BUSY_RETRIES + 1):
        attempt_log = pair_dir / (
            "stage-launcher.log"
            if attempt == 1
            else f"stage-launcher-retry-{attempt}.log"
        )
        stage = run_process(
            launcher_command(pair, suffix, port, stage=True),
            min(timeout, 120),
            output=attempt_log,
        )
        attempts.append(stage)
        if stage["returncode"] == 0 or not is_runtime_busy(stage):
            stage["retry_count"] = attempt - 1
            stage["attempt_log_paths"] = [
                str(
                    path.relative_to(WORKSPACE_ROOT)
                    if path.is_relative_to(WORKSPACE_ROOT)
                    else path
                )
                for path in (
                    pair_dir / (
                        "stage-launcher.log"
                        if index == 1
                        else f"stage-launcher-retry-{index}.log"
                    )
                    for index in range(1, attempt + 1)
                )
            ]
            return stage
        if attempt < STAGE_BUSY_RETRIES:
            time.sleep(STAGE_BUSY_RETRY_DELAY_SEC)
    stage = attempts[-1]
    stage["retry_count"] = STAGE_BUSY_RETRIES - 1
    stage["attempt_log_paths"] = [
        str(
            path.relative_to(WORKSPACE_ROOT)
            if path.is_relative_to(WORKSPACE_ROOT)
            else path
        )
        for path in (
            pair_dir / (
                "stage-launcher.log"
                if index == 1
                else f"stage-launcher-retry-{index}.log"
            )
            for index in range(1, STAGE_BUSY_RETRIES + 1)
        )
    ]
    return stage


def launcher_command(pair: dict, suffix: str, port: int, *, stage: bool) -> list[str]:
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(LAUNCHER),
        "-MapName",
        pair["map_name"],
        "-Commander",
        pair["commander_id"],
        "-LegacyRootOverride",
        str(LEGACY_ROOT),
        "-MapSourceOverride",
        pair.get("map_source", str(LEGACY_ROOT / "Maps" / "CMRE" / pair["map_name"])),
        "-Mode",
        "1",
        "-DifficultyBase",
        "0",
        "-DifficultyPlus",
        "0",
        "-MapCopySuffix",
        suffix,
    ]
    if pair.get("enable_reborn"):
        command += ["-EnableReborn"]
    if stage:
        command += ["-PlayerMode", "-NoLaunch"]
    else:
        command += [
            "-ReuseStagedMap",
            "-ListenPort",
            str(port),
            "-ApiMinimal",
            "-DebugMode",
            "-KeepAlive",
        ]
    return command


def wait_for_port(port: int, process: subprocess.Popen, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(1)
    return False


def stop_port_owner(port: int) -> None:
    # The target is the exact listener selected by the matrix-owned port.
    # SC2 can stop listening before its process exits, so also terminate only
    # SC2_x64 instances whose command line carries this matrix-owned port.
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            f"$targetPort={port}; "
            "Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort $targetPort "
            "-State Listen -ErrorAction SilentlyContinue | "
            "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }; "
            "Get-CimInstance Win32_Process | Where-Object { "
            "$_.Name -eq 'SC2_x64.exe' -and $_.CommandLine -match ('-port\\s+' + $targetPort + '(\\s|$)') "
            "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        ),
    ]
    subprocess.run(command, cwd=WORKSPACE_ROOT, capture_output=True, check=False)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def script_error_check(since: float, output: Path) -> dict:
    command = [
        PYTHON,
        str(WORKSPACE_ROOT / "tools" / "galaxy-vibe" / "script_error_check.py"),
        "--since",
        str(since),
        "--out",
        str(output),
    ]
    result = run_process(command, 30)
    verdict = read_json(output)
    verdict["returncode"] = result["returncode"]
    verdict["stdout_tail"] = result["stdout_tail"]
    return verdict


def find_stormlib() -> Path:
    candidates = [
        WORKSPACE_ROOT / "artifacts" / "stormlib-v9.40" / "x64" / "StormLib.dll",
        WORKSPACE_ROOT / "artifacts" / "stormlib-v9.40" / "Win32" / "StormLib.dll",
        WORKSPACE_ROOT.parent / "artifacts" / "stormlib-v9.40" / "x64" / "StormLib.dll",
        WORKSPACE_ROOT.parent / "artifacts" / "stormlib-v9.40" / "Win32" / "StormLib.dll",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("StormLib.dll not found in the registered artifact locations")


def pack_staged_map(staged_map: Path, packed_map: Path, log_path: Path) -> dict:
    packed_map.parent.mkdir(parents=True, exist_ok=True)
    command = [
        PYTHON,
        str(PACKER),
        str(staged_map),
        str(packed_map),
        "--stormlib",
        str(find_stormlib()),
    ]
    return run_process(command, 180, output=log_path)


def stage_packed_map_for_sc2(packed_map: Path, suffix: str) -> Path:
    """Place an API map beside SC2's installed maps.

    Reborn maps keep external Campaign dependencies in their DocumentHeader.
    SC2 can accept a workspace path for ordinary maps, but the campaign
    resolver runs from the installed data root and may reject that same path
    during JoinGame. Keep the auditable artifact in ``artifacts/`` and give
    the native client an installation-local packed copy.
    """
    runtime_map = SC2_ROOT / "Maps" / f"{suffix}-api.SC2Map"
    runtime_map.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(packed_map, runtime_map)
    return runtime_map


def run_pair(pair: dict, index: int, output_dir: Path, max_loops: int, timeout: int) -> dict:
    suffix = f"cmre-runtime-{index:03d}"
    port = 5900 + index
    pair_dir = output_dir / f"{index:03d}-{pair['commander_id']}-{Path(pair['map_name']).stem}"
    pair_dir.mkdir(parents=True, exist_ok=True)
    result = dict(pair)
    result.update({"tier": "runtime", "suffix": suffix, "port": port})
    stage = run_stage_with_retry(pair, suffix, port, pair_dir, timeout)
    result["stage"] = stage
    if stage["returncode"] != 0:
        result["status"] = "blocked" if is_runtime_busy(stage) else "fail"
        result["failure_class"] = "runtime_busy" if is_runtime_busy(stage) else "staging"
        staged_root = SC2_ROOT / "Maps" / suffix
        if staged_root.is_dir() and staged_root.parent == SC2_ROOT / "Maps":
            shutil.rmtree(staged_root, ignore_errors=True)
        return result

    launcher_log = pair_dir / "runtime-launcher.log"
    log_handle = launcher_log.open("w", encoding="utf-8")
    launcher = subprocess.Popen(
        powershell_command(launcher_command(pair, suffix, port, stage=False)),
        cwd=WORKSPACE_ROOT,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    since = time.time()
    live_map = SC2_ROOT / "Maps" / suffix / pair["map_name"]
    packed_map = output_dir / "packed-maps" / f"cmre-runtime-{index:03d}.SC2Map"
    report_path = pair_dir / "runtime-report.json"
    trace_path = pair_dir / "runtime-trace.jsonl"
    try:
        if not wait_for_port(port, launcher, min(timeout, 180)):
            result["status"] = "blocked" if launcher.poll() is None else "fail"
            result["failure_class"] = "api_listener"
            result["launcher_returncode"] = launcher.poll()
            return result
        pack = pack_staged_map(
            live_map,
            packed_map,
            pair_dir / "pack-map.log",
        )
        result["pack"] = pack
        if pack["returncode"] != 0 or not packed_map.is_file():
            result["status"] = "fail"
            result["failure_class"] = "map_pack"
            return result
        runtime_map = packed_map
        if pair.get("enable_reborn"):
            runtime_map = stage_packed_map_for_sc2(packed_map, suffix)
            result["runtime_map_path"] = str(runtime_map)
        live_command = [
            PYTHON,
            "-m",
            "vibe.run_dead_of_night_live",
            "--port",
            str(port),
            "--map",
            str(runtime_map),
            "--map-source",
            str(pair.get("map_source", LEGACY_ROOT / "Maps" / "CMRE" / pair["map_name"])),
            "--max-loops",
            str(max_loops),
            "--step-size",
            "4",
            "--decision-interval",
            "22",
            "--replay-log",
            str(trace_path),
            "--output",
            str(report_path),
        ]
        if pair.get("enable_reborn"):
            live_command.append("--realtime")
        live = run_process(live_command, timeout, output=pair_dir / "live-runner.log")
        result["live"] = live
        report = read_json(report_path)
        result["runtime_report"] = report
        error_path = pair_dir / "script-error-verdict.json"
        result["script_errors"] = script_error_check(since, error_path)
        assertions = report.get("runtime_assertions", {})
        required = {
            key: bool(assertions.get(key))
            for key in (
                "frames_advanced",
                "player_units_observed",
                "p1_p2_computer_roster",
                "p2_owned_units_observed",
                "p2_visible_as_p1_ally",
                "p2_native_melee_init_observed",
                "p2_starting_units_initialized",
                "p2_starting_resources_initialized",
                "native_strategy_no_debug_injection",
                "native_strategy_state_delta",
                "action_success_observed",
            )
        }
        result["required_assertions"] = required
        result["status"] = (
            "pass"
            if report
            and all(required.values())
            and not result["script_errors"].get("has_new_errors", True)
            else "fail"
        )
        result["failure_class"] = "runtime_assertion" if result["status"] != "pass" else ""
    except Exception as exc:
        result["status"] = "fail"
        result["failure_class"] = "runtime_exception"
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        stop_port_owner(port)
        try:
            launcher.wait(timeout=30)
        except subprocess.TimeoutExpired:
            launcher.terminate()
            try:
                launcher.wait(timeout=10)
            except subprocess.TimeoutExpired:
                launcher.kill()
        log_handle.close()
        staged_root = SC2_ROOT / "Maps" / suffix
        if staged_root.is_dir() and staged_root.parent == SC2_ROOT / "Maps":
            shutil.rmtree(staged_root, ignore_errors=True)
        runtime_map = SC2_ROOT / "Maps" / f"{suffix}-api.SC2Map"
        if runtime_map.is_file() and runtime_map.parent == SC2_ROOT / "Maps":
            try:
                runtime_map.unlink()
            except OSError:
                pass
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-loops", type=int, default=500)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument(
        "--order",
        choices=("map-first", "commander-first", "commander-then-map"),
        default="map-first",
    )
    parser.add_argument("--focus-commander", default=None)
    parser.add_argument("--focus-map", default=None)
    parser.add_argument("--commander", dest="commander_id", default=None)
    parser.add_argument("--map-root", type=Path, default=None)
    parser.add_argument("--map-set", choices=("cmre", "reborn"), default="cmre")
    args = parser.parse_args()
    pairs = build_pairs(
        order=args.order,
        focus_commander=args.focus_commander,
        focus_map=args.focus_map,
        map_root=args.map_root,
        map_set=args.map_set,
        commander_id=args.commander_id,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results_path = args.output_dir / "runtime-results.jsonl"
    completed: set[str] = set()
    rows: list[dict] = []
    if args.resume and results_path.exists():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.append(row)
            if row.get("status") == "pass":
                completed.add(row.get("pair_key", ""))
    pending = [pair for pair in pairs if pair["pair_key"] not in completed]
    if args.limit > 0:
        pending = pending[: args.limit]
    with results_path.open("a", encoding="utf-8") as stream:
        for offset, pair in enumerate(pending):
            index = next(i for i, candidate in enumerate(pairs) if candidate["pair_key"] == pair["pair_key"]) + 1
            row = run_pair(pair, index, args.output_dir, args.max_loops, args.timeout)
            rows.append(row)
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            print(json.dumps({"index": index, "remaining": len(pending) - offset - 1, "pair_key": pair["pair_key"], "status": row["status"]}, ensure_ascii=False), flush=True)
    counts: dict[str, int] = {}
    latest_by_pair: dict[str, dict] = {}
    for row in rows:
        if row.get("pair_key"):
            latest_by_pair[row["pair_key"]] = row
    rows = [
        latest_by_pair[pair["pair_key"]]
        for pair in pairs
        if pair["pair_key"] in latest_by_pair
    ]
    for row in rows:
        counts[row.get("status", "unknown")] = counts.get(row.get("status", "unknown"), 0) + 1
    summary = {
        "schemaVersion": 1,
        "tier": "runtime",
        "order": args.order,
        "focus_commander": args.focus_commander,
        "focus_map": args.focus_map,
        "status": "PASS" if len(rows) == len(pairs) and all(row.get("status") == "pass" for row in rows) else "FAIL",
        "pair_count": len(pairs),
        "completed_count": len(rows),
        "counts": counts,
        "commander_count": len({pair["commander_id"] for pair in pairs}),
        "map_count": len({pair["map_name"] for pair in pairs}),
        "results": rows,
    }
    (args.output_dir / "runtime-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
