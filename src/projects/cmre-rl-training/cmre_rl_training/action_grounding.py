"""Ground high-level policy actions into canonical SC2 action arguments."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .action_space import ACTION_NAMES
from .map_profiles import MapProfile


class ActionGroundingError(ValueError):
    """Raised when an action has no legal actor or target in the observation."""


class ActionGrounder:
    """Resolve policy actions without embedding transport-specific IDs."""

    def __init__(self, profile: MapProfile, *, player_id: int = 1) -> None:
        self.profile = profile
        self.player_id = int(player_id)

    def ground(self, action_id: str, observation: Mapping[str, Any] | None) -> dict[str, Any]:
        if action_id not in ACTION_NAMES:
            raise ActionGroundingError(f"unknown_action:{action_id}")
        obs = observation if isinstance(observation, Mapping) else {}
        own = _units(obs.get("own_units", ()))
        if not own:
            raise ActionGroundingError("no_own_units")

        actors = _actors(action_id, own)
        if not actors:
            raise ActionGroundingError(f"no_actor_for:{action_id}")
        args: dict[str, Any] = {
            "entity_ids": [int(_entity_id(unit)) for unit in actors],
            "issuer_player_id": self.player_id,
        }

        if action_id in {"move_units", "patrol_units", "attack_move_units", "rally_producer"}:
            role = "attack" if action_id == "attack_move_units" else "defend"
            args.update(_point_args(self.profile, role, obs))
        elif action_id == "build_structure":
            args.update(_point_args(self.profile, "defend", obs))
            args["unit_type_id"] = "SupplyDepot"
        elif action_id == "attack_units":
            args["target_entity_id"] = _target_id(obs.get("visible_enemies", ()), "no_visible_enemy")
        elif action_id == "gather_resources":
            args["target_entity_id"] = _target_id(obs.get("mineral_fields", ()), "no_resource_target")
        elif action_id in {"repair_units", "cast_unit_ability"}:
            args["target_entity_id"] = _target_id(obs.get("own_units", ()), "no_unit_target")
        elif action_id == "load_units":
            cargo = [
                unit for unit in own
                if _unit_type(unit) not in {
                    "Medivac", "Bunker", "WarpPrism", "Overlord", "NydusWorm",
                }
            ]
            args["target_entity_id"] = _target_id(cargo, "no_cargo_target")
        elif action_id == "produce_unit":
            args["unit_type_id"] = "Marine"
        elif action_id == "research_upgrade":
            args["upgrade_id"] = "TerranInfantryWeaponsLevel1"
        elif action_id in {"cast_point_ability", "cast_no_target_ability"}:
            args["ability_id"] = "Stimpack"
            if action_id == "cast_point_ability":
                args.update(_point_args(self.profile, "attack", obs))
        elif action_id == "cast_unit_ability":
            args["ability_id"] = "Repair"
            args["target_entity_id"] = _target_id(obs.get("own_units", ()), "no_unit_target")
        elif action_id == "repair_units":
            args["target_entity_id"] = _target_id(obs.get("own_units", ()), "no_unit_target")
        elif action_id == "morph_unit":
            args["unit_type_id"] = "SiegeTankSieged"
        return args


def _actors(action_id: str, own: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    if action_id in {"gather_resources", "build_structure", "repair_units"}:
        workers = [unit for unit in own if _unit_type(unit) in {"SCV", "Probe", "Drone"}]
        return workers[:1]
    if action_id in {"produce_unit", "research_upgrade", "rally_producer"}:
        producers = [
            unit for unit in own
            if _unit_type(unit) in {
                "CommandCenter", "OrbitalCommand", "PlanetaryFortress", "Barracks",
                "Factory", "Starport", "EngineeringBay", "Armory", "GhostAcademy",
                "FusionCore", "BarracksTechLab", "FactoryTechLab", "StarportTechLab",
            }
        ]
        return producers[:1]
    if action_id in {"load_units", "unload_units"}:
        transports = [unit for unit in own if _unit_type(unit) in {"Medivac", "Bunker", "WarpPrism", "Overlord", "NydusWorm"}]
        return transports[:1]
    if action_id == "cancel_order":
        ordered = [unit for unit in own if unit.get("orders") or unit.get("state") in {"building", "training", "researching"}]
        return (ordered or own)[:1]
    combat = [
        unit for unit in own
        if _unit_type(unit) not in {
            "SCV", "Probe", "Drone", "CommandCenter", "OrbitalCommand", "PlanetaryFortress",
            "Barracks", "Factory", "Starport", "EngineeringBay", "Armory", "GhostAcademy",
            "FusionCore", "BarracksTechLab", "FactoryTechLab", "StarportTechLab", "Medivac",
        }
    ]
    return (combat or own)[:1]


def _point_args(profile: MapProfile, role: str, observation: Mapping[str, Any]) -> dict[str, float]:
    x, y = profile.point_for(role, observation)
    return {"target_x": float(x), "target_y": float(y)}


def _target_id(values: Any, error_code: str) -> int:
    if not isinstance(values, (list, tuple)):
        raise ActionGroundingError(error_code)
    for value in values:
        if isinstance(value, Mapping):
            raw = value.get("entity_id", value.get("tag"))
            if raw is not None:
                try:
                    return int(raw)
                except (TypeError, ValueError):
                    continue
    raise ActionGroundingError(error_code)


def _units(values: Any) -> list[Mapping[str, Any]]:
    if not isinstance(values, (list, tuple)):
        return []
    return [value for value in values if isinstance(value, Mapping)]


def _unit_type(unit: Mapping[str, Any]) -> str:
    return str(unit.get("unit_type_id", ""))


def _entity_id(unit: Mapping[str, Any]) -> int:
    value = unit.get("entity_id", unit.get("tag", 0))
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ActionGroundingError("unit_entity_id_invalid") from exc


__all__ = ["ActionGrounder", "ActionGroundingError"]
