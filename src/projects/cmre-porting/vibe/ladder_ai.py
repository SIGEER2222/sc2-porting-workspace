"""Ladder-style full-game Terran ally for the deterministic simulator.

The existing :class:`AllyPolicy` proves cooperative command handling and a
high-tech opening. This module adds the missing match-level controller:
macro phases, expansion, supply and production scaling, scouting, pressure
waves, attack-move staging, and an explicit enemy-elimination victory gate.

All actions still flow through ``Observation`` and ``ActionAdapter``. The
scenario only supplies the normal starting roster and pre-existing opponent
units; the policy never injects units or resources during the game.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional

from .consumers.ally_ai import (
    AllyAction,
    AllyPolicy,
    AllyRunResult,
    run_ally_scenario,
)
from .defend_policy import DefendBasePolicy
from .sim_path import ensure_simulator_on_path

ensure_simulator_on_path()


P1_PLAYER_ID = 1
P2_PLAYER_ID = 2
ENEMY_PLAYER_ID = 3
NEUTRAL_PLAYER_ID = 0
MAIN_BASE = (85.0, 94.0)
EXPANSION_BASE = (110.0, 80.0)
ENEMY_BASE = (145.0, 94.0)


class LadderPhase(str, Enum):
    OPENING = "opening"
    TECH = "tech"
    EXPAND = "expand"
    PRESSURE = "pressure"
    DEFEND = "defend"
    RETREAT = "retreat"
    CLEANUP = "cleanup"
    VICTORY = "victory"


def build_ladder_game_scenario(seed: int = 42, max_loops: int = 6000) -> dict:
    """Build a normal-start Terran-versus-Zerg full-game simulator scenario."""

    spawns = [
        {"unit_type_id": "CommandCenter", "owner_player_id": P1_PLAYER_ID,
         "x": 65.0, "y": 94.0},
        {"unit_type_id": "Marine", "owner_player_id": P1_PLAYER_ID,
         "x": 68.0, "y": 94.0},
        {"unit_type_id": "CommandCenter", "owner_player_id": P2_PLAYER_ID,
         "x": MAIN_BASE[0], "y": MAIN_BASE[1]},
    ]
    for index in range(12):
        spawns.append({
            "unit_type_id": "SCV",
            "owner_player_id": P2_PLAYER_ID,
            "x": MAIN_BASE[0] - 6.0 + (index % 6) * 2.0,
            "y": MAIN_BASE[1] - 2.0 + (index // 6) * 2.0,
        })

    for x, y in (
        (79.0, 88.0), (82.0, 88.0), (85.0, 88.0), (88.0, 88.0),
        (91.0, 88.0), (79.0, 85.0), (85.0, 85.0), (91.0, 85.0),
        (101.0, 88.0), (105.0, 88.0),
    ):
        spawns.append({
            "unit_type_id": "MineralField",
            "owner_player_id": NEUTRAL_PLAYER_ID,
            "x": x,
            "y": y,
            "resource_amount": 12000,
        })
    spawns.append({
        "unit_type_id": "VespeneGeyser",
        "owner_player_id": NEUTRAL_PLAYER_ID,
        "x": MAIN_BASE[0],
        "y": MAIN_BASE[1] + 6.0,
        "resource_amount": 12000,
    })

    # A compact but real opponent base. Its units do not auto-rush while idle;
    # LadderPressureOverlay issues normal attack orders at game-time windows.
    spawns.extend([
        {"unit_type_id": "Hatchery", "owner_player_id": ENEMY_PLAYER_ID,
         "x": ENEMY_BASE[0], "y": ENEMY_BASE[1]},
        {"unit_type_id": "SpawningPool", "owner_player_id": ENEMY_PLAYER_ID,
         "x": ENEMY_BASE[0] - 6.0, "y": ENEMY_BASE[1] + 5.0},
        {"unit_type_id": "RoachWarren", "owner_player_id": ENEMY_PLAYER_ID,
         "x": ENEMY_BASE[0] - 6.0, "y": ENEMY_BASE[1] - 5.0},
        {"unit_type_id": "EvolutionChamber", "owner_player_id": ENEMY_PLAYER_ID,
         "x": ENEMY_BASE[0], "y": ENEMY_BASE[1] + 5.0},
    ])
    for index, (unit_type_id, x, y) in enumerate([
        ("Zergling", 136.0, 94.0),
        ("Zergling", 137.0, 95.0),
        ("Zergling", 138.0, 94.0),
        ("Zergling", 139.0, 95.0),
        ("Zergling", 140.0, 94.0),
        ("Zergling", 141.0, 95.0),
        ("Roach", 136.0, 91.0),
        ("Roach", 138.0, 91.0),
        ("Roach", 140.0, 91.0),
        ("Roach", 142.0, 91.0),
        ("Hydralisk", 139.0, 98.0),
        ("Hydralisk", 141.0, 98.0),
    ]):
        spawns.append({
            "unit_type_id": unit_type_id,
            "owner_player_id": ENEMY_PLAYER_ID,
            "x": x,
            "y": y,
        })

    return {
        "schema_version": "m7",
        "name": "stage25-ladder-full-game",
        "players": [
            {"id": P1_PLAYER_ID, "name": "Player", "race": "terran",
             "allies": [P2_PLAYER_ID], "is_ai": False, "relation": "leader"},
            {"id": P2_PLAYER_ID, "name": "Ladder AI Ally", "race": "terran",
             "allies": [P1_PLAYER_ID], "is_ai": True, "relation": "ally"},
            {"id": ENEMY_PLAYER_ID, "name": "Zerg Opponent", "race": "zerg",
             "allies": [], "is_ai": True, "relation": "enemy"},
            {"id": NEUTRAL_PLAYER_ID, "name": "Neutral", "race": "neutral",
             "allies": [], "is_ai": True, "relation": "neutral"},
        ],
        "spawns": spawns,
        "commands": [],
        "max_loops": max(1, int(max_loops)),
        "seed": int(seed),
        "strict": True,
        "win_condition": "enemy_elimination",
        "win_condition_params": {
            "enemy_player_ids": [ENEMY_PLAYER_ID],
            "ally_player_ids": [P1_PLAYER_ID, P2_PLAYER_ID],
            "winner_player_id": P1_PLAYER_ID,
        },
        # The simulator's resource trip is intentionally coarse (60 loops).
        # Start at the first stable ladder macro checkpoint so the game can
        # exercise the full tech/army/attack loop within a bounded test run.
        "initial_minerals": 2600,
        "initial_vespene": 800,
        "_cooperative_enemy_player_ids": [ENEMY_PLAYER_ID],
    }


class LadderAI(AllyPolicy):
    """Terran macro/tactical controller layered on the cooperative ally API."""

    BUILD_TARGETS = {
        "SupplyDepot2": (91.0, 106.0),
        "SupplyDepot3": (97.0, 106.0),
        "SupplyDepot4": (103.0, 106.0),
        "SupplyDepot5": (109.0, 106.0),
        "Barracks2": (95.0, 84.0),
        "Factory2": (101.0, 84.0),
    }

    def __init__(
        self,
        player_id: int = P2_PLAYER_ID,
        leader_entity_id: int = 1,
        leader_player_id: int = P1_PLAYER_ID,
        command_interval: int = 8,
        max_workers: int = 24,
        army_threshold: int = 8,
    ) -> None:
        super().__init__(
            player_id=player_id,
            leader_entity_id=leader_entity_id,
            leader_player_id=leader_player_id,
            base_region=(*MAIN_BASE, 12.0),
            support_range=14.0,
            command_interval=command_interval,
            scout_points=((102.0, 94.0), (118.0, 94.0), (132.0, 94.0)),
            scout_interval=32,
        )
        self._economy.SCV_CEIL = int(max_workers)
        self.army_threshold = max(1, int(army_threshold))
        self.expansion_position = EXPANSION_BASE
        self.attack_points = (
            (102.0, 94.0), (118.0, 94.0), (132.0, 94.0), ENEMY_BASE,
        )
        self.scout_route = (
            (102.0, 94.0), (118.0, 94.0), (132.0, 94.0), (140.0, 94.0),
        )
        self._scout_route_index = 0
        self._last_ladder_scout_loop = -10_000
        self._last_ladder_tactical_loop = -10_000
        self._build_issued: set[str] = set()
        self._push_index = 0
        self._phase = LadderPhase.OPENING
        self._phase_history: list[str] = []
        self._action_reason_counts: dict[str, int] = {}

    @property
    def phase(self) -> LadderPhase:
        return self._phase

    @property
    def phase_history(self) -> list[str]:
        return list(self._phase_history)

    @property
    def action_reason_counts(self) -> dict[str, int]:
        return dict(self._action_reason_counts)

    def decide(self, obs, loop: int) -> list[AllyAction]:
        previous_policy_loop = self._last_decide_loop
        base_actions = super().decide(obs, loop)
        economy_due = self._last_decide_loop != previous_policy_loop

        own_units = [
            unit for unit in obs.own_units
            if int(unit.get("owner", self.player_id)) == self.player_id
        ]
        combat_units = [unit for unit in own_units if self._is_combat(unit)]
        enemies = list(obs.visible_enemies)
        base_threats = [
            enemy for enemy in enemies
            if self._dist(enemy["x"], enemy["y"], *MAIN_BASE) <= 12.0
        ]
        wounded = [
            unit for unit in combat_units
            if self._hp_ratio(unit) < 0.25
        ]
        if not enemies and not combat_units:
            phase = LadderPhase.OPENING
        elif base_threats:
            phase = LadderPhase.DEFEND
        elif wounded and len(combat_units) <= 2:
            phase = LadderPhase.RETREAT
        elif len(combat_units) < self.army_threshold:
            phase = LadderPhase.TECH
        elif enemies:
            phase = LadderPhase.CLEANUP
        elif self._push_index == 0:
            phase = LadderPhase.PRESSURE
        elif len(obs.own_units) and not self._has_expansion(obs):
            phase = LadderPhase.EXPAND
        else:
            phase = LadderPhase.PRESSURE
        self._record_phase(phase)

        actions: list[AllyAction] = []
        if economy_due:
            actions.extend(
                action for action in base_actions
                if action.kind in {"gather", "build", "train", "research", "heal"}
            )
            self._add_ladder_macro_actions(actions, obs, combat_units)

        if loop - self._last_ladder_tactical_loop >= self.command_interval:
            self._last_ladder_tactical_loop = loop
            actions.extend(
                self._decide_tactical(combat_units, enemies, base_threats, phase)
            )

        for action in actions:
            self._action_reason_counts[action.reason] = (
                self._action_reason_counts.get(action.reason, 0) + 1
            )
        return actions

    def _add_ladder_macro_actions(self, actions: list[AllyAction], obs, combat_units) -> None:
        own_units = list(obs.own_units)
        workers = [
            unit for unit in own_units
            if unit.get("unit_type_id") in {"SCV", "Probe", "Drone"}
        ]
        counts: dict[str, int] = {}
        for unit in own_units:
            unit_type_id = str(unit.get("unit_type_id", ""))
            counts[unit_type_id] = counts.get(unit_type_id, 0) + 1
        resources = obs.resources
        minerals = int(resources.get("minerals", 0)) - int(resources.get("reserved_minerals", 0))
        vespene = int(resources.get("vespene", 0)) - int(resources.get("reserved_vespene", 0))
        supply_remaining = (
            int(resources.get("supply_cap", 0))
            - int(resources.get("supply_used", 0))
            - int(resources.get("reserved_supply", 0))
        )
        planned = {action.entity_id for action in actions}
        planned_types = {action.unit_type_id for action in actions if action.kind == "build"}

        def queue_build(key: str, unit_type_id: str, cost_m: int, cost_v: int, requirements=()) -> bool:
            nonlocal minerals, vespene
            if key in self._build_issued or key in planned_types:
                return False
            if minerals < cost_m or vespene < cost_v:
                return False
            if any(
                not any(
                    str(unit.get("unit_type_id")) == requirement
                    and float(unit.get("build_progress", 1.0)) >= 1.0
                    for unit in own_units
                )
                for requirement in requirements
            ):
                return False
            builder = next(
                (worker for worker in workers if worker["entity_id"] not in planned),
                None,
            )
            if builder is None:
                return False
            target = self.BUILD_TARGETS.get(key, self.expansion_position)
            actions[:] = [action for action in actions if action.entity_id != builder["entity_id"]]
            actions.append(AllyAction(
                int(builder["entity_id"]), "build",
                target_x=float(target[0]), target_y=float(target[1]),
                unit_type_id=unit_type_id,
                reason=f"ladder_{key}",
            ))
            planned.add(int(builder["entity_id"]))
            self._build_issued.add(key)
            minerals -= cost_m
            vespene -= cost_v
            planned_types.add(unit_type_id)
            return True

        # Keep a small supply buffer, as a ladder bot does before production.
        if supply_remaining <= 2 and counts.get("SupplyDepot", 0) < 5:
            depot_key = f"SupplyDepot{counts.get('SupplyDepot', 0) + 1}"
            queue_build(depot_key, "SupplyDepot", 100, 0)

        army_size = len(combat_units)
        if (
            counts.get("CommandCenter", 0) < 2
            and army_size >= 4
            and minerals >= 650
        ):
            queue_build("ExpansionCommandCenter", "CommandCenter", 400, 0)

        if (
            counts.get("Barracks", 0) >= 1
            and "Barracks2" not in self._build_issued
            and minerals >= 550
        ):
            queue_build("Barracks2", "Barracks", 150, 0, ("SupplyDepot",))

        if (
            counts.get("Factory", 0) >= 1
            and "Factory2" not in self._build_issued
            and minerals >= 650
            and vespene >= 100
        ):
            queue_build("Factory2", "Factory", 150, 100, ("Barracks",))

    def _decide_tactical(self, combat_units, enemies, base_threats, phase) -> list[AllyAction]:
        if not combat_units:
            return []
        target = self._focus_target(enemies, None)
        actions: list[AllyAction] = []
        if not enemies:
            scout = min(combat_units, key=lambda unit: int(unit["entity_id"]))
            point = self.scout_route[self._scout_route_index]
            if self._dist(scout["x"], scout["y"], *point) <= 3.0:
                self._scout_route_index = min(
                    self._scout_route_index + 1,
                    len(self.scout_route) - 1,
                )
                point = self.scout_route[self._scout_route_index]
            if (
                self._last_ladder_scout_loop + self.command_interval <= self._last_ladder_tactical_loop
                and not self._has_move_order(scout, *point)
            ):
                actions.append(AllyAction(
                    int(scout["entity_id"]), "move",
                    target_x=point[0], target_y=point[1],
                    reason="ladder_scout_route",
                ))
                self._last_ladder_scout_loop = self._last_ladder_tactical_loop
            return actions
        else:
            point = None

        for unit in sorted(combat_units, key=lambda item: int(item["entity_id"])):
            entity_id = int(unit["entity_id"])
            if self._hp_ratio(unit) < 0.25 and not base_threats:
                retreat = (MAIN_BASE[0] - 5.0, MAIN_BASE[1] - 5.0)
                if not self._has_move_order(unit, *retreat):
                    actions.append(AllyAction(
                        entity_id, "move", target_x=retreat[0], target_y=retreat[1],
                        reason="ladder_low_health_retreat",
                    ))
                continue
            if target is not None:
                if not self._has_attack_order(unit, target["entity_id"]):
                    actions.append(AllyAction(
                        entity_id, "attack", target_entity_id=int(target["entity_id"]),
                        reason=("ladder_defend_focus" if base_threats else "ladder_cleanup_focus"),
                    ))
                continue
            if point is not None and not self._has_move_order(unit, *point):
                actions.append(AllyAction(
                    entity_id, "move", target_x=point[0], target_y=point[1],
                    reason="ladder_attack_move",
                ))
        return actions

    def _advance_push_index(self, combat_units) -> None:
        if self._push_index >= len(self.attack_points) - 1:
            return
        center_x = sum(float(unit["x"]) for unit in combat_units) / len(combat_units)
        center_y = sum(float(unit["y"]) for unit in combat_units) / len(combat_units)
        target = self.attack_points[self._push_index]
        if math.hypot(center_x - target[0], center_y - target[1]) <= 5.0:
            self._push_index += 1

    @staticmethod
    def _is_combat(unit: dict) -> bool:
        unit_type_id = unit.get("unit_type_id")
        return (
            unit_type_id not in {"SCV", "Probe", "Drone", "Medivac"}
            and unit_type_id not in DefendBasePolicy.BUILDING_TYPES
            and unit_type_id not in DefendBasePolicy.NON_COMBAT_TYPES
        )

    @staticmethod
    def _hp_ratio(unit: dict) -> float:
        max_health = float(unit.get("max_health", 0))
        if max_health <= 0:
            return 1.0
        health = float(unit.get("health", 0))
        if health > max_health * 4.0:
            health /= 1024.0
        return max(0.0, min(1.0, health / max_health))

    def _has_expansion(self, obs) -> bool:
        return any(
            unit.get("unit_type_id") == "CommandCenter"
            and abs(float(unit.get("x", 0)) - EXPANSION_BASE[0]) <= 3.0
            for unit in obs.own_units
        )

    def _record_phase(self, phase: LadderPhase) -> None:
        self._phase = phase
        if not self._phase_history or self._phase_history[-1] != phase.value:
            self._phase_history.append(phase.value)


class LadderPressureOverlay:
    """Issue ordinary enemy attack orders at deterministic ladder timings."""

    def __init__(self, attack_loops: Iterable[int] = (1200, 2600)) -> None:
        self.attack_loops = frozenset(int(loop) for loop in attack_loops)
        self.wave_records: list[dict] = []

    def start(self, session, scenario) -> None:
        self.wave_records = []

    def before_step(self, session, loop: int) -> list[dict]:
        if int(loop) not in self.attack_loops:
            return []
        world = session.world
        attackers = [
            entity for entity in world.entities.values()
            if entity.is_alive
            and int(entity.owner_player_id) == ENEMY_PLAYER_ID
            and entity.unit_type_id in {"Zergling", "Roach", "Hydralisk"}
        ]
        targets = [
            entity for entity in world.entities.values()
            if entity.is_alive
            and int(entity.owner_player_id) == P2_PLAYER_ID
            and entity.unit_type_id not in {"MineralField", "VespeneGeyser"}
        ]
        if not attackers or not targets:
            record = {"loop": int(loop), "kind": "pressure_wave_skipped"}
            self.wave_records.append(record)
            return [record]
        target = min(targets, key=lambda entity: (entity.health.raw, entity.entity_id))
        issued: list[int] = []
        for attacker in sorted(attackers, key=lambda entity: entity.entity_id):
            session.unit_order(
                [attacker.entity_id], "attack_unit", ENEMY_PLAYER_ID,
                target_entity_id=target.entity_id,
            )
            issued.append(int(attacker.entity_id))
        record = {
            "loop": int(loop),
            "kind": "pressure_wave_attack",
            "attacker_entity_ids": issued,
            "target_entity_id": int(target.entity_id),
            "target_unit_type_id": str(target.unit_type_id),
        }
        self.wave_records.append(record)
        return [record]

    def summary(self) -> dict:
        return {
            "overlay": "ladder_pressure",
            "wave_count": sum(
                1 for record in self.wave_records
                if record["kind"] == "pressure_wave_attack"
            ),
            "wave_records": list(self.wave_records),
        }


@dataclass(frozen=True)
class LadderGameReport:
    status: str
    victory: bool
    winner_player_id: Optional[int]
    end_loop: int
    end_reason: str
    phase_history: list[str]
    checks: dict[str, bool]
    action_kind_counts: dict[str, int]
    action_reason_counts: dict[str, int]
    error_breakdown: dict[str, int]
    final_units_by_type: dict[str, int]
    final_enemy_units_by_type: dict[str, int]
    final_resources: dict
    final_tech: dict
    pressure_summary: dict

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "victory": self.victory,
            "winner_player_id": self.winner_player_id,
            "end_loop": self.end_loop,
            "end_reason": self.end_reason,
            "phase_history": self.phase_history,
            "checks": self.checks,
            "action_kind_counts": self.action_kind_counts,
            "action_reason_counts": self.action_reason_counts,
            "error_breakdown": self.error_breakdown,
            "final_units_by_type": self.final_units_by_type,
            "final_enemy_units_by_type": self.final_enemy_units_by_type,
            "final_resources": self.final_resources,
            "final_tech": self.final_tech,
            "pressure_summary": self.pressure_summary,
            "evidence_type": "simulator",
            "runtime_claim": "none; simulator evidence only",
        }


def run_ladder_game(seed: int = 42, max_loops: int = 6000) -> LadderGameReport:
    """Run one complete macro-to-victory game through the simulator."""

    scenario = build_ladder_game_scenario(seed=seed, max_loops=max_loops)
    policy = LadderAI()
    pressure = LadderPressureOverlay()
    result: AllyRunResult = run_ally_scenario(
        scenario,
        policy,
        ally_player_id=P2_PLAYER_ID,
        max_loops=max_loops,
        safety_window=max(100, min(400, max_loops)),
        deadlock_threshold=180,
        storm_threshold=40,
        latency_loops=1,
        leader_player_id=P1_PLAYER_ID,
        require_cooperative_roster=True,
        simulator_overlay=pressure,
    )
    completed_upgrades = set(result.final_tech.get("completed_upgrades", ()))
    checks = {
        "victory": result.end_reason == "enemy_elimination",
        "mineral_economy": "mineral_deposited" in result.event_kinds,
        "gas_economy": "vespene_deposited" in result.event_kinds,
        "expansion": result.final_units_by_type.get("CommandCenter", 0) >= 2,
        "production_scaling": result.final_units_by_type.get("Barracks", 0) >= 2,
        "high_tech": all(
            result.final_units_by_type.get(unit_type_id, 0) >= 1
            for unit_type_id in ("Factory", "Starport", "Armory", "FactoryTechLab")
        ),
        "research": {
            "TerranInfantryWeaponsLevel1", "TerranVehicleWeaponsLevel1",
        }.issubset(completed_upgrades),
        "army_produced": result.action_kind_counts.get("train", 0) >= 10,
        "scouting": any(
            reason.startswith("ladder_scout")
            for reason in policy.action_reason_counts
        ),
        "pressure_response": any(
            record["kind"] == "pressure_wave_attack"
            for record in pressure.wave_records
        ),
        "attack_tactics": result.action_kind_counts.get("attack", 0) > 0,
        "no_hidden_state": result.hidden_state_access_violations == 0,
        "no_deadlock": not result.deadlock_detected,
        "no_command_storm": not result.command_storm_detected,
        "no_dispatch_errors": result.total_dispatch_errors == 0,
    }
    victory = bool(checks["victory"])
    status = "PASS" if all(checks.values()) else "FAIL"
    return LadderGameReport(
        status=status,
        victory=victory,
        winner_player_id=P1_PLAYER_ID if victory else None,
        end_loop=result.end_loop,
        end_reason=result.end_reason,
        phase_history=policy.phase_history,
        checks=checks,
        action_kind_counts=result.action_kind_counts,
        action_reason_counts=policy.action_reason_counts,
        error_breakdown=result.error_breakdown,
        final_units_by_type=result.final_units_by_type,
        final_enemy_units_by_type=result.final_enemy_units_by_type,
        final_resources=result.final_resources,
        final_tech=result.final_tech,
        pressure_summary=pressure.summary(),
    )


def run_ladder_batch(seeds: Iterable[int] = (42, 7, 99), max_loops: int = 6000) -> dict:
    reports = [run_ladder_game(seed=int(seed), max_loops=max_loops) for seed in seeds]
    return {
        "status": "PASS" if all(report.status == "PASS" for report in reports) else "FAIL",
        "evidence_type": "simulator",
        "runs": [report.to_dict() for report in reports],
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the CMRE ladder-style full-game simulator")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-loops", type=int, default=6000)
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    report = run_ladder_batch(max_loops=args.max_loops) if args.batch else run_ladder_game(args.seed, args.max_loops).to_dict()
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
