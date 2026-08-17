"""Stage 30 simulator-to-native differential validation contract.

This module compares only normalized observations.  It never treats a simulator
result, a static catalog value, or the historical P9 stub as native SC2 runtime
evidence.  A native record must be explicitly labelled ``runtime``; otherwise
its comparisons remain ``INFERENCE`` or ``BLOCKED``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .normal_start_contract import run_normal_start_contract


REPORT_SCHEMA_VERSION = "differential-report.v1"
OBSERVATION_SCHEMA_VERSION = "differential-observation.v1"
COMPARISON_SCOPE = (
    "entity_creation",
    "resource_changes",
    "unit_stats",
    "build_time",
    "cost",
    "ability_execution",
    "upgrade_state",
    "trigger_result",
)
FIDELITY_LABELS = frozenset({"EXACT", "APPROXIMATE", "PARTIAL", "UNSUPPORTED", "BLOCKED"})


@dataclass(frozen=True)
class NormalizedObservation:
    """One source's normalized data for one differential fixture.

    Each entry in ``values`` must include a ``value`` and a fidelity label.  A
    value can be ``None`` only when its fidelity is ``BLOCKED`` or
    ``UNSUPPORTED``.  ``source`` is intentionally independent from
    ``evidence_type`` so a caller cannot relabel a simulator result as native.
    """

    fixture_id: str
    source: str
    evidence_type: str
    values: dict[str, dict[str, Any]]
    source_path: str = ""
    notes: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "NormalizedObservation":
        schema_version = str(data.get("schema_version", OBSERVATION_SCHEMA_VERSION))
        if schema_version != OBSERVATION_SCHEMA_VERSION:
            raise ValueError(f"unsupported observation schema: {schema_version}")
        source = str(data.get("source", ""))
        if source not in {"simulator", "native"}:
            raise ValueError("observation source must be simulator or native")
        fixture_id = str(data.get("fixture_id", "")).strip()
        if not fixture_id:
            raise ValueError("observation fixture_id is required")
        evidence_type = str(data.get("evidence_type", "")).strip()
        if not evidence_type:
            raise ValueError("observation evidence_type is required")
        raw_values = data.get("values")
        if not isinstance(raw_values, Mapping) or not raw_values:
            raise ValueError("observation values must be a non-empty object")

        values: dict[str, dict[str, Any]] = {}
        for scope, item in raw_values.items():
            if scope not in COMPARISON_SCOPE:
                raise ValueError(f"unsupported comparison scope: {scope}")
            if not isinstance(item, Mapping) or "fidelity" not in item:
                raise ValueError(f"observation value {scope} requires fidelity")
            fidelity = str(item["fidelity"]).upper()
            if fidelity not in FIDELITY_LABELS:
                raise ValueError(f"unsupported fidelity label for {scope}: {fidelity}")
            if fidelity in {"BLOCKED", "UNSUPPORTED"} and "reason" not in item:
                raise ValueError(f"{scope} {fidelity} observation requires reason")
            values[str(scope)] = {
                "value": item.get("value"),
                "fidelity": fidelity,
                **({"reason": str(item["reason"])} if "reason" in item else {}),
            }

        return cls(
            fixture_id=fixture_id,
            source=source,
            evidence_type=evidence_type,
            values=values,
            source_path=str(data.get("source_path", "")),
            notes=str(data.get("notes", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            **asdict(self),
        }


def compare_observations(
    simulator: NormalizedObservation | Mapping[str, Any] | None,
    native: NormalizedObservation | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return a `differential-report.v1` without promoting untrusted evidence.

    A ``PASS`` report requires a runtime-labelled native observation for every
    comparison scope and exact canonical value equality.  ``APPROXIMATE`` and
    ``PARTIAL`` fidelity can match but are explicitly restricted to regression
    use.  No missing or inference-only input can yield PASS.
    """

    sim = _coerce_observation(simulator, expected_source="simulator")
    nat = _coerce_observation(native, expected_source="native")
    fixture_id = _fixture_id(sim, nat)
    if sim is not None and nat is not None and sim.fixture_id != nat.fixture_id:
        raise ValueError("simulator and native observations must use the same fixture_id")

    comparisons = []
    for scope in COMPARISON_SCOPE:
        comparisons.append(_compare_scope(scope, sim, nat))
    counts = Counter(item["status"] for item in comparisons)
    report_status = _report_status(comparisons)
    native_runtime_present = nat is not None and nat.evidence_type == "runtime"

    return {
        "schemaVersion": 1,
        "contract_schema_version": REPORT_SCHEMA_VERSION,
        "status": report_status,
        "fixture_id": fixture_id,
        "result_category": "differential_validation",
        "native_claim": False,
        "runtime_claim": (
            "comparison-only; native runtime observations are present"
            if native_runtime_present
            else "none; no native runtime observation is available"
        ),
        "sources": {
            "simulator": sim.to_dict() if sim is not None else None,
            "native": nat.to_dict() if nat is not None else None,
        },
        "comparisons": comparisons,
        "summary": {
            "comparison_counts": dict(sorted(counts.items())),
            "all_scopes_runtime_matched": report_status == "PASS",
            "native_runtime_present": native_runtime_present,
            "native_mission_completion_claim": False,
        },
    }


def build_stage30_fixture_report(
    *,
    seed: int = 29,
    max_loops: int = 900,
    native_observation: NormalizedObservation | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the Stage 30 report from the Stage 29 normal-start fixture.

    The Stage 29 run provides actual simulator observations for entity creation
    and resource changes.  The other six scopes are deliberately blocked until
    dedicated fixtures and runtime observations are supplied in later work.
    This generated artifact is a truthful report of layer readiness, not a
    native-equivalence pass.
    """

    contract = run_normal_start_contract(seed=seed, max_loops=max_loops)
    if contract["status"] != "PASS":
        raise RuntimeError("Stage 29 normal-start contract must pass before Stage 30 comparison")

    initial = contract["initial_state"]["p2"]
    final_units = contract["summary"]["final_units_by_type"]
    initial_units = {
        "CommandCenter": int(initial["command_centers"]),
        "SCV": int(initial["workers"]),
    }
    created = {
        unit_type: int(count) - int(initial_units.get(unit_type, 0))
        for unit_type, count in sorted(final_units.items())
        if int(count) > int(initial_units.get(unit_type, 0))
    }
    values: dict[str, dict[str, Any]] = {
        "entity_creation": {
            "value": {"created_units": created},
            "fidelity": "EXACT",
        },
        "resource_changes": {
            "value": {
                "initial_minerals": int(initial["minerals"]),
                "final_resources": contract["summary"]["final_resources"],
                "earned_minerals_lower_bound": int(
                    contract["check_details"]["earned_minerals_lower_bound"]
                ),
            },
            "fidelity": "EXACT",
        },
    }
    for scope in COMPARISON_SCOPE:
        if scope not in values:
            values[scope] = {
                "value": None,
                "fidelity": "BLOCKED",
                "reason": "not exercised by the Stage 29 normal-start fixture",
            }

    simulator = NormalizedObservation(
        fixture_id="stage30-normal-start-baseline",
        source="simulator",
        evidence_type="simulator",
        source_path="artifacts/projects/cmre-porting/stage29-normal-start-contract/normal-start-contract-20260817.json",
        values=values,
        notes="Stage 29 normal-start fixture; unsupported scopes remain blocked until dedicated fixtures exist.",
    )
    report = compare_observations(simulator, native_observation)
    report["fixture_coverage"] = _fixture_coverage()
    report["stage29_contract"] = {
        "schema_version": contract["contract_schema_version"],
        "status": contract["status"],
        "trace_hash": contract["summary"]["trace_hash"],
    }
    return report


def write_stage30_fixture_report(
    output_path: str | Path,
    *,
    seed: int = 29,
    max_loops: int = 900,
    native_observation: NormalizedObservation | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate and persist a Stage 30 differential report artifact."""

    report = build_stage30_fixture_report(
        seed=seed,
        max_loops=max_loops,
        native_observation=native_observation,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def load_observation(path: str | Path) -> NormalizedObservation:
    """Load one normalized observation from JSON with schema validation."""

    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, Mapping):
        raise ValueError("observation JSON root must be an object")
    return NormalizedObservation.from_mapping(data)


def _coerce_observation(
    observation: NormalizedObservation | Mapping[str, Any] | None,
    *,
    expected_source: str,
) -> NormalizedObservation | None:
    if observation is None:
        return None
    result = observation if isinstance(observation, NormalizedObservation) else NormalizedObservation.from_mapping(observation)
    if result.source != expected_source:
        raise ValueError(f"expected {expected_source} observation, got {result.source}")
    return result


def _fixture_id(simulator: NormalizedObservation | None, native: NormalizedObservation | None) -> str:
    if simulator is not None:
        return simulator.fixture_id
    if native is not None:
        return native.fixture_id
    return "unbound"


def _compare_scope(
    scope: str,
    simulator: NormalizedObservation | None,
    native: NormalizedObservation | None,
) -> dict[str, Any]:
    sim_value = simulator.values.get(scope) if simulator is not None else None
    native_value = native.values.get(scope) if native is not None else None
    base = {"scope": scope, "simulator": sim_value, "native": native_value}

    if sim_value is None:
        return {**base, "status": "SIMULATOR_MISSING", "reason": "simulator observation missing"}
    if sim_value["fidelity"] in {"BLOCKED", "UNSUPPORTED"}:
        return {
            **base,
            "status": sim_value["fidelity"],
            "reason": sim_value.get("reason", "simulator scope is unavailable"),
        }
    if native is None or native_value is None:
        return {**base, "status": "NATIVE_MISSING", "reason": "native runtime observation missing"}
    if native.evidence_type != "runtime":
        return {
            **base,
            "status": "INFERENCE",
            "reason": f"native evidence_type={native.evidence_type!r}; runtime evidence is required",
        }
    if native_value["fidelity"] in {"BLOCKED", "UNSUPPORTED"}:
        return {
            **base,
            "status": native_value["fidelity"],
            "reason": native_value.get("reason", "native scope is unavailable"),
        }

    equal = _canonical_json(sim_value["value"]) == _canonical_json(native_value["value"])
    fidelity = _combined_fidelity(sim_value["fidelity"], native_value["fidelity"])
    return {
        **base,
        "status": "MATCH" if equal else "MISMATCH",
        "fidelity": fidelity,
        "allowed_use": "balance_validation" if fidelity == "EXACT" else "regression_only",
    }


def _combined_fidelity(simulator: str, native: str) -> str:
    order = {"EXACT": 0, "APPROXIMATE": 1, "PARTIAL": 2, "UNSUPPORTED": 3, "BLOCKED": 4}
    return simulator if order[simulator] >= order[native] else native


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _report_status(comparisons: list[dict[str, Any]]) -> str:
    statuses = {item["status"] for item in comparisons}
    if "MISMATCH" in statuses:
        return "FAIL"
    if "NATIVE_MISSING" in statuses or "BLOCKED" in statuses:
        return "BLOCKED"
    if statuses & {"SIMULATOR_MISSING", "UNSUPPORTED", "INFERENCE"}:
        return "PARTIAL"
    return "PASS" if statuses == {"MATCH"} else "PARTIAL"


def _fixture_coverage() -> list[dict[str, Any]]:
    return [
        {
            "fixture_id": "stage30-normal-start-baseline",
            "scopes": ["entity_creation", "resource_changes"],
            "status": "simulator_observed_native_pending",
        },
        {
            "fixture_id": "stage31-unit-catalog-and-production",
            "scopes": ["unit_stats", "build_time", "cost"],
            "status": "planned",
        },
        {
            "fixture_id": "stage31-ability-upgrade-trigger",
            "scopes": ["ability_execution", "upgrade_state", "trigger_result"],
            "status": "planned",
        },
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a Stage 30 differential report")
    parser.add_argument("--out", required=True, help="report JSON output path")
    parser.add_argument("--native-observation", help="optional runtime-labelled native observation JSON")
    parser.add_argument("--seed", type=int, default=29)
    parser.add_argument("--max-loops", type=int, default=900)
    args = parser.parse_args(argv)

    native = load_observation(args.native_observation) if args.native_observation else None
    report = write_stage30_fixture_report(
        args.out,
        seed=args.seed,
        max_loops=args.max_loops,
        native_observation=native,
    )
    print(json.dumps({"status": report["status"], "out": args.out}, ensure_ascii=False))
    return 0 if report["status"] in {"PASS", "BLOCKED", "PARTIAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
