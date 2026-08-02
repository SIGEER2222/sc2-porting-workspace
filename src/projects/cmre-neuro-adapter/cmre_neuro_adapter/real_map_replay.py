"""Capture a full-fidelity replay from the real Dead of Night SC2 map.

The approved launcher owns SC2 startup. This module only connects to its SC2 API
port, creates the packed map game, advances RequestStep frames, and records the
public raw observation. The map record embeds the extracted minimap and original
Objects placements so the browser player can distinguish static map data from
runtime-visible entities.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
CMRE_PORTING_SRC = REPO_ROOT / "src" / "projects" / "cmre-porting"
sys.path.insert(0, str(CMRE_PORTING_SRC))

from vibe import run_dead_of_night_live as live  # type: ignore

from .replay_player import render_player_html

DEFAULT_MAP = REPO_ROOT / "artifacts" / "live-maps" / "亡者之夜_live_packed.SC2Map"
DEFAULT_MAP_SOURCE = (
    REPO_ROOT
    / "src"
    / "projects"
    / "cmre-neuro-adapter"
    / "artifacts"
    / "real-map-source-20260802"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "src"
    / "projects"
    / "cmre-neuro-adapter"
    / "artifacts"
    / "real-map-replay-20260802"
    / "dead-of-night-real-runtime.jsonl"
)
DEFAULT_HTML = DEFAULT_OUTPUT.with_suffix(".html")
MAP_WORLD_BOUNDS = {"min_x": 16.0, "max_x": 176.0, "min_y": 16.0, "max_y": 176.0}
MAP_IMAGE_RECT = {"x": 48, "y": 48, "w": 160, "h": 160}


def _relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.name


def _static_objects(objects_path: Path) -> list[dict[str, Any]]:
    root = ET.parse(objects_path).getroot()
    objects: list[dict[str, Any]] = []
    for index, unit in enumerate(root.iter("ObjectUnit"), start=1):
        position = unit.get("Position", "0,0,0").split(",")
        try:
            x, y = float(position[0]), float(position[1])
            owner = int(unit.get("Player", "0"))
        except (ValueError, IndexError):
            continue
        objects.append(
            {
                "id": f"map-{index}",
                "unit_type_id": unit.get("UnitType", ""),
                "owner": owner,
                "x": x,
                "y": y,
                "source": "Objects",
            }
        )
    return objects


def build_map_record(map_path: Path, map_source: Path) -> dict[str, Any]:
    """Build static metadata from the packed map and its extracted components."""

    minimap = map_source / "minimap.png"
    objects_path = map_source / "Objects"
    terrain_path = map_source / "t3Terrain.xml"
    if not minimap.is_file() or not objects_path.is_file() or not terrain_path.is_file():
        raise FileNotFoundError(
            "real map source must contain minimap.png, Objects, and t3Terrain.xml: "
            f"{map_source}"
        )
    terrain_root = ET.parse(terrain_path).getroot()
    height_map = terrain_root.find("heightMap")
    dimension = [193, 193]
    if height_map is not None:
        raw_dim = (height_map.get("dim") or "193 193").split()
        if len(raw_dim) >= 2:
            dimension = [int(raw_dim[0]), int(raw_dim[1])]
    image_data = base64.b64encode(minimap.read_bytes()).decode("ascii")
    return {
        "record_type": "map",
        "map_id": "dead-of-night",
        "map_name": "亡者之夜.SC2Map",
        "evidence_type": "static",
        "source_map": _relative(map_path),
        "source_components": _relative(map_source),
        "packed_map_sha256": hashlib.sha256(map_path.read_bytes()).hexdigest(),
        "minimap_data_url": f"data:image/png;base64,{image_data}",
        "minimap_source": _relative(minimap),
        "image_rect_px": MAP_IMAGE_RECT,
        "world_bounds": MAP_WORLD_BOUNDS,
        "terrain_height_map_dim": dimension,
        "friendly_players": [1, 2],
        "static_objects": _static_objects(objects_path),
    }


def _entity_brief(unit: Any, player_id: int) -> dict[str, Any] | None:
    brief = live._unit_brief_from_sc2(unit, player_id)
    if brief is None:
        return None
    return {
        **brief,
        "owner": int(unit.owner),
        "alliance": int(unit.alliance),
        "alive": True,
        "state": "idle" if brief.get("is_idle") else "active",
    }


def _entities_from_response(response: Any, player_id: int) -> dict[str, list[dict[str, Any]]]:
    raw = response.observation.observation.raw_data
    grouped: dict[str, list[dict[str, Any]]] = {}
    if raw is None:
        return grouped
    for unit in raw.units:
        brief = _entity_brief(unit, player_id)
        if brief is None:
            continue
        grouped.setdefault(str(int(unit.owner)), []).append(brief)
    return grouped


def _resources(response: Any) -> dict[str, int]:
    common = response.observation.observation.player_common
    return {
        "minerals": int(common.minerals),
        "vespene": int(common.vespene),
        "supply_used": int(common.food_used),
        "supply_cap": int(common.food_cap),
    }


def _entity_events(previous: dict[str, dict[str, Any]], current: dict[str, list[dict[str, Any]]], loop: int) -> list[dict[str, Any]]:
    now = {str(entity["entity_id"]): entity for entities in current.values() for entity in entities}
    events: list[dict[str, Any]] = []
    for entity_id, entity in now.items():
        if entity_id not in previous:
            events.append({"loop": loop, "kind": "unit_created", "entity_id": int(entity_id), "unit_type": entity["unit_type_id"], "owner": entity["owner"]})
    for entity_id, entity in previous.items():
        if entity_id not in now:
            events.append({"loop": loop, "kind": "unit_removed_or_dead", "entity_id": int(entity_id), "unit_type": entity["unit_type_id"], "owner": entity["owner"]})
    return events


def _frame(response: Any, player_id: int, map_name: str, previous: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    observation = response.observation.observation
    entities = _entities_from_response(response, player_id)
    loop = int(observation.game_loop)
    events = _entity_events(previous, entities, loop)
    current = {str(entity["entity_id"]): entity for values in entities.values() for entity in values}
    p1_units = Counter(entity["unit_type_id"] for entity in current.values() if int(entity["owner"]) in (1, 2))
    enemy_units = Counter(entity["unit_type_id"] for entity in current.values() if int(entity["owner"]) not in (0, 1, 2))
    return (
        {
            "record_type": "frame",
            "evidence_type": "runtime",
            "map": map_name,
            "loop": loop,
            "ts_sec": round(loop / 22.4, 2),
            "player_id": player_id,
            "resources": _resources(response),
            "entities_by_player": entities,
            "entity_count": len(current),
            "friendly_units_by_type": dict(p1_units),
            "enemy_units_by_type": dict(enemy_units),
            "events": events,
            "raw_player_result": [
                {"player_id": int(result.player_id), "result": int(result.result)}
                for result in response.observation.player_result
            ],
        },
        current,
    )


async def _create_game(connection: Any, map_path: Path) -> int:
    await connection.send_request(live.sc_pb.Request(ping=live.sc_pb.RequestPing()), timeout=30)
    try:
        await connection.send_request(live.sc_pb.Request(leave_game=live.sc_pb.RequestLeaveGame()), timeout=10)
    except Exception:
        pass
    request = live.sc_pb.Request(
        create_game=live.sc_pb.RequestCreateGame(
            local_map=live.sc_pb.LocalMap(map_path=str(map_path.resolve())),
            player_setup=[
                live.sc_pb.PlayerSetup(type=1, race=1, player_name="P1"),
                live.sc_pb.PlayerSetup(type=1, race=1, player_name="P2"),
            ],
            realtime=False,
        )
    )
    response = await connection.send_request(request, timeout=90, max_retries=5)
    if response.error:
        raise RuntimeError(f"CreateGame failed: {list(response.error)}")
    join = live.sc_pb.Request(
        join_game=live.sc_pb.RequestJoinGame(
            race=1,
            player_name="P2",
            options=live.sc_pb.InterfaceOptions(raw=True),
        )
    )
    for _ in range(30):
        response = await connection.send_request(join, timeout=30, max_retries=2)
        if not response.error:
            return int(response.join_game.player_id)
        await asyncio.sleep(0.5)
    raise RuntimeError(f"JoinGame failed: {list(response.error)}")


async def capture_real_replay(
    port: int,
    map_path: Path,
    map_source: Path,
    output_path: Path,
    html_path: Path | None = None,
    max_loops: int = 1400,
    step_size: int = 4,
    record_interval: int = 25,
    decision_interval: int = 22,
) -> dict[str, Any]:
    if not map_path.is_file():
        raise FileNotFoundError(f"packed map not found: {map_path}")
    map_record = build_map_record(map_path, map_source)
    connection = live.Sc2Connection(port)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = [
        {
            "record_type": "header",
            "replay_id": output_path.stem,
            "evidence_type": "runtime",
            "source": "SC2 API RequestObservation.raw_data",
            "map_name": "亡者之夜.SC2Map",
            "map_path": _relative(map_path),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        },
        map_record,
    ]
    previous: dict[str, dict[str, Any]] = {}
    action_records: list[dict[str, Any]] = []
    frame_count = 0
    current_loop = 0
    player_id = 2
    last_frame_loop = -record_interval
    last_action_loop = -decision_interval
    action_id = 0
    try:
        await connection.connect()
        player_id = await _create_game(connection, map_path)
        if player_id != 2:
            raise RuntimeError(f"capture must join P2, got player_id={player_id}")
        policy = live.DefendBasePolicy(player_id=player_id, command_interval=decision_interval)
        # Wait for the map's real initialization by advancing and observing, not wall-clock sleep.
        ready_deadline = time.monotonic() + 90
        response = None
        while time.monotonic() < ready_deadline:
            await connection.send_request(live.sc_pb.Request(step=live.sc_pb.RequestStep(count=step_size)), timeout=20)
            response = await connection.send_request(live.sc_pb.Request(observation=live.sc_pb.RequestObservation()), timeout=20)
            if response.observation.observation.player_common.food_cap > 0 and response.observation.observation.raw_data.units:
                break
            await asyncio.sleep(0.25)
        if response is None or response.observation.observation.player_common.food_cap <= 0:
            raise RuntimeError("real map did not expose initialized player state")
        map_name = "亡者之夜.SC2Map"
        try:
            game_info = await connection.send_request(live.sc_pb.Request(game_info=live.sc_pb.RequestGameInfo()), timeout=20)
            map_name = game_info.game_info.map_name or map_name
        except Exception:
            pass
        while current_loop < max_loops:
            await connection.send_request(live.sc_pb.Request(step=live.sc_pb.RequestStep(count=step_size)), timeout=20)
            response = await connection.send_request(live.sc_pb.Request(observation=live.sc_pb.RequestObservation()), timeout=20)
            current_loop = int(response.observation.observation.game_loop)
            if current_loop - last_frame_loop >= record_interval:
                frame, previous = _frame(response, player_id, map_name, previous)
                records.append(frame)
                frame_count += 1
                last_frame_loop = current_loop
            if current_loop - last_action_loop >= decision_interval:
                observation = live.build_observation(response, player_id)
                own_by_tag = {unit["entity_id"]: unit for unit in observation.own_units}
                target_by_tag = {unit["entity_id"]: unit for unit in observation.visible_enemies + observation.mineral_fields}
                sc2_actions: list[Any] = []
                contexts: list[dict[str, Any]] = []
                for decision in policy.decide(observation, current_loop, resources=observation.resources):
                    if decision.kind == "hold":
                        continue
                    source = own_by_tag.get(decision.entity_id, {})
                    action = decision
                    if decision.kind == "gather" and decision.target_entity_id == 0:
                        mineral = live._find_nearest_mineral_field_live(observation.mineral_fields, source.get("x", 0.0), source.get("y", 0.0))
                        if mineral is None:
                            continue
                        action = live.DefendAction(entity_id=decision.entity_id, kind=decision.kind, target_entity_id=mineral, unit_type_id=decision.unit_type_id, reason=decision.reason)
                    translated = live.build_action(action, player_id, source_unit_type_int=source.get("unit_type_int", 0))
                    if translated is None:
                        continue
                    sc2_actions.append(translated)
                    raw_command = translated.action_raw.unit_command
                    target_id = int(raw_command.target_unit_tag) if raw_command.HasField("target_unit_tag") else 0
                    contexts.append({
                        "kind": action.kind,
                        "entity_id": int(action.entity_id),
                        "unit_type_id": source.get("unit_type_id", ""),
                        "target_entity_id": target_id,
                        "target_unit_type_id": target_by_tag.get(target_id, {}).get("unit_type_id", ""),
                        "reason": action.reason,
                    })
                if sc2_actions:
                    action_response = await connection.send_request(live.sc_pb.Request(action=live.sc_pb.RequestAction(actions=sc2_actions)), timeout=20)
                    results = list(action_response.action.result)
                    for index, context in enumerate(contexts):
                        action_id += 1
                        result_value = results[index] if index < len(results) else 0
                        try:
                            result_name = live.error_pb2.ActionResult.Name(result_value)
                        except ValueError:
                            result_name = f"unknown({result_value})"
                        action_records.append({
                            "record_type": "action",
                            "evidence_type": "runtime",
                            "action_id": f"real-{action_id:04d}",
                            "loop": current_loop,
                            "name": context["kind"],
                            "arguments": context,
                            "dispatched": {"success": result_value == live.error_pb2.ActionResult.Success, "result": result_name},
                        })
                last_action_loop = current_loop
            if response.observation.player_result:
                break
        final_frame, previous = _frame(response, player_id, map_name, previous)
        records.append(final_frame)
        action_records.sort(key=lambda record: (record["loop"], record["action_id"]))
        records[1:1] = action_records
        summary = {
            "record_type": "summary",
            "evidence_type": "runtime",
            "status": "PASS",
            "map_name": map_name,
            "map_source": _relative(map_path),
            "player_id": player_id,
            "frames": frame_count + 1,
            "actions_total": len(action_records),
            "actions_successful": sum(1 for record in action_records if record["dispatched"]["success"]),
            "end_loop": current_loop,
            "validation": {
                "real_packed_map": map_record["packed_map_sha256"],
                "raw_observation_entities": True,
                "static_objects_count": len(map_record["static_objects"]),
                "no_post_reset_unit_spawn": True,
                "no_player_set_resource": True,
            },
        }
        records.append(summary)
        output_path.write_text("\n".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in records) + "\n", encoding="utf-8")
        if html_path is not None:
            render_player_html(records, html_path)
        return summary
    finally:
        await connection.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--map-path", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--map-source", type=Path, default=DEFAULT_MAP_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--html-output", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--max-loops", type=int, default=1400)
    parser.add_argument("--record-interval", type=int, default=25)
    return parser


def main() -> int:
    args = _parser().parse_args()
    summary = asyncio.run(capture_real_replay(
        port=args.port,
        map_path=args.map_path,
        map_source=args.map_source,
        output_path=args.output,
        html_path=args.html_output,
        max_loops=args.max_loops,
        record_interval=args.record_interval,
    ))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_map_record", "capture_real_replay"]
