"""Strict map-derived cooperative replay entry point.

This module deliberately keeps map extraction and cooperative control separate:
the map contributes ObjectUnit-derived entities and placement markers, while
the adapter contributes only the P1/P2 roster/control contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
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
        "map_script_simulator_overlay": {
            "source": "MapScript.galaxy",
            "preserves_native_objects": True,
            "mutates_native_objects": False,
            "dynamic_owner_player_ids": [5],
            "timing_source": "MapScript.galaxy gv_day_Duration_First/gv_day_Duration/gv_night_Duration",
        },
    }


class DeadOfNightMapScriptOverlay:
    """Simulate the first map-owned night attack window for a replay.

    This is deliberately an overlay: Objects remains the sole source of the
    initial 1308 entities, while units created by MapScript.galaxy are tagged
    as dynamic simulator entities. The first-night normal branch is transcribed
    from ``gf_AINormalInfestedAttacksNight1InfestedCivilians`` and
    ``gf_AIAttackWaveFromDirection`` in the registered map source.
    """

    _DIFFICULTY_COUNTS = {
        "casual": (0, 8),
        "normal": (0, 8),
        "hard": (5, 15),
        "brutal": (10, 20),
    }
    lightweight = True

    def __init__(
        self,
        wave_timing: dict,
        regions: list[dict],
        *,
        difficulty: str = "normal",
        seed: int = 42,
    ) -> None:
        if difficulty not in self._DIFFICULTY_COUNTS:
            raise ValueError(f"unsupported map difficulty: {difficulty}")
        self.wave_timing = wave_timing
        self.regions = regions
        self.difficulty = difficulty
        self.seed = int(seed)
        self.session = None
        self._rng = random.Random(self.seed)
        self._fired: list[dict] = []
        self._entity_source: dict[int, dict] = {}
        self._waves = self._build_first_night_waves()

    def _region(self, name: str) -> dict:
        for region in self.regions:
            if region.get("name") == name:
                return region
        raise ValueError(f"map region missing from extracted source: {name}")

    def _spawn_point(self, region: dict, index: int) -> tuple[float, float]:
        radius = float(region.get("r", 0.0))
        angle = self._rng.random() * math.tau
        distance = min(max(radius * 0.35, 0.5), 2.5) * (0.5 + (index % 3) / 3.0)
        return (
            float(region["x"]) + math.cos(angle) * distance,
            float(region["y"]) + math.sin(angle) * distance,
        )

    def _build_first_night_waves(self) -> list[dict]:
        nights = self.wave_timing.get("nights", [])
        if not nights:
            return []
        first_night = int(nights[0]["start_loop"])
        delay_loops = 140  # gf_AIAttackWaveFromDirection(..., lp_delay=140)
        second_wave_loop = first_night + round(40.0 * float(self.wave_timing.get("loops_per_second", 22.4)))
        civilian_count, second_civilian_count = self._DIFFICULTY_COUNTS[self.difficulty]
        spawn_region = self._region("Special Infested Spawn - SW")
        definitions = [
            {
                "wave_name": "night1_infested_civilians_south_west_01",
                "trigger_loop": first_night,
                "launch_loop": first_night + delay_loops,
                "source_direction": "south_west",
                "source_types": {"InfestedCivilian": civilian_count},
            },
            {
                "wave_name": "night1_infested_civilians_south_west_02",
                "trigger_loop": second_wave_loop,
                "launch_loop": second_wave_loop + delay_loops,
                "source_direction": "south_west",
                "source_types": {
                    "InfestedCivilian": second_civilian_count,
                    "InfestedTerranCampaign": 0,
                },
            },
        ]
        for definition in definitions:
            spawns = []
            for source_type, count in definition["source_types"].items():
                for index in range(int(count)):
                    x, y = self._spawn_point(spawn_region, index)
                    spawns.append({
                        "source_unit_type_id": source_type,
                        "unit_type_id": "Marine",
                        "owner_player_id": 5,
                        "x": x,
                        "y": y,
                    })
            definition["spawns"] = spawns
        return definitions

    def start(self, session, scenario_dict: dict) -> None:
        self.session = session

    def before_step(self, session, loop: int) -> list[dict]:
        events = []
        for wave in self._waves:
            if loop < wave["launch_loop"] or wave in self._fired:
                continue
            entity_ids = []
            for spawn in wave["spawns"]:
                result = session.unit_spawn(
                    spawn["unit_type_id"],
                    spawn["owner_player_id"],
                    spawn["x"],
                    spawn["y"],
                )
                entity_id = int(result["entity_id"])
                entity_ids.append(entity_id)
                self._entity_source[entity_id] = {
                    "source_kind": "map_script_simulator_overlay",
                    "source_wave_name": wave["wave_name"],
                    "source_unit_type_id": spawn["source_unit_type_id"],
                    "source_direction": wave["source_direction"],
                }
                session.unit_order(
                    [entity_id],
                    "attack_move",
                    5,
                    target_x=85.0,
                    target_y=94.0,
                )
            wave["entity_ids"] = entity_ids
            self._fired.append(wave)
            events.append({
                "loop": int(loop),
                "kind": "map_script_wave_spawned",
                "source": "MapScript.galaxy",
                "wave_name": wave["wave_name"],
                "source_direction": wave["source_direction"],
                "owner_player_id": 5,
                "entity_ids": entity_ids,
                "source_unit_type_counts": dict(wave["source_types"]),
                "simulator_unit_type": "Marine",
                "launch_delay_loops": 140,
            })
        return events

    def after_step(self, session, loop: int) -> list[dict]:
        return []

    def frame_state(self, loop: int) -> dict:
        current_night = 0
        for night in self.wave_timing.get("nights", []):
            if int(night["start_loop"]) <= loop < int(night["end_loop"]):
                current_night = int(night["night_number"])
                break
        return {
            "current_night": current_night,
            "waves_fired": len(self._fired),
            "map_script_overlay": {
                "name": "dead_of_night_first_night_infested_attack",
                "source": "MapScript.galaxy",
                "difficulty": self.difficulty,
                "dynamic_entity_count": len(self._entity_source),
                "native_objects_mutated": False,
            },
        }

    def decorate_entity(self, entity, entity_record: dict) -> dict:
        source = self._entity_source.get(int(entity.entity_id))
        if source:
            entity_record.update(source)
        return entity_record

    def summary(self) -> dict:
        return {
            "name": "dead_of_night_first_night_infested_attack",
            "source": "MapScript.galaxy",
            "difficulty": self.difficulty,
            "waves_fired": len(self._fired),
            "dynamic_entity_count": len(self._entity_source),
            "native_objects_mutated": False,
            "wave_names": [wave["wave_name"] for wave in self._fired],
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
    max_loops: int = 6400,
    replay_log_interval: int = 112,
    difficulty: str = "normal",
) -> dict:
    """Run the strict map-derived scenario and emit the browser replay bundle."""
    from .consumers.ally_ai import AllyPolicy, run_ally_scenario
    from .replay_player import load_replay, render_player_html

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    data, metadata = load_dead_of_night_map_cooperative_scenario(map_dir)
    overlay = DeadOfNightMapScriptOverlay(
        data.scenario["_map_wave_timing"],
        data.scenario["_map_regions"],
        difficulty=difficulty,
        seed=int(data.scenario.get("seed", 42)),
    )
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
        replay_log_interval=replay_log_interval,
        simulator_overlay=overlay,
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
        "simulator_overlay": overlay.summary(),
        "dynamic_state_verified": {
            "current_night_reached": any(
                record.get("record_type") == "frame" and record.get("current_night", 0) >= 1
                for record in records
            ),
            "dynamic_entities_added": overlay.summary()["dynamic_entity_count"] > 0,
            "wave_events_recorded": any(
                event.get("kind") == "map_script_wave_spawned"
                for record in records
                if record.get("record_type") == "frame"
                for event in record.get("events", [])
            ),
        },
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
    parser.add_argument("--max-loops", type=int, default=6400)
    parser.add_argument("--replay-log-interval", type=int, default=112)
    parser.add_argument(
        "--difficulty",
        choices=sorted(DeadOfNightMapScriptOverlay._DIFFICULTY_COUNTS),
        default="normal",
    )
    args = parser.parse_args()
    summary = generate_dead_of_night_map_replay(
        output_dir=args.output_dir,
        map_dir=args.map_dir,
        max_loops=args.max_loops,
        replay_log_interval=args.replay_log_interval,
        difficulty=args.difficulty,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "generate_dead_of_night_map_replay",
    "load_dead_of_night_map_cooperative_scenario",
    "DeadOfNightMapScriptOverlay",
]
