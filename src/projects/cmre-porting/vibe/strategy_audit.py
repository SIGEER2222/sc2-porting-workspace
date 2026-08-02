"""Auditing helpers for native task-strategy runtime reports.

Native strategy evidence must distinguish real SC2 commands from debug state
injection. The audit is deliberately transport-agnostic: the live runner
records typed action kinds while the debug host records function IDs.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping


DEBUG_INJECTION_FUNCTIONS = frozenset(
    {
        "vibe.unit.spawn",
        "vibe.player.set_resource",
        "vibe.unit.kill",
        "unit.spawn",
        "player.set_resource",
        "unit.kill",
    }
)

NATIVE_ACTION_KINDS = frozenset({"gather", "train", "move", "attack", "build"})


def _unit_counts(units: Iterable[Mapping]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for unit in units:
        unit_type = str(unit.get("unit_type_id", ""))
        if unit_type:
            counts[unit_type] += 1
    return dict(sorted(counts.items()))


def audit_native_strategy(
    action_trace: Iterable[Mapping],
    *,
    initial_observation: Mapping | None = None,
    final_observation: Mapping | None = None,
    debug_operations: Iterable[str] = (),
    expected_player_id: int | None = None,
    required_buildings: Iterable[str] = (),
    required_units: Iterable[str] = (),
) -> dict:
    """Return truthful strategy checks without mutating the runtime report."""

    trace = list(action_trace)
    debug_ops = [str(op) for op in debug_operations]
    injection_ops = [op for op in debug_ops if op in DEBUG_INJECTION_FUNCTIONS]
    action_counts = Counter(
        str(item.get("kind", ""))
        for item in trace
        if str(item.get("kind", ""))
    )
    success_counts = Counter(
        str(item.get("kind", ""))
        for item in trace
        if item.get("result") == "Success" and item.get("kind")
    )
    successful_build_types = {
        str(item.get("command_unit_type_id", ""))
        for item in trace
        if item.get("kind") == "build" and item.get("result") == "Success"
    }
    successful_train_types = {
        str(item.get("command_unit_type_id", ""))
        for item in trace
        if item.get("kind") == "train" and item.get("result") == "Success"
    }
    unknown_kinds = sorted(set(action_counts) - NATIVE_ACTION_KINDS)
    worker_attack_operations = [
        item for item in trace
        if item.get("kind") == "attack"
        and str(item.get("unit_type_id", "")) in {"SCV", "Probe", "Drone"}
    ]
    owner_mismatches = [
        item for item in trace
        if expected_player_id is not None
        and item.get("kind") in NATIVE_ACTION_KINDS
        and (
            int(item.get("issuer_player_id", expected_player_id)) != expected_player_id
            or int(item.get("source_owner", expected_player_id)) != expected_player_id
        )
    ]

    initial_resources = dict((initial_observation or {}).get("resources", {}))
    final_resources = dict((final_observation or {}).get("resources", {}))
    initial_units = list((initial_observation or {}).get("own_units", []))
    final_units = list((final_observation or {}).get("own_units", []))
    initial_types = {str(unit.get("unit_type_id", "")) for unit in initial_units}
    final_types = {str(unit.get("unit_type_id", "")) for unit in final_units}
    required_buildings = tuple(str(item) for item in required_buildings)
    required_units = tuple(str(item) for item in required_units)
    resource_delta = {
        key: final_resources.get(key, 0) - initial_resources.get(key, 0)
        for key in sorted(set(initial_resources) | set(final_resources))
        if isinstance(initial_resources.get(key, 0), (int, float))
        and isinstance(final_resources.get(key, 0), (int, float))
    }

    checks = {
        "no_debug_injection": not injection_ops,
        "native_action_kinds_only": not unknown_kinds,
        "gather_success": success_counts.get("gather", 0) > 0,
        "train_success": success_counts.get("train", 0) > 0,
        "move_or_attack_success": (
            success_counts.get("move", 0) + success_counts.get("attack", 0) > 0
        ),
        "state_observed_before_after": bool(initial_observation and final_observation),
        "scv_never_attacks": not worker_attack_operations,
        "expected_player_ownership": not owner_mismatches,
        "required_buildings_observed": all(
            unit_type in final_types for unit_type in required_buildings
        ),
        "required_build_actions_succeeded": all(
            unit_type in successful_build_types for unit_type in required_buildings
        ),
        "required_units_observed": all(
            unit_type in final_types and unit_type not in initial_types
            for unit_type in required_units
        ),
        "required_train_actions_succeeded": all(
            unit_type in successful_train_types for unit_type in required_units
        ),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "debug_operations": debug_ops,
        "injection_operations": injection_ops,
        "action_counts": dict(sorted(action_counts.items())),
        "successful_action_counts": dict(sorted(success_counts.items())),
        "unknown_action_kinds": unknown_kinds,
        "worker_attack_operations": worker_attack_operations,
        "owner_mismatches": owner_mismatches,
        "expected_player_id": expected_player_id,
        "required_buildings": list(required_buildings),
        "required_units": list(required_units),
        "successful_build_types": sorted(successful_build_types),
        "successful_train_types": sorted(successful_train_types),
        "initial_resources": initial_resources,
        "final_resources": final_resources,
        "resource_delta": resource_delta,
        "initial_units_by_type": _unit_counts(initial_units),
        "final_units_by_type": _unit_counts(final_units),
        "initial_unit_count": len(initial_units),
        "final_unit_count": len(final_units),
    }


__all__ = [
    "DEBUG_INJECTION_FUNCTIONS",
    "NATIVE_ACTION_KINDS",
    "audit_native_strategy",
]
