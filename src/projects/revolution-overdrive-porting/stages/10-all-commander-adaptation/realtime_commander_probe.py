"""Manifest-driven realtime proof for a Revolution Overdrive commander patch.

The approved launcher owns staging and SC2 process startup. This probe owns only the
SC2API session and observation contract. It deliberately sends no manual step request:
the CreateGame request uses realtime=True, so the game loop must advance on its own.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"))

import aiohttp  # noqa: E402
from s2clientprotocol import common_pb2 as sc_common  # noqa: E402
from s2clientprotocol import sc2api_pb2 as sc_pb  # noqa: E402


STATUS_NAMES = {
    1: "launched",
    2: "init_game",
    3: "in_game",
    4: "in_replay",
    5: "ended",
    6: "quit",
}
RACE_NAMES = {
    "Terran": sc_common.Terran,
    "Zerg": sc_common.Zerg,
    "Protoss": sc_common.Protoss,
    "Random": sc_common.Random,
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve_commander(manifest: dict[str, Any], commander: str) -> dict[str, Any]:
    matches = [
        item for item in manifest.get("commanders", [])
        if str(item.get("commander", "")) == commander
    ]
    if len(matches) != 1:
        raise ValueError(f"manifest commander must resolve exactly once: {commander}")
    patch = matches[0]
    startup = patch.get("startup") or {}
    required = (startup.get("startingStructure"), startup.get("startingWorker"))
    if not all(isinstance(value, str) and value for value in required):
        raise ValueError(f"commander has incomplete startup target contract: {commander}")
    race = str(patch.get("race", ""))
    if race not in RACE_NAMES:
        raise ValueError(f"unsupported commander race in manifest: {race}")
    return patch


def relative_repo_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def utc_from_text(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def script_errors_since(game_logs: Path, since: datetime | None) -> list[dict[str, Any]]:
    if not game_logs.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(game_logs.rglob("*ScriptError*.txt")):
        if not path.is_file() or path.stat().st_size <= 0:
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if since is not None and modified < since:
            continue
        records.append(
            {
                "path": relative_repo_path(path),
                "bytes": path.stat().st_size,
                "modifiedUtc": modified.isoformat(),
            }
        )
    return records


async def rpc(ws: aiohttp.ClientWebSocketResponse, request: sc_pb.Request, timeout: float) -> sc_pb.Response:
    await ws.send_bytes(request.SerializeToString())
    message = await asyncio.wait_for(ws.receive(), timeout=timeout)
    if message.type != aiohttp.WSMsgType.BINARY:
        raise RuntimeError(f"SC2API returned websocket message type {message.type}")
    response = sc_pb.Response()
    response.ParseFromString(message.data)
    return response


def response_error(response: sc_pb.Response, field: str) -> int | None:
    if not response.HasField(field):
        return None
    nested = getattr(response, field)
    return int(nested.error) if nested.HasField("error") else None


def status(response: sc_pb.Response) -> str:
    return STATUS_NAMES.get(int(response.status), str(response.status))


def census(
    response: sc_pb.Response,
    names: dict[int, str],
    target_names: set[str],
) -> dict[str, Any]:
    observation = response.observation.observation
    units = list(observation.raw_data.units)
    p1_units = [unit for unit in units if unit.owner == 1 and not unit.is_blip]
    target_units = [
        {
            "tag": int(unit.tag),
            "name": names.get(int(unit.unit_type), str(unit.unit_type)),
            "x": round(float(unit.pos.x), 3),
            "y": round(float(unit.pos.y), 3),
            "health": round(float(unit.health), 3),
            "healthMax": round(float(unit.health_max), 3),
        }
        for unit in p1_units
        if names.get(int(unit.unit_type), str(unit.unit_type)) in target_names
    ]
    counts: dict[str, int] = {}
    for unit in p1_units:
        name = names.get(int(unit.unit_type), str(unit.unit_type))
        counts[name] = counts.get(name, 0) + 1
    return {
        "gameLoop": int(observation.game_loop),
        "status": status(response),
        "p1UnitCount": len(p1_units),
        "p1Counts": counts,
        "targetUnits": target_units,
    }


async def run(options: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(options.manifest).resolve()
    manifest = load_json(manifest_path)
    patch = resolve_commander(manifest, options.commander)
    startup = patch["startup"]
    target_names = {str(startup["startingStructure"]), str(startup["startingWorker"])}
    map_path = Path(options.map).resolve()
    if not map_path.is_file():
        raise FileNotFoundError(f"packed map not found: {map_path}")
    launcher_evidence: dict[str, Any] = {}
    if options.launcher_evidence:
        launcher_path = Path(options.launcher_evidence).resolve()
        launcher_evidence = load_json(launcher_path)
    since = utc_from_text(launcher_evidence.get("startedAtUtc"))
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "classification": "runtime",
        "commander": options.commander,
        "group": patch.get("group"),
        "race": patch.get("race"),
        "map": relative_repo_path(map_path),
        "manifest": relative_repo_path(manifest_path),
        "launcherEvidence": relative_repo_path(Path(options.launcher_evidence)) if options.launcher_evidence else None,
        "expectedStartingStructure": startup["startingStructure"],
        "expectedStartingWorker": startup["startingWorker"],
        "port": options.port,
        "realtime": True,
        "requestStepsSent": 0,
        "create": {},
        "join": {},
        "catalog": {},
        "observations": [],
        "scriptErrors": [],
        "errors": [],
        "verdict": "blocked",
    }
    started = time.monotonic()
    timeout = aiohttp.ClientTimeout(total=options.timeout)
    try:
        async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as session:
            async with session.ws_connect(
                f"ws://127.0.0.1:{options.port}/sc2api", max_msg_size=0
            ) as ws:
                ping = await rpc(ws, sc_pb.Request(ping=sc_pb.RequestPing()), 20.0)
                result["ping"] = {"baseBuild": int(ping.ping.base_build), "gameVersion": ping.ping.game_version}

                race = RACE_NAMES[str(patch["race"])]
                create = sc_pb.RequestCreateGame(
                    local_map=sc_pb.LocalMap(map_path=str(map_path)),
                    realtime=True,
                )
                create.player_setup.add(type=sc_pb.Participant, race=race)
                create.player_setup.add(type=sc_pb.Computer, race=sc_common.Terran, difficulty=sc_pb.VeryEasy)
                create_response = await rpc(ws, sc_pb.Request(create_game=create), 120.0)
                create_error = response_error(create_response, "create_game")
                result["create"] = {
                    "status": status(create_response),
                    "error": create_error,
                    "errorDetails": create_response.create_game.error_details,
                }
                if create_error is not None or status(create_response) != "init_game":
                    result["errors"].append("CreateGame did not reach init_game")
                    return result

                join = sc_pb.RequestJoinGame(
                    race=race,
                    options=sc_pb.InterfaceOptions(
                        raw=True,
                        score=True,
                        show_cloaked=True,
                        show_burrowed_shadows=True,
                        show_placeholders=True,
                    ),
                )
                join_response = await rpc(ws, sc_pb.Request(join_game=join), 120.0)
                join_error = response_error(join_response, "join_game")
                result["join"] = {
                    "status": status(join_response),
                    "error": join_error,
                    "playerId": int(join_response.join_game.player_id),
                }
                if join_error is not None or status(join_response) != "in_game":
                    result["errors"].append("JoinGame did not reach in_game")
                    return result

                data_response = await rpc(ws, sc_pb.Request(data=sc_pb.RequestData(unit_type_id=True)), 60.0)
                names = {int(unit.unit_id): unit.name for unit in data_response.data.units}
                target_ids = {name: unit_id for unit_id, name in names.items() if name in target_names}
                result["catalog"] = {
                    "unitTypeCount": len(names),
                    "targetTypeIds": target_ids,
                    "targetNamesFound": sorted(target_names.intersection(target_ids)),
                }
                if set(target_ids) != target_names:
                    result["errors"].append("one or more manifest startup targets are absent from RequestData")
                    return result

                last_loop = -1
                advancing = False
                deadline = time.monotonic() + options.observe_seconds
                while time.monotonic() < deadline:
                    observation = await rpc(ws, sc_pb.Request(observation=sc_pb.RequestObservation()), 30.0)
                    snapshot = census(observation, names, target_names)
                    snapshot["elapsedSeconds"] = round(time.monotonic() - started, 3)
                    result["observations"].append(snapshot)
                    loop = int(snapshot["gameLoop"])
                    if loop > last_loop:
                        advancing = advancing or last_loop >= 0
                    last_loop = max(last_loop, loop)
                    if (
                        advancing
                        and {item["name"] for item in snapshot["targetUnits"]} == target_names
                    ):
                        break
                    await asyncio.sleep(options.poll_seconds)

                observed_names = {
                    item["name"]
                    for snapshot in result["observations"]
                    for item in snapshot["targetUnits"]
                }
                loops = [int(snapshot["gameLoop"]) for snapshot in result["observations"]]
                result["realtimeEvidence"] = {
                    "observationCount": len(loops),
                    "firstGameLoop": loops[0] if loops else None,
                    "lastGameLoop": loops[-1] if loops else None,
                    "gameLoopAdvanced": advancing and len(set(loops)) > 1,
                    "targetNamesObserved": sorted(observed_names),
                }
    except Exception as exc:  # pragma: no cover - live environment path
        result["errors"].append(f"probe: {exc}")
    finally:
        result["scriptErrors"] = script_errors_since(Path(options.game_logs).resolve(), since)

    loop_evidence = result.get("realtimeEvidence", {})
    target_pass = set(loop_evidence.get("targetNamesObserved", [])) == target_names
    result["verdict"] = (
        "passed_realtime_starting_structure_and_worker_observed"
        if result["create"].get("status") == "init_game"
        and result["join"].get("status") == "in_game"
        and loop_evidence.get("gameLoopAdvanced")
        and target_pass
        and not result["scriptErrors"]
        and not result["errors"]
        else "blocked_realtime_starting_targets_not_proven"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--map", required=True, help="packed map generated by the approved launcher")
    parser.add_argument("--commander", required=True)
    parser.add_argument(
        "--manifest",
        default=str(REPO_ROOT / "src/projects/revolution-overdrive-porting/vibe/commander_map_patches.json"),
    )
    parser.add_argument("--launcher-evidence", default="")
    parser.add_argument(
        "--game-logs",
        default=str(Path(os.environ.get("USERPROFILE", "")) / "Documents/StarCraft II/GameLogs"),
    )
    parser.add_argument("--observe-seconds", type=float, default=90.0)
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--out", required=True)
    options = parser.parse_args()
    try:
        result = asyncio.run(run(options))
    except Exception as exc:
        result = {"schemaVersion": 1, "classification": "blocked", "verdict": "blocked_probe_setup", "errors": [str(exc)]}
    output = Path(options.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if str(result.get("verdict", "")).startswith("passed_realtime_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
