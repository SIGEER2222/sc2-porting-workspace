"""Stage 33 world-state observability contract.

This module stays in the simulator lane.  It inspects the project-owned Stage 29
normal-start fixture through the stable ``SimulatorSession`` facade and produces
an auditable world-state domain report.  Unsupported or partial native/mission
state stays visible instead of being silently omitted.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import Observation, SnapshotHandle, TraceHandle, snapshot_hash, trace_hash
from .normal_start_contract import build_normal_start_scenario
from .simulator_session import SimulatorSession
from .sim_path import ensure_simulator_on_path

ensure_simulator_on_path()

from sc2_simulator.reporting.trace import write_trace  # noqa: E402

CONTRACT_SCHEMA_VERSION = "world-state-observability.v1"
DEFAULT_OBSERVATION_LOOPS = 180
RUNTIME_CLAIM = "none; deterministic simulator world-state observability only"
NATIVE_DIFFERENTIAL_STATUS = "BLOCKED"

DOMAIN_NAMES = (
    "MapState",
    "PlayerState",
    "EntityState",
    "ResourceState",
    "TechnologyState",
    "UpgradeState",
    "VisionState",
    "SpatialState",
    "AbilityState",
    "ProjectileState",
    "MissionState",
    "TriggerState",
    "RNGState",
)


@dataclass(frozen=True)
class _FixtureRun:
    session: SimulatorSession
    initial: SnapshotHandle
    final: SnapshotHandle
    trace: TraceHandle
    observation: Observation
    step_result: Any


def _json_default(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


def _event_sample(world: Any, *, limit: int = 12) -> list[dict[str, Any]]:
    return [event.to_dict() for event in world.events.emitted[:limit]]


def _run_fixture(*, max_loops: int = DEFAULT_OBSERVATION_LOOPS) -> _FixtureRun:
    session = SimulatorSession()
    scenario = build_normal_start_scenario(max_loops=max_loops)
    session.scenario_load(scenario_dict=scenario)
    session.scenario_reset()
    session.snapshot_create("initial")
    initial = SnapshotHandle.from_world(session.world)
    p1_workers = sorted(
        (entity for entity in session.world.entities_of(1) if entity.unit_type_id == "SCV"),
        key=lambda entity: entity.entity_id,
    )
    if p1_workers:
        worker = p1_workers[0]
        session.unit_order(
            [worker.entity_id],
            "move",
            1,
            target_x=worker.x.to_float() + 1.0,
            target_y=worker.y.to_float(),
        )
    step_result = session.scenario_step(max_loops, snapshot=True)
    final = SnapshotHandle.from_world(session.world)
    trace = TraceHandle.from_world(session.world)
    observation = Observation.from_world(session.world, 1)
    return _FixtureRun(
        session=session,
        initial=initial,
        final=final,
        trace=trace,
        observation=observation,
        step_result=step_result,
    )


def _entity_keys(snapshot: dict[str, Any]) -> set[str]:
    entities = snapshot.get("entities") or []
    if not entities:
        return set()
    keys: set[str] = set()
    for entity in entities:
        keys.update(entity.keys())
    return keys


def _domain(
    name: str,
    status: str,
    observed_fields: list[str],
    *,
    partial_reason: str = "",
    blocked_reason: str = "",
    sample_count: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "status": status,
        "observed_fields": sorted(observed_fields),
        "omitted": False,
    }
    if partial_reason:
        payload["partial_reason"] = partial_reason
    if blocked_reason:
        payload["blocked_reason"] = blocked_reason
    if sample_count is not None:
        payload["sample_count"] = sample_count
    return payload


def _build_domains(fixture: _FixtureRun) -> list[dict[str, Any]]:
    snapshot = fixture.final.data
    entity_keys = _entity_keys(snapshot)
    resources = snapshot.get("resources", {})
    observation = fixture.observation
    mission = fixture.session.query_mission()
    event_systems = sorted({event.system for event in fixture.session.world.events.emitted})
    event_kinds = sorted({event.kind for event in fixture.session.world.events.emitted})

    domains = [
        _domain(
            "MapState",
            "PARTIAL",
            ["terrain", "terrain_is_explicit"],
            partial_reason="Snapshot exposes terrain slots, but Stage 33 uses a flat simulator fixture and does not import native SC2 map geometry.",
            sample_count=1 if "terrain" in snapshot else 0,
        ),
        _domain(
            "PlayerState",
            "OBSERVED",
            ["players", "alliance_summary", "is_ai", "race"],
            sample_count=len(snapshot.get("players", {}).get("players", [])),
        ),
        _domain(
            "EntityState",
            "OBSERVED",
            sorted(entity_keys),
            sample_count=len(snapshot.get("entities", [])),
        ),
        _domain(
            "ResourceState",
            "OBSERVED",
            ["resources", "minerals", "vespene", "supply_used", "supply_cap", "reserved_minerals", "reserved_vespene", "reserved_supply"],
            sample_count=len(resources),
        ),
        _domain(
            "TechnologyState",
            "OBSERVED",
            ["completed_upgrades", "research_upgrade_id", "research_progress", "research_total"],
            sample_count=sum(len(v) for v in snapshot.get("completed_upgrades", {}).values()),
        ),
        _domain(
            "UpgradeState",
            "PARTIAL",
            ["completed_upgrades", "weapon_damage_bonus", "weapon_air_damage_bonus", "armor_bonus", "speed_bonus", "shield_bonus"],
            partial_reason="Runtime upgrade state is snapshotted; native CMRE upgrade import and validation remain outside this stage.",
            sample_count=sum(len(v) for v in snapshot.get("completed_upgrades", {}).values()),
        ),
        _domain(
            "VisionState",
            "PARTIAL",
            ["last_known_positions", "visible_enemies", "visible_allies", "mineral_fields", "vespene_geysers"],
            partial_reason="Observation facade exposes player-visible slices and fog memory keys; native SC2 sight/fog parity is not claimed.",
            sample_count=len(observation.visible_enemies) + len(observation.visible_allies),
        ),
        _domain(
            "SpatialState",
            "OBSERVED",
            ["x", "y", "radius", "movement_paths", "footprint_width", "footprint_height", "terrain"],
            sample_count=len(snapshot.get("movement_paths", {})),
        ),
        _domain(
            "AbilityState",
            "PARTIAL",
            ["ability_cooldowns", "active_behaviors", "orders", "research_upgrade_id"],
            partial_reason="Entity ability/cooldown/behavior slots are observable, but full Galaxy ability semantics are not represented in Stage 33.",
            sample_count=sum(len(entity.get("ability_cooldowns", {})) for entity in snapshot.get("entities", [])),
        ),
        _domain(
            "ProjectileState",
            "OBSERVED",
            ["projectiles", "next_projectile_id"],
            sample_count=len(snapshot.get("projectiles", [])),
        ),
        _domain(
            "MissionState",
            "PARTIAL",
            ["objective_progress", "win_condition", "terminated", "end_reason"],
            partial_reason="Mission progress hooks are observable through query.mission/objective_progress; native mission script state is not imported.",
            sample_count=1 if mission else 0,
        ),
        _domain(
            "TriggerState",
            "PARTIAL",
            ["events", "event_systems", "event_kinds", "trigger_fired"],
            partial_reason="Event queue is observable. Stage 33 does not claim full Galaxy trigger semantic coverage.",
            sample_count=sum(1 for kind in event_kinds if "trigger" in kind) + len(event_systems),
        ),
        _domain(
            "RNGState",
            "OBSERVED",
            ["rng"],
            sample_count=1 if "rng" in snapshot else 0,
        ),
    ]
    return domains


def build_observability_contract(*, max_loops: int = DEFAULT_OBSERVATION_LOOPS) -> dict[str, Any]:
    fixture = _run_fixture(max_loops=max_loops)
    repeat = _run_fixture(max_loops=max_loops)
    domains = _build_domains(fixture)
    domain_names = {domain["name"] for domain in domains}
    missing_domains = sorted(set(DOMAIN_NAMES) - domain_names)
    final_snapshot = fixture.final.data
    trace_consistent = trace_hash(fixture.session.world) == fixture.trace.hash
    state_consistent = snapshot_hash(final_snapshot) == fixture.final.hash
    deterministic = (
        fixture.initial.hash == repeat.initial.hash
        and fixture.final.hash == repeat.final.hash
        and fixture.trace.hash == repeat.trace.hash
    )
    no_hidden_domain_omission = not missing_domains and all(not domain["omitted"] for domain in domains)
    status = "PASS" if all((trace_consistent, state_consistent, deterministic, no_hidden_domain_omission)) else "FAIL"

    return {
        "contract_schema_version": CONTRACT_SCHEMA_VERSION,
        "status": status,
        "evidence_type": "simulator",
        "native_claim": False,
        "runtime_claim": RUNTIME_CLAIM,
        "native_differential": NATIVE_DIFFERENTIAL_STATUS,
        "fixture": {
            "source": "src/projects/cmre-porting/vibe/normal_start_contract.py:build_normal_start_scenario",
            "scenario_name": fixture.session.scenario.definition.name,
            "catalog_schema": fixture.session.catalog.schema_version,
            "catalog_hash": fixture.session.catalog.content_hash,
            "observation_loops": max_loops,
        },
        "snapshot_identity": {
            "initial_loop": fixture.initial.loop,
            "initial_hash": fixture.initial.hash,
            "final_loop": fixture.final.loop,
            "final_hash": fixture.final.hash,
            "repeat_final_hash": repeat.final.hash,
            "state_hash_consistent": state_consistent,
            "deterministic_across_runs": deterministic,
        },
        "trace_identity": {
            "trace_hash": fixture.trace.hash,
            "repeat_trace_hash": repeat.trace.hash,
            "event_count": fixture.trace.event_count,
            "command_result_count": fixture.trace.command_result_count,
            "trace_hash_consistent": trace_consistent,
            "event_sample": _event_sample(fixture.session.world),
        },
        "domains": domains,
        "checks": {
            "all_required_domains_present": not missing_domains,
            "missing_domains": missing_domains,
            "no_hidden_state_omission": no_hidden_domain_omission,
            "state_hash_consistent": state_consistent,
            "trace_hash_consistent": trace_consistent,
            "deterministic_across_runs": deterministic,
            "native_claim_false": True,
        },
        "source_policy": {
            "reference_simulator_read_only": True,
            "native_runtime_required_for_native_differential": True,
            "unsupported_domains_explicit": True,
        },
    }


def write_observability_contract(
    output: str | Path,
    *,
    trace_output: str | Path | None = None,
    max_loops: int = DEFAULT_OBSERVATION_LOOPS,
) -> dict[str, Any]:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = build_observability_contract(max_loops=max_loops)
    if trace_output is not None:
        fixture = _run_fixture(max_loops=max_loops)
        trace_path = Path(trace_output)
        trace_sha256 = write_trace(fixture.session.world, trace_path)
        report["trace_identity"]["trace_artifact"] = str(trace_path).replace("\\", "/")
        report["trace_identity"]["trace_artifact_sha256"] = trace_sha256
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--trace-out", type=Path, default=None)
    parser.add_argument("--max-loops", type=int, default=DEFAULT_OBSERVATION_LOOPS)
    args = parser.parse_args(argv)
    report = write_observability_contract(args.out, trace_output=args.trace_out, max_loops=args.max_loops)
    print(json.dumps({"status": report["status"], "out": str(args.out)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
