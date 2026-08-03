"""Generate a complete map-scheduled Dead of Night simulator replay.

The map source remains read-only.  Its extracted Objects are embedded as the
static map layer, while the owned adapter runs a clean Terran opening through
the deterministic simulator and projects map-script-owned activity onto the
same world coordinates.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[4]
CMRE_PORTING_SRC = REPO_ROOT / "src" / "projects" / "cmre-porting"
if str(CMRE_PORTING_SRC) not in sys.path:
    sys.path.insert(0, str(CMRE_PORTING_SRC))

from vibe.contracts import Observation  # type: ignore
from vibe.defend_policy import DefendBasePolicy  # type: ignore
from vibe.map_replay import build_dead_of_night_map_cooperative_scenario  # type: ignore
from vibe.mission_engine import MissionEngine, Objective, Trigger, Wave  # type: ignore
from vibe.simulator_session import SimulatorSession  # type: ignore
from vibe.sim_path import ensure_simulator_on_path  # type: ignore

from .replay_player import render_player_html
from .map_script_extractor import FORCE_BUCKETS, SPECIAL_TYPE_CANDIDATES, extract_map_script

ensure_simulator_on_path()

from sc2_simulator.catalog.m7_units import m7_catalog  # noqa: E402

from .real_map_replay import build_map_record as build_real_map_record


PLAYER_ID = 1
ENEMY_PLAYERS = (3, 4, 5, 7)
MAP_NAME = "亡者之夜.SC2Map"
BASE_X = 85.0
BASE_Y = 94.0
LOOPS_PER_SECOND = 22.4
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
    / "full-game-replay-20260802"
    / "dead-of-night-full-simulator.jsonl"
)
DEFAULT_HTML = DEFAULT_OUTPUT.with_suffix(".html")
DYNAMIC_ENEMY_HEALTH_SCALE = 0.10
DEFAULT_DYNAMIC_ENEMY_DAMAGE_SCALE = 0.25
DEFAULT_STRUCTURE_HEALTH_SCALE = 0.20
NIGHT_DEFENDER_COOLDOWN_LOOPS = round(30.0 * LOOPS_PER_SECOND)
NIGHT_DEFENDER_LIFE_THRESHOLD = 150.0
DAYTIME_STRUCTURE_PUSH_COOLDOWN_LOOPS = round(40.0 * LOOPS_PER_SECOND)


_DIRECTION_REGIONS = {
    "north_west": "Special Infested Spawn - NW",
    "north_east": "Special Infested Spawn - NE",
    "south_east": "Special Infested Spawn - SE",
    "south_west": "Special Infested Spawn - SW",
}
_SOURCE_TO_SIM = {
    "InfestedCivilian": "Marine",
    "InfestedTerranCampaign": "Marine",
    "InfestedAbomination": "Roach",
    "InfestedExploder": "Baneling",
}
def _scaled_count(base_count: int, scale: float) -> int:
    if base_count <= 0 or scale <= 0:
        return 0
    return max(1, int(round(base_count * scale)))


def _region_lookup(regions: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(region.get("name")): region for region in regions}


def _force_source_types(resource_bucket: str) -> dict[str, int]:
    profile = FORCE_BUCKETS.get(resource_bucket)
    if profile is None:
        return {"InfestedCivilian": 8, "InfestedTerranCampaign": 4}
    return dict(profile["source_type_counts"])


def _build_map_record(map_path: Path, map_source: Path) -> dict[str, Any]:
    """Use the same source-derived map metadata as the live-map replay."""

    return build_real_map_record(map_path, map_source)


def _source_wave_specs(
    data: Any,
    script_model: dict[str, Any],
    *,
    time_scale: float,
    strength_scale: float,
    seed: int,
    boss_type: str = "Nydus",
) -> list[dict[str, Any]]:
    regions = _region_lookup(data.scenario["_map_regions"])
    rng = random.Random(seed)
    waves: list[dict[str, Any]] = []
    nights = {
        int(night["night_number"]): night
        for night in script_model.get("nights", [])
    }
    direction_cycle = ["south_west", "south_east", "north_west", "north_east"]

    def build_spawns(
        *,
        number: int,
        direction: str,
        source_types: dict[str, int],
        owner: int,
        simulator_type_by_source: dict[str, str],
    ) -> list[dict[str, Any]]:
        region = regions[_DIRECTION_REGIONS[direction]]
        spawns: list[dict[str, Any]] = []
        for source_type, base_count in source_types.items():
            count = _scaled_count(int(base_count), strength_scale)
            for spawn_index in range(count):
                angle = rng.random() * 6.283185307
                radius = min(max(float(region.get("r", 3.0)) * 0.35, 0.7), 2.8)
                distance = radius * (0.45 + (spawn_index % 3) / 3.0)
                spawns.append(
                    {
                        "unit_type_id": simulator_type_by_source[source_type],
                        "source_unit_type_id": source_type,
                        "owner_player_id": owner,
                        "x": round(float(region["x"]) + distance * math.cos(angle), 3),
                        "y": round(float(region["y"]) + distance * math.sin(angle), 3),
                    }
                )
        return spawns

    source_structure_points = [
        spawn
        for spawn in data.scenario.get("spawns", [])
        if int(spawn.get("owner_player_id", 0)) in (5, 7)
        and str(spawn.get("unit_type_id", "")).startswith((
            "Infestable",
            "Infested",
            "CreepTumor",
        ))
    ]

    def build_structure_spawns(
        *,
        number: int,
        source_types: dict[str, int],
        owner: int,
        simulator_type_by_source: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Project white-noise spawns onto the source infestation buildings."""

        if not source_structure_points:
            return build_spawns(
                number=number,
                direction="south_west",
                source_types=source_types,
                owner=owner,
                simulator_type_by_source=simulator_type_by_source,
            )
        spawns: list[dict[str, Any]] = []
        spawn_index = 0
        for source_type, base_count in source_types.items():
            count = _scaled_count(int(base_count), strength_scale)
            for _ in range(count):
                source = source_structure_points[spawn_index % len(source_structure_points)]
                spawn_index += 1
                angle = rng.random() * 6.283185307
                distance = 0.65 + (spawn_index % 3) * 0.25
                spawns.append(
                    {
                        "unit_type_id": simulator_type_by_source[source_type],
                        "source_unit_type_id": source_type,
                        "source_structure_index": (spawn_index - 1) % len(source_structure_points),
                        "owner_player_id": owner,
                        "x": round(float(source["x"]) + distance * math.cos(angle), 3),
                        "y": round(float(source["y"]) + distance * math.sin(angle), 3),
                    }
                )
        return spawns

    selection = script_model.get("special_selection", {})
    candidates = list(selection.get("candidates", ("Hunterling", "Spotter", "Kaboomer", "Choker")))
    selected_special_types = set(random.Random(seed + 1).sample(candidates, min(2, len(candidates))))
    if boss_type not in {"Nydus", "Stank"}:
        raise ValueError(f"unsupported replay boss branch: {boss_type}")

    normal_index = 0
    for call in script_model.get("normal_attack_calls", []):
        number = int(call["night"])
        night = nights[number]
        direction = call.get("direction")
        if not direction:
            options = list(call.get("direction_options") or direction_cycle)
            direction = options[normal_index % len(options)]
        normal_index += 1
        source_types = {
            key: int(value)
            for key, value in call.get("source_type_counts", {}).items()
            if int(value) > 0
        }
        if not source_types:
            continue
        trigger_loop = int(int(night["start_loop"]) * time_scale + round(float(call["offset_seconds"]) * LOOPS_PER_SECOND * time_scale))
        launch_loop = trigger_loop + round(int(call.get("delay_loops", 140)) * time_scale)
        index = int(call["source_call_index"])
        waves.append(
            {
                "name": f"night{number}_normal_{index:02d}",
                "night": number,
                "kind": "normal",
                "direction": direction,
                "trigger_loop": trigger_loop,
                "launch_loop": launch_loop,
                "source_trigger": call["source_trigger"],
                "source_call_index": index,
                "source_types": source_types,
                "spawns": build_spawns(
                    number=number,
                    direction=direction,
                    source_types=source_types,
                    owner=5,
                    simulator_type_by_source=_SOURCE_TO_SIM,
                ),
            }
        )

    for call in script_model.get("special_attack_calls", []):
        number = int(call["night"])
        night = nights.get(number)
        if night is None or int(call.get("count", 0)) <= 0:
            continue
        direction_options = list(call.get("direction_options") or direction_cycle)
        direction = direction_options[(number + int(call["source_call_index"])) % len(direction_options)]
        trigger_loop = int(int(night["start_loop"]) * time_scale + round(float(call["offset_seconds"]) * LOOPS_PER_SECOND * time_scale))
        source_type = str(call["source_special_type"])
        if source_type in SPECIAL_TYPE_CANDIDATES and source_type not in selected_special_types:
            continue
        if source_type == "Stank" and boss_type != "Stank":
            continue
        if source_type == "NydusWorm" and boss_type != "Nydus":
            continue
        if source_type == "NydusWorm":
            stage_index = 0
            force_profile = script_model.get("nydus_force_profile", {})
            for worm_index in range(int(call["count"])):
                worm_loop = trigger_loop + worm_index * round(2.0 * LOOPS_PER_SECOND * time_scale)
                first_force_loop = worm_loop + round(
                    (float(force_profile.get("post_spawn_delay_seconds", 6.0))
                     + float(force_profile.get("initial_delay_seconds", 20.0)))
                    * LOOPS_PER_SECOND * time_scale
                )
                for stage in force_profile.get("stage_plan", []):
                    for repeat_index in range(int(stage.get("repeat_count", 0))):
                        force_loop = first_force_loop + round(
                            stage_index * float(force_profile.get("repeat_interval_seconds", 60.0))
                            * LOOPS_PER_SECOND * time_scale
                        )
                        stage_index += 1
                        resource_bucket = str(stage.get("resource_bucket", "2Smaller"))
                        source_types = _force_source_types(resource_bucket)
                        force_direction = direction_options[(worm_index + stage_index) % len(direction_options)]
                        waves.append(
                            {
                                "name": f"night{number}_nydus_{int(call['source_call_index']):02d}_{worm_index:02d}_{stage_index:02d}",
                                "night": number,
                                "kind": "nydus_force",
                                "direction": force_direction,
                                "trigger_loop": worm_loop,
                                "launch_loop": force_loop,
                                "source_trigger": call["source_trigger"],
                                "source_call_index": int(call["source_call_index"]),
                                "source_special_type": "NydusWorm",
                                "source_types": source_types,
                                "source_force_bucket": resource_bucket,
                                "source_tech_bucket": str(stage.get("tech_bucket", "")),
                                "source_worm_index": worm_index + 1,
                                "source_stage": int(stage.get("stage", 0)),
                                "composition_source": "cooperative_ai_engine_projection",
                                "spawns": build_spawns(
                                    number=number,
                                    direction=force_direction,
                                    source_types=source_types,
                                    owner=3,
                                    simulator_type_by_source=_SOURCE_TO_SIM,
                                ),
                            }
                        )
            continue
        source_types = {source_type: int(call["count"])}
        simulator_type = str(call.get("simulator_unit_type") or "Zergling")
        waves.append(
            {
                "name": f"night{number}_special_{source_type.lower()}_{int(call['source_call_index']):02d}_{len(waves):03d}",
                "night": number,
                "kind": "special",
                "direction": direction,
                "trigger_loop": trigger_loop,
                "launch_loop": trigger_loop,
                "source_trigger": call["source_trigger"],
                "source_call_index": int(call["source_call_index"]),
                "source_special_type": source_type,
                "source_types": source_types,
                "spawns": build_spawns(
                    number=number,
                    direction=direction,
                    source_types=source_types,
                    owner=7,
                    simulator_type_by_source={source_type: simulator_type},
                ),
            }
        )
    generic_index = 0
    for call in script_model.get("generic_attack_calls", []):
        number = int(call["night"])
        night = nights.get(number)
        if night is None:
            continue
        generic_index += 1
        remaining_loops = round(float(call.get("night_end_remaining_seconds", 60.0)) * LOOPS_PER_SECOND * time_scale)
        launch_loop = int(int(night["end_loop"]) * time_scale) - remaining_loops
        direction = direction_cycle[(generic_index + number) % len(direction_cycle)]
        resource_bucket = str(call.get("resource_bucket", "2Smaller"))
        source_types = _force_source_types(resource_bucket)
        waves.append(
            {
                "name": f"night{number}_generic_{call['source_trigger']}_{generic_index:02d}",
                "night": number,
                "kind": "generic_force",
                "direction": direction,
                "trigger_loop": launch_loop,
                "launch_loop": launch_loop,
                "source_trigger": call["source_trigger"],
                "source_caller": call.get("source_caller", ""),
                "source_call_index": int(call.get("source_call_index", generic_index)),
                "source_types": source_types,
                "source_force_bucket": resource_bucket,
                "source_tech_bucket": str(call.get("tech_bucket", "")),
                "composition_source": "cooperative_ai_engine_projection",
                "spawns": build_spawns(
                    number=number,
                    direction=direction,
                    source_types=source_types,
                    owner=3,
                    simulator_type_by_source=_SOURCE_TO_SIM,
                ),
            }
        )

    # This service runs throughout the night and is separate from the named
    # attack triggers above.  Preserve its cooldown and quotas instead of
    # collapsing it into one synthetic attack at night start.
    white_noise = script_model.get("white_noise_spawn_profile", {})
    white_profiles = {
        int(profile["night"]): profile
        for profile in white_noise.get("profiles", [])
    }
    previous_quantities: dict[str, int] = {}
    for night in sorted(nights.values(), key=lambda item: int(item["night_number"])):
        number = int(night["night_number"])
        profile = white_profiles.get(number)
        if profile is None:
            quantities = dict(previous_quantities)
            cooldown_seconds = float(white_noise.get("night_6_cooldown_seconds", 20.0))
        else:
            quantities = {
                str(source_type): int(count)
                for source_type, count in profile.get("source_quantities", {}).items()
                if int(count) > 0
            }
            previous_quantities = dict(quantities)
            cooldown_seconds = float(profile.get("cooldown_seconds", 30.0))
        if not quantities:
            continue
        launch_loop = int(night["start_loop"] * time_scale)
        end_loop = int(night["end_loop"] * time_scale)
        cycle_index = 0
        while launch_loop < end_loop:
            cycle_index += 1
            waves.append(
                {
                    "name": f"night{number}_white_noise_{cycle_index:02d}",
                    "night": number,
                    "kind": "white_noise",
                    "direction": "structure_local",
                    "trigger_loop": launch_loop,
                    "launch_loop": launch_loop,
                    "source_trigger": white_noise.get("source_trigger", "gt_AIWhiteNoiseSpawning_Func"),
                    "source_call_index": cycle_index,
                    "source_types": quantities,
                    "source_selection_mode": white_noise.get("selection_mode", ""),
                    "composition_source": "MapScript.galaxy",
                    "source_cooldown_seconds": cooldown_seconds,
                    "spawns": build_structure_spawns(
                        number=number,
                        source_types=quantities,
                        owner=5,
                        simulator_type_by_source=_SOURCE_TO_SIM,
                    ),
                }
            )
            launch_loop += max(1, round(cooldown_seconds * LOOPS_PER_SECOND * time_scale))

    hybrid = script_model.get("hybrid_reinforcement_profile", {})
    hybrid_profiles = {
        int(profile["night"]): profile
        for profile in hybrid.get("profiles", [])
    }
    fallback_hybrid = hybrid.get("fallback_profile", {})
    hybrid_sim_types = {
        "HybridLight": str(hybrid.get("simulator_unit_types", {}).get("light", "Marauder")),
        "HybridHeavy": str(hybrid.get("simulator_unit_types", {}).get("heavy", "Ultralisk")),
    }
    for night in sorted(nights.values(), key=lambda item: int(item["night_number"])):
        number = int(night["night_number"])
        profile = hybrid_profiles.get(number, fallback_hybrid if number >= 5 else {})
        source_types = {
            "HybridLight": int(profile.get("light_count", 0)),
            "HybridHeavy": int(profile.get("heavy_count", 0)),
        }
        source_types = {key: value for key, value in source_types.items() if value > 0}
        if not source_types:
            continue
        launch_loop = int(
            int(night["start_loop"]) * time_scale
            + round(float(hybrid.get("delay_seconds", 60.0)) * LOOPS_PER_SECOND * time_scale)
        )
        waves.append(
            {
                "name": f"night{number}_hybrid_reinforcements",
                "night": number,
                "kind": "hybrid_reinforcement",
                "direction": direction_cycle[(number + 1) % len(direction_cycle)],
                "trigger_loop": launch_loop,
                "launch_loop": launch_loop,
                "source_trigger": hybrid.get("source_trigger", "gt_HybridReinforcements_Func"),
                "source_call_index": number,
                "source_types": source_types,
                "source_selection_mode": hybrid.get("selection_mode", ""),
                "source_defend_region_ids": list(hybrid.get("defend_region_ids", [])),
                "composition_source": "MapScript.galaxy",
                "spawns": build_spawns(
                    number=number,
                    direction=direction_cycle[(number + 1) % len(direction_cycle)],
                    source_types=source_types,
                    owner=3 if number % 2 else 4,
                    simulator_type_by_source=hybrid_sim_types,
                ),
            }
        )
    return sorted(waves, key=lambda item: (int(item["launch_loop"]), item["name"]))
    return waves


def _clean_scenario(
    data: Any,
    *,
    max_loops: int,
    initial_minerals: int,
    dynamic_structure_limit: int = 32,
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    catalog = m7_catalog()
    all_enemy_structures = [
        dict(spawn)
        for spawn in data.scenario["spawns"]
        if int(spawn["owner_player_id"]) in ENEMY_PLAYERS
        and catalog.get(spawn["unit_type_id"]).is_structure
        and catalog.get(spawn["unit_type_id"]).race != "neutral"
    ]
    # The full 344-unit Objects layer stays in the browser.  Only a
    # cross-map, source-derived objective slice enters the expensive combat
    # kernel; this keeps the replay responsive while preserving the original
    # map census and coordinates in the static layer.  Prefer structures with
    # no catalog weapon for the daytime cleanup objective: the original map's
    # defensive emplacements remain visible in the static layer, while the
    # replay army is not forced into an artificial siege against them.
    non_defensive_structures = [
        item
        for item in all_enemy_structures
        if getattr(catalog.get(item["unit_type_id"]), "weapon_ground", None) is None
        and getattr(catalog.get(item["unit_type_id"]), "weapon_air", None) is None
    ]
    objective_structures = non_defensive_structures or all_enemy_structures
    if len(objective_structures) <= dynamic_structure_limit:
        enemy_structures = objective_structures
    else:
        by_distance = sorted(
            objective_structures,
            key=lambda item: (item["x"] - BASE_X) ** 2 + (item["y"] - BASE_Y) ** 2,
        )
        nearby = by_distance[: dynamic_structure_limit // 2]
        stride = max(1, len(objective_structures) // max(1, dynamic_structure_limit - len(nearby)))
        spread = objective_structures[::stride][: dynamic_structure_limit - len(nearby)]
        seen = {(item["x"], item["y"], item["unit_type_id"]) for item in nearby}
        enemy_structures = nearby + [
            item for item in spread
            if (item["x"], item["y"], item["unit_type_id"]) not in seen
        ][: dynamic_structure_limit - len(nearby)]
    resources = [
        dict(spawn)
        for spawn in data.scenario["spawns"]
        if int(spawn["owner_player_id"]) == 0
        and spawn["unit_type_id"] in {"MineralField", "VespeneGeyser"}
    ]
    starting_units = [
        {"unit_type_id": "CommandCenter", "owner_player_id": PLAYER_ID, "x": BASE_X, "y": BASE_Y},
        *[
            {
                "unit_type_id": "SCV",
                "owner_player_id": PLAYER_ID,
                "x": BASE_X - 1.4 + (index % 4) * 0.9,
                "y": BASE_Y - 2.0 - (index // 4) * 0.8,
            }
            for index in range(8)
        ],
    ]
    players = [dict(player) for player in data.scenario["players"]]
    player_ids = {int(player["id"]) for player in players}
    if PLAYER_ID not in player_ids:
        players.append({"id": PLAYER_ID, "name": "User1", "race": "terran", "allies": [], "is_ai": True})
    for player_id in ENEMY_PLAYERS:
        if player_id not in player_ids:
            players.append({"id": player_id, "name": f"Enemy{player_id}", "race": "zerg", "allies": [], "is_ai": True})
    scenario = {
        "schema_version": "m7",
        "name": MAP_NAME,
        "players": sorted(players, key=lambda item: int(item["id"])),
        "spawns": [*resources, *enemy_structures, *starting_units],
        "commands": [],
        "max_loops": max_loops,
        "seed": 42,
        "strict": False,
        "win_condition": "custom",
        "initial_minerals": initial_minerals,
        "initial_vespene": 0,
    }
    return scenario, enemy_structures, len(all_enemy_structures)


def _source_entity_metadata(scenario: dict[str, Any], session: Any) -> dict[int, dict[str, Any]]:
    """Attach native ObjectUnit identity to entities created from map spawns."""

    pending: dict[tuple[int, str, float, float], list[dict[str, Any]]] = {}
    for spawn in scenario.get("spawns", []):
        source_object_id = spawn.get("source_object_id")
        if source_object_id is None:
            continue
        key = (
            int(spawn["owner_player_id"]),
            str(spawn["unit_type_id"]),
            round(float(spawn["x"]), 3),
            round(float(spawn["y"]), 3),
        )
        pending.setdefault(key, []).append(spawn)
    metadata: dict[int, dict[str, Any]] = {}
    for entity in session.world.entities.values():
        key = (
            int(entity.owner_player_id),
            str(entity.unit_type_id),
            round(entity.x.to_float(), 3),
            round(entity.y.to_float(), 3),
        )
        candidates = pending.get(key, [])
        if candidates:
            spawn = candidates.pop(0)
        else:
            nearby: list[tuple[float, list[dict[str, Any]], dict[str, Any]]] = []
            for pending_items in pending.values():
                for candidate in pending_items:
                    if (
                        int(candidate["owner_player_id"]) == int(entity.owner_player_id)
                        and str(candidate["unit_type_id"]) == str(entity.unit_type_id)
                    ):
                        dx = float(candidate["x"]) - entity.x.to_float()
                        dy = float(candidate["y"]) - entity.y.to_float()
                        distance_sq = dx * dx + dy * dy
                        if distance_sq <= 0.75 * 0.75:
                            nearby.append((distance_sq, pending_items, candidate))
            if not nearby:
                continue
            _, pending_items, spawn = min(nearby, key=lambda item: (item[0], int(item[2].get("source_object_id", 0))))
            pending_items.remove(spawn)
        source_object_id = int(spawn["source_object_id"])
        metadata[int(entity.entity_id)] = {
            "source": "Objects",
            "source_object_id": source_object_id,
            "source_map_id": f"map-{source_object_id}",
            "source_unit_type_id": str(spawn.get("source_unit_type_id", spawn["unit_type_id"])),
        }
    return metadata


def _annotate_map_record_for_simulation(
    map_record: dict[str, Any],
    scenario: dict[str, Any],
) -> None:
    """Mark which native map objects are represented by this finite replay."""

    source_spawns = {
        int(spawn["source_object_id"]): spawn
        for spawn in scenario.get("spawns", [])
        if spawn.get("source_object_id") is not None
    }
    for static_object in map_record.get("static_objects", []):
        source_object_id = static_object.get("source_object_id")
        spawn = source_spawns.get(int(source_object_id)) if source_object_id is not None else None
        static_object["simulated_in_replay"] = spawn is not None
        if spawn is not None:
            static_object["simulation_unit_type_id"] = str(spawn["unit_type_id"])
    map_record["simulation_alignment"] = {
        "source_object_count": len(map_record.get("static_objects", [])),
        "simulated_source_object_count": len(source_spawns),
        "unmodeled_source_objects_remain_static": True,
        "dynamic_entities_use_source_object_id": True,
    }


def _unit_record(entity: Any, meta: dict[int, dict[str, Any]]) -> dict[str, Any]:
    record = {
        "id": int(entity.entity_id),
        "t": str(entity.unit_type_id),
        "p": int(entity.owner_player_id),
        "x": round(entity.x.to_float(), 3),
        "y": round(entity.y.to_float(), 3),
        "hp": int(entity.health.raw),
        "alive": bool(entity.is_alive),
        "state": getattr(entity.state, "value", str(entity.state)),
        "gather_target_id": int(getattr(entity, "gather_target_id", 0)),
        "gather_phase": str(getattr(entity, "gather_phase", "")),
        "carry_minerals": int(getattr(entity, "carry_minerals", 0)),
        "carry_vespene": int(getattr(entity, "carry_vespene", 0)),
        "build_target_id": int(getattr(entity, "build_target_id", 0)),
        "build_progress": int(getattr(entity, "build_progress", 0)),
        "build_total_loops": int(getattr(entity, "build_total_loops", 0)),
        "production_queue": [
            {
                "product": str(item.product_unit_id),
                "remaining_loops": int(item.remaining_loops),
            }
            for item in getattr(entity, "production_queue", [])
        ],
    }
    if int(entity.entity_id) in meta:
        record.update(meta[int(entity.entity_id)])
    return record


def _current_night(wave_timing: dict[str, Any], loop: int, *, time_scale: float) -> int:
    for night in wave_timing["nights"]:
        start = int(int(night["start_loop"]) * time_scale)
        end = int(int(night["end_loop"]) * time_scale)
        if start <= loop < end:
            return int(night["night_number"])
    return 0


def _night_schedule_info(wave_timing: dict[str, Any]) -> tuple[int, str, str]:
    """Return labels derived from the extracted map schedule."""

    total_nights = len(wave_timing.get("nights", []))
    if total_nights < 1:
        raise ValueError("map wave timing must contain at least one night")
    objective_name = f"survive_all_{total_nights}_nights"
    win_condition = f"survive_all_{total_nights}_nights_and_clear_infestation"
    return total_nights, objective_name, win_condition


def _dispatch_policy_action(session: Any, action: Any, obs: Any) -> dict[str, Any]:
    if action.kind == "hold":
        return {"success": True, "operation": "hold"}
    target = next((unit for unit in obs.own_units if int(unit["entity_id"]) == int(action.entity_id)), None)
    if target is None:
        return {"success": False, "operation": action.kind, "error": "unit_missing"}
    try:
        resolved_target_id = int(action.target_entity_id)
        if action.kind == "gather":
            kind = "smart"
            target_id = int(action.target_entity_id)
            if target_id == 0:
                fields = list(obs.mineral_fields)
                if fields:
                        target_id = int(min(fields, key=lambda item: (item["x"] - target["x"]) ** 2 + (item["y"] - target["y"]) ** 2)["entity_id"])
            resolved_target_id = target_id
            session.unit_order([int(action.entity_id)], kind, PLAYER_ID, target_entity_id=target_id)
        elif action.kind == "attack":
            session.unit_order([int(action.entity_id)], "attack_unit", PLAYER_ID, target_entity_id=int(action.target_entity_id))
        elif action.kind == "move":
            session.unit_order([int(action.entity_id)], "move", PLAYER_ID, target_x=float(action.target_x), target_y=float(action.target_y))
        elif action.kind == "train":
            session.unit_order([int(action.entity_id)], "train", PLAYER_ID, unit_type_id=action.unit_type_id)
        elif action.kind == "build":
            session.unit_order(
                [int(action.entity_id)],
                "build",
                PLAYER_ID,
                target_entity_id=int(action.target_entity_id),
                target_x=float(action.target_x),
                target_y=float(action.target_y),
                unit_type_id=action.unit_type_id,
            )
        elif action.kind == "research":
            session.unit_order([int(action.entity_id)], "research", PLAYER_ID, unit_type_id=action.unit_type_id)
        else:
            return {"success": False, "operation": action.kind, "error": "unsupported_policy_action"}
    except Exception as exc:  # pragma: no cover - exercised by simulator failures
        return {"success": False, "operation": action.kind, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "success": True,
        "operation": action.kind,
        "resolved_target_entity_id": resolved_target_id,
    }


def _world_resources(session: Any) -> dict[str, int]:
    resources = session.query_player(PLAYER_ID)["resources"]
    return {
        "minerals": int(resources.get("minerals", 0)),
        "vespene": int(resources.get("vespene", 0)),
        "supply_used": int(resources.get("supply_used", 0)),
        "supply_cap": int(resources.get("supply_cap", 0)),
        "reserved_minerals": int(resources.get("reserved_minerals", 0)),
        "reserved_vespene": int(resources.get("reserved_vespene", 0)),
        "reserved_supply": int(resources.get("reserved_supply", 0)),
    }


def _configure_replay_policy(policy: DefendBasePolicy) -> None:
    """Tune the shared policy for a map replay's macro acceptance contract.

    The general policy owns a full Terran tech-tree strategy.  That is useful
    for the broader commander runner, but it delays the first Marines behind
    optional Factory/Starport tech.  This replay is specifically proving the
    native opening, economy, production, and night defense loop, so its
    adapter-local profile keeps only the map-relevant prerequisites.
    """

    policy.BUILD_PLAN = (
        {"unit_type_id": "SupplyDepot", "min_m": 100, "min_v": 0, "offset": (-5.0, 0.0)},
        {"unit_type_id": "Barracks", "min_m": 150, "min_v": 0, "offset": (5.0, 0.0)},
        {"unit_type_id": "Refinery", "min_m": 75, "min_v": 0, "offset": (0.0, 5.0)},
    )
    policy.BUILD_REQUIREMENTS = {"Barracks": ("SupplyDepot",)}
    policy.ARMY_COMP = {
        "Marine": {
            "proportion": 1.0,
            "priority": 0,
            "producer": "Barracks",
            "min_m": 50,
            "min_v": 0,
            "supply": 1,
        },
    }
    policy.UNIT_REQUIREMENTS = {}
    policy.RESEARCH_PLAN = ()
    # Four workers above the clean eight-SCV opening are enough to keep the
    # early Marine stream funded without starving the first-night defense.
    policy.SCV_CEIL = 12


def _enemy_structure_count(session: Any) -> int:
    catalog = session.world.catalog
    return sum(
        1
        for entity in session.world.entities.values()
        if entity.is_alive
        and int(entity.owner_player_id) in ENEMY_PLAYERS
        and catalog.get(entity.unit_type_id).is_structure
        and catalog.get(entity.unit_type_id).race != "neutral"
    )


def _build_context(
    session: Any,
    mission: MissionEngine,
    wave_timing: dict[str, Any],
    *,
    time_scale: float,
    last_night: int,
    structure_count: int,
    meta: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    loop = int(session.world.clock.now.loop)
    night = _current_night(wave_timing, loop, time_scale=time_scale)
    completed_nights = sum(
        loop >= int(int(item["end_loop"]) * time_scale)
        for item in wave_timing["nights"]
    )
    _, _, win_condition = _night_schedule_info(wave_timing)
    visible_enemies = [
        _unit_record(entity, meta)
        for entity in session.world.entities.values()
        if entity.is_alive and int(entity.owner_player_id) in ENEMY_PLAYERS
    ]
    own_units = [
        _unit_record(entity, meta)
        for entity in session.world.entities.values()
        if entity.is_alive and int(entity.owner_player_id) == PLAYER_ID
    ]
    resources = _world_resources(session)
    objective_data = [
        {"id": item.name, "name": item.name, "kind": item.kind, "status": item.status, "target": item.params.get("target_loops")}
        for item in mission.objectives
    ]
    return {
        "context_version": loop + 1,
        "state_version": loop,
        "source_loop": loop,
        "map": "dead-of-night",
        "player_id": PLAYER_ID,
        "mission": {
            "phase": "victory" if mission.terminated else ("night" if night else "day"),
            "night": max(night, completed_nights),
            "wave": len(mission._waves_fired),
            "terminated": mission.terminated,
            "end_reason": mission.end_reason if mission.terminated else "",
            "win_condition": win_condition,
            "objectives": objective_data,
            "enemy_structures_remaining": structure_count,
        },
        "own_units": own_units,
        "visible_enemies": visible_enemies,
        "resources": resources,
        "threats": visible_enemies,
    }


def _frame(
    session: Any,
    context: dict[str, Any],
    events: list[dict[str, Any]],
    meta: dict[int, dict[str, Any]],
    *,
    time_scale: float,
) -> dict[str, Any]:
    entities_by_player: dict[str, list[dict[str, Any]]] = {}
    for entity in session.world.entities.values():
        if not entity.is_alive:
            continue
        entities_by_player.setdefault(str(int(entity.owner_player_id)), []).append(_unit_record(entity, meta))
    loop = int(session.world.clock.now.loop)
    return {
        "record_type": "frame",
        "evidence_type": "simulator",
        "map": MAP_NAME,
        "loop": loop,
        "source_loop": round(loop / max(time_scale, 1e-9)),
        "ts_sec": round(loop / LOOPS_PER_SECOND, 2),
        "real_sec": round(loop / max(time_scale, 1e-9) / LOOPS_PER_SECOND, 2),
        "current_night": context["mission"]["night"],
        "waves_fired": context["mission"]["wave"],
        "entities_by_player": entities_by_player,
        "entity_count": sum(len(items) for items in entities_by_player.values()),
        "friendly_units_by_type": dict(Counter(item["t"] for item in entities_by_player.get("1", []))),
        "enemy_units_by_type": dict(
            Counter(
                item["t"]
                for owner, items in entities_by_player.items()
                if int(owner) in ENEMY_PLAYERS
                for item in items
            )
        ),
        "p1_resources": context["resources"],
        "context": context,
        "events": events,
    }


def _add_wave_events(
    session: Any,
    mission: MissionEngine,
    wave_specs: list[dict[str, Any]],
    meta: dict[int, dict[str, Any]],
    event_buffer: list[dict[str, Any]],
    known_ids: set[int],
    spawned_ids: list[int] | None = None,
    enemy_health_scale: float = DYNAMIC_ENEMY_HEALTH_SCALE,
    enemy_damage_scale: float = 1.0,
) -> None:
    for spec in wave_specs:
        if spec["name"] not in mission._waves_fired:
            continue
        ids = list(spawned_ids or [entity_id for entity_id in session.world.entities if entity_id not in known_ids])
        if not ids:
            continue
        ids = [
            entity_id
            for entity_id in ids
            if session.world.get_entity(entity_id).owner_player_id in ENEMY_PLAYERS
        ]
        spawn_by_entity_id = {
            entity_id: spawn
            for entity_id, spawn in zip(ids, spec.get("spawns", []), strict=False)
        }
        for entity_id in ids:
            entity = session.world.get_entity(entity_id)
            if entity is None:
                continue
            max_health = session.world.catalog.get(entity.unit_type_id).max_health.raw
            entity.health = entity.health.__class__(max(1, int(max_health * enemy_health_scale)))
            _apply_dynamic_enemy_damage_scale(entity, session.world.catalog, enemy_damage_scale)
            source_spawn = spawn_by_entity_id.get(entity_id)
            meta[entity_id] = {
                "source": "MapScript.galaxy",
                "source_wave": spec["name"],
                "source_trigger": spec.get("source_trigger", ""),
                "source_call_index": int(spec.get("source_call_index", 0)),
                "source_direction": spec["direction"],
                "source_special_type": spec.get("source_special_type", ""),
                "source_force_bucket": spec.get("source_force_bucket", ""),
                "source_tech_bucket": spec.get("source_tech_bucket", ""),
                "source_worm_index": spec.get("source_worm_index"),
                "source_stage": spec.get("source_stage"),
                "source_selection_mode": spec.get("source_selection_mode", ""),
                "source_structure_index": (
                    source_spawn.get("source_structure_index")
                    if source_spawn is not None
                    else None
                ),
                "composition_source": spec.get("composition_source", "source_call"),
                "source_unit_type_id": (
                    source_spawn.get("source_unit_type_id", "")
                    if source_spawn is not None
                    else next(
                        (
                            spawn["source_unit_type_id"]
                            for spawn in spec["spawns"]
                            if spawn["unit_type_id"] == entity.unit_type_id
                        ),
                        "",
                    )
                ),
            }
            owner = int(entity.owner_player_id)
            session.unit_order([entity_id], "attack_move", owner, target_x=BASE_X, target_y=BASE_Y)
            known_ids.add(entity_id)
        event_buffer.append(
            {
                "loop": int(session.world.clock.now.loop),
                "kind": (
                    "special_infested_spawned"
                    if spec.get("kind") == "special"
                    else "white_noise_infested_spawned"
                    if spec.get("kind") == "white_noise"
                    else "hybrid_reinforcements_spawned"
                    if spec.get("kind") == "hybrid_reinforcement"
                    else "map_script_force_spawned"
                    if spec.get("kind") in {"generic_force", "nydus_force"}
                    else "map_script_wave_spawned"
                ),
                "source": "MapScript.galaxy",
                "wave_name": spec["name"],
                "night": spec["night"],
                "wave_kind": spec.get("kind", "normal"),
                "source_trigger": spec.get("source_trigger", ""),
                "source_call_index": int(spec.get("source_call_index", 0)),
                "source_direction": spec["direction"],
                "source_force_bucket": spec.get("source_force_bucket", ""),
                "source_tech_bucket": spec.get("source_tech_bucket", ""),
                "source_worm_index": spec.get("source_worm_index"),
                "source_stage": spec.get("source_stage"),
                "source_selection_mode": spec.get("source_selection_mode", ""),
                "source_defend_region_ids": spec.get("source_defend_region_ids", []),
                "composition_source": spec.get("composition_source", "source_call"),
                "source_unit_type_counts": spec["source_types"],
                "entity_ids": ids,
                "entity_count": len(ids),
            }
        )


def _apply_dynamic_enemy_damage_scale(entity: Any, catalog: Any, damage_scale: float) -> None:
    """Scale only replay-spawned enemy weapons without mutating shared catalog data.

    The source wave schedule and unit identities remain unchanged.  The simulator's
    catalog is immutable, so the supported per-entity combat modifier is used to
    express the replay's explicit difficulty profile in the evidence header.
    """

    bounded_scale = max(0.0, min(1.0, float(damage_scale)))
    if bounded_scale >= 1.0:
        return
    unit_type = catalog.get(entity.unit_type_id)
    weapons = [
        weapon
        for weapon in (getattr(unit_type, "weapon_ground", None), getattr(unit_type, "weapon_air", None))
        if weapon is not None and not getattr(weapon, "is_heal", False)
    ]
    if not weapons:
        return
    max_damage = max(
        (weapon.damage.raw / 1024.0) * max(1, int(weapon.attacks))
        for weapon in weapons
    )
    reduction = int(math.ceil(max_damage * (1.0 - bounded_scale)))
    entity.weapon_damage_bonus = -max(0, reduction)


def build_full_game_replay(
    *,
    map_path: Path = DEFAULT_MAP,
    map_source: Path = DEFAULT_MAP_SOURCE,
    output_path: Path = DEFAULT_OUTPUT,
    html_path: Path | None = DEFAULT_HTML,
    max_loops: int | None = None,
    time_scale: float = 1.0,
    wave_strength_scale: float = 1.0,
    enemy_damage_scale: float = DEFAULT_DYNAMIC_ENEMY_DAMAGE_SCALE,
    replay_interval: int = 112,
    initial_minerals: int = 250,
    seed: int = 42,
    boss_type: str = "Nydus",
) -> dict[str, Any]:
    """Run the map-scheduled simulator game and write JSONL/HTML artifacts."""

    map_path = Path(map_path).resolve()
    map_source = Path(map_source).resolve()
    output_path = Path(output_path).resolve()
    if html_path is not None:
        html_path = Path(html_path).resolve()
    script_model = extract_map_script(map_source, difficulty="normal")
    data = build_dead_of_night_map_cooperative_scenario(map_source)
    # The legacy porting extractor supplies the native Object/Region scenario,
    # while this adapter owns the source-trigger extraction used by the full
    # replay. Replace only the timing/attack projection; native map entities
    # remain untouched.
    data.wave_timing = script_model
    data.scenario["_map_wave_timing"] = script_model
    data.scenario["_map_script_model"] = script_model
    total_nights, survive_objective_name, win_condition = _night_schedule_info(data.wave_timing)
    replay_interval = max(1, int(replay_interval))
    final_night_end = int(data.wave_timing["nights"][-1]["end_loop"] * time_scale)
    run_limit = max_loops or final_night_end + int(12 * LOOPS_PER_SECOND)
    scenario, enemy_structures, source_structure_count = _clean_scenario(
        data,
        max_loops=run_limit,
        initial_minerals=initial_minerals,
    )
    wave_specs = _source_wave_specs(
        data,
        script_model,
        time_scale=time_scale,
        strength_scale=wave_strength_scale,
        seed=seed,
        boss_type=boss_type,
    )
    dynamic_enemy_damage_scale = max(0.001, min(1.0, float(enemy_damage_scale)))
    session = SimulatorSession()
    session.scenario_load(scenario_dict=scenario, catalog="m7")
    session.set_wave_timing(
        {
            **data.wave_timing,
            "nights": [
                {
                    **night,
                    "start_loop": int(int(night["start_loop"]) * time_scale),
                    "end_loop": int(int(night["end_loop"]) * time_scale),
                }
                for night in data.wave_timing["nights"]
            ],
        }
    )
    session.scenario_reset()

    # Keep the source structures as real simulator objectives, but use the
    # existing compressed probe scale so the complete replay remains finite.
    # Keep source-derived targets observable without turning daylight into a
    # multi-minute siege against every defensive emplacement.  The original
    # 344 Objects remain untouched in the static map layer.
    structure_health_scale = DEFAULT_STRUCTURE_HEALTH_SCALE
    catalog = session.world.catalog
    for entity in session.world.entities.values():
        if int(entity.owner_player_id) in ENEMY_PLAYERS and catalog.get(entity.unit_type_id).is_structure:
            entity.health = entity.health.__class__(max(1, int(entity.health.raw * structure_health_scale)))

    mission = MissionEngine(session)
    mission.add_objective(
        Objective(
            name=survive_objective_name,
            kind="survive_loops",
            params={"target_loops": final_night_end},
        )
    )
    mission.add_objective(
        Objective(
            name="destroy_infestation_structures",
            kind="destroy_all_enemy_structures",
            params={"enemy_player_ids": list(ENEMY_PLAYERS), "defender_player_id": PLAYER_ID},
        )
    )
    for spec in wave_specs:
        mission.add_wave(Wave(name=spec["name"], at_loop=spec["launch_loop"], spawns=spec["spawns"]))

    active_enemy_ids: set[int] = set()
    structure_targeted_enemy_ids: set[int] = set()

    def enemy_attack_target(engine: Any, attacker: Any | None = None) -> int:
        live_structures = [
            entity
            for entity in engine.session.world.entities.values()
            if entity.is_alive
            and entity.entity_id in source_building_id_set
            and entity.owner_player_id in ENEMY_PLAYERS
            and catalog.get(entity.unit_type_id).is_structure
        ]
        if live_structures:
            if attacker is None:
                return min(entity.entity_id for entity in live_structures)
            return min(
                live_structures,
                key=lambda entity: (
                    (entity.x.to_float() - attacker.x.to_float()) ** 2
                    + (entity.y.to_float() - attacker.y.to_float()) ** 2,
                    entity.entity_id,
                ),
            ).entity_id
        defenders = [
            entity
            for entity in engine.session.world.entities.values()
            if entity.is_alive
            and entity.owner_player_id == PLAYER_ID
            and not catalog.get(entity.unit_type_id).is_structure
            and not catalog.get(entity.unit_type_id).is_worker
        ]
        if defenders:
            return min(entity.entity_id for entity in defenders)
        return min(
            (
                target.entity_id
                for target in engine.session.world.entities.values()
                if target.is_alive and target.owner_player_id == PLAYER_ID
            ),
            default=0,
        )

    mission.add_trigger(
        Trigger(
            name="map_enemy_attack_player_base",
            condition=lambda eng: any(
                entity.is_alive and entity.entity_id in active_enemy_ids
                for entity in eng.session.world.entities.values()
            ),
            action=lambda eng: [
                eng.session.unit_order(
                    [entity.entity_id],
                    "attack_unit",
                    entity.owner_player_id,
                    target_entity_id=enemy_attack_target(eng, entity),
                )
                for entity in eng.session.world.entities.values()
                if entity.is_alive
                and entity.entity_id in active_enemy_ids
                and entity.entity_id not in structure_targeted_enemy_ids
            ],
            cooldown=44,
        )
    )
    # Keep workers on the real mineral/gas loop while combat units defend the
    # base perimeter; the dynamic wave overlay is already damage-scaled and
    # should not freeze the economy merely by entering the outer base radius.
    policy = DefendBasePolicy(
        player_id=PLAYER_ID,
        base_region=(BASE_X, BASE_Y, 0.0),
        command_interval=44,
        econ_interval=88,
    )
    _configure_replay_policy(policy)
    marine_army_comp = dict(policy.ARMY_COMP)
    rng = random.Random(seed + 100)
    meta: dict[int, dict[str, Any]] = _source_entity_metadata(scenario, session)
    events: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    action_records: list[dict[str, Any]] = []
    known_ids = set(session.world.entities)
    last_night = 0
    last_record_loop = -replay_interval
    processed_events = 0
    action_id = 0
    reported_waves: set[str] = set()
    previous_alive_ids = set(session.world.entities)
    source_building_ids = sorted({
        entity.entity_id
        for entity in session.world.entities.values()
        if entity.owner_player_id in ENEMY_PLAYERS and catalog.get(entity.unit_type_id).is_structure
    })
    source_building_id_set = set(source_building_ids)
    infected_ids: set[int] = set()
    special_ids: set[int] = set()
    dynamic_enemy_ids: set[int] = set()
    nydus_active_ids: set[int] = set()
    nydus_active_cap = int(script_model.get("nydus_force_profile", {}).get("max_spawned_units", 100))
    nydus_forces_capped = 0
    destroyed_structures = 0
    initial_structure_count = len(source_building_ids)
    defender_cooldown_loops = round(
        float(script_model.get("night_defender_cooldown_seconds", 30.0)) * LOOPS_PER_SECOND
    )
    defender_life_threshold = float(script_model.get("night_defender_life_threshold", 150.0))
    next_defender_loop: dict[int, int] = {}
    damaged_structures_during_night: set[int] = set()
    extra_barracks_targets = [(90.0, 99.0), (90.0, 89.0)]
    extra_barracks_issued = 0
    last_structure_push_loop = -DAYTIME_STRUCTURE_PUSH_COOLDOWN_LOOPS
    extra_depot_targets = [
        (80.0, 100.0),
        (80.0, 88.0),
        (85.0, 100.0),
        (85.0, 88.0),
    ]
    extra_depots_issued = 0

    def spawn_night_defenders(source_id: int, at_loop: int, current_night: int) -> None:
        source = session.world.get_entity(source_id)
        if source is None or not source.is_alive:
            return
        if at_loop < next_defender_loop.get(source_id, -1):
            return
        if source.health.raw / 1024.0 >= defender_life_threshold:
            return
        spawned_ids: list[int] = []
        composition: list[dict[str, Any]] = []
        for rule in script_model.get("night_defender_rules", []):
            maximum = rule.get("night_max_exclusive")
            if current_night < int(rule["night_min"]):
                continue
            if maximum is not None and current_night >= int(maximum):
                continue
            count = _scaled_count(int(rule["count_per_structure"]), wave_strength_scale)
            if count <= 0:
                continue
            source_type = str(rule["source_unit_type"])
            simulator_type = str(rule["simulator_unit_type"])
            composition.append({"source_unit_type": source_type, "simulator_unit_type": simulator_type, "count": count})
            for _ in range(count):
                result = session.unit_spawn(
                    simulator_type,
                    5,
                    source.x.to_float(),
                    source.y.to_float(),
                )
                entity_id = int(result["entity_id"])
                spawned = session.world.get_entity(entity_id)
                if spawned is None:
                    continue
                max_health = session.world.catalog.get(spawned.unit_type_id).max_health.raw
                spawned.health = spawned.health.__class__(max(1, int(max_health * DYNAMIC_ENEMY_HEALTH_SCALE)))
                _apply_dynamic_enemy_damage_scale(spawned, catalog, dynamic_enemy_damage_scale)
                infected_ids.add(entity_id)
                dynamic_enemy_ids.add(entity_id)
                active_enemy_ids.add(entity_id)
                known_ids.add(entity_id)
                meta[entity_id] = {
                    "source": "MapScript.galaxy",
                    "source_trigger": "gf_AINightDefenderSpawn",
                    "source_kind": "building_reinforcement",
                    "source_structure_id": source_id,
                    "source_structure_type": source.unit_type_id,
                    "source_unit_type_id": source_type,
                }
                session.unit_order([entity_id], "attack_move", 5, target_x=BASE_X, target_y=BASE_Y)
                spawned_ids.append(entity_id)
        if not spawned_ids:
            return
        next_defender_loop[source_id] = at_loop + max(1, defender_cooldown_loops)
        events.append(
            {
                "loop": at_loop,
                "kind": "building_reinforcements_spawned",
                "source": "MapScript.galaxy",
                "source_trigger": "gf_AINightDefenderSpawn",
                "night": current_night,
                "source_structure_id": source_id,
                "source_structure_type": source.unit_type_id,
                "entity_ids": spawned_ids,
                "entity_count": len(spawned_ids),
                "composition": composition,
                "cooldown_seconds": round(defender_cooldown_loops / LOOPS_PER_SECOND, 3),
            }
        )

    def append_action_record(action: Any, dispatched: dict[str, Any], obs: Any, at_loop: int) -> None:
        nonlocal action_id
        action_id += 1
        action_records.append({
            "record_type": "action",
            "evidence_type": "simulator",
            "action_id": f"full-{action_id:05d}",
            "loop": at_loop,
            "name": action.kind,
            "arguments": {
                "entity_id": int(action.entity_id),
                "unit_type_id": action.unit_type_id,
                "target_entity_id": int(action.target_entity_id),
                "target_x": float(action.target_x),
                "target_y": float(action.target_y),
                "reason": action.reason,
            },
            "dispatched": dispatched,
        })

    def record_frame(force: bool = False) -> None:
        nonlocal last_record_loop
        loop = int(session.world.clock.now.loop)
        # Keep every event in the next sampled frame, but do not duplicate the
        # full entity census for every combat damage event.  Mission and
        # economy events remain exact in the aggregated frame event list.
        if not force and loop - last_record_loop < replay_interval:
            return
        context = _build_context(
            session,
            mission,
            data.wave_timing,
            time_scale=time_scale,
            last_night=last_night,
            structure_count=_enemy_structure_count(session),
            meta=meta,
        )
        records.append(_frame(session, context, list(events), meta, time_scale=time_scale))
        events.clear()
        last_record_loop = loop

    # The simulator still executes every underlying loop.  The adapter only
    # needs to regain control at policy, map-event, objective, or replay-frame
    # boundaries; calling scenario_step once per loop added avoidable Python
    # overhead and repeatedly rebuilt the simulator command table.
    scheduled_boundaries = {
        int(spec["launch_loop"])
        for spec in wave_specs
    }
    scheduled_boundaries.update(
        int(int(item[key]) * time_scale)
        for item in data.wave_timing["nights"]
        for key in ("start_loop", "end_loop")
    )
    scheduled_boundaries.add(final_night_end)

    def next_simulation_boundary(loop: int) -> int:
        candidates = [
            loop + policy.command_interval,
            ((loop // policy.command_interval) + 1) * policy.command_interval,
            last_record_loop + replay_interval,
            *(item for item in scheduled_boundaries if item > loop),
            run_limit,
        ]
        return min(max(loop + 1, int(item)) for item in candidates)

    def public_resources(observation: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Expose extracted neutral nodes to the policy as map-visible facts."""

        mineral_fields: list[dict[str, Any]] = []
        geysers: list[dict[str, Any]] = []
        for entity in session.world.entities.values():
            if not entity.is_alive or entity.unit_type_id not in {"MineralField", "VespeneGeyser"}:
                continue
            item = {
                "entity_id": int(entity.entity_id),
                "unit_type_id": entity.unit_type_id,
                "x": entity.x.to_float(),
                "y": entity.y.to_float(),
            }
            (mineral_fields if entity.unit_type_id == "MineralField" else geysers).append(item)
        return mineral_fields, geysers

    def policy_observation() -> Any:
        """Project dynamic combat threats while retaining the full public map replay."""

        observation = Observation.from_world(session.world, PLAYER_ID)
        observation.visible_enemies = [
            enemy
            for enemy in observation.visible_enemies
            if int(enemy.get("entity_id", 0)) in active_enemy_ids
        ]
        observation.mineral_fields, observation.vespene_geysers = public_resources(observation)
        return observation

    record_frame(force=True)
    while not mission.terminated and session.world.clock.now.loop < run_limit:
        loop = int(session.world.clock.now.loop)
        night = _current_night(data.wave_timing, loop, time_scale=time_scale)
        completed_nights = sum(loop >= int(int(item["end_loop"]) * time_scale) for item in data.wave_timing["nights"])
        if night != last_night:
            if night > last_night:
                events.append({"loop": loop, "kind": "night_started", "night": night, "source": "MapScript.galaxy"})
                regrouped = 0
                for entity in session.world.entities.values():
                    unit_type = catalog.get(entity.unit_type_id)
                    if (
                        entity.is_alive
                        and entity.owner_player_id == PLAYER_ID
                        and not unit_type.is_structure
                        and not unit_type.is_worker
                    ):
                        session.unit_order(
                            [entity.entity_id],
                            "move",
                            PLAYER_ID,
                            target_x=BASE_X - 4.0,
                            target_y=BASE_Y - 4.0,
                        )
                        regrouped += 1
                events.append({
                    "loop": loop,
                    "kind": "night_defense_regrouped",
                    "night": night,
                    "entity_count": regrouped,
                    "target": {"x": BASE_X - 4.0, "y": BASE_Y - 4.0},
                })
                night_plan = [
                    item for item in wave_specs
                    if int(item["night"]) == night
                ]
                events.append({
                    "loop": loop,
                    "kind": "night_attack_plan_armed",
                    "night": night,
                    "source": "MapScript.galaxy",
                    "normal_wave_count": sum(item.get("kind") == "normal" for item in night_plan),
                    "special_wave_count": sum(item.get("kind") == "special" for item in night_plan),
                    "source_trigger_count": len({item.get("source_trigger") for item in night_plan}),
                })
            else:
                cleared = 0
                for entity_id in list(dynamic_enemy_ids):
                    entity = session.world.get_entity(entity_id)
                    if entity is not None and entity.is_alive:
                        session.unit_kill(entity_id)
                        cleared += 1
                    dynamic_enemy_ids.discard(entity_id)
                    infected_ids.discard(entity_id)
                    special_ids.discard(entity_id)
                    active_enemy_ids.discard(entity_id)
                # Retreat orders cancel the simulator gather state.  Clear
                # the policy's bookkeeping too, so daylight reassigns those
                # workers instead of believing they are still mining/gassing.
                policy._gathering_scvs.clear()
                policy._gas_workers.clear()
                events.append({"loop": loop, "kind": "daytime_infected_cleared", "night": completed_nights, "entity_count": cleared})
            last_night = night

        before_wave_ids = set(session.world.entities)
        mission._fire_waves(loop)
        new_ids = sorted(
            entity_id
            for entity_id in set(session.world.entities) - before_wave_ids
            if session.world.get_entity(entity_id) is not None
            and session.world.get_entity(entity_id).owner_player_id in ENEMY_PLAYERS
        )
        pending_specs = [
            spec
            for spec in wave_specs
            if spec["name"] in mission._waves_fired
            and spec["name"] not in reported_waves
        ]
        cursor = 0
        for spec in pending_specs:
            spec_ids = new_ids[cursor : cursor + len(spec.get("spawns", []))]
            cursor += len(spec.get("spawns", []))
            if not spec_ids:
                continue
            suppressed_ids: list[int] = []
            if spec.get("kind") == "nydus_force":
                live_nydus_ids = [
                    entity_id
                    for entity_id in nydus_active_ids
                    if session.world.get_entity(entity_id) is not None
                    and session.world.get_entity(entity_id).is_alive
                ]
                capacity = max(0, nydus_active_cap - len(live_nydus_ids))
                if len(spec_ids) > capacity:
                    suppressed_ids = spec_ids[capacity:]
                    spec_ids = spec_ids[:capacity]
                    for entity_id in suppressed_ids:
                        session.unit_kill(entity_id)
                    nydus_forces_capped += 1
            for entity_id in spec_ids:
                dynamic_enemy_ids.add(entity_id)
                active_enemy_ids.add(entity_id)
                if spec.get("kind") == "nydus_force":
                    nydus_active_ids.add(entity_id)
            if suppressed_ids:
                events.append(
                    {
                        "loop": loop,
                        "kind": "map_script_force_capped",
                        "source": "MapScript.galaxy",
                        "source_trigger": spec.get("source_trigger", ""),
                        "wave_name": spec["name"],
                        "night": spec["night"],
                        "wave_kind": spec.get("kind"),
                        "active_unit_cap": nydus_active_cap,
                        "scheduled_entity_count": len(suppressed_ids) + len(spec_ids),
                        "suppressed_entity_count": len(suppressed_ids),
                    }
                )
            if not spec_ids:
                reported_waves.add(spec["name"])
                continue
            _add_wave_events(
                session,
                mission,
                [spec],
                meta,
                events,
                known_ids,
                spawned_ids=spec_ids,
                enemy_health_scale=DYNAMIC_ENEMY_HEALTH_SCALE,
                enemy_damage_scale=dynamic_enemy_damage_scale,
            )
            if spec.get("kind") == "normal" and int(spec["night"]) >= 2:
                live_structures = [
                    entity
                    for entity in session.world.entities.values()
                    if entity.is_alive
                    and entity.entity_id in source_building_id_set
                    and entity.owner_player_id in (5, 7)
                    and catalog.get(entity.unit_type_id).is_structure
                ]
                if not live_structures:
                    live_structures = [
                        entity
                        for entity in session.world.entities.values()
                        if entity.is_alive
                        and entity.entity_id in source_building_id_set
                        and entity.owner_player_id in ENEMY_PLAYERS
                        and catalog.get(entity.unit_type_id).is_structure
                    ]
                region = _region_lookup(data.scenario["_map_regions"]).get(
                    _DIRECTION_REGIONS.get(str(spec["direction"]), "")
                )
                if live_structures and region is not None:
                    target = min(
                        live_structures,
                        key=lambda item: (
                            (item.x.to_float() - float(region["x"])) ** 2
                            + (item.y.to_float() - float(region["y"])) ** 2,
                            item.entity_id,
                        ),
                    )
                    target_count = max(1, len(spec_ids) // 3)
                    targeted_ids = spec_ids[:target_count]
                    for entity_id in targeted_ids:
                        attacker = session.world.get_entity(entity_id)
                        if attacker is not None and attacker.is_alive:
                            structure_targeted_enemy_ids.add(entity_id)
                            session.unit_order(
                                [entity_id],
                                "attack_unit",
                                int(attacker.owner_player_id),
                                target_entity_id=int(target.entity_id),
                            )
                    events.append(
                        {
                            "loop": loop,
                            "kind": "map_wave_structure_targeted",
                            "source": "MapScript.galaxy",
                            "night": int(spec["night"]),
                            "source_trigger": spec.get("source_trigger", ""),
                            "source_direction": spec["direction"],
                            "attacker_entity_ids": targeted_ids,
                            "target_structure_id": int(target.entity_id),
                            "target_structure_source_object_id": meta.get(int(target.entity_id), {}).get("source_object_id"),
                        }
                    )
            reported_waves.add(spec["name"])

        # During daylight the player keeps a real attack order on the nearest
        # live map structure.  This makes the original destroy-infestation
        # objective observable instead of ending at a timer-only victory.
        if (
            night == 0
            and completed_nights >= 1
            and loop % 112 == 0
            and loop - last_structure_push_loop >= DAYTIME_STRUCTURE_PUSH_COOLDOWN_LOOPS
        ):
            structures = [
                entity
                for entity in session.world.entities.values()
                if entity.is_alive and entity.owner_player_id in ENEMY_PLAYERS and catalog.get(entity.unit_type_id).is_structure
            ]
            combat_units = [
                entity
                for entity in session.world.entities.values()
                if entity.is_alive and entity.owner_player_id == PLAYER_ID and not catalog.get(entity.unit_type_id).is_structure and not catalog.get(entity.unit_type_id).is_worker
            ]
            if structures and combat_units:
                # Keep a small home guard while nights are active.  Once the
                # source schedule is complete, release every surviving combat
                # unit so the destroy-infestation objective can actually
                # finish instead of repeatedly poking one remote structure.
                structures.sort(
                    key=lambda item: (
                        (item.x.raw - BASE_X) ** 2 + (item.y.raw - BASE_Y) ** 2,
                        item.entity_id,
                    )
                )
                clear_budget = min(
                    initial_structure_count,
                    max(5, completed_nights * 5),
                )
                structures = structures[:clear_budget]
                expeditionary_units = (
                    combat_units
                    if completed_nights >= total_nights
                    else combat_units[:2]
                )
                pushed_structure = False
                for index, unit in enumerate(expeditionary_units):
                    target = min(
                        structures,
                        key=lambda item: ((item.x.raw - unit.x.raw) ** 2 + (item.y.raw - unit.y.raw) ** 2, item.entity_id),
                    )
                    result = _dispatch_policy_action(
                        session,
                        type("ClearAction", (), {"kind": "attack", "entity_id": unit.entity_id, "target_entity_id": target.entity_id})(),
                        Observation.from_world(session.world, PLAYER_ID),
                    )
                    if result["success"]:
                        pushed_structure = True
                        events.append({"loop": loop, "kind": "daytime_structure_push", "entity_id": unit.entity_id, "target_entity_id": target.entity_id})
                if pushed_structure:
                    last_structure_push_loop = loop

        if loop % policy.command_interval == 0:
            obs = policy_observation()
            resource_view = _world_resources(session)
            resource_view["vespene_geysers"] = list(obs.vespene_geysers)

            # Keep worker growth ahead of the Marine queue once the native
            # opening is complete.  The shared policy intentionally optimizes
            # army composition first; this adapter replay must visibly prove
            # SCV production as well as combat production.
            opening_ready = all(
                any(
                    unit.get("unit_type_id") == required
                    and float(unit.get("build_progress", 1.0)) >= 1.0
                    for unit in obs.own_units
                )
                for required in ("SupplyDepot", "Barracks", "Refinery")
            )
            enemy_at_base = any(
                entity.is_alive
                and entity.entity_id in active_enemy_ids
                and (entity.x.to_float() - BASE_X) ** 2 + (entity.y.to_float() - BASE_Y) ** 2 <= 15.0 ** 2
                for entity in session.world.entities.values()
            )
            scv_count = sum(1 for unit in obs.own_units if unit.get("unit_type_id") == "SCV")
            command_center = next(
                (
                    entity for entity in session.world.entities.values()
                    if entity.is_alive
                    and entity.owner_player_id == PLAYER_ID
                    and entity.unit_type_id == "CommandCenter"
                    and entity.is_structure_complete
                    and not entity.production_queue
                ),
                None,
            )
            if (
                loop > 0
                and opening_ready
                and not enemy_at_base
                and scv_count < policy.SCV_CEIL
                and command_center is not None
                and resource_view["minerals"] - resource_view["reserved_minerals"] >= policy.SCV_COST_M
            ):
                scv_action = type(
                    "PriorityScvAction",
                    (),
                    {
                        "kind": "train",
                        "entity_id": int(command_center.entity_id),
                        "target_entity_id": 0,
                        "target_x": 0.0,
                        "target_y": 0.0,
                        "unit_type_id": "SCV",
                        "reason": "train_SCV_priority",
                    },
                )()
                dispatched = _dispatch_policy_action(session, scv_action, obs)
                append_action_record(scv_action, dispatched, obs, loop)
                obs = policy_observation()
                resource_view = _world_resources(session)
                resource_view["vespene_geysers"] = list(obs.vespene_geysers)

            live_barracks_count = sum(
                1
                for unit in obs.own_units
                if unit.get("unit_type_id") == "Barracks"
            )
            live_marine_count = sum(
                1
                for unit in obs.own_units
                if unit.get("unit_type_id") == "Marine"
            )
            # Bootstrap a small first-night force, then bank minerals for the
            # extra production buildings before returning to continuous Marine
            # production.  This prevents a single Barracks from consuming the
            # entire mineral stream forever.
            policy.ARMY_COMP = (
                marine_army_comp
                if live_barracks_count >= 3 or live_marine_count < 6
                else {}
            )
            for action in policy.decide(obs, loop, resources=resource_view):
                if action.kind == "hold":
                    continue
                dispatched = _dispatch_policy_action(session, action, obs)
                append_action_record(action, dispatched, obs, loop)

            # The shared policy deliberately de-duplicates building types.
            # A replay needs enough production throughput for the extracted
            # night schedule, so
            # add two additional Barracks only after the first one exists and
            # only when the simulator reports spendable minerals.  Positions
            # stay in the source map's P1 base perimeter.
            barracks = [
                entity
                for entity in session.world.entities.values()
                if entity.is_alive and entity.owner_player_id == PLAYER_ID and entity.unit_type_id == "Barracks"
            ]
            fresh_obs = Observation.from_world(session.world, PLAYER_ID)
            fresh_obs.mineral_fields, fresh_obs.vespene_geysers = public_resources(fresh_obs)
            fresh_resources = _world_resources(session)
            if (
                any(entity.is_structure_complete for entity in barracks)
                and len(barracks) >= 1
                and extra_barracks_issued < len(extra_barracks_targets)
            ):
                spendable_minerals = fresh_resources["minerals"] - fresh_resources["reserved_minerals"]
                enemy_at_base = any(
                    entity.is_alive
                    and entity.entity_id in active_enemy_ids
                    and (entity.x.to_float() - BASE_X) ** 2 + (entity.y.to_float() - BASE_Y) ** 2 <= 15.0 ** 2
                    for entity in session.world.entities.values()
                )
                if spendable_minerals >= 150 and not enemy_at_base:
                    target_x, target_y = extra_barracks_targets[extra_barracks_issued]
                    if any(
                        abs(entity.x.to_float() - target_x) < 0.1
                        and abs(entity.y.to_float() - target_y) < 0.1
                        for entity in barracks
                    ):
                        extra_barracks_issued += 1
                    else:
                        builder = next(
                            (
                                unit for unit in session.world.entities.values()
                                if unit.is_alive
                                and unit.owner_player_id == PLAYER_ID
                                and unit.unit_type_id == "SCV"
                                and unit.entity_id not in getattr(policy, "_gas_workers", set())
                                and getattr(unit.state, "value", str(unit.state)) in {"idle", "gathering"}
                                and not unit.build_target_id
                            ),
                            None,
                        )
                        if builder is not None:
                            repeat_action = type(
                                "RepeatBarracksAction",
                                (),
                                {
                                    "kind": "build",
                                    "entity_id": int(builder.entity_id),
                                    "target_entity_id": 0,
                                    "target_x": target_x,
                                    "target_y": target_y,
                                    "unit_type_id": "Barracks",
                                    "reason": "build_Barracks_repeat",
                                },
                            )()
                            dispatched = _dispatch_policy_action(session, repeat_action, fresh_obs)
                            append_action_record(repeat_action, dispatched, fresh_obs, loop)
                            if dispatched.get("success") and any(
                                abs(entity.x.to_float() - target_x) < 0.1
                                and abs(entity.y.to_float() - target_y) < 0.1
                                for entity in session.world.entities.values()
                                if entity.is_alive and entity.unit_type_id == "Barracks" and entity.owner_player_id == PLAYER_ID
                            ):
                                extra_barracks_issued += 1

            # Keep supply from hard-locking the real production queues after
            # the clean opening reaches 12 SCVs and the first Marine wave.
            fresh_resources = _world_resources(session)
            supply_remaining = (
                fresh_resources["supply_cap"]
                - fresh_resources["supply_used"]
                - fresh_resources["reserved_supply"]
            )
            depots = [
                entity
                for entity in session.world.entities.values()
                if entity.is_alive and entity.owner_player_id == PLAYER_ID and entity.unit_type_id == "SupplyDepot"
            ]
            if supply_remaining <= 1 and extra_depots_issued < len(extra_depot_targets):
                target_x, target_y = extra_depot_targets[extra_depots_issued]
                if any(
                    abs(entity.x.to_float() - target_x) < 0.1
                    and abs(entity.y.to_float() - target_y) < 0.1
                    for entity in depots
                ):
                    extra_depots_issued += 1
                elif (
                    fresh_resources["minerals"] - fresh_resources["reserved_minerals"] >= 100
                    and not any(
                        entity.is_alive
                        and entity.entity_id in active_enemy_ids
                        and (entity.x.to_float() - BASE_X) ** 2 + (entity.y.to_float() - BASE_Y) ** 2 <= 15.0 ** 2
                        for entity in session.world.entities.values()
                    )
                ):
                    builder = next(
                        (
                            entity for entity in session.world.entities.values()
                            if entity.is_alive
                            and entity.owner_player_id == PLAYER_ID
                            and entity.unit_type_id == "SCV"
                            and entity.entity_id not in getattr(policy, "_gas_workers", set())
                            and getattr(entity.state, "value", str(entity.state)) in {"idle", "gathering"}
                            and not entity.build_target_id
                        ),
                        None,
                    )
                    if builder is not None:
                        depot_action = type(
                            "ExtraDepotAction",
                            (),
                            {
                                "kind": "build",
                                "entity_id": int(builder.entity_id),
                                "target_entity_id": 0,
                                "target_x": target_x,
                                "target_y": target_y,
                                "unit_type_id": "SupplyDepot",
                                "reason": "build_SupplyDepot_repeat",
                            },
                        )()
                        depot_obs = Observation.from_world(session.world, PLAYER_ID)
                        depot_obs.mineral_fields, depot_obs.vespene_geysers = public_resources(depot_obs)
                        dispatched = _dispatch_policy_action(session, depot_action, depot_obs)
                        append_action_record(depot_action, dispatched, depot_obs, loop)
                        if dispatched.get("success") and any(
                            abs(entity.x.to_float() - target_x) < 0.1
                            and abs(entity.y.to_float() - target_y) < 0.1
                            for entity in session.world.entities.values()
                            if entity.is_alive and entity.owner_player_id == PLAYER_ID and entity.unit_type_id == "SupplyDepot"
                        ):
                            extra_depots_issued += 1

        step_end_loop = next_simulation_boundary(loop)
        session.scenario_step(step_end_loop - loop, snapshot=False)
        mission._fire_triggers(step_end_loop)
        new_emitted = session.world.events.emitted[processed_events:]
        processed_events = len(session.world.events.emitted)
        replay_event_kinds = {
            "build_started",
            "build_completed",
            "train_queued",
            "train_completed",
            "research_started",
            "research_completed",
            "gather_start_mining",
            "gather_picked_up",
            "gather_start_deposit",
            "mineral_deposited",
            "vespene_deposited",
            "resource_depleted",
            "damage",
            "entity_removed",
        }
        for emitted in new_emitted:
            kind = str(emitted.kind)
            if kind == "damage" and int(emitted.entity_id) in source_building_id_set:
                damaged_structures_during_night.add(int(emitted.entity_id))
            if kind not in replay_event_kinds:
                continue
            events.append({
                "loop": int(emitted.loop),
                "kind": kind,
                "entity_id": int(emitted.entity_id),
                "payload": dict(emitted.payload),
            })
        effective_night = _current_night(data.wave_timing, step_end_loop, time_scale=time_scale)
        if effective_night > 0:
            for source_id in sorted(damaged_structures_during_night):
                spawn_night_defenders(source_id, step_end_loop, effective_night)
            damaged_structures_during_night.clear()
        current_ids = set(session.world.entities)
        destroyed_structure_this_step = False
        for removed_id in previous_alive_ids - current_ids:
            old_meta = meta.get(removed_id, {})
            owner = old_meta.get("owner", 0)
            if removed_id in source_building_id_set:
                destroyed_structure_this_step = True
                destroyed_structures += 1
                destroy_event = {
                    "loop": step_end_loop,
                    "kind": "infested_structure_destroyed",
                    "entity_id": removed_id,
                    "remaining": _enemy_structure_count(session),
                }
                for field in ("source_object_id", "source_map_id", "source_unit_type_id"):
                    if field in old_meta:
                        destroy_event[field] = old_meta[field]
                events.append(destroy_event)
            elif removed_id in active_enemy_ids:
                events.append({"loop": step_end_loop, "kind": "enemy_unit_destroyed", "entity_id": removed_id, "owner": owner})
            active_enemy_ids.discard(removed_id)
        if destroyed_structure_this_step and night == 0:
            for entity in session.world.entities.values():
                unit_type = catalog.get(entity.unit_type_id)
                if (
                    entity.is_alive
                    and entity.owner_player_id == PLAYER_ID
                    and not unit_type.is_structure
                    and not unit_type.is_worker
                ):
                    session.unit_order([entity.entity_id], "hold_position", PLAYER_ID)
        previous_alive_ids = current_ids
        known_ids.update(current_ids)
        structure_targeted_enemy_ids.intersection_update(current_ids)
        nydus_active_ids.intersection_update(current_ids)
        mission._check_objectives(step_end_loop)
        if not any(entity.is_alive and entity.owner_player_id == PLAYER_ID and entity.unit_type_id == "CommandCenter" for entity in session.world.entities.values()):
            mission.terminated = True
            mission.end_reason = "player_base_destroyed"
        record_frame()

    if not mission.terminated and session.world.clock.now.loop >= run_limit:
        mission.terminated = True
        mission.end_reason = "max_loops_reached"
    record_frame(force=True)

    map_record = _build_map_record(map_path, map_source)
    _annotate_map_record_for_simulation(map_record, scenario)
    map_record["display_note"] = "真实地图 Objects + 原始坐标 simulator 动态回放"
    replay_events = [event for frame in records for event in frame.get("events", [])]
    mineral_deposits = [event for event in replay_events if event.get("kind") == "mineral_deposited"]
    vespene_deposits = [event for event in replay_events if event.get("kind") == "vespene_deposited"]
    training_completions = [event for event in replay_events if event.get("kind") == "train_completed"]
    building_completions = [event for event in replay_events if event.get("kind") == "build_completed"]
    mineral_collected = sum(int(event.get("payload", {}).get("amount", 0)) for event in mineral_deposits)
    vespene_collected = sum(int(event.get("payload", {}).get("amount", 0)) for event in vespene_deposits)
    production_counts = Counter(str(event.get("payload", {}).get("product", "")) for event in training_completions)
    building_counts = Counter(str(event.get("payload", {}).get("product", "")) for event in building_completions)
    header = {
        "record_type": "header",
        "schema_version": "cmre-full-game-replay.v1",
        "replay_id": "dead-of-night-full-simulator",
        "evidence_type": "simulator",
        "runtime_claim": "none; deterministic simulator evidence only",
        "map_name": MAP_NAME,
        "map_source": str(map_source.relative_to(REPO_ROOT)).replace("\\", "/"),
        "source_logic": {
            "map_script": "MapScript.galaxy",
            "map_script_sha256": script_model["source_sha256"],
            "normal_attack_triggers": sorted({item["source_trigger"] for item in script_model["normal_attack_calls"]}),
            "normal_attack_call_count": len(script_model["normal_attack_calls"]),
            "special_attack_call_count": len(script_model["special_attack_calls"]),
            "night_defender_rule_count": len(script_model["night_defender_rules"]),
            "white_noise_spawn_profile_count": int(script_model.get("white_noise_profile_count", 0)),
            "hybrid_reinforcement_profile_count": int(script_model.get("hybrid_profile_count", 0)),
            "selection_modes": sorted({item["selection_mode"] for item in script_model["special_attack_calls"]}),
            "day_night_transitions": True,
            "infection_cleanup": True,
            "building_reinforcements": True,
            "white_noise_spawning": True,
            "hybrid_reinforcements": True,
        },
        "simulation_contract": {
            "clean_opening": True,
            "initial_minerals": initial_minerals,
            "initial_p1_units": {"CommandCenter": 1, "SCV": 8},
            "enemy_structure_health_scale": structure_health_scale,
            "dynamic_enemy_health_scale": DYNAMIC_ENEMY_HEALTH_SCALE,
            "dynamic_enemy_damage_scale": dynamic_enemy_damage_scale,
            "time_scale": time_scale,
            "wave_strength_scale": wave_strength_scale,
            "source_wave_timing": data.wave_timing,
            "source_attack_plan": {
                "normal_calls": len(script_model["normal_attack_calls"]),
                "special_calls": len(script_model["special_attack_calls"]),
                "generic_force_calls": len(script_model.get("generic_attack_calls", [])),
                "white_noise_cycles": sum(spec.get("kind") == "white_noise" for spec in wave_specs),
                "hybrid_reinforcement_waves": sum(spec.get("kind") == "hybrid_reinforcement" for spec in wave_specs),
                "replay_waves": len(wave_specs),
                "replay_entity_budget": sum(len(spec["spawns"]) for spec in wave_specs),
            },
            "special_branch_selection": {
                "selected_types": sorted({
                    str(spec.get("source_special_type"))
                    for spec in wave_specs
                    if spec.get("kind") == "special"
                    and spec.get("source_special_type") in SPECIAL_TYPE_CANDIDATES
                }),
                "boss_type": boss_type,
                "source_selection_mode": script_model.get("special_selection", {}).get("selection_mode"),
            },
            "engine_force_projection": True,
            "source_structure_count": source_structure_count,
            "dynamic_structure_targets": len(enemy_structures),
            "policy_profile": "replay-native-opening",
            "policy_profile_steps": ["SupplyDepot", "Barracks", "Refinery", "Marine x continuous", "SCV to 16"],
            "extra_barracks_max": len(extra_barracks_targets),
            "scheduled_nights": total_nights,
            "win_condition": win_condition,
        },
    }
    summary = {
        "record_type": "summary",
        "status": "PASS" if mission.end_reason == "all_objectives_success" else "FAIL",
        "evidence_type": "simulator",
        "runtime_claim": "none; deterministic simulator evidence only",
        "map_name": MAP_NAME,
        "replay_id": header["replay_id"],
        "end_loop": int(session.world.clock.now.loop),
        "end_reason": mission.end_reason,
        "victory": mission.end_reason == "all_objectives_success",
        "actions_total": len(action_records),
        "actions_successful": sum(1 for item in action_records if item["dispatched"].get("success")),
        "actions_failed": sum(1 for item in action_records if not item["dispatched"].get("success")),
        "timeline_frames": len(records),
        "event_count": sum(len(item.get("events", [])) for item in records),
        "nights_completed": sum(
            int(session.world.clock.now.loop >= int(int(item["end_loop"]) * time_scale))
            for item in data.wave_timing["nights"]
        ),
        "waves_fired": len(mission._waves_fired),
        "expected_waves": len(wave_specs),
        "source_normal_attack_calls": len(script_model["normal_attack_calls"]),
        "source_special_attack_calls": len(script_model["special_attack_calls"]),
        "source_generic_attack_calls": len(script_model.get("generic_attack_calls", [])),
        "source_white_noise_profile_count": int(script_model.get("white_noise_profile_count", 0)),
        "source_hybrid_profile_count": int(script_model.get("hybrid_profile_count", 0)),
        "source_attack_entity_budget": sum(len(spec["spawns"]) for spec in wave_specs),
        "special_infested_spawned": sum(1 for item in records for event in item.get("events", []) if event.get("kind") == "special_infested_spawned"),
        "special_infested_units_spawned": sum(int(event.get("entity_count", 0)) for item in records for event in item.get("events", []) if event.get("kind") == "special_infested_spawned"),
        "white_noise_infested_spawned": sum(int(event.get("entity_count", 0)) for item in records for event in item.get("events", []) if event.get("kind") == "white_noise_infested_spawned"),
        "white_noise_infested_events": sum(1 for item in records for event in item.get("events", []) if event.get("kind") == "white_noise_infested_spawned"),
        "hybrid_reinforcements_spawned": sum(int(event.get("entity_count", 0)) for item in records for event in item.get("events", []) if event.get("kind") == "hybrid_reinforcements_spawned"),
        "hybrid_reinforcement_events": sum(1 for item in records for event in item.get("events", []) if event.get("kind") == "hybrid_reinforcements_spawned"),
        "map_script_force_spawned": sum(1 for item in records for event in item.get("events", []) if event.get("kind") == "map_script_force_spawned"),
        "map_script_force_units_spawned": sum(int(event.get("entity_count", 0)) for item in records for event in item.get("events", []) if event.get("kind") == "map_script_force_spawned"),
        "nydus_force_spawned": sum(1 for item in records for event in item.get("events", []) if event.get("kind") == "map_script_force_spawned" and event.get("wave_kind") == "nydus_force"),
        "nydus_forces_capped": nydus_forces_capped,
        "building_reinforcements_spawned": sum(int(event.get("entity_count", 0)) for item in records for event in item.get("events", []) if event.get("kind") == "building_reinforcements_spawned"),
        "structures_initial": initial_structure_count,
        "source_structures_in_static_layer": source_structure_count,
        "structures_remaining": _enemy_structure_count(session),
        "resources_collected": {
            "minerals": mineral_collected,
            "vespene": vespene_collected,
            "mineral_deposit_events": len(mineral_deposits),
            "vespene_deposit_events": len(vespene_deposits),
        },
        "production_completed": dict(sorted(production_counts.items())),
        "buildings_completed": dict(sorted(building_counts.items())),
        "objectives": [{"name": item.name, "kind": item.kind, "status": item.status} for item in mission.objectives],
        "static_objects_count": len(map_record["static_objects"]),
        "checks": {
            "clean_opening": True,
            "real_map_coordinates": True,
            "night_schedule": (
                len(mission._waves_fired) == len(wave_specs)
                and len(data.wave_timing["nights"]) == total_nights
            ),
            "resources_progressed": mineral_collected > 0 or vespene_collected > 0,
            "scv_production_observed": production_counts.get("SCV", 0) > 0,
            "marine_production_observed": production_counts.get("Marine", 0) > 0,
            "production_building_observed": building_counts.get("Barracks", 0) > 0,
            "structures_cleared": _enemy_structure_count(session) == 0,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    all_records = [header, map_record, *action_records, *records, summary]
    output_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in all_records) + "\n",
        encoding="utf-8",
    )
    if html_path is not None:
        render_player_html(all_records, html_path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-path", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--map-source", type=Path, default=DEFAULT_MAP_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--html-output", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--max-loops", type=int, default=None)
    parser.add_argument("--time-scale", type=float, default=1.0)
    parser.add_argument("--wave-strength-scale", type=float, default=1.0)
    parser.add_argument("--enemy-damage-scale", type=float, default=DEFAULT_DYNAMIC_ENEMY_DAMAGE_SCALE)
    parser.add_argument("--replay-interval", type=int, default=112)
    parser.add_argument("--initial-minerals", type=int, default=250)
    parser.add_argument("--boss-type", choices=("Nydus", "Stank"), default="Nydus")
    args = parser.parse_args()
    summary = build_full_game_replay(
        map_path=args.map_path,
        map_source=args.map_source,
        output_path=args.output,
        html_path=args.html_output,
        max_loops=args.max_loops,
        time_scale=args.time_scale,
        wave_strength_scale=args.wave_strength_scale,
        enemy_damage_scale=args.enemy_damage_scale,
        replay_interval=args.replay_interval,
        initial_minerals=args.initial_minerals,
        boss_type=args.boss_type,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_full_game_replay"]
