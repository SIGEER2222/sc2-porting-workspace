"""Public structured observation encoder for the P2 policy."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Mapping

from ..ml_policy import FEATURE_NAMES as LEGACY_FEATURE_NAMES
from ..ml_policy import encode_observation as encode_legacy_observation


FEATURE_SCHEMA = "cmre-ally-observation.v2"
EXTRA_FEATURE_NAMES = (
    "own_command_centers", "own_barracks", "own_factories", "own_starports",
    "own_refineries", "own_supply_depots", "idle_workers", "busy_workers",
    "active_producers", "queued_products", "researching", "completed_upgrades",
    "visible_mineral_fields", "visible_geysers", "mission_progress",
    "p1_command_active", "state_version", "enemy_near_base_ratio",
    "enemy_near_leader_ratio", "allied_combat_ratio", "own_combat_ratio",
)
FEATURE_NAMES = tuple(f"base.{name}" for name in LEGACY_FEATURE_NAMES) + EXTRA_FEATURE_NAMES


def _get(observation, name: str, default):
    if isinstance(observation, Mapping):
        return observation.get(name, default)
    return getattr(observation, name, default)


def _unit_type(unit: Mapping) -> str:
    return str(unit.get("unit_type_id", ""))


def _is_worker(unit: Mapping) -> bool:
    return _unit_type(unit) in {"SCV", "Probe", "Drone"}


def _is_structure(unit: Mapping) -> bool:
    return _unit_type(unit) in {
        "CommandCenter", "OrbitalCommand", "PlanetaryFortress", "SupplyDepot",
        "Barracks", "Factory", "Starport", "EngineeringBay", "Armory",
        "FusionCore", "TechLab", "Reactor", "Refinery", "GhostAcademy",
        "MissileTurret", "Bunker", "SensorTower", "BarracksTechLab",
        "BarracksReactor", "FactoryTechLab", "FactoryReactor",
        "StarportTechLab", "StarportReactor",
    }


def _is_combat(unit: Mapping) -> bool:
    return not _is_worker(unit) and not _is_structure(unit) and _unit_type(unit) != "Medivac"


def _distance(a: Mapping, b: Mapping) -> float:
    return math.hypot(
        float(a.get("x", 0.0)) - float(b.get("x", 0.0)),
        float(a.get("y", 0.0)) - float(b.get("y", 0.0)),
    )


def _has_order(unit: Mapping) -> bool:
    return bool(unit.get("orders")) or str(unit.get("state", "")) in {
        "building", "gathering", "moving", "attack_moving", "training", "researching",
    }


def encode_observation(
    observation,
    requested_mode: str = "follow",
    base_region: tuple[float, float, float] = (85.0, 94.0, 14.0),
    support_range: float = 14.0,
) -> list[float]:
    """Encode only the public Observation surface into a stable vector."""

    base = encode_legacy_observation(observation, requested_mode, base_region, support_range)
    own = list(_get(observation, "own_units", ()) or ())
    allies = list(_get(observation, "visible_allies", ()) or ())
    enemies = list(_get(observation, "visible_enemies", ()) or ())
    resources = dict(_get(observation, "resources", {}) or {})
    mission = dict(_get(observation, "mission", {}) or {})
    own_types = Counter(_unit_type(unit) for unit in own)
    workers = [unit for unit in own if _is_worker(unit)]
    combat = [unit for unit in own if _is_combat(unit)]
    producers = [unit for unit in own if _unit_type(unit) in {"CommandCenter", "Barracks", "Factory", "Starport"}]
    leader = next((unit for unit in allies if int(unit.get("owner", -1)) == 1), None)
    bx, by, br = map(float, base_region)
    near_base = [
        unit for unit in enemies
        if math.hypot(float(unit.get("x", 0.0)) - bx, float(unit.get("y", 0.0)) - by) <= br
    ]
    near_leader = [unit for unit in enemies if leader is not None and _distance(unit, leader) <= support_range]
    allied_combat = [unit for unit in allies if _is_combat(unit)]
    resources_state = resources.get("state_version", mission.get("state_version", 0))
    state_version = max(0, int(resources_state or 0))
    mission_progress = float(mission.get("progress", 0.0) or 0.0)
    if mission_progress > 1.0:
        mission_progress /= 100.0
    values = [
        min(1.0, own_types["CommandCenter"] / 4.0),
        min(1.0, own_types["Barracks"] / 8.0),
        min(1.0, own_types["Factory"] / 6.0),
        min(1.0, own_types["Starport"] / 4.0),
        min(1.0, own_types["Refinery"] / 6.0),
        min(1.0, own_types["SupplyDepot"] / 12.0),
        min(1.0, sum(not _has_order(unit) for unit in workers) / 40.0),
        min(1.0, sum(_has_order(unit) for unit in workers) / 40.0),
        min(1.0, sum(_has_order(unit) for unit in producers) / 12.0),
        min(1.0, sum(len(unit.get("orders", ())) for unit in own) / 24.0),
        min(1.0, sum(bool(unit.get("research_upgrade_id")) for unit in own) / 4.0),
        min(1.0, len(dict(_get(observation, "tech", {}) or {}).get("completed_upgrades", ())) / 12.0),
        min(1.0, len(_get(observation, "mineral_fields", ()) or ()) / 32.0),
        min(1.0, len(_get(observation, "vespene_geysers", ()) or ()) / 8.0),
        max(0.0, min(1.0, mission_progress)),
        0.0 if str(requested_mode).lower() == "follow" else 1.0,
        min(1.0, state_version / 100000.0),
        min(1.0, len(near_base) / max(1.0, len(enemies) or 1.0)),
        min(1.0, len(near_leader) / max(1.0, len(enemies) or 1.0)),
        min(1.0, len(allied_combat) / 32.0),
        min(1.0, len(combat) / 40.0),
    ]
    result = [float(value) for value in (*base, *values)]
    if len(result) != len(FEATURE_NAMES):
        raise AssertionError("p2_feature_schema_drift")
    return result


def feature_schema_hash() -> str:
    payload = json.dumps(
        {"schema": FEATURE_SCHEMA, "features": FEATURE_NAMES},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
