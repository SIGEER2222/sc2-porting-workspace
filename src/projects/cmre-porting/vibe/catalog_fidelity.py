"""Catalog fidelity baseline reports for CMRE simulator evidence.

This module is intentionally project-local: it reads the reusable simulator
CatalogSnapshot and produces an auditable baseline without modifying the
read-only simulator package or promoting simulator evidence to native runtime
completion.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .contracts import wrap_catalog
from .sim_path import ensure_simulator_on_path

ensure_simulator_on_path()

from sc2_simulator.catalog.m7_units import m7_catalog  # noqa: E402


BASELINE_SCHEMA = "cmre-catalog-fidelity-baseline.v1"
REQUIRED_UNIT_MODEL_UNITS = (
    "SCV",
    "CommandCenter",
    "SupplyDepot",
    "Barracks",
    "Refinery",
    "Marine",
    "Marauder",
    "SiegeTank",
    "Medivac",
    "MineralField",
    "VespeneGeyser",
)
REQUIRED_ECONOMY_UNITS = (
    "SCV",
    "CommandCenter",
    "SupplyDepot",
    "Refinery",
    "MineralField",
    "VespeneGeyser",
)
REQUIRED_BUILD_PRODUCTS = (
    "SupplyDepot",
    "Barracks",
    "Refinery",
    "Factory",
    "FactoryTechLab",
    "EngineeringBay",
)
REQUIRED_PRODUCTION_PRODUCTS = (
    "SCV",
    "Marine",
    "Marauder",
    "SiegeTank",
    "Medivac",
)
REQUIRED_UPGRADES = (
    "CombatShield",
    "TerranInfantryWeaponsLevel1",
    "TerranInfantryArmorLevel1",
    "TerranVehicleWeaponsLevel1",
)
REQUIRED_ABILITIES = (
    "Stimpack",
    "Heal",
    "SiegeMode",
)
REQUIRED_CASTER_ABILITIES = (
    "Stimpack",
    "SiegeMode",
)



def build_catalog_fidelity_baseline(scenario: Mapping[str, Any] | None = None) -> dict:
    """Build the Stage 28 static catalog-fidelity baseline.

    The baseline answers a narrow question: can the deterministic simulator
    catalog explain the units and minimum economy/production/ability surfaces
    used by the CMRE adapter-clearance run?  It does not claim exact SC2 parity.
    """

    snapshot = m7_catalog()
    handle = wrap_catalog(snapshot, source="sc2_simulator.m7")
    used_units = _scenario_unit_ids(scenario or {})
    used_fidelity = {
        unit_id: handle.fidelity_of(unit_id)
        for unit_id in used_units
        if unit_id in snapshot.units
    }
    missing_scenario_units = [
        unit_id for unit_id in used_units if unit_id not in snapshot.units
    ]
    unsupported_scenario_units = [
        unit_id for unit_id, fidelity in used_fidelity.items()
        if fidelity == "unsupported"
    ]

    unit_model = _unit_model_report(snapshot, handle)
    economy_model = _economy_model_report(snapshot)
    production_model = _production_model_report(snapshot)
    ability_model = _ability_model_report(snapshot)
    reference_closure = _catalog_reference_closure(snapshot)

    checks = {
        "scenario_unit_refs_resolve": not missing_scenario_units,
        "no_unsupported_scenario_units": not unsupported_scenario_units,
        "unit_model_minimum": unit_model["status"] == "PASS",
        "economy_model_minimum": economy_model["status"] == "PASS",
        "production_model_minimum": production_model["status"] == "PASS",
        "ability_model_minimum": ability_model["status"] == "PASS",
        "catalog_reference_closure": reference_closure["status"] == "PASS",
    }

    return {
        "schema_version": BASELINE_SCHEMA,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "evidence_type": "static",
        "runtime_claim": "none; simulator catalog fidelity only",
        "approximation_policy": (
            "m7 is a hand-authored simulator IR; exact native SC2 parity is not claimed"
        ),
        "catalog": {
            "source": handle.source,
            "schema_version": handle.schema_version,
            "content_hash": handle.content_hash,
            "unit_count": len(snapshot.units),
            "build_rule_count": len(snapshot.build_rules),
            "production_rule_count": len(snapshot.production_rules),
            "morph_rule_count": len(snapshot.morph_rules),
            "upgrade_count": len(snapshot.upgrades),
            "ability_count": len(snapshot.abilities),
            "fidelity_summary": dict(Counter(handle.fidelity.values())),
        },
        "scenario_usage": {
            "used_units": used_units,
            "used_unit_count": len(used_units),
            "used_fidelity_summary": dict(Counter(used_fidelity.values())),
            "missing_units": missing_scenario_units,
            "unsupported_units": unsupported_scenario_units,
        },
        "checks": checks,
        "unit_model": unit_model,
        "economy_model": economy_model,
        "production_model": production_model,
        "ability_model": ability_model,
        "reference_closure": reference_closure,
    }


def _scenario_unit_ids(scenario: Mapping[str, Any]) -> list[str]:
    units: set[str] = set()
    for spawn in scenario.get("spawns", []):
        unit_id = str(spawn.get("unit_type_id", ""))
        if unit_id:
            units.add(unit_id)
    for command in scenario.get("commands", []):
        unit_id = str(command.get("unit_type_id", ""))
        if unit_id:
            units.add(unit_id)
    return sorted(units)


def _unit_model_report(snapshot, handle) -> dict:
    missing = [unit_id for unit_id in REQUIRED_UNIT_MODEL_UNITS if unit_id not in snapshot.units]
    invalid_stats: list[str] = []
    for unit_id in REQUIRED_UNIT_MODEL_UNITS:
        unit = snapshot.units.get(unit_id)
        if unit is None:
            continue
        if unit.max_health.raw <= 0:
            invalid_stats.append(f"{unit_id}.max_health")
        if unit.radius.raw <= 0:
            invalid_stats.append(f"{unit_id}.radius")
        if unit.sight.raw <= 0:
            invalid_stats.append(f"{unit_id}.sight")
    fidelity = {
        unit_id: handle.fidelity_of(unit_id)
        for unit_id in REQUIRED_UNIT_MODEL_UNITS
        if unit_id in snapshot.units
    }
    unsupported = [unit_id for unit_id, label in fidelity.items() if label == "unsupported"]
    return {
        "status": "PASS" if not missing and not invalid_stats and not unsupported else "FAIL",
        "required_units": list(REQUIRED_UNIT_MODEL_UNITS),
        "missing_units": missing,
        "invalid_stats": invalid_stats,
        "fidelity": fidelity,
        "unsupported_units": unsupported,
    }


def _economy_model_report(snapshot) -> dict:
    missing = [unit_id for unit_id in REQUIRED_ECONOMY_UNITS if unit_id not in snapshot.units]
    checks = {
        "worker_marked": bool(snapshot.units.get("SCV") and snapshot.units["SCV"].is_worker),
        "townhall_trains_worker": _rule_exists(
            snapshot.production_rules, "SCV", "producer_unit_id", "CommandCenter"
        ),
        "supply_depot_build_rule": "SupplyDepot" in snapshot.build_rules,
        "refinery_builds_on_geyser": bool(
            snapshot.units.get("Refinery") and snapshot.units["Refinery"].builds_on_geyser
        ),
        "resource_nodes_present": all(
            unit_id in snapshot.units for unit_id in ("MineralField", "VespeneGeyser")
        ),
    }
    return {
        "status": "PASS" if not missing and all(checks.values()) else "FAIL",
        "required_units": list(REQUIRED_ECONOMY_UNITS),
        "missing_units": missing,
        "checks": checks,
    }


def _production_model_report(snapshot) -> dict:
    missing_build = [
        product for product in REQUIRED_BUILD_PRODUCTS
        if product not in snapshot.build_rules
    ]
    missing_production = [
        product for product in REQUIRED_PRODUCTION_PRODUCTS
        if product not in snapshot.production_rules
    ]
    rule_ref_errors = []
    for product in REQUIRED_BUILD_PRODUCTS:
        rule = snapshot.build_rules.get(product)
        if rule is not None:
            rule_ref_errors.extend(_rule_unit_ref_errors(rule, snapshot.units))
    for product in REQUIRED_PRODUCTION_PRODUCTS:
        rule = snapshot.production_rules.get(product)
        if rule is not None:
            rule_ref_errors.extend(_rule_unit_ref_errors(rule, snapshot.units))
    checks = {
        "terran_build_chain_present": not missing_build,
        "terran_production_chain_present": not missing_production,
        "rule_references_resolve": not rule_ref_errors,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "required_build_products": list(REQUIRED_BUILD_PRODUCTS),
        "required_production_products": list(REQUIRED_PRODUCTION_PRODUCTS),
        "missing_build_products": missing_build,
        "missing_production_products": missing_production,
        "rule_reference_errors": rule_ref_errors,
        "checks": checks,
    }


def _ability_model_report(snapshot) -> dict:
    missing_abilities = [
        ability_id for ability_id in REQUIRED_ABILITIES
        if ability_id not in snapshot.abilities
    ]
    missing_upgrades = [
        upgrade_id for upgrade_id in REQUIRED_UPGRADES
        if upgrade_id not in snapshot.upgrades
    ]
    missing_caster_mappings = [
        ability_id for ability_id in REQUIRED_CASTER_ABILITIES
        if ability_id not in snapshot.casters_by_ability
    ]
    caster_ref_errors: list[str] = []
    for ability_id in REQUIRED_CASTER_ABILITIES:
        for caster in snapshot.casters_by_ability.get(ability_id, ()):
            if caster not in snapshot.units:
                caster_ref_errors.append(f"{ability_id}.caster={caster}")
    ability_ref_errors: list[str] = []
    for ability_id in REQUIRED_ABILITIES:
        ability = snapshot.abilities.get(ability_id)
        if ability is None:
            continue
        # Commandable caster ownership is recorded in CatalogSnapshot.casters_by_ability.
        for effect in getattr(ability, "effects", ()):  # summoned units / applied behaviors
            unit_id = getattr(effect, "unit_type_id", "")
            if unit_id and unit_id not in snapshot.units:
                ability_ref_errors.append(f"{ability_id}.effect.unit_type_id={unit_id}")
            behavior_id = getattr(effect, "behavior_id", "")
            if behavior_id and behavior_id not in snapshot.behaviors:
                ability_ref_errors.append(f"{ability_id}.effect.behavior_id={behavior_id}")
    upgrade_ref_errors = _upgrade_reference_errors(snapshot)
    checks = {
        "required_abilities_present": not missing_abilities,
        "required_upgrades_present": not missing_upgrades,
        "ability_references_resolve": not ability_ref_errors,
        "caster_mappings_present": not missing_caster_mappings,
        "caster_references_resolve": not caster_ref_errors,
        "upgrade_references_resolve": not upgrade_ref_errors,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "required_abilities": list(REQUIRED_ABILITIES),
        "required_upgrades": list(REQUIRED_UPGRADES),
        "required_caster_abilities": list(REQUIRED_CASTER_ABILITIES),
        "missing_abilities": missing_abilities,
        "missing_upgrades": missing_upgrades,
        "missing_caster_mappings": missing_caster_mappings,
        "ability_reference_errors": ability_ref_errors,
        "caster_reference_errors": caster_ref_errors,
        "upgrade_reference_errors": upgrade_ref_errors,
        "checks": checks,
    }


def _catalog_reference_closure(snapshot) -> dict:
    errors: list[str] = []
    for rule in snapshot.build_rules.values():
        errors.extend(_rule_unit_ref_errors(rule, snapshot.units))
    for rule in snapshot.production_rules.values():
        errors.extend(_rule_unit_ref_errors(rule, snapshot.units))
    for rule in snapshot.morph_rules.values():
        errors.extend(_rule_unit_ref_errors(rule, snapshot.units))
    errors.extend(_upgrade_reference_errors(snapshot))
    return {
        "status": "PASS" if not errors else "FAIL",
        "error_count": len(errors),
        "errors": errors[:50],
    }


def _rule_exists(rules: Mapping[str, Any], product: str, field: str, expected: str) -> bool:
    rule = rules.get(product)
    return bool(rule is not None and getattr(rule, field, "") == expected)


def _rule_unit_ref_errors(rule: Any, units: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for attr in ("builder_unit_id", "producer_unit_id", "source_unit_id", "product_unit_id"):
        unit_id = getattr(rule, attr, "")
        if unit_id and unit_id not in units:
            errors.append(f"{type(rule).__name__}.{attr}={unit_id}")
    for unit_id in getattr(rule, "requires", ()):
        if unit_id and unit_id not in units:
            errors.append(f"{type(rule).__name__}.requires={unit_id}")
    addon = getattr(rule, "addon", None)
    if addon and addon not in units:
        errors.append(f"{type(rule).__name__}.addon={addon}")
    return errors


def _upgrade_reference_errors(snapshot) -> list[str]:
    errors: list[str] = []
    for upgrade_id, upgrade in snapshot.upgrades.items():
        for unit_id in getattr(upgrade, "requires", ()):  # requirement structures
            if unit_id and unit_id not in snapshot.units:
                errors.append(f"{upgrade_id}.requires={unit_id}")
        for unit_id in getattr(upgrade, "researched_at", ()):
            if unit_id and unit_id not in snapshot.units:
                errors.append(f"{upgrade_id}.researched_at={unit_id}")
        for effect_path in getattr(upgrade, "effects", {}).keys():
            unit_id = str(effect_path).split(".", 1)[0]
            if unit_id and unit_id not in snapshot.units:
                errors.append(f"{upgrade_id}.effects={effect_path}")
    return errors


__all__ = ["BASELINE_SCHEMA", "build_catalog_fidelity_baseline"]
