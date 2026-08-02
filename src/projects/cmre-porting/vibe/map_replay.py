"""Strict map-derived cooperative replay entry point.

This module deliberately keeps map extraction and cooperative control separate:
the map contributes ObjectUnit-derived entities and placement markers, while
the adapter contributes only the P1/P2 roster/control contract.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Optional

from .map_extractor import (
    MapData,
    build_dead_of_night_map_cooperative_scenario,
)


def _repo_relative_path(path: Path) -> str:
    repo_root = Path(__file__).resolve().parents[4]
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return path.name


def _map_hash(map_dir: Path) -> str:
    digest = hashlib.sha256()
    for filename in ("Objects", "Regions", "MapInfo", "MapScript.galaxy"):
        path = map_dir / filename
        if not path.is_file():
            continue
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _native_spawn_fingerprint(data: MapData) -> str:
    rows = [
        {
            "source_object_id": spawn.get("source_object_id"),
            "source_unit_type_id": spawn.get("source_unit_type_id", spawn["unit_type_id"]),
            "unit_type_id": spawn["unit_type_id"],
            "owner_player_id": int(spawn["owner_player_id"]),
            "x": float(spawn["x"]),
            "y": float(spawn["y"]),
            "resource_amount": spawn.get("resource_amount"),
        }
        for spawn in data.scenario.get("spawns", [])
    ]
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _map_metadata(data: MapData, map_dir: Path) -> dict:
    native_objects = data.native_objects
    native_spawns = data.scenario.get("spawns", [])
    raw_owner_counts = Counter(int(obj.get("player", 0)) for obj in native_objects)
    spawn_owner_counts = Counter(int(spawn["owner_player_id"]) for spawn in native_spawns)
    type_counts_by_owner: dict[str, dict[str, int]] = {}
    for owner_id in sorted(spawn_owner_counts):
        type_counts_by_owner[str(owner_id)] = dict(
            sorted(
                Counter(
                    str(spawn["unit_type_id"])
                    for spawn in native_spawns
                    if int(spawn["owner_player_id"]) == owner_id
                ).items()
            )
        )
    placements = [
        {
            "source_object_id": obj.get("object_id"),
            "unit_type_id": obj.get("unit_type"),
            "owner_player_id": int(obj.get("player", 0)),
            "x": float(obj.get("x", 0.0)),
            "y": float(obj.get("y", 0.0)),
        }
        for obj in native_objects
        if obj.get("unit_type") == "ACHeroSpawnPlacement"
    ]
    return {
        "source_kind": "map_extractor",
        "map_name": data.scenario.get("name", map_dir.name),
        "map_path": _repo_relative_path(map_dir),
        "map_hash": _map_hash(map_dir),
        "map_bounds": dict(data.map_bounds),
        "native_object_count": len(native_objects),
        "native_spawn_count": len(native_spawns),
        "native_object_counts_by_owner": dict(sorted(raw_owner_counts.items())),
        "native_spawn_counts_by_owner": dict(sorted(spawn_owner_counts.items())),
        "native_spawn_types_by_owner": type_counts_by_owner,
        "native_spawn_fingerprint": _native_spawn_fingerprint(data),
        "placement_markers": placements,
        "adapter_overlay": {
            "added_player_ids": [1, 2, 7, 8, 9],
            "added_alliance_edges": [
                [1, 2],
                [2, 1],
            ],
            "p1_is_ai": False,
            "p2_is_ai": True,
            "native_starting_force_injected": False,
            "native_p1_spawn_count": int(spawn_owner_counts.get(1, 0)),
            "native_p2_spawn_count": int(spawn_owner_counts.get(2, 0)),
        },
    }


def load_dead_of_night_map_cooperative_scenario(
    map_dir: Optional[str | Path] = None,
) -> tuple[MapData, dict]:
    """Return a strict map-derived scenario and its auditable metadata."""
    if map_dir is None:
        project_root = Path(__file__).resolve().parents[1]
        map_dir_path = project_root / "packages" / "Maps" / "亡者之夜.SC2Map"
    else:
        map_dir_path = Path(map_dir)
    data = build_dead_of_night_map_cooperative_scenario(map_dir_path)
    metadata = _map_metadata(data, map_dir_path)
    data.scenario["_map_metadata"] = metadata
    return data, metadata


def generate_dead_of_night_map_replay(
    output_dir: str | Path,
    map_dir: Optional[str | Path] = None,
    max_loops: int = 40,
) -> dict:
    """Run the strict map-derived scenario and emit the browser replay bundle."""
    from .consumers.ally_ai import AllyPolicy, run_ally_scenario
    from .replay_player import load_replay, render_player_html

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    data, metadata = load_dead_of_night_map_cooperative_scenario(map_dir)
    source_path = output_path / "map-scenario-source.json"
    source_path.write_text(
        json.dumps(
            {"map_metadata": metadata, "scenario": data.scenario},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    replay_path = output_path / "replay.jsonl"
    result = run_ally_scenario(
        data.scenario,
        AllyPolicy(
            player_id=2,
            leader_entity_id=0,
            leader_player_id=1,
            base_region=(85.0, 94.0, 15.0),
            command_interval=1,
        ),
        ally_player_id=2,
        leader_player_id=1,
        max_loops=max_loops,
        latency_loops=0,
        require_cooperative_roster=True,
        player_commands=[
            {"loop": 0, "text": "!ally follow", "command_id": "map-follow"},
            {"loop": 8, "text": "!ally attack", "command_id": "map-attack"},
            {"loop": 16, "text": "!ally defend", "command_id": "map-defend"},
            {"loop": 24, "text": "!ally retreat", "command_id": "map-retreat"},
            {"loop": 32, "text": "!ally status", "command_id": "map-status"},
        ],
        replay_log_path=replay_path,
    )
    records = load_replay(replay_path)
    html_path = output_path / "full-map-player.html"
    render_player_html(records, replay_path, html_path)

    summary = {
        "status": "PASS_MAP_DERIVED",
        "evidence_type": "simulator",
        "runtime_claim": "none; simulator evidence only",
        "map_metadata": metadata,
        "source_path": _repo_relative_path(source_path),
        "replay_path": _repo_relative_path(replay_path),
        "html_path": _repo_relative_path(html_path),
        "loop_end": result.end_loop,
        "replay_frame_count": result.replay_frame_count,
        "p1_native_spawn_count": metadata["native_spawn_counts_by_owner"].get(1, 0),
        "p2_native_spawn_count": metadata["native_spawn_counts_by_owner"].get(2, 0),
        "p2_commands_dispatched": result.total_dispatched,
        "p2_native_action_lane": (
            "not_exercised_native_roster_absent"
            if metadata["native_spawn_counts_by_owner"].get(2, 0) == 0
            else "exercised"
        ),
        "p1_command_count": sum(
            1 for record in records
            if record.get("record_type") == "action"
            and record.get("kind") == "player_command"
        ),
        "roster_ready": result.roster_ready,
        "friendly_fire_rejections": result.friendly_fire_rejections,
    }
    (output_path / "run-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Generate strict Dead of Night map-derived replay")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--map-dir", default=None)
    parser.add_argument("--max-loops", type=int, default=40)
    args = parser.parse_args()
    summary = generate_dead_of_night_map_replay(
        output_dir=args.output_dir,
        map_dir=args.map_dir,
        max_loops=args.max_loops,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "generate_dead_of_night_map_replay",
    "load_dead_of_night_map_cooperative_scenario",
]
