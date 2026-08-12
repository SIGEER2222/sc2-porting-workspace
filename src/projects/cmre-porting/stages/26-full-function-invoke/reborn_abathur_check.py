"""Fail-closed comparison helpers for the Reborn Abathur runtime probe."""
from __future__ import annotations

from collections import Counter
from typing import Any


EPHEMERAL_MORPH_UNITS = {"Larva", "Egg"}


def command_key(command: dict[str, Any]) -> tuple[str, int]:
    return command["ability"], int(command["command_index"])


def counter_from(value: dict[str, int] | Counter[str]) -> Counter[str]:
    return Counter({name: int(count) for name, count in value.items() if int(count) > 0})


def classify_command_output(expected_products: list[str], produced_delta: dict[str, int]) -> dict[str, Any]:
    expected = Counter(expected_products)
    actual = counter_from(produced_delta)
    relevant = Counter({name: count for name, count in actual.items() if name not in EPHEMERAL_MORPH_UNITS})
    missing = expected - relevant
    unexpected = relevant - expected
    if missing and not relevant:
        status = "MISSING_OUTPUT"
    elif missing:
        status = "WRONG_OUTPUT"
    elif unexpected:
        status = "UNEXPECTED_OUTPUT"
    else:
        status = "PASS"
    return {
        "status": status,
        "expected_products": dict(sorted(expected.items())),
        "produced_delta": dict(sorted(relevant.items())),
        "missing_products": dict(sorted(missing.items())),
        "unexpected_products": dict(sorted(unexpected.items())),
    }


def compare_census_roster(baseline: dict[str, Any], census: dict[str, dict[str, int]]) -> dict[str, Any]:
    roster = baseline["roster"]
    original_roster = roster.get("original_roster", roster.get("potentially_unlockable", {}))
    original_units = set(original_roster.get("units", []))
    original_buildings = set(original_roster.get("buildings", []))
    comparison: dict[str, Any] = {}
    for player in ("p1", "p2"):
        observed = {unit for unit, count in census[player].items() if int(count) > 0}
        observed_units = observed & original_units
        observed_buildings = observed & original_buildings
        comparison[player] = {
            "observed_original_units": sorted(observed_units),
            "observed_original_buildings": sorted(observed_buildings),
            "unobserved_original_units": sorted(original_units - observed_units),
            "unobserved_original_buildings": sorted(original_buildings - observed_buildings),
            "non_roster_units": sorted(observed - original_units - original_buildings),
        }
    return comparison


def compare_runtime(baseline: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    """Return PASS only when every source card command is runnable and exact."""
    failures: list[dict[str, Any]] = []
    larva_count = int(runtime.get("larva_count", 0))
    if larva_count <= 0:
        failures.append({"code": "NO_LARVA", "detail": "no P1 Larva was observed"})
    available = {
        (str(item.get("ability")), int(item.get("command_index", -1)))
        for item in runtime.get("available_commands", [])
    }
    result_by_key = {
        (str(item.get("ability")), int(item.get("command_index", -1))): item
        for item in runtime.get("command_results", [])
    }
    for command in baseline["larva"]["card_exposed_commands"]:
        key = command_key(command)
        identity = {"ability": key[0], "command_index": key[1], "command": command["command"]}
        if key not in available:
            failures.append({"code": "EXPECTED_ABILITY_MISSING", **identity})
            continue
        result = result_by_key.get(key)
        if result is None:
            failures.append({"code": "COMMAND_NOT_EXECUTED", **identity})
            continue
        output = classify_command_output(command["products"], result.get("produced_delta", {}))
        if result.get("action_error"):
            failures.append({"code": "ACTION_REJECTED", **identity, "detail": result["action_error"]})
        if output["status"] != "PASS":
            failures.append({"code": output["status"], **identity, **output})
    census = runtime.get("census")
    census_roster_comparison: dict[str, Any] = {}
    observed_external: dict[str, list[str]] = {}
    if not isinstance(census, dict) or not isinstance(census.get("p1"), dict) or not isinstance(census.get("p2"), dict):
        failures.append({"code": "EMPTY_RUNTIME_CENSUS", "detail": "P1 and P2 raw census are required"})
    else:
        census_roster_comparison = compare_census_roster(baseline, census)
        observed_external = {
            player: comparison["non_roster_units"] for player, comparison in census_roster_comparison.items()
        }
    return {
        "verdict": "PASS" if not failures else "FAIL",
        "failure_count": len(failures),
        "failures": failures,
        "checked_command_count": len(baseline["larva"]["card_exposed_commands"]),
        "observed_external_census_units": observed_external,
        "census_roster_comparison": census_roster_comparison,
    }
