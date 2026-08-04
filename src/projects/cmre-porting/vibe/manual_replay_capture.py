"""Hold a real P1/P2 Computer game for manual demonstration capture.

The API connection only creates the game, joins P1, observes realtime state,
and saves the native replay. It never sends a player action, so the human UI
remains the sole source of P1 behavior.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from .run_dead_of_night_live import (
    INT_TO_NAME,
    PLAYER_TYPE_COMPUTER,
    PLAYER_TYPE_PARTICIPANT,
    P1_PLAYER_ID,
    P2_PLAYER_ID,
    Sc2Connection,
    sc_pb,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "artifacts"
    / "projects"
    / "cmre-porting"
    / "stage25-ai-ally-capability-completion"
)


def _unit_record(unit) -> dict:
    return {
        "tag": int(unit.tag),
        "unit_type": INT_TO_NAME.get(int(unit.unit_type), str(int(unit.unit_type))),
        "unit_type_int": int(unit.unit_type),
        "owner": int(unit.owner),
        "alliance": int(unit.alliance),
        "x": round(float(unit.pos.x), 3) if unit.HasField("pos") else 0.0,
        "y": round(float(unit.pos.y), 3) if unit.HasField("pos") else 0.0,
        "health": round(float(unit.health), 3),
        "health_max": round(float(unit.health_max), 3),
        "shield": round(float(unit.shield), 3),
        "build_progress": round(float(unit.build_progress), 4),
        "orders": [
            {
                "ability_id": int(order.ability_id),
                "progress": round(float(order.progress), 4),
                "target_unit_tag": int(getattr(order, "target_unit_tag", 0)),
            }
            for order in unit.orders
        ],
    }


def _observation_record(response: sc_pb.Response) -> dict:
    observation = response.observation.observation
    common = observation.player_common
    raw_units = list(observation.raw_data.units)
    return {
        "record_type": "frame",
        "evidence_type": "runtime",
        "loop": int(observation.game_loop),
        "p1_resources": {
            "minerals": int(common.minerals),
            "vespene": int(common.vespene),
            "supply_used": int(common.food_used),
            "supply_cap": int(common.food_cap),
        },
        "units": [_unit_record(unit) for unit in raw_units],
        "player_results": [
            {"player_id": int(result.player_id), "result": int(result.result)}
            for result in response.observation.player_result
        ],
    }


def _roster(game_info) -> dict[str, dict]:
    return {
        str(info.player_id): {
            "player_id": int(info.player_id),
            "type": int(info.type),
            "race_requested": int(info.race_requested),
            "race_actual": int(info.race_actual),
            "difficulty": int(info.difficulty),
            "player_name": info.player_name,
        }
        for info in game_info.player_info
    }


def _roster_is_expected(roster: dict[str, dict]) -> bool:
    return (
        roster.get(str(P1_PLAYER_ID), {}).get("type") == PLAYER_TYPE_PARTICIPANT
        and roster.get(str(P2_PLAYER_ID), {}).get("type") == PLAYER_TYPE_COMPUTER
    )


async def _create_and_join(conn: Sc2Connection, map_path: Path) -> dict[str, dict]:
    try:
        await conn.send_request(
            sc_pb.Request(leave_game=sc_pb.RequestLeaveGame()), timeout=10
        )
    except Exception:
        pass
    await asyncio.sleep(1.0)

    create = sc_pb.Request(
        create_game=sc_pb.RequestCreateGame(
            local_map=sc_pb.LocalMap(map_path=str(map_path.resolve())),
            player_setup=[
                sc_pb.PlayerSetup(
                    type=PLAYER_TYPE_PARTICIPANT,
                    race=1,
                    player_name="P1 Human",
                ),
                sc_pb.PlayerSetup(
                    type=PLAYER_TYPE_COMPUTER,
                    race=1,
                    difficulty=2,
                    player_name="P2 AI Ally",
                ),
            ],
            realtime=True,
        )
    )
    created = await conn.send_request(create, timeout=60, max_retries=5)
    if created.error:
        raise RuntimeError(f"CreateGame failed: {list(created.error)}")
    if created.HasField("create_game") and created.create_game.HasField("error"):
        raise RuntimeError(
            f"CreateGame failed: {created.create_game.error} "
            f"{created.create_game.error_details}"
        )

    join = sc_pb.Request(
        join_game=sc_pb.RequestJoinGame(
            race=1,
            player_name="P1 Human",
            options=sc_pb.InterfaceOptions(raw=True, score=True, show_placeholders=True),
        )
    )
    joined = await conn.send_request(join, timeout=60, max_retries=5)
    if joined.error:
        raise RuntimeError(f"JoinGame failed: {list(joined.error)}")
    if not joined.HasField("join_game") or joined.join_game.player_id != P1_PLAYER_ID:
        player_id = joined.join_game.player_id if joined.HasField("join_game") else 0
        raise RuntimeError(f"expected P1 join, got player_id={player_id}")

    deadline = time.monotonic() + 60.0
    while True:
        info_response = await conn.send_request(
            sc_pb.Request(game_info=sc_pb.RequestGameInfo()), timeout=20
        )
        roster = _roster(info_response.game_info)
        if _roster_is_expected(roster):
            return roster
        if time.monotonic() >= deadline:
            raise RuntimeError(f"unexpected player roster: {roster}")
        await asyncio.sleep(0.5)


async def capture(
    *,
    port: int,
    map_path: Path,
    output_dir: Path,
    poll_seconds: float,
    max_seconds: float,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    replay_jsonl = output_dir / "manual-runtime-observations.jsonl"
    replay_path = output_dir / "manual-native-replay.SC2Replay"
    status_path = output_dir / "manual-session.json"
    stop_path = output_dir / "STOP"
    start_time = time.time()
    result = {
        "schema": "cmre-manual-replay-session.v1",
        "status": "starting",
        "evidence_type": "runtime",
        "map_path": str(map_path),
        "output_dir": str(output_dir),
        "replay_path": str(replay_path),
        "observation_path": str(replay_jsonl),
        "roster": {},
        "frames": 0,
        "last_loop": 0,
        "player_results": [],
        "elapsed_seconds": 0.0,
    }

    def write_status() -> None:
        result["elapsed_seconds"] = round(time.time() - start_time, 2)
        status_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    conn = Sc2Connection(port)
    replay_file = replay_jsonl.open("w", encoding="utf-8")
    try:
        await conn.connect()
        roster = await _create_and_join(conn, map_path)
        result["roster"] = roster
        result["status"] = "ready_for_manual_play"
        result["instructions"] = (
            "Play P1 in the visible SC2 window. The capture process sends no actions. "
            "The native replay is saved after player_result or STOP."
        )
        write_status()

        deadline = time.monotonic() + max_seconds
        while time.monotonic() < deadline:
            if stop_path.exists():
                result["status"] = "stopped_by_marker"
                break
            response = await conn.send_request(
                sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=20
            )
            if response.error:
                result["status"] = "observation_error"
                result["error"] = list(response.error)
                break
            record = _observation_record(response)
            replay_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            replay_file.flush()
            result["frames"] += 1
            result["last_loop"] = record["loop"]
            if record["player_results"]:
                result["player_results"] = record["player_results"]
                result["status"] = "game_finished"
                break
            write_status()
            await asyncio.sleep(max(0.1, poll_seconds))
        else:
            result["status"] = "max_duration_reached"
    except KeyboardInterrupt:
        result["status"] = "interrupted"
    except Exception as exc:
        result["status"] = "capture_error"
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        replay_file.close()
        try:
            saved = await conn.send_request(
                sc_pb.Request(save_replay=sc_pb.RequestSaveReplay()),
                timeout=90,
                max_retries=2,
            )
            data = bytes(saved.save_replay.data)
            if data:
                replay_path.write_bytes(data)
                result["native_replay_saved"] = True
            else:
                result["native_replay_saved"] = False
                result["native_replay_error"] = "empty save_replay response"
        except Exception as exc:
            result["native_replay_saved"] = False
            result["native_replay_error"] = f"{type(exc).__name__}: {exc}"
        await conn.close()
        if result["status"] == "ready_for_manual_play":
            result["status"] = "capture_closed"
        write_status()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a manual P1 game with a native P2 Computer ally")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--max-seconds", type=float, default=4 * 60 * 60)
    args = parser.parse_args()
    output = args.out or (DEFAULT_OUTPUT_ROOT / f"manual-p1-{time.strftime('%Y%m%d-%H%M%S')}")
    report = asyncio.run(
        capture(
            port=args.port,
            map_path=args.map,
            output_dir=output,
            poll_seconds=args.poll_seconds,
            max_seconds=args.max_seconds,
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("native_replay_saved") else 1


if __name__ == "__main__":
    raise SystemExit(main())
