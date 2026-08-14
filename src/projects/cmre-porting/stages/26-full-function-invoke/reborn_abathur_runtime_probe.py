"""Execute and verify every original Reborn Abathur Larva card command in SC2.

The probe is intentionally fail-closed. It reports a command only after the
SC2 API exposes the exact ability and a fresh Larva actually produces the
source-baseline unit type(s). It also records the P1/P2 raw census before and
after the controlled test; that census is classified, not equated to the full
potential tech tree.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import socket
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import aiohttp

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "reference/SC2-Neuro-API-Integration"))
sys.path.insert(0, str(Path(__file__).parent))

from s2clientprotocol import common_pb2 as common_pb  # noqa: E402
from s2clientprotocol import debug_pb2 as debug_pb  # noqa: E402
from s2clientprotocol import query_pb2  # noqa: E402
from s2clientprotocol import raw_pb2  # noqa: E402
from s2clientprotocol import sc2api_pb2 as sc_pb  # noqa: E402
from reborn_abathur_check import compare_runtime  # noqa: E402


DEFAULT_BASELINE = ROOT / "artifacts/projects/cmre-porting/stage26-full-function-invoke/reborn-abathur-baseline.json"
DEFAULT_OUT_DIR = ROOT / "artifacts/projects/cmre-porting/stage26-full-function-invoke/runtime"
STATUS_NAMES = {1: "launched", 2: "init_game", 3: "in_game", 4: "in_replay", 5: "ended", 6: "quit"}
ACTION_SUCCESS = 1


class RuntimeBlocked(RuntimeError):
    """The probe could not establish the required live runtime evidence."""


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def send_recv(ws: aiohttp.ClientWebSocketResponse, request: sc_pb.Request, timeout: float = 45.0) -> sc_pb.Response:
    await ws.send_bytes(request.SerializeToString())
    payload = await asyncio.wait_for(ws.receive_bytes(), timeout=timeout)
    response = sc_pb.Response()
    response.ParseFromString(payload)
    return response


async def wait_for_port(port: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return
        except (ConnectionRefusedError, OSError):
            await asyncio.sleep(1.0)
    raise RuntimeBlocked(f"SC2 API port 127.0.0.1:{port} did not open within {timeout:.0f}s")


async def connect(port: int) -> tuple[aiohttp.ClientSession, aiohttp.ClientWebSocketResponse]:
    session = aiohttp.ClientSession()
    try:
        websocket = await session.ws_connect(f"ws://127.0.0.1:{port}/sc2api", max_msg_size=0)
    except Exception:
        await session.close()
        raise
    return session, websocket


async def create_and_join_game(ws: aiohttp.ClientWebSocketResponse, map_path: Path) -> dict[str, Any]:
    candidates = [str(map_path), f"Maps\\{map_path.name}", map_path.name]
    errors: list[str] = []
    for candidate in candidates:
        create = sc_pb.RequestCreateGame(local_map=sc_pb.LocalMap(map_path=candidate), realtime=True)
        player = create.player_setup.add()
        player.type = 1  # Participant
        player.race = 2  # Zerg; the map overlay owns the selected commander.
        response = await send_recv(ws, sc_pb.Request(create_game=create), timeout=240.0)
        if response.create_game.HasField("error"):
            errors.append(f"{candidate}: {response.create_game.error} {response.create_game.error_details}")
            continue
        join = sc_pb.Request(
            join_game=sc_pb.RequestJoinGame(
                race=2,
                options=sc_pb.InterfaceOptions(raw=True, score=True, show_cloaked=True, show_burrowed_shadows=True),
            )
        )
        joined = await send_recv(ws, join, timeout=180.0)
        if joined.error or (joined.join_game.HasField("error")):
            detail = joined.join_game.error_details if joined.join_game.HasField("error_details") else ""
            raise RuntimeBlocked(f"RequestJoinGame failed: {list(joined.error)} {detail}")
        return {"map_candidate": map_path.name if candidate == str(map_path) else candidate, "player_id": joined.join_game.player_id}
    raise RuntimeBlocked("RequestCreateGame failed for all map paths: " + " | ".join(errors))


async def fetch_catalog(ws: aiohttp.ClientWebSocketResponse) -> tuple[dict[int, tuple[str, int]], dict[tuple[str, int], int], dict[int, str], dict[str, int]]:
    response = await send_recv(ws, sc_pb.Request(data=sc_pb.RequestData(ability_id=True, unit_type_id=True)))
    ability_by_id = {item.ability_id: (item.link_name, item.link_index) for item in response.data.abilities}
    ability_by_key = {key: ability_id for ability_id, key in ability_by_id.items()}
    unit_by_id = {item.unit_id: item.name for item in response.data.units}
    unit_by_name = {name: unit_id for unit_id, name in unit_by_id.items()}
    return ability_by_id, ability_by_key, unit_by_id, unit_by_name


async def observe(ws: aiohttp.ClientWebSocketResponse) -> tuple[int, list[Any]]:
    response = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
    if not response.observation.HasField("observation"):
        raise RuntimeBlocked(f"SC2 did not return an observation (status={STATUS_NAMES.get(response.status, response.status)})")
    observation = response.observation.observation
    return observation.game_loop, list(observation.raw_data.units)


def named_census(units: list[Any], unit_by_id: dict[int, str], owner: int) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for unit in units:
        if unit.owner == owner:
            counts[unit_by_id.get(unit.unit_type, f"unknown_{unit.unit_type}")] += 1
    return dict(sorted(counts.items()))


def classify_census(counts: dict[str, int], baseline: dict[str, Any]) -> dict[str, Any]:
    known = set(baseline["roster"]["catalog_unit_ids"])
    original_roster = baseline["roster"].get("original_roster", baseline["roster"]["potentially_unlockable"])
    original_units = set(original_roster["units"])
    original_buildings = set(original_roster["buildings"])
    return {
        "counts": counts,
        "original_reborn_units": sorted(name for name in counts if name in original_units),
        "original_reborn_buildings": sorted(name for name in counts if name in original_buildings),
        "other_original_catalog_units": sorted(name for name in counts if name in known and name not in original_units | original_buildings),
        "map_or_external_units": sorted(name for name in counts if name not in known),
    }


async def step_and_observe(ws: aiohttp.ClientWebSocketResponse, count: int = 16) -> tuple[int, list[Any]]:
    await send_recv(ws, sc_pb.Request(step=sc_pb.RequestStep(count=count)))
    await asyncio.sleep(0.5)
    return await observe(ws)


async def wait_for_larvae(ws: aiohttp.ClientWebSocketResponse, unit_by_id: dict[int, str], timeout: float) -> tuple[list[Any], int]:
    deadline = time.monotonic() + timeout
    last_loop = 0
    while time.monotonic() < deadline:
        last_loop, units = await step_and_observe(ws)
        larvae = [unit for unit in units if unit.owner == 1 and unit_by_id.get(unit.unit_type) == "Larva"]
        if larvae:
            return larvae, last_loop
    return [], last_loop


async def available_abilities(ws: aiohttp.ClientWebSocketResponse, unit_tag: int) -> tuple[list[int], str | None]:
    request = sc_pb.Request(
        query=query_pb2.RequestQuery(abilities=[query_pb2.RequestQueryAvailableAbilities(unit_tag=unit_tag)])
    )
    response = await send_recv(ws, request)
    if not response.query.abilities:
        return [], "QueryAvailableAbilities returned no unit result"
    result = response.query.abilities[0]
    if result.unit_tag != unit_tag:
        return [], f"QueryAvailableAbilities returned tag {result.unit_tag} for requested tag {unit_tag}"
    return [ability.ability_id for ability in result.abilities], None


async def wait_for_native_commands(
    ws: aiohttp.ClientWebSocketResponse,
    unit_by_id: dict[int, str],
    expected_ability_ids: set[int],
    timeout: float,
) -> tuple[list[Any], set[int], int, list[dict[str, Any]]]:
    deadline = time.monotonic() + timeout
    last_larvae: list[Any] = []
    last_available: set[int] = set()
    last_loop = 0
    samples: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        last_loop, units = await step_and_observe(ws)
        larvae = [unit for unit in units if unit.owner == 1 and unit_by_id.get(unit.unit_type) == "Larva"]
        available: set[int] = set()
        query_errors: list[str] = []
        for larva in larvae:
            ability_ids, query_error = await available_abilities(ws, larva.tag)
            available.update(ability_ids)
            if query_error:
                query_errors.append(query_error)
        samples.append(
            {
                "game_loop": last_loop,
                "larva_count": len(larvae),
                "available_ability_count": len(available),
                "baseline_ability_count": len(available & expected_ability_ids),
                "query_errors": sorted(set(query_errors)),
            }
        )
        last_larvae, last_available = larvae, available
        if available & expected_ability_ids:
            return larvae, available, last_loop, samples
    return last_larvae, last_available, last_loop, samples


async def enable_controlled_test_cheats(ws: aiohttp.ClientWebSocketResponse) -> None:
    commands = [
        debug_pb.DebugCommand(game_state=debug_pb.DebugGameState.all_resources),
        # Card parity is measured after the original tech prerequisites are
        # satisfied. The opening census above remains a normal-game sample.
        debug_pb.DebugCommand(game_state=debug_pb.DebugGameState.tech_tree),
        debug_pb.DebugCommand(game_state=debug_pb.DebugGameState.fast_build),
    ]
    response = await send_recv(ws, sc_pb.Request(debug=sc_pb.RequestDebug(debug=commands)))
    if response.error:
        raise RuntimeBlocked(f"RequestDebug rejected controlled-test cheats: {list(response.error)}")


async def spawn_larva(
    ws: aiohttp.ClientWebSocketResponse,
    larva_unit_type: int,
    unit_by_id: dict[int, str],
    position: tuple[float, float],
) -> Any:
    _, before_units = await observe(ws)
    before_tags = {unit.tag for unit in before_units}
    command = debug_pb.DebugCommand(
        create_unit=debug_pb.DebugCreateUnit(
            unit_type=larva_unit_type,
            owner=1,
            pos=common_pb.Point2D(x=position[0], y=position[1]),
            quantity=1,
        )
    )
    response = await send_recv(ws, sc_pb.Request(debug=sc_pb.RequestDebug(debug=[command])))
    if response.error:
        raise RuntimeBlocked(f"DebugCreateUnit(Larva) rejected: {list(response.error)}")
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        _, units = await step_and_observe(ws)
        candidates = [
            unit for unit in units if unit.owner == 1 and unit.tag not in before_tags and unit_by_id.get(unit.unit_type) == "Larva"
        ]
        if candidates:
            return candidates[0]
    raise RuntimeBlocked("DebugCreateUnit(Larva) returned but no fresh P1 Larva was observable")


async def issue_larva_command(ws: aiohttp.ClientWebSocketResponse, larva_tag: int, ability_id: int) -> str | None:
    action = sc_pb.Action(
        action_raw=raw_pb2.ActionRaw(
            unit_command=raw_pb2.ActionRawUnitCommand(ability_id=ability_id, unit_tags=[larva_tag])
        )
    )
    response = await send_recv(ws, sc_pb.Request(action=sc_pb.RequestAction(actions=[action])))
    if response.error:
        return f"top_level_error={list(response.error)}"
    results = list(response.action.result)
    if not results:
        return "SC2 returned no ActionResult"
    if any(result != ACTION_SUCCESS for result in results):
        return f"ActionResult={results}"
    return None


def delta_counts(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {
        unit: change
        for unit in sorted(set(before) | set(after))
        if (change := after.get(unit, 0) - before.get(unit, 0)) > 0
    }


async def wait_for_output(
    ws: aiohttp.ClientWebSocketResponse,
    before: dict[str, int],
    unit_by_id: dict[int, str],
    expected_products: list[str],
    timeout: float,
) -> tuple[dict[str, int], int]:
    deadline = time.monotonic() + timeout
    last_loop = 0
    last_delta: dict[str, int] = {}
    while time.monotonic() < deadline:
        last_loop, units = await step_and_observe(ws)
        last_delta = delta_counts(before, named_census(units, unit_by_id, 1))
        expected = Counter(expected_products)
        relevant = {unit: count for unit, count in last_delta.items() if unit not in {"Larva", "Egg"}}
        if set(relevant) - set(expected):
            return last_delta, last_loop
        if all(last_delta.get(product, 0) >= count for product, count in expected.items()):
            return last_delta, last_loop
    return last_delta, last_loop


def scan_script_errors(since: float) -> list[dict[str, Any]]:
    logs = Path.home() / "Documents/StarCraft II/GameLogs"
    if not logs.is_dir():
        return [{"path": "Documents/StarCraft II/GameLogs", "reason": "GameLogs directory is absent"}]
    findings: list[dict[str, Any]] = []
    for path in logs.glob("*ScriptError*.txt"):
        if path.stat().st_mtime < since:
            continue
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            findings.append({"name": path.name, "bytes": len(text.encode("utf-8"))})
    return findings


async def run_probe(args: argparse.Namespace, baseline: dict[str, Any]) -> dict[str, Any]:
    map_path = args.map_path.resolve()
    if not map_path.is_file():
        raise RuntimeBlocked(f"packed map path does not exist: {map_path}")
    await wait_for_port(args.port, args.port_timeout)
    session, ws = await connect(args.port)
    try:
        ping = await send_recv(ws, sc_pb.Request(ping=sc_pb.RequestPing()))
        join = await create_and_join_game(ws, map_path)
        ability_by_id, ability_by_key, unit_by_id, unit_by_name = await fetch_catalog(ws)
        if "Larva" not in unit_by_name:
            raise RuntimeBlocked("SC2 unit catalog has no Larva unit type")
        native_larvae, native_loop = await wait_for_larvae(ws, unit_by_id, args.startup_timeout)
        _, native_units = await observe(ws)
        opening_census = {"p1": named_census(native_units, unit_by_id, 1), "p2": named_census(native_units, unit_by_id, 2)}

        expected = baseline["larva"]["card_exposed_commands"]
        expected_ability_ids = {
            ability_by_key[key]
            for command in expected
            if (key := (command["ability"], command["command_index"])) in ability_by_key
        }
        await enable_controlled_test_cheats(ws)
        native_larvae, native_available_ids, native_loop, native_readiness_samples = await wait_for_native_commands(
            ws, unit_by_id, expected_ability_ids, args.command_readiness_timeout
        )
        native_available_abilities = [
            {
                "ability": ability_by_id[ability_id][0],
                "command_index": ability_by_id[ability_id][1],
                "ability_id": ability_id,
            }
            for ability_id in sorted(native_available_ids)
            if ability_id in ability_by_id
        ]
        available_commands = [
            {"ability": command["ability"], "command_index": command["command_index"], "ability_id": ability_by_key[key]}
            for command in expected
            if (key := (command["ability"], command["command_index"])) in ability_by_key
            and ability_by_key[key] in native_available_ids
        ]

        results: list[dict[str, Any]] = []
        controlled_test_skipped_reason: str | None = None
        if not native_larvae:
            controlled_test_skipped_reason = "no native P1 Larva was observed before the startup timeout"
        else:
            anchor = native_larvae[0].pos
            for index, command in enumerate(expected):
                ability_key = (command["ability"], command["command_index"])
                result: dict[str, Any] = {
                    "ability": command["ability"],
                    "command": command["command"],
                    "command_index": command["command_index"],
                    "expected_products": command["products"],
                }
                ability_id = ability_by_key.get(ability_key)
                if ability_id is None:
                    result["action_error"] = "ability is absent from SC2 catalog"
                    result["produced_delta"] = {}
                    results.append(result)
                    continue
                position = (anchor.x + 3.0 * (index % 5), anchor.y + 3.0 * (index // 5))
                larva = await spawn_larva(ws, unit_by_name["Larva"], unit_by_id, position)
                controlled_available, controlled_query_error = await available_abilities(ws, larva.tag)
                result["ability_id"] = ability_id
                result["available_on_controlled_larva"] = ability_id in controlled_available
                if controlled_query_error:
                    result["query_error"] = controlled_query_error
                _, before_units = await observe(ws)
                before = named_census(before_units, unit_by_id, 1)
                if ability_id not in controlled_available:
                    result["action_error"] = "ability is not available on fresh controlled Larva"
                    result["produced_delta"] = {}
                    results.append(result)
                    continue
                result["action_error"] = await issue_larva_command(ws, larva.tag, ability_id)
                result["produced_delta"], result["observed_game_loop"] = await wait_for_output(
                    ws, before, unit_by_id, command["products"], args.command_timeout
                )
                results.append(result)

        final_loop, final_units = await observe(ws)
        final_census = {"p1": named_census(final_units, unit_by_id, 1), "p2": named_census(final_units, unit_by_id, 2)}
        runtime = {
            "larva_count": len(native_larvae),
            "available_commands": available_commands,
            "command_results": results,
            "census": final_census,
        }
        comparison = compare_runtime(baseline, runtime)
        script_errors = scan_script_errors(args.script_error_since)
        if script_errors:
            comparison["verdict"] = "FAIL"
            comparison["failures"].append({"code": "SCRIPT_ERROR", "files": script_errors})
            comparison["failure_count"] = len(comparison["failures"])
        return {
            "schemaVersion": 1,
            "subject": "reborn-abathur-larva-runtime",
            "generatedAt": iso_now(),
            "status": comparison["verdict"],
            "evidence_type": "runtime",
            "method": "sc2api_create_join_query_action_raw_census",
            "map": {"name": map_path.name, "sha256": file_hash(map_path), "bytes": map_path.stat().st_size},
            "sc2": {"version": ping.ping.game_version, "base_build": ping.ping.base_build, "join": join},
            "native_opening": {
                "game_loop": native_loop,
                "larva_count": len(native_larvae),
                "available_abilities": native_available_abilities,
                "command_readiness_samples": native_readiness_samples,
                "census": {player: classify_census(counts, baseline) for player, counts in opening_census.items()},
            },
            "controlled_test": {
                "setup": "RequestDebug(all_resources, tech_tree, fast_build) plus one fresh P1 Larva per card command",
                "skipped_reason": controlled_test_skipped_reason,
                "commands": results,
                "final_game_loop": final_loop,
                "census": {player: classify_census(counts, baseline) for player, counts in final_census.items()},
            },
            "comparison": comparison,
            "script_error_gate": {"since_epoch": args.script_error_since, "new_nonempty": script_errors, "pass": not script_errors},
        }
    finally:
        await ws.close()
        await session.close()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def async_main(args: argparse.Namespace) -> int:
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    try:
        result = await run_probe(args, baseline)
    except RuntimeBlocked as error:
        result = {
            "schemaVersion": 1,
            "subject": "reborn-abathur-larva-runtime",
            "generatedAt": iso_now(),
            "status": "BLOCKED",
            "evidence_type": "blocked",
            "blocker": str(error),
        }
    except Exception as error:  # Preserve unexpected transport/API failures as evidence.
        result = {
            "schemaVersion": 1,
            "subject": "reborn-abathur-larva-runtime",
            "generatedAt": iso_now(),
            "status": "BLOCKED",
            "evidence_type": "blocked",
            "blocker": f"unexpected probe error: {type(error).__name__}: {error}",
        }
    write_json(args.out, result)
    print(f"{result['status']}: {args.out}")
    return 0 if result["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed Reborn Abathur Larva product runtime probe")
    parser.add_argument("--map-path", type=Path, required=True, help="packed map path printed by the approved launcher")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR / "reborn-abathur-larva-runtime.json")
    parser.add_argument("--port-timeout", type=float, default=120.0)
    parser.add_argument("--startup-timeout", type=float, default=120.0)
    parser.add_argument("--command-timeout", type=float, default=20.0)
    parser.add_argument("--command-readiness-timeout", type=float, default=45.0)
    parser.add_argument("--script-error-since", type=float, required=True, help="UTC Unix epoch captured before launcher start")
    args = parser.parse_args()
    if args.command_timeout <= 0 or args.command_readiness_timeout <= 0 or args.startup_timeout <= 0 or args.port_timeout <= 0:
        parser.error("timeouts must be positive")
    if not args.baseline.is_file():
        parser.error(f"baseline does not exist: {args.baseline}")
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
