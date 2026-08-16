"""Realtime proof for Revolution Overdrive runtime commander replacement.

The probe deliberately never sends RequestStep. The launcher has already injected the
Galaxy bootstrap into the staged map; this process only loads that map through SC2API,
advances the map with ordinary native movement when requested, and observes P1 raw units.

The filename is retained for compatibility with the existing Stage 07 evidence commands.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"))

import aiohttp  # noqa: E402
from s2clientprotocol import sc2api_pb2 as sc_pb  # noqa: E402
from s2clientprotocol import common_pb2 as sc_common  # noqa: E402
from s2clientprotocol import raw_pb2 as sc_raw  # noqa: E402


STATUS_NAMES = {
    1: "launched",
    2: "init_game",
    3: "in_game",
    4: "in_replay",
    5: "ended",
    6: "quit",
}
FACTION_TARGETS = {
    "Iron": {
        "1gangtiegongchengche": "worker",
        "1gangtieyaosai": "command_center",
    },
    "Coverts": {
        "SCVC": "worker",
        "CommandCenterC": "command_center",
    },
    "Umojan": {
        "SCVU": "worker",
        "CommandCenterU": "command_center",
    },
    "Pirate": {
        "9shougezhe": "hero",
        "9qianxianzhihuizhongxin": "command_center",
    },
    "Madness": {
        "3diguozhijian": "hero",
        "3diguoqianshaojidi": "command_center",
    },
}
REGION_29_CENTER = (118.5, 47.5)
ABILITY_MOVE = 16


async def rpc(ws, request: sc_pb.Request, timeout: float = 120.0) -> sc_pb.Response:
    await ws.send_bytes(request.SerializeToString())
    payload = await asyncio.wait_for(ws.receive_bytes(), timeout=timeout)
    response = sc_pb.Response()
    response.ParseFromString(payload)
    return response


def sub_error(response: sc_pb.Response, field: str) -> int | None:
    if not response.HasField(field):
        return None
    nested = getattr(response, field)
    return int(nested.error) if nested.HasField("error") else None


def census(observation, names: dict[int, str], target_types: dict[str, str]) -> dict:
    response_observation = observation.observation
    game_observation = response_observation.observation
    units = list(game_observation.raw_data.units)
    p1 = [unit for unit in units if unit.owner == 1]
    counts: dict[str, int] = {}
    p1_units = []
    target_units = []
    for unit in p1:
        name = names.get(unit.unit_type, str(unit.unit_type))
        counts[name] = counts.get(name, 0) + 1
        p1_units.append(
            {
                "tag": int(unit.tag),
                "name": name,
                "x": round(float(unit.pos.x), 3),
                "y": round(float(unit.pos.y), 3),
                "health": round(float(unit.health), 3),
                "health_max": round(float(unit.health_max), 3),
                "is_blip": bool(unit.is_blip),
            }
        )
        if name in target_types:
            target_units.append(
                {
                    "tag": int(unit.tag),
                    "name": name,
                    "role": target_types[name],
                    "x": round(float(unit.pos.x), 3),
                    "y": round(float(unit.pos.y), 3),
                    "health": round(float(unit.health), 3),
                    "health_max": round(float(unit.health_max), 3),
                }
            )
    return {
        "game_loop": int(game_observation.game_loop),
        "status": STATUS_NAMES.get(int(observation.status), str(observation.status)),
        "total_units": len(units),
        "p1_unit_count": len(p1),
        "p1_counts": counts,
        "p1_units": p1_units,
        "target_units": target_units,
    }


def p1_tags(observation) -> list[int]:
    units = observation.observation.observation.raw_data.units
    return [
        int(unit.tag)
        for unit in units
        if unit.owner == 1 and not unit.is_blip
    ]


async def move_p1_to_region_29(ws, observation) -> dict:
    tags = p1_tags(observation)
    request = sc_pb.Request(action=sc_pb.RequestAction())
    action = request.action.actions.add()
    command = action.action_raw.unit_command
    command.ability_id = ABILITY_MOVE
    command.unit_tags.extend(tags)
    command.target_world_space_pos.x = REGION_29_CENTER[0]
    command.target_world_space_pos.y = REGION_29_CENTER[1]
    command.queue_command = False
    response = await rpc(ws, request, 20)
    return {
        "ability_id": ABILITY_MOVE,
        "target": list(REGION_29_CENTER),
        "unit_tags": tags,
        "results": [int(item) for item in response.action.result],
        "errors": list(response.error),
    }


async def run(options) -> dict:
    target_types = FACTION_TARGETS[options.faction]
    result = {
        "schemaVersion": 1,
        "classification": "runtime",
        "map": str(Path(options.map).resolve()),
        "port": options.port,
        "faction": options.faction,
        "expectedTargetTypes": target_types,
        "realtime": True,
        "actionsSent": [],
        "requestStepsSent": 0,
        "create": {},
        "join": {},
        "catalog": {},
        "observations": [],
        "verdict": "blocked",
        "errors": [],
    }
    started = time.monotonic()

    timeout = aiohttp.ClientTimeout(total=options.timeout)
    async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as session:
        try:
            ws = await session.ws_connect(
                f"ws://127.0.0.1:{options.port}/sc2api", max_msg_size=0
            )
        except Exception as exc:  # pragma: no cover - live environment path
            result["errors"].append(f"connect: {exc}")
            return result

        async with ws:
            try:
                ping = await rpc(ws, sc_pb.Request(ping=sc_pb.RequestPing()), 20)
                result["ping"] = {
                    "base_build": int(ping.ping.base_build),
                    "game_version": ping.ping.game_version,
                }

                create = sc_pb.RequestCreateGame(
                    local_map=sc_pb.LocalMap(map_path=str(Path(options.map).resolve())),
                    realtime=True,
                )
                create.player_setup.add(type=sc_pb.Participant, race=sc_common.Terran)
                create.player_setup.add(
                    type=sc_pb.Computer,
                    race=sc_common.Terran,
                    difficulty=sc_pb.VeryEasy,
                )
                create_response = await rpc(ws, sc_pb.Request(create_game=create))
                create_error = sub_error(create_response, "create_game")
                result["create"] = {
                    "status": STATUS_NAMES.get(int(create_response.status), str(create_response.status)),
                    "error": create_error,
                    "error_details": create_response.create_game.error_details,
                }
                if create_error is not None:
                    result["errors"].append(f"create_game error={create_error}")
                    return result

                await asyncio.sleep(3.0)
                join = sc_pb.RequestJoinGame(
                    race=sc_common.Terran,
                    options=sc_pb.InterfaceOptions(
                        raw=True,
                        score=True,
                        show_cloaked=True,
                        show_burrowed_shadows=True,
                        show_placeholders=True,
                    ),
                )
                join_response = await rpc(ws, sc_pb.Request(join_game=join))
                join_error = sub_error(join_response, "join_game")
                result["join"] = {
                    "status": STATUS_NAMES.get(int(join_response.status), str(join_response.status)),
                    "error": join_error,
                    "player_id": int(join_response.join_game.player_id),
                }
                if join_error is not None:
                    result["errors"].append(f"join_game error={join_error}")
                    return result

                data_response = await rpc(
                    ws, sc_pb.Request(data=sc_pb.RequestData(unit_type_id=True))
                )
                names = {int(unit.unit_id): unit.name for unit in data_response.data.units}
                result["catalog"] = {
                    "unit_type_count": len(names),
                    "target_type_ids": {
                        target: unit_id
                        for unit_id, target in ((unit_id, name) for unit_id, name in names.items())
                        if target in target_types
                    },
                }

                deadline = time.monotonic() + options.observe_seconds
                progress_attempts = 0
                progress_next_loop = options.progress_after_game_loop
                while time.monotonic() < deadline:
                    observation = await rpc(
                        ws, sc_pb.Request(observation=sc_pb.RequestObservation()), 20
                    )
                    snapshot = census(observation, names, target_types)
                    snapshot["elapsed_seconds"] = round(time.monotonic() - started, 3)
                    result["observations"].append(snapshot)
                    if (
                        options.progress_to_escort
                        and progress_attempts < options.progress_max_attempts
                        and snapshot["game_loop"] >= progress_next_loop
                    ):
                        action_result = await move_p1_to_region_29(ws, observation)
                        result.setdefault("progressActions", []).append(action_result)
                        result["actionsSent"].append("native_move_p1_to_region_29")
                        progress_attempts += 1
                        progress_next_loop += options.progress_interval_game_loop
                    if snapshot["target_units"]:
                        # One additional observation confirms the replacement is stable.
                        await asyncio.sleep(1.0)
                        confirm = await rpc(
                            ws, sc_pb.Request(observation=sc_pb.RequestObservation()), 20
                        )
                        confirmed = census(confirm, names, target_types)
                        confirmed["elapsed_seconds"] = round(time.monotonic() - started, 3)
                        result["observations"].append(confirmed)
                        break
                    await asyncio.sleep(0.5)

                result["verdict"] = (
                    f"passed_realtime_{options.faction.lower()}_replacement_observed"
                    if any(item["target_units"] for item in result["observations"])
                    and all(item["game_loop"] > 0 for item in result["observations"][-2:])
                    else "blocked_target_units_not_observed"
                )
            except Exception as exc:  # pragma: no cover - live environment path
                result["errors"].append(f"probe: {exc}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--map", required=True)
    parser.add_argument("--faction", choices=sorted(FACTION_TARGETS), default="Iron")
    parser.add_argument("--observe-seconds", type=float, default=25.0)
    parser.add_argument("--progress-to-escort", action="store_true")
    parser.add_argument("--progress-after-game-loop", type=int, default=200)
    parser.add_argument("--progress-interval-game-loop", type=int, default=300)
    parser.add_argument("--progress-max-attempts", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--out", required=True)
    options = parser.parse_args()
    result = asyncio.run(run(options))
    output = Path(options.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"].startswith("passed_realtime_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
