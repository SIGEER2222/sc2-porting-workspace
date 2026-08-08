"""Ground high-level policy actions into canonical SC2 action arguments."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .action_space import ACTION_NAMES
from .map_profiles import MapProfile


class ActionGroundingError(ValueError):
    """Raised when an action has no legal actor or target in the observation."""


#: Which producer structure can actually train a given unit type.
#: ``produce_unit`` must pick a *matching* producer, not merely the first one
#: in observation order (a CommandCenter cannot train a Marine).
PRODUCER_FOR_UNIT: dict[str, tuple[str, ...]] = {
    "SCV": ("CommandCenter", "OrbitalCommand", "PlanetaryFortress"),
    "Marine": ("Barracks",),
    "Marauder": ("Barracks",),
    "Reaper": ("Barracks",),
    "Ghost": ("Barracks",),
    "Hellion": ("Factory",),
    "SiegeTank": ("Factory",),
    "Thor": ("Factory",),
    "Medivac": ("Starport",),
    "Viking": ("Starport",),
    "Banshee": ("Starport",),
}

#: Default unit each producer can train, used when the policy asks to produce
#: but no specific unit type is pinned by the caller.
DEFAULT_PRODUCT = "Marine"


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
        elif action_id == "repair_units":
            args["target_entity_id"] = _target_id(obs.get("own_units", ()), "no_unit_target")
        elif action_id == "cast_unit_ability":
            # NOTE: this branch must stay ahead of any broader membership test,
            # otherwise ``ability_id`` is never set and dispatch rejects the
            # command with "missing required argument 'ability_id'".
            #
            # "Repair" is a CommandKind, NOT an ability, so the old hard-coded
            # value always failed with "unknown ability: Repair". Pick a real
            # unit-targeted ability whose caster we actually own instead.
            ability, caster = _pick_ability(own, "cast_unit")
            args["ability_id"] = ability
            args["entity_ids"] = [int(_entity_id(caster))]
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
            # Pick a producer that can actually train the product. Falling back
            # to ``producers[0]`` picks a CommandCenter and the simulator then
            # rejects the order with "需要 Barracks".
            product, producer = _match_producer(own)
            args["unit_type_id"] = product
            if producer is not None:
                args["entity_ids"] = [int(_entity_id(producer))]
        elif action_id == "research_upgrade":
            args["upgrade_id"] = "TerranInfantryWeaponsLevel1"
        elif action_id in {"cast_point_ability", "cast_no_target_ability"}:
            # The caster matters: the simulator rejects the order outright when
            # the selected entity cannot cast the ability (e.g. the old
            # unconditional "Stimpack" on whatever unit came first produced
            # "SupplyDepot 不能施放 Stimpack" on every single step).
            kind = "cast_point" if action_id == "cast_point_ability" else "cast_no_target"
            ability, caster = _pick_ability(own, kind)
            args["ability_id"] = ability
            args["entity_ids"] = [int(_entity_id(caster))]
            if action_id == "cast_point_ability":
                args.update(_point_args(self.profile, "attack", obs))
        elif action_id == "morph_unit":
            product, source = _pick_morph(own)
            args["unit_type_id"] = product
            args["entity_ids"] = [int(_entity_id(source))]
        return args


# Mirrors the simulator's ``CatalogSnapshot.abilities[*].kind`` and
# ``casters_by_ability`` for the m7 catalog. Keeping a static copy here avoids
# a hard dependency on the simulator package from the grounding layer while
# still refusing to emit orders the engine is guaranteed to reject.
ABILITY_TABLE: dict[str, tuple[str, tuple[str, ...]]] = {
    "Stimpack": ("cast_no_target", ("Marine", "Marauder")),
    "SiegeMode": ("cast_no_target", ("SiegeTank",)),
    "Unsiege": ("cast_no_target", ("SiegeTank",)),
    "GuardianShield": ("cast_no_target", ("Sentry",)),
    "CloakOnBanshee": ("cast_no_target", ("Banshee",)),
    "CloakOnGhost": ("cast_no_target", ("Ghost",)),
    "BurrowDown": (
        "cast_no_target",
        ("Zergling", "Baneling", "Roach", "Hydralisk", "Infestor", "Ultralisk", "Drone"),
    ),
    "Blink": ("cast_point", ("Stalker",)),
    "PsionicStorm": ("cast_point", ("HighTemplar",)),
    "EMP": ("cast_point", ("Ghost",)),
    "FungalGrowth": ("cast_point", ("Infestor",)),
    "SpawnLocusts": ("cast_point", ("SwarmHost",)),
    "Heal": ("cast_unit", ("Medivac",)),
    "Feedback": ("cast_unit", ("HighTemplar",)),
    "YamatoCannon": ("cast_unit", ("Battlecruiser",)),
    "Abduct": ("cast_unit", ("Viper",)),
    "NeuralParasite": ("cast_unit", ("Infestor",)),
    "SpawnLarva": ("cast_unit", ("Queen",)),
}

# Morph products keyed by the unit type that can morph into them. Terran has no
# morphs in the m7 catalog (SiegeMode is an ability, not a morph), so a Terran
# scenario legitimately has no groundable morph.
MORPH_SOURCES: dict[str, tuple[str, ...]] = {
    "Larva": (
        "Drone", "Overlord", "Zergling", "Roach", "Hydralisk",
        "Mutalisk", "Corruptor", "Infestor", "SwarmHost", "Viper", "Queen",
    ),
    "Zergling": ("Baneling",),
    "Corruptor": ("BroodLord",),
    "Gateway": ("WarpGate",),
    "Drone": ("Hatchery", "SpawningPool", "Extractor", "EvolutionChamber"),
}


def _pick_ability(
    own: list[Mapping[str, Any]], kind: str
) -> tuple[str, Mapping[str, Any]]:
    """Return ``(ability_id, caster)`` for an ability we can actually cast.

    Raises ``ActionGroundingError`` when no owned unit can cast anything of the
    requested kind, so the action is skipped rather than dispatched into a
    guaranteed engine rejection.
    """

    by_type: dict[str, Mapping[str, Any]] = {}
    for unit in own:
        by_type.setdefault(_unit_type(unit), unit)
    for ability, (ability_kind, casters) in ABILITY_TABLE.items():
        if ability_kind != kind:
            continue
        for caster_type in casters:
            unit = by_type.get(caster_type)
            if unit is not None:
                return ability, unit
    raise ActionGroundingError(f"no_caster_for:{kind}")


def _pick_morph(own: list[Mapping[str, Any]]) -> tuple[str, Mapping[str, Any]]:
    """Return ``(product, source_unit)`` for a viable morph order."""

    by_type: dict[str, Mapping[str, Any]] = {}
    for unit in own:
        by_type.setdefault(_unit_type(unit), unit)
    for source_type, products in MORPH_SOURCES.items():
        unit = by_type.get(source_type)
        if unit is not None and products:
            return products[0], unit
    raise ActionGroundingError("no_morph_source")


def _match_producer(
    own: list[Mapping[str, Any]],
) -> tuple[str, Mapping[str, Any] | None]:
    """Return ``(unit_type_id, producer)`` for a viable production order.

    Prefers the default product when a matching producer exists; otherwise
    falls back to any owned producer and the unit it can actually train.
    """

    by_type: dict[str, Mapping[str, Any]] = {}
    for unit in own:
        by_type.setdefault(_unit_type(unit), unit)

    for structure in PRODUCER_FOR_UNIT.get(DEFAULT_PRODUCT, ()):
        if structure in by_type:
            return DEFAULT_PRODUCT, by_type[structure]

    for product, structures in PRODUCER_FOR_UNIT.items():
        for structure in structures:
            if structure in by_type:
                return product, by_type[structure]

    return DEFAULT_PRODUCT, None


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
