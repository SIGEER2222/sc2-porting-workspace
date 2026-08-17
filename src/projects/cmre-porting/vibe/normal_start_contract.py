"""Stage 29 normal-start macro-bootstrap contract.

This module intentionally stays inside the deterministic simulator lane.  It
builds a fair Terran/Terran opening fixture, runs only a macro-economy policy
for P2, and reports ``normal-start-contract.v1`` without any native runtime or
map-completion claim.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

from .consumers.ally_ai import AllyAction, run_ally_scenario
from .defend_policy import DefendBasePolicy
from .simulator_session import SimulatorSession


P1_PLAYER_ID = 1
P2_PLAYER_ID = 2
NEUTRAL_PLAYER_ID = 0
P1_BASE = (45.0, 94.0)
P2_BASE = (85.0, 94.0)
DEFAULT_SEED = 29
DEFAULT_MAX_LOOPS = 900
CONTRACT_SCHEMA_VERSION = "normal-start-contract.v1"
RESULT_CATEGORY = "macro_bootstrap"
RUNTIME_CLAIM = "none; deterministic simulator macro-bootstrap only"

REQUIRED_CHECKS = (
    "worker_mining",
    "resource_income",
    "resource_deposit",
    "supply_handling",
    "worker_survival",
    "building_construction",
    "production_completion",
    "combat_unit_creation",
    "no_dispatch_error",
    "no_deadlock",
)

_PROHIBITED_ADVANTAGES = (
    "initial_combat_unit_injection",
    "extra_building_injection",
    "resource_multiplier_or_boosted_starting_resources",
    "enemy_replacement",
    "enemy_relocation_or_staging",
    "map_count_expansion_as_success_substitute",
)


@dataclass(frozen=True)
class _PlayerStart:
    race: str
    minerals: int
    vespene: int
    workers: int
    command_centers: int
    combat_units: int
    extra_buildings: int
    supply_used: int
    supply_cap: int


def build_normal_start_scenario(
    *,
    seed: int = DEFAULT_SEED,
    max_loops: int = DEFAULT_MAX_LOOPS,
) -> dict[str, Any]:
    """Return the Stage 29 fair normal-start simulator fixture.

    Both Terran players begin with one Command Center, twelve SCVs, 50 minerals,
    zero gas, and mirrored neutral resource clusters.  The fixture has no enemy
    player and no initial combat units; P1 is intentionally idle while P2 proves
    that macro bootstrap can progress from the same starting economy.
    """

    spawns: list[dict[str, Any]] = []
    for player_id, base in ((P1_PLAYER_ID, P1_BASE), (P2_PLAYER_ID, P2_BASE)):
        base_x, base_y = base
        spawns.append({
            "unit_type_id": "CommandCenter",
            "owner_player_id": player_id,
            "x": base_x,
            "y": base_y,
        })
        for index in range(12):
            spawns.append({
                "unit_type_id": "SCV",
                "owner_player_id": player_id,
                "x": base_x - 6.0 + (index % 6) * 2.0,
                "y": base_y - 4.0 + (index // 6) * 2.0,
            })

    for base_x, base_y in (P1_BASE, P2_BASE):
        for offset_x, offset_y in (
            (-6.0, 8.0), (-3.0, 8.0), (0.0, 8.0), (3.0, 8.0),
            (6.0, 8.0), (-6.0, 11.0), (0.0, 11.0), (6.0, 11.0),
        ):
            spawns.append({
                "unit_type_id": "MineralField",
                "owner_player_id": NEUTRAL_PLAYER_ID,
                "x": base_x + offset_x,
                "y": base_y + offset_y,
                "resource_amount": 12000,
            })
        spawns.append({
            "unit_type_id": "VespeneGeyser",
            "owner_player_id": NEUTRAL_PLAYER_ID,
            "x": base_x,
            "y": base_y + 14.0,
            "resource_amount": 12000,
        })

    return {
        "schema_version": "m7",
        "name": "stage29-normal-start-contract",
        "players": [
            {
                "id": P1_PLAYER_ID,
                "name": "P1 Terran",
                "race": "terran",
                "allies": [P2_PLAYER_ID],
                "is_ai": False,
                "relation": "leader",
            },
            {
                "id": P2_PLAYER_ID,
                "name": "P2 Terran Macro",
                "race": "terran",
                "allies": [P1_PLAYER_ID],
                "is_ai": True,
                "relation": "ally",
            },
            {
                "id": NEUTRAL_PLAYER_ID,
                "name": "Neutral",
                "race": "neutral",
                "allies": [],
                "is_ai": True,
                "relation": "neutral",
            },
        ],
        "spawns": spawns,
        "commands": [],
        "max_loops": max(1, int(max_loops)),
        "seed": int(seed),
        "strict": True,
        "win_condition": "custom",
        "initial_minerals": 50,
        "initial_vespene": 0,
        "_cooperative_enemy_player_ids": [],
        "_stage29_contract": CONTRACT_SCHEMA_VERSION,
    }


class NormalStartMacroPolicy:
    """P2-only macro policy used by the Stage 29 contract.

    The policy intentionally delegates to the existing economy planner but
    disables unrelated tactical follow/attack behavior.  This keeps the check
    focused on natural mining, construction, supply, and production from a
    normal start instead of pathing a combat squad toward a P1 structure.
    """

    def __init__(self, *, player_id: int = P2_PLAYER_ID) -> None:
        self.player_id = int(player_id)
        self.mode = SimpleNamespace(value="macro_bootstrap")
        self.mode_history: list[str] = []
        self._economy = DefendBasePolicy(
            player_id=self.player_id,
            base_region=(P2_BASE[0], P2_BASE[1], 16.0),
            command_interval=1,
            econ_interval=8,
        )
        # Stage 29 validates bootstrap, not a full tech tree.  Keep the
        # natural opening bounded to depot -> barracks -> marine production.
        self._economy.SCV_CEIL = 12
        self._economy.BUILD_PLAN = (
            {
                "unit_type_id": "SupplyDepot",
                "min_m": 100,
                "min_v": 0,
                "offset": (0.0, -14.0),
            },
            {
                "unit_type_id": "Barracks",
                "min_m": 150,
                "min_v": 0,
                "offset": (12.0, -14.0),
                "requires": ("SupplyDepot",),
            },
        )
        self._economy.BUILD_REQUIREMENTS = {"Barracks": ("SupplyDepot",)}
        self._economy.ARMY_COMP = {
            "Marine": {
                "proportion": 1.0,
                "priority": 0,
                "producer": "Barracks",
                "min_m": 50,
                "min_v": 0,
                "supply": 1,
            }
        }

    def receive_player_command(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def decide(self, obs: Any, loop: int) -> list[AllyAction]:
        resources = dict(obs.resources)
        resources["vespene_geysers"] = list(obs.vespene_geysers)
        actions: list[AllyAction] = []
        for action in self._economy.decide(obs, loop, resources=resources):
            if action.kind not in {"gather", "build", "train", "research"}:
                continue
            actions.append(AllyAction(
                entity_id=int(action.entity_id),
                kind=str(action.kind),
                target_entity_id=int(action.target_entity_id),
                target_x=float(action.target_x),
                target_y=float(action.target_y),
                unit_type_id=str(action.unit_type_id),
                ability_id="",
                reason=str(action.reason),
            ))
        if actions and (not self.mode_history or self.mode_history[-1] != self.mode.value):
            self.mode_history.append(self.mode.value)
        return actions

    def oscillation_score(self) -> int:
        return 0

    def drain_notices(self) -> list[Any]:
        return []


def run_normal_start_contract(
    *,
    seed: int = DEFAULT_SEED,
    max_loops: int = DEFAULT_MAX_LOOPS,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the Stage 29 contract and optionally write its JSON report."""

    scenario = build_normal_start_scenario(seed=seed, max_loops=max_loops)
    initial = _initial_state(scenario)
    result = run_ally_scenario(
        scenario,
        NormalStartMacroPolicy(player_id=P2_PLAYER_ID),
        ally_player_id=P2_PLAYER_ID,
        leader_player_id=P1_PLAYER_ID,
        max_loops=max_loops,
        deadlock_threshold=300,
        latency_loops=0,
    )
    final_units = dict(result.final_units_by_type)
    final_resources = dict(result.final_resources)
    event_kinds = set(result.event_kinds)
    checks, details = _build_checks(initial, result, event_kinds)
    status = "PASS" if all(checks[name] for name in REQUIRED_CHECKS) and all(
        checks[name] for name in (
            "initial_state_fair",
            "no_initial_adapter_advantage",
            "enemy_none",
            "native_claim_false",
        )
    ) else "FAIL"

    report = {
        "schemaVersion": 1,
        "contract_schema_version": CONTRACT_SCHEMA_VERSION,
        "status": status,
        "evidence_type": "simulator",
        "result_category": RESULT_CATEGORY,
        "native_claim": False,
        "runtime_claim": RUNTIME_CLAIM,
        "seed": int(seed),
        "max_loops": int(max_loops),
        "scenario_name": scenario["name"],
        "initial_state": {
            "p1": initial["p1"].__dict__,
            "p2": initial["p2"].__dict__,
            "enemy": "none",
        },
        "prohibited_adapter_advantages": {
            advantage: False for advantage in _PROHIBITED_ADVANTAGES
        },
        "checks": checks,
        "check_details": details,
        "summary": {
            "end_loop": int(result.end_loop),
            "end_reason": result.end_reason,
            "trace_hash": result.trace_hash,
            "event_kinds": sorted(event_kinds),
            "action_kind_counts": dict(result.action_kind_counts),
            "final_units_by_type": final_units,
            "final_resources": final_resources,
            "total_dispatched": int(result.total_dispatched),
            "total_dispatch_errors": int(result.total_dispatch_errors),
            "error_breakdown": dict(result.error_breakdown),
            "deadlock_detected": bool(result.deadlock_detected),
            "command_storm_detected": bool(result.command_storm_detected),
            "max_commands_per_loop": int(result.max_commands_per_loop),
        },
    }
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return report


def _initial_state(scenario: dict[str, Any]) -> dict[str, _PlayerStart]:
    session = SimulatorSession()
    session.scenario_load(scenario_dict=scenario, catalog="m7")
    session.scenario_reset()
    return {
        "p1": _player_start(session, P1_PLAYER_ID, scenario),
        "p2": _player_start(session, P2_PLAYER_ID, scenario),
    }


def _player_start(
    session: SimulatorSession,
    player_id: int,
    scenario: dict[str, Any],
) -> _PlayerStart:
    units = session.query_units(owner_player_id=player_id)["units"]
    counts = _count_by_type(unit["unit_type_id"] for unit in units)
    resources = session.query_player(player_id)["resources"]
    combat_units = sum(
        count for unit_type_id, count in counts.items()
        if unit_type_id not in {"SCV", "CommandCenter"}
    )
    extra_buildings = sum(
        count for unit_type_id, count in counts.items()
        if unit_type_id != "CommandCenter"
        and unit_type_id not in {"SCV"}
        and unit_type_id[0].isupper()
    )
    player = next(item for item in scenario["players"] if int(item["id"]) == int(player_id))
    return _PlayerStart(
        race=str(player["race"]).capitalize(),
        minerals=int(resources["minerals"]),
        vespene=int(resources["vespene"]),
        workers=int(counts.get("SCV", 0)),
        command_centers=int(counts.get("CommandCenter", 0)),
        combat_units=int(combat_units),
        extra_buildings=int(extra_buildings),
        supply_used=int(resources["supply_used"]),
        supply_cap=int(resources["supply_cap"]),
    )


def _build_checks(
    initial: dict[str, _PlayerStart],
    result: Any,
    event_kinds: set[str],
) -> tuple[dict[str, bool], dict[str, Any]]:
    p1 = initial["p1"]
    p2 = initial["p2"]
    final_units = dict(result.final_units_by_type)
    final_resources = dict(result.final_resources)
    earned_minerals = _earned_minerals_lower_bound(p2, final_units, final_resources)
    checks = {
        "initial_state_fair": p1 == p2,
        "no_initial_adapter_advantage": all(
            getattr(player, field) == expected
            for player in (p1, p2)
            for field, expected in (
                ("minerals", 50),
                ("vespene", 0),
                ("workers", 12),
                ("command_centers", 1),
                ("combat_units", 0),
                ("extra_buildings", 0),
            )
        ),
        "enemy_none": True,
        "native_claim_false": True,
        "worker_mining": (
            "command_accepted" in event_kinds
            and "gather_start_mining" in event_kinds
            and "gather_picked_up" in event_kinds
            and result.action_kind_counts.get("gather", 0) > 0
        ),
        "resource_income": earned_minerals > 0,
        "resource_deposit": "mineral_deposited" in event_kinds,
        "supply_handling": (
            final_resources.get("supply_cap", 0) > p2.supply_cap
            and final_units.get("SupplyDepot", 0) >= 1
        ),
        "worker_survival": final_units.get("SCV", 0) >= p2.workers,
        "building_construction": (
            "build_completed" in event_kinds
            and final_units.get("SupplyDepot", 0) >= 1
            and final_units.get("Barracks", 0) >= 1
        ),
        "production_completion": "train_completed" in event_kinds,
        "combat_unit_creation": final_units.get("Marine", 0) >= 1,
        "no_dispatch_error": (
            int(result.total_dispatch_errors) == 0
            and not dict(result.error_breakdown)
        ),
        "no_deadlock": not bool(result.deadlock_detected),
    }
    details = {
        "initial_p1": p1.__dict__,
        "initial_p2": p2.__dict__,
        "earned_minerals_lower_bound": earned_minerals,
        "final_units_by_type": final_units,
        "final_resources": final_resources,
        "event_kinds": sorted(event_kinds),
        "action_kind_counts": dict(result.action_kind_counts),
        "error_breakdown": dict(result.error_breakdown),
    }
    return checks, details


def _earned_minerals_lower_bound(
    initial: _PlayerStart,
    final_units: dict[str, int],
    final_resources: dict[str, int],
) -> int:
    completed_cost = (
        max(0, int(final_units.get("SupplyDepot", 0))) * 100
        + max(0, int(final_units.get("Barracks", 0))) * 150
        + max(0, int(final_units.get("Marine", 0))) * 50
    )
    return (
        int(final_resources.get("minerals", 0))
        + int(final_resources.get("reserved_minerals", 0))
        + completed_cost
        - int(initial.minerals)
    )


def _count_by_type(unit_types: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for unit_type_id in unit_types:
        counts[str(unit_type_id)] = counts.get(str(unit_type_id), 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Stage 29 normal-start contract")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--max-loops", type=int, default=DEFAULT_MAX_LOOPS)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run_normal_start_contract(
        seed=args.seed,
        max_loops=args.max_loops,
        output_path=args.out,
    )
    print(json.dumps({
        "status": report["status"],
        "contract_schema_version": report["contract_schema_version"],
        "result_category": report["result_category"],
        "native_claim": report["native_claim"],
        "out": str(args.out),
    }, ensure_ascii=False, separators=(",", ":")))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
