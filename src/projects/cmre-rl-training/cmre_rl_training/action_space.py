"""RL action space built on existing BASIC_ACTION_ROUTES contract.

Action names mirror ``cmre_neuro_adapter.neuro.basic_actions.BASIC_ACTION_ROUTES``
so that RL actions map 1:1 to the existing transport-neutral command surface.
Stage 01 defines them locally to avoid cross-project import coupling; Stage 02
verifies alignment with the source of truth.
"""

from __future__ import annotations

from typing import Any, Mapping

try:
    import numpy as np
except ModuleNotFoundError as exc:  # pragma: no cover - dependency gate
    raise RuntimeError("numpy is required for RL action space") from exc


ACTION_NAMES: tuple[str, ...] = (
    "move_units",
    "stop_units",
    "hold_units",
    "patrol_units",
    "attack_move_units",
    "attack_units",
    "gather_resources",
    "build_structure",
    "produce_unit",
    "research_upgrade",
    "cast_point_ability",
    "cast_unit_ability",
    "cast_no_target_ability",
    "repair_units",
    "morph_unit",
    "cancel_order",
    "load_units",
    "unload_units",
    "rally_producer",
)
"""19 basic actions matching BASIC_ACTION_ROUTES in cmre_neuro_adapter."""

ACTION_INDEX: dict[str, int] = {name: i for i, name in enumerate(ACTION_NAMES)}
NUM_ACTIONS = len(ACTION_NAMES)

_WORKER_TYPES = frozenset({"SCV", "Probe", "Drone"})
_BASE_TYPES = frozenset({
    "CommandCenter", "OrbitalCommand", "PlanetaryFortress",
})
_PRODUCER_TYPES = frozenset({"CommandCenter", "Barracks", "Factory", "Starport"})
_TECH_TYPES = frozenset({
    "EngineeringBay", "Armory", "GhostAcademy", "FusionCore",
    "BarracksTechLab", "FactoryTechLab", "StarportTechLab",
})
_TRANSPORT_TYPES = frozenset({"Medivac", "Bunker", "WarpPrism", "Overlord", "NydusWorm"})
_STRUCTURE_TYPES = _BASE_TYPES | _PRODUCER_TYPES | _TECH_TYPES | frozenset({
    "SupplyDepot", "Refinery", "MissileTurret", "SensorTower",
    "BarracksReactor", "FactoryReactor", "StarportReactor",
})


def _unit_type(unit: Mapping[str, Any]) -> str:
    return str(unit.get("unit_type_id", ""))


def _is_worker(unit: Mapping[str, Any]) -> bool:
    return _unit_type(unit) in _WORKER_TYPES


def _is_combat(unit: Mapping[str, Any]) -> bool:
    ut = _unit_type(unit)
    return ut not in _WORKER_TYPES and ut not in _STRUCTURE_TYPES and ut != "Medivac"


def _is_producer(unit: Mapping[str, Any]) -> bool:
    return _unit_type(unit) in _PRODUCER_TYPES


def _is_tech(unit: Mapping[str, Any]) -> bool:
    return _unit_type(unit) in _TECH_TYPES


def _is_transport(unit: Mapping[str, Any]) -> bool:
    return _unit_type(unit) in _TRANSPORT_TYPES


def _has_orders(unit: Mapping[str, Any]) -> bool:
    return bool(unit.get("orders")) or str(unit.get("state", "")) in {
        "building", "gathering", "moving", "attack_moving", "training", "researching",
    }


def compute_action_mask(observation: Mapping[str, Any]) -> "np.ndarray":
    """Return boolean mask: ``True`` = action is legal given the observation.

    Masking rules:
    - Movement/combat actions (move/stop/hold/patrol/attack_move/attack) require
      at least one combat unit.
    - gather_resources and repair_units require at least one worker.
    - build_structure requires a worker AND >= 50 minerals.
    - produce_unit requires a production structure AND >= 50 minerals.
    - research_upgrade requires a tech structure AND >= 50 minerals.
    - cast_* abilities require at least one combat unit.
    - morph_unit requires at least one own unit.
    - cancel_order requires at least one unit with active orders.
    - load_units / unload_units require a transport-capable unit.
    - rally_producer requires a production structure.
    """

    mask = np.zeros(NUM_ACTIONS, dtype=bool)
    own_units = list(observation.get("own_units", []))
    resources = dict(observation.get("resources", {}))
    minerals = float(resources.get("minerals", 0))

    has_units = len(own_units) > 0
    has_workers = any(_is_worker(u) for u in own_units)
    has_combat = any(_is_combat(u) for u in own_units)
    has_producer = any(_is_producer(u) for u in own_units)
    has_tech = any(_is_tech(u) for u in own_units)
    has_transport = any(_is_transport(u) for u in own_units)
    has_orders = any(_has_orders(u) for u in own_units)
    can_afford = minerals >= 50.0

    if has_combat:
        for name in (
            "move_units", "stop_units", "hold_units", "patrol_units",
            "attack_move_units", "attack_units",
            "cast_point_ability", "cast_unit_ability", "cast_no_target_ability",
        ):
            mask[ACTION_INDEX[name]] = True

    if has_workers:
        mask[ACTION_INDEX["gather_resources"]] = True
        mask[ACTION_INDEX["repair_units"]] = True

    if has_workers and can_afford:
        mask[ACTION_INDEX["build_structure"]] = True

    if has_producer and can_afford:
        mask[ACTION_INDEX["produce_unit"]] = True

    if has_tech and can_afford:
        mask[ACTION_INDEX["research_upgrade"]] = True

    if has_units:
        mask[ACTION_INDEX["morph_unit"]] = True

    if has_orders:
        mask[ACTION_INDEX["cancel_order"]] = True

    if has_transport:
        mask[ACTION_INDEX["load_units"]] = True
        mask[ACTION_INDEX["unload_units"]] = True

    if has_producer:
        mask[ACTION_INDEX["rally_producer"]] = True

    return mask


__all__ = [
    "ACTION_NAMES",
    "ACTION_INDEX",
    "NUM_ACTIONS",
    "compute_action_mask",
]
