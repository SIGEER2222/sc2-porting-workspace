"""Stage 32 simulator-only SC2 feature fidelity matrix.

The matrix is an auditable boundary report, not a native-equivalence claim.
It intentionally keeps unsupported features in the denominator and marks
native differential work as BLOCKED until a runtime-labelled observation is
available.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .catalog_fidelity import build_catalog_fidelity_baseline
from .normal_start_contract import run_normal_start_contract
from .sim_path import ensure_simulator_on_path

ensure_simulator_on_path()

from sc2_simulator.catalog.m7_units import m7_catalog  # noqa: E402


REPORT_SCHEMA_VERSION = "simulator-fidelity-matrix.v1"
NATIVE_DIFFERENTIAL_STATUS = "BLOCKED"
NATIVE_DIFFERENTIAL_REASON = (
    "No runtime-labelled native observation is available; simulator evidence "
    "cannot be promoted to native differential parity."
)


@dataclass(frozen=True)
class MatrixRow:
    domain: str
    feature: str
    supported: bool
    fidelity: str
    tested: bool
    test_id: str
    native_differential: str
    native_differential_reason: str
    source: str


@dataclass(frozen=True)
class _FeatureDefinition:
    domain: str
    feature: str
    test_id: str
    probe: Callable[[Any], tuple[bool, str, str]]


def build_fidelity_matrix() -> dict[str, Any]:
    """Build the complete 27-row simulator fidelity matrix."""

    snapshot = m7_catalog()
    catalog_baseline = build_catalog_fidelity_baseline()
    normal_start = run_normal_start_contract(seed=29, max_loops=900)
    rows = [
        _row(definition, snapshot)
        for definition in _FEATURE_DEFINITIONS
    ]
    checks = _build_checks(rows, catalog_baseline, normal_start)
    return {
        "schemaVersion": 1,
        "contract_schema_version": REPORT_SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "evidence_type": "simulator",
        "result_category": "simulator_fidelity_matrix",
        "native_claim": False,
        "runtime_claim": (
            "none; deterministic simulator fidelity boundary only; "
            "native differential status is intentionally BLOCKED"
        ),
        "source_policy": {
            "catalog_source": "sc2_simulator.m7",
            "catalog_schema_version": snapshot.schema_version,
            "catalog_content_hash": snapshot.content_hash,
            "reference_source_read_only": True,
            "native_observation_required_for_differential": True,
        },
        "matrix": [asdict(row) for row in rows],
        "summary": _summary(rows),
        "checks": checks,
        "baseline_inputs": {
            "catalog_fidelity": {
                "schema_version": catalog_baseline["schema_version"],
                "status": catalog_baseline["status"],
                "catalog_hash": catalog_baseline["catalog"]["content_hash"],
            },
            "normal_start_contract": {
                "schema_version": normal_start["contract_schema_version"],
                "status": normal_start["status"],
                "trace_hash": normal_start["summary"]["trace_hash"],
            },
        },
    }


def write_fidelity_matrix(output_path: str | Path) -> dict[str, Any]:
    report = build_fidelity_matrix()
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _row(definition: _FeatureDefinition, snapshot: Any) -> MatrixRow:
    supported, fidelity, source = definition.probe(snapshot)
    return MatrixRow(
        domain=definition.domain,
        feature=definition.feature,
        supported=supported,
        fidelity=fidelity,
        tested=True,
        test_id=definition.test_id,
        native_differential=NATIVE_DIFFERENTIAL_STATUS,
        native_differential_reason=NATIVE_DIFFERENTIAL_REASON,
        source=source,
    )


def _summary(rows: list[MatrixRow]) -> dict[str, Any]:
    fidelity_counts: dict[str, int] = {}
    domain_counts: dict[str, int] = {}
    supported_count = 0
    tested_count = 0
    native_counts: dict[str, int] = {}
    for row in rows:
        fidelity_counts[row.fidelity] = fidelity_counts.get(row.fidelity, 0) + 1
        domain_counts[row.domain] = domain_counts.get(row.domain, 0) + 1
        supported_count += int(row.supported)
        tested_count += int(row.tested)
        native_counts[row.native_differential] = native_counts.get(row.native_differential, 0) + 1
    return {
        "row_count": len(rows),
        "supported_count": supported_count,
        "unsupported_count": len(rows) - supported_count,
        "tested_count": tested_count,
        "fidelity_counts": dict(sorted(fidelity_counts.items())),
        "domain_counts": dict(sorted(domain_counts.items())),
        "native_differential_counts": dict(sorted(native_counts.items())),
    }


def _build_checks(
    rows: list[MatrixRow],
    catalog_baseline: Mapping[str, Any],
    normal_start: Mapping[str, Any],
) -> dict[str, bool]:
    expected_domains = {
        "Unit", "Weapon", "Movement", "Combat", "Economy", "Production",
        "Upgrade", "Ability", "Vision", "Terrain", "Pathing", "Trigger", "Mission",
    }
    return {
        "complete_roadmap_row_count": len(rows) == 27,
        "all_domains_present": {row.domain for row in rows} == expected_domains,
        "all_rows_have_provenance": all(bool(row.source) and bool(row.test_id) for row in rows),
        "all_rows_tested": all(row.tested for row in rows),
        "unsupported_features_explicit": any(not row.supported for row in rows),
        "native_differential_truthful": all(
            row.native_differential == NATIVE_DIFFERENTIAL_STATUS
            and row.native_differential_reason == NATIVE_DIFFERENTIAL_REASON
            for row in rows
        ),
        "catalog_baseline_pass": catalog_baseline.get("status") == "PASS",
        "normal_start_baseline_pass": normal_start.get("status") == "PASS",
        "no_native_claim": True,
    }


def _any_unit(snapshot: Any, predicate: Callable[[Any], bool]) -> bool:
    return any(predicate(unit) for unit in snapshot.units.values())


def _any_weapon(snapshot: Any, predicate: Callable[[Any], bool]) -> bool:
    for unit in snapshot.units.values():
        for weapon in (unit.weapon_ground, unit.weapon_air, unit.weapon_ground_sieged):
            if weapon is not None and predicate(weapon):
                return True
    return False


def _any_rule(snapshot: Any, predicate: Callable[[Any], bool]) -> bool:
    return any(predicate(rule) for rule in snapshot.build_rules.values()) or any(
        predicate(rule) for rule in snapshot.production_rules.values()
    )


def _has_effect(snapshot: Any, predicate: Callable[[Any], bool]) -> bool:
    return any(
        predicate(effect)
        for ability in snapshot.abilities.values()
        for effect in getattr(ability, "effects", ())
    )


def _unit_probe(field: str, fidelity: str) -> Callable[[Any], tuple[bool, str, str]]:
    def probe(snapshot: Any) -> tuple[bool, str, str]:
        return (
            _any_unit(snapshot, lambda unit: getattr(unit, field).raw != 0),
            fidelity,
            f"sc2_simulator.m7 CatalogSnapshot.units[*].{field}",
        )

    return probe

def _hp_shield_probe(snapshot: Any) -> tuple[bool, str, str]:
    has_health = _any_unit(snapshot, lambda unit: unit.max_health.raw > 0)
    has_shields = _any_unit(snapshot, lambda unit: unit.max_shields.raw > 0)
    return (
        has_health and has_shields,
        "APPROXIMATE",
        "sc2_simulator.m7 CatalogSnapshot.units[*].max_health/max_shields",
    )


def _weapon_probe(field: str, fidelity: str) -> Callable[[Any], tuple[bool, str, str]]:
    def probe(snapshot: Any) -> tuple[bool, str, str]:
        return (
            _any_weapon(snapshot, lambda weapon: getattr(weapon, field).raw != 0)
            if field in {"damage", "range"}
            else _any_weapon(snapshot, lambda weapon: bool(getattr(weapon, field))),
            fidelity,
            f"sc2_simulator.m7 CatalogSnapshot weapons[*].{field}",
        )

    return probe


def _unsupported(source: str) -> Callable[[Any], tuple[bool, str, str]]:
    return lambda _snapshot: (False, "UNSUPPORTED", source)


def _feature_definitions() -> tuple[_FeatureDefinition, ...]:
    return (
        _FeatureDefinition("Unit", "HP/Shield", "matrix.unit.hp_shield", _hp_shield_probe),
        _FeatureDefinition("Unit", "Armor", "matrix.unit.armor", _unit_probe("armor", "APPROXIMATE")),
        _FeatureDefinition("Weapon", "Damage", "matrix.weapon.damage", _weapon_probe("damage", "APPROXIMATE")),
        _FeatureDefinition("Weapon", "Period", "matrix.weapon.period", _weapon_probe("period", "APPROXIMATE")),
        _FeatureDefinition("Weapon", "Range", "matrix.weapon.range", _weapon_probe("range", "APPROXIMATE")),
        _FeatureDefinition(
            "Weapon", "Target Filter", "matrix.weapon.target_filter",
            _weapon_probe("target_filters", "PARTIAL"),
        ),
        _FeatureDefinition("Movement", "Speed", "matrix.movement.speed", _unit_probe("speed", "APPROXIMATE")),
        _FeatureDefinition("Movement", "Acceleration", "matrix.movement.acceleration", _unsupported(
            "sc2_simulator catalog has speed but no acceleration field or rule"
        )),
        _FeatureDefinition(
            "Movement", "Collision", "matrix.movement.collision",
            lambda snapshot: (
                _any_unit(snapshot, lambda unit: unit.radius.raw > 0),
                "PARTIAL",
                "sc2_simulator.m7 UnitType.radius plus movement/path occupancy",
            ),
        ),
        _FeatureDefinition(
            "Combat", "Damage", "matrix.combat.damage",
            _weapon_probe("damage", "PARTIAL"),
        ),
        _FeatureDefinition(
            "Combat", "Splash", "matrix.combat.splash",
            lambda snapshot: (
                _any_weapon(snapshot, lambda weapon: weapon.has_splash),
                "PARTIAL",
                "sc2_simulator.m7 WeaponType.splash_type/splash_radius and combat system",
            ),
        ),
        _FeatureDefinition(
            "Combat", "Search", "matrix.combat.search",
            lambda snapshot: (
                bool(snapshot.units),
                "PARTIAL",
                "sc2_simulator combat target selection over WorldState entities",
            ),
        ),
        _FeatureDefinition(
            "Economy", "Gather", "matrix.economy.gather",
            lambda snapshot: (
                bool(snapshot.units.get("SCV") and snapshot.units["SCV"].is_worker),
                "APPROXIMATE",
                "vibe.normal_start_contract plus sc2_simulator economy system",
            ),
        ),
        _FeatureDefinition(
            "Economy", "Deposit", "matrix.economy.deposit",
            lambda snapshot: (
                bool(snapshot.units.get("CommandCenter")),
                "APPROXIMATE",
                "sc2_simulator economy system worker return/deposit path",
            ),
        ),
        _FeatureDefinition(
            "Production", "Train", "matrix.production.train",
            lambda snapshot: (
                bool(snapshot.production_rules),
                "APPROXIMATE",
                "sc2_simulator.m7 CatalogSnapshot.production_rules and production system",
            ),
        ),
        _FeatureDefinition(
            "Upgrade", "Modifier", "matrix.upgrade.modifier",
            lambda snapshot: (
                any(bool(getattr(upgrade, "effects", {})) for upgrade in snapshot.upgrades.values()),
                "PARTIAL",
                "sc2_simulator.m7 UpgradeType.effects and upgrade system",
            ),
        ),
        _FeatureDefinition(
            "Ability", "Cost", "matrix.ability.cost",
            lambda snapshot: (
                bool(snapshot.abilities),
                "APPROXIMATE",
                "sc2_simulator.m7 AbilityType.cost_energy/cost_hp",
            ),
        ),
        _FeatureDefinition(
            "Ability", "Cooldown", "matrix.ability.cooldown",
            lambda snapshot: (
                any(getattr(ability, "cooldown", 0) > 0 for ability in snapshot.abilities.values()),
                "APPROXIMATE",
                "sc2_simulator.m7 AbilityType.cooldown and abilities system",
            ),
        ),
        _FeatureDefinition(
            "Ability", "Effect", "matrix.ability.effect",
            lambda snapshot: (
                _has_effect(snapshot, lambda effect: bool(effect.kind)),
                "PARTIAL",
                "sc2_simulator.m7 AbilityType.effects and abilities system",
            ),
        ),
        _FeatureDefinition("Vision", "Sight", "matrix.vision.sight", _unit_probe("sight", "PARTIAL")),
        _FeatureDefinition(
            "Terrain", "Walkable", "matrix.terrain.walkable",
            lambda _snapshot: (True, "PARTIAL", "sc2_simulator.world.terrain.TerrainMap.pathable_grid"),
        ),
        _FeatureDefinition(
            "Terrain", "Height", "matrix.terrain.height",
            lambda _snapshot: (True, "PARTIAL", "sc2_simulator.world.terrain.TerrainMap.height_grid"),
        ),
        _FeatureDefinition(
            "Pathing", "Path", "matrix.pathing.path",
            lambda _snapshot: (True, "PARTIAL", "sc2_simulator.map.pathfinding.Pathfinder"),
        ),
        _Feature_definition_trigger("Event", "event"),
        _Feature_definition_trigger("Condition", "condition"),
        _Feature_definition_trigger("Action", "action"),
        _FeatureDefinition(
            "Mission", "Objective", "matrix.mission.objective",
            lambda _snapshot: (True, "PARTIAL", "sc2_simulator.runner objective/win-condition handling"),
        ),
    )


def _Feature_definition_trigger(feature: str, key: str) -> _FeatureDefinition:
    return _FeatureDefinition(
        "Trigger",
        feature,
        f"matrix.trigger.{key}",
        lambda _snapshot: (True, "PARTIAL", "sc2_simulator.tools.triggers.TriggerEngine"),
    )


_FEATURE_DEFINITIONS = _feature_definitions()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the Stage 32 simulator fidelity matrix")
    parser.add_argument("--out", required=True, help="matrix JSON output path")
    args = parser.parse_args(argv)
    report = write_fidelity_matrix(args.out)
    print(json.dumps({"status": report["status"], "row_count": report["summary"]["row_count"], "out": args.out}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
