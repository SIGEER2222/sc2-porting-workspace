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
    AllyMode,
    AllyPolicy,
    AllyRunResult,
    run_ally_scenario,
)
from .defend_policy import DefendBasePolicy
from .replay_player import load_replay, render_player_html
from .sim_path import ensure_simulator_on_path

ensure_simulator_on_path()


P1_PLAYER_ID = 1
P2_PLAYER_ID = 2
ENEMY_PLAYER_ID = 3
NEUTRAL_PLAYER_ID = 0
MAIN_BASE = (85.0, 94.0)
EXPANSION_BASE = (110.0, 80.0)
ENEMY_BASE = (145.0, 94.0)
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_REPLAY_DIR = (
    REPO_ROOT
    / "artifacts"
    / "projects"
    / "cmre-porting"
    / "stage25-ai-ally-capability-completion"
    / "ladder-full-game-replay"
)


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
        base_position: tuple[float, float] = MAIN_BASE,
        expansion_position: tuple[float, float] = EXPANSION_BASE,
        attack_points: Optional[Iterable[tuple[float, float]]] = None,
        scout_route: Optional[Iterable[tuple[float, float]]] = None,
        base_radius: float = 12.0,
        allow_expansion: bool = True,
        build_offsets: Optional[dict[str, tuple[float, float]]] = None,
        enable_map_main_push: bool = True,
        mode_model: Optional[object] = None,
    ) -> None:
        self.base_position = (float(base_position[0]), float(base_position[1]))
        self.base_radius = float(base_radius)
        self.allow_expansion = bool(allow_expansion)
        self.enable_map_main_push = bool(enable_map_main_push)
        self.expansion_position = (
            float(expansion_position[0]), float(expansion_position[1])
        )
        self.attack_points = tuple(
            (float(x), float(y))
            for x, y in (attack_points or (
                (102.0, 94.0), (118.0, 94.0), (132.0, 94.0), ENEMY_BASE,
            ))
        ) or (self.expansion_position,)
        self.scout_route = tuple(
            (float(x), float(y))
            for x, y in (scout_route or (
                (102.0, 94.0), (118.0, 94.0), (132.0, 94.0), (140.0, 94.0),
            ))
        ) or (self.base_position,)
        base_x, base_y = self.base_position
        self.build_targets = {
            "SupplyDepot2": (base_x + 6.0, base_y + 12.0),
            "SupplyDepot3": (base_x + 12.0, base_y + 12.0),
            "SupplyDepot4": (base_x + 18.0, base_y + 12.0),
            "SupplyDepot5": (base_x + 24.0, base_y + 12.0),
            # Keep the production ring on the side of the AI base away from
            # the leader.  A map-derived P1/P2 pair can be close together,
            # and building through the leader's footprint is a real placement
            # failure rather than a harmless replay artifact.
            "Barracks2": (base_x - 10.0, base_y - 10.0),
            "Factory2": (base_x - 4.0, base_y - 10.0),
        }
        if build_offsets:
            for unit_type_id, offset in build_offsets.items():
                target = (
                    base_x + float(offset[0]), base_y + float(offset[1])
                )
                self.build_targets[unit_type_id] = target
                if not unit_type_id.startswith("SupplyDepot"):
                    self.build_targets[f"{unit_type_id}2"] = target
        super().__init__(
            player_id=player_id,
            leader_entity_id=leader_entity_id,
            leader_player_id=leader_player_id,
            base_region=(*self.base_position, self.base_radius),
            support_range=14.0,
            command_interval=command_interval,
            scout_points=self.scout_route[:3],
            scout_interval=32,
            mode_model=mode_model,
        )
        self._economy.SCV_CEIL = int(max_workers)
        if build_offsets:
            self._economy.BUILD_PLAN = tuple(
                {**build, "offset": tuple(build_offsets.get(build["unit_type_id"], build["offset"]))}
                for build in self._economy.BUILD_PLAN
            )
        self.army_threshold = max(1, int(army_threshold))
        self._scout_route_index = 0
        self._last_ladder_scout_loop = -10_000
        self._last_ladder_tactical_loop = -10_000
        self._build_issued: set[str] = set()
        self._push_index = 0
        self._map_scout_issued = False
        self._phase = LadderPhase.OPENING
        self._phase_history: list[str] = []
        self._action_reason_counts: dict[str, int] = {}
        self._last_observation_own_units: list[dict] = []
        self._last_observation_structure_points: tuple[tuple[float, float], ...] = ()
        self._map_adapter_mode = bool(build_offsets)
        self._map_primary_build_types = set(build_offsets or {})

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
        self._last_observation_own_units = own_units
        self._last_observation_structure_points = tuple(
            (float(unit.get("x", 0.0)), float(unit.get("y", 0.0)))
            for unit in [*obs.own_units, *obs.visible_allies]
            if unit.get("unit_type_id") in DefendBasePolicy.BUILDING_TYPES
        )
        combat_units = [unit for unit in own_units if self._is_combat(unit)]
        enemies = list(obs.visible_enemies)
        base_threats = [
            enemy for enemy in enemies
            if self._dist(enemy["x"], enemy["y"], *self.base_position) <= self.base_radius
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

        # The map-derived ring is selected from static Objects, while the
        # ladder macro can add a second production building or a depot after
        # the opening.  Repair targets against the current public observation
        # before dispatch so two valid plans cannot converge on one footprint.
        self._repair_build_targets(actions, obs)

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
        # The base economy policy and the ladder macro planner share one
        # decision batch.  Simulator reservations cover earlier dispatched
        # orders, but not actions returned by the base policy in this batch.
        # Remove those costs before considering an additional macro order so
        # the combined batch cannot overspend the public balance.
        planned_minerals = 0
        planned_vespene = 0
        for action in actions:
            cost_m, cost_v = self._action_cost(action)
            planned_minerals += cost_m
            planned_vespene += cost_v
        minerals = max(0, minerals - planned_minerals)
        vespene = max(0, vespene - planned_vespene)
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
            target = self.build_targets.get(key, self.expansion_position)
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
            self.allow_expansion
            and counts.get("CommandCenter", 0) < 2
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

    @staticmethod
    def _action_cost(action: AllyAction) -> tuple[int, int]:
        """Return the canonical cost for an already planned typed action."""

        unit_type_id = str(action.unit_type_id or "")
        if action.kind == "train":
            if unit_type_id == "SCV":
                return DefendBasePolicy.SCV_COST_M, DefendBasePolicy.SCV_COST_V
            info = DefendBasePolicy.ARMY_COMP.get(unit_type_id)
            if info is not None:
                return int(info["min_m"]), int(info["min_v"])
        elif action.kind == "build":
            for build in DefendBasePolicy.BUILD_PLAN:
                if unit_type_id == str(build["unit_type_id"]):
                    return int(build["min_m"]), int(build["min_v"])
            macro_costs = {
                "CommandCenter": (400, 0),
                "Barracks": (150, 0),
                "Factory": (150, 100),
            }
            if unit_type_id in macro_costs:
                return macro_costs[unit_type_id]
        elif action.kind == "research":
            for research in DefendBasePolicy.RESEARCH_PLAN:
                if unit_type_id == str(research["upgrade_id"]):
                    return int(research["min_m"]), int(research["min_v"])
        return 0, 0

    def _repair_build_targets(self, actions: list[AllyAction], obs) -> None:
        """Move map-adapter build orders to the next visible free placement.

        ``DefendBasePolicy`` already handles add-on socket placement from the
        exact parent Factory.  All other build orders are point placements and
        can be checked using only the public observation plus earlier actions
        in the same decision batch.
        """

        building_types = set(DefendBasePolicy.BUILDING_TYPES)
        resources = list(getattr(obs, "mineral_fields", ()))
        resources.extend(getattr(obs, "vespene_geysers", ()))
        occupied = [
            (float(unit.get("x", 0.0)), float(unit.get("y", 0.0)))
            for unit in obs.own_units
            if unit.get("unit_type_id") in building_types
        ]
        if self._map_adapter_mode:
            occupied.extend(
                (float(unit.get("x", 0.0)), float(unit.get("y", 0.0)))
                for unit in getattr(obs, "visible_allies", ())
                if unit.get("unit_type_id") in building_types
            )
        occupied.extend(
            (float(resource.get("x", 0.0)), float(resource.get("y", 0.0)))
            for resource in resources
        )
        placed: list[tuple[float, float]] = []
        candidate_offsets = (
            (0.0, 0.0), (0.0, -12.0), (12.0, 0.0), (-12.0, 0.0),
            (0.0, 12.0), (12.0, -12.0), (-12.0, -12.0),
            (12.0, 12.0), (-12.0, 12.0), (18.0, -6.0), (-18.0, -6.0),
        )
        if self._map_adapter_mode:
            candidate_offsets += (
                (18.0, 6.0), (-18.0, 6.0), (24.0, -12.0), (-24.0, -12.0),
                (24.0, 12.0), (-24.0, 12.0), (30.0, 0.0), (-30.0, 0.0),
                (0.0, 30.0), (0.0, -30.0), (36.0, 0.0), (-36.0, 0.0),
                (48.0, 0.0), (-48.0, 0.0), (0.0, 48.0), (0.0, -48.0),
                (60.0, 0.0), (-60.0, 0.0), (0.0, 60.0), (0.0, -60.0),
            )
        placement_clearance = 12.0 if self._map_adapter_mode else 9.0

        gas_building_types = {"Refinery", "Assimilator", "Extractor"}
        for action in actions:
            if action.kind != "build" or action.unit_type_id == "FactoryTechLab":
                continue
            # Gas structures are not free-form point placements. Their target
            # must stay on the visible geyser selected by DefendBasePolicy;
            # moving the point to avoid the geyser silently produces a fake
            # refinery that can never start a gas economy.
            if action.unit_type_id in gas_building_types:
                continue
            preferred = (float(action.target_x), float(action.target_y))
            # A build action without a point is invalid for this adapter; let
            # the existing dispatch error model report it truthfully.
            if preferred == (0.0, 0.0):
                continue
            is_map_primary = (
                self._map_adapter_mode
                and action.unit_type_id in self._map_primary_build_types
                and action.reason == f"build_{action.unit_type_id}"
            )
            if is_map_primary:
                # Keep the static point available as a fallback if the
                # public-observation candidate below is rejected at dispatch.
                action.fallback_target_x = preferred[0]
                action.fallback_target_y = preferred[1]
            candidates = [
                preferred,
                *(
                    (preferred[0] + dx, preferred[1] + dy)
                    for dx, dy in candidate_offsets[1:]
                ),
            ]
            selected = None
            for candidate in candidates:
                if any(self._dist(candidate[0], candidate[1], x, y) < placement_clearance for x, y in occupied):
                    continue
                if any(self._dist(candidate[0], candidate[1], x, y) < placement_clearance for x, y in placed):
                    continue
                selected = candidate
                break
            if selected is None:
                if action.unit_type_id != "CommandCenter":
                    continue
                # Some CMRE expansion markers overlap a native resource. If
                # every conservative candidate is occupied, choose the
                # farthest public-observation point in the same local search
                # ring. This keeps expansion in the map adapter's area while
                # avoiding a known position_blocked dispatch.
                selected = max(
                    candidates,
                    key=lambda candidate: min(
                        (
                            self._dist(candidate[0], candidate[1], x, y)
                            for x, y in occupied
                        ),
                        default=float("inf"),
                    ),
                )
            action.target_x, action.target_y = selected
            placed.append(selected)

    def _decide_tactical(self, combat_units, enemies, base_threats, phase) -> list[AllyAction]:
        if not combat_units:
            return []
        if self.mode == AllyMode.HOLD:
            return []
        if self.mode == AllyMode.RETREAT and not base_threats:
            actions: list[AllyAction] = []
            retreat = (self.base_position[0] - 5.0, self.base_position[1] - 5.0)
            for unit in sorted(combat_units, key=lambda item: int(item["entity_id"])):
                # A learned mode is a group-level recommendation. Apply it
                # to genuinely wounded combat units only; sending a healthy
                # army home because one visible unit is hurt stalls macro
                # progress and is not the intended P2 safety contract.
                if self._hp_ratio(unit) >= 0.50:
                    continue
                if self._movement_start_blocked(unit) or self._has_move_order(unit, *retreat):
                    continue
                actions.append(AllyAction(
                    int(unit["entity_id"]), "move",
                    target_x=retreat[0], target_y=retreat[1],
                    reason="ml_retreat_mode",
                ))
            return actions
        target = self._focus_target(enemies, None)
        actions: list[AllyAction] = []
        if not enemies:
            if self.enable_map_main_push and len(combat_units) >= self.army_threshold:
                # Once a medium-sized force exists, behave like a simple
                # python-sc2 ladder bot: periodically attack-move the main
                # army through known pressure points instead of scouting with
                # one unit forever while the rest holds at home.
                self._advance_push_index(combat_units)
                point = self.attack_points[
                    min(self._push_index, len(self.attack_points) - 1)
                ]
                scout_id = None
                if not self._map_scout_issued:
                    scout = min(
                        combat_units,
                        key=lambda unit: int(unit["entity_id"]),
                    )
                    if not self._has_move_order(scout, *self.scout_route[0]):
                        actions.append(AllyAction(
                            int(scout["entity_id"]), "move",
                            target_x=self.scout_route[0][0],
                            target_y=self.scout_route[0][1],
                            reason="ladder_scout_route",
                        ))
                        scout_id = int(scout["entity_id"])
                        self._map_scout_issued = True
                for index, unit in enumerate(
                    sorted(combat_units, key=lambda item: int(item["entity_id"]))
                ):
                    entity_id = int(unit["entity_id"])
                    if entity_id == scout_id:
                        continue
                    if self._movement_start_blocked(unit):
                        continue
                    # Keep the force in a compact lateral spread. Vertical
                    # offsets can land on the production ring and make the
                    # simulator's deterministic ground path unreachable.
                    slot_x = point[0] + (float(index % 5) - 2.0) * 3.0
                    slot_y = point[1]
                    if (
                        self._dist(unit["x"], unit["y"], slot_x, slot_y) > 3.0
                        and unit.get("state") != "moving"
                        and not self._has_move_order(unit, slot_x, slot_y)
                    ):
                        actions.append(AllyAction(
                            entity_id, "attack_move",
                            target_x=slot_x, target_y=slot_y,
                            reason="ladder_attack_move",
                        ))
                return actions
            structure_points = [
                (float(unit.get("x", 0.0)), float(unit.get("y", 0.0)))
                for unit in getattr(self, "_last_observation_own_units", ())
                if unit.get("unit_type_id") in DefendBasePolicy.BUILDING_TYPES
            ]
            scout_candidates = [
                unit for unit in combat_units
                if unit.get("state") not in {"moving", "attacking", "building"}
                and not any(
                    self._dist(unit["x"], unit["y"], x, y) < 4.0
                    for x, y in structure_points
                )
            ]
            if not scout_candidates:
                return actions
            scout = min(scout_candidates, key=lambda unit: int(unit["entity_id"]))
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

        focus_attack_issued = False
        for unit in sorted(combat_units, key=lambda item: int(item["entity_id"])):
            entity_id = int(unit["entity_id"])
            if self._hp_ratio(unit) < 0.25 and not base_threats:
                retreat = (self.base_position[0] - 5.0, self.base_position[1] - 5.0)
                if not self._movement_start_blocked(unit) and not self._has_move_order(unit, *retreat):
                    actions.append(AllyAction(
                        entity_id, "move", target_x=retreat[0], target_y=retreat[1],
                        reason="ladder_low_health_retreat",
                    ))
                continue
            if target is not None:
                if self._has_attack_order(unit, target["entity_id"]):
                    continue
                if not focus_attack_issued:
                    actions.append(AllyAction(
                        entity_id, "attack", target_entity_id=int(target["entity_id"]),
                        reason=("ladder_defend_focus" if base_threats else "ladder_cleanup_focus"),
                    ))
                    focus_attack_issued = True
                else:
                    # Once a visible target exists, focus-fire it directly.
                    # The initial no-contact branch still uses group
                    # attack-move; direct focus avoids repeatedly pathing
                    # through an enemy structure footprint during cleanup.
                    if (
                        not self._has_attack_order(unit, int(target["entity_id"]))
                    ):
                        actions.append(AllyAction(
                            entity_id,
                            "attack",
                            target_entity_id=int(target["entity_id"]),
                            reason="ladder_cleanup_focus",
                        ))
                continue
            if (
                point is not None
                and not self._movement_start_blocked(unit)
                and not self._has_move_order(unit, *point)
            ):
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

    def _movement_start_blocked(self, unit: dict) -> bool:
        """Avoid point orders from a public-observation structure footprint.

        Production can place a newly trained unit on an addon cell, and the
        cooperative leader can leave a unit beside its base structure. The
        simulator correctly rejects paths that start inside those occupied
        cells. Skipping that unit keeps the rest of the P2 force moving and
        avoids retrying an order that cannot become valid without hidden map
        state or a teleport-like correction.
        """

        if not self._map_adapter_mode:
            return False
        return any(
            self._dist(float(unit.get("x", 0.0)), float(unit.get("y", 0.0)), x, y) <= 2.5
            for x, y in self._last_observation_structure_points
        )

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
            and abs(float(unit.get("x", 0)) - self.expansion_position[0]) <= 3.0
            and abs(float(unit.get("y", 0)) - self.expansion_position[1]) <= 3.0
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
    replay_path: str = ""
    replay_html_path: str = ""
    replay_frame_count: int = 0
    ml_decision_count: int = 0

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
            "replay_path": self.replay_path,
            "replay_html_path": self.replay_html_path,
            "replay_frame_count": self.replay_frame_count,
            "ml_decision_count": self.ml_decision_count,
            "evidence_type": "simulator",
            "runtime_claim": "none; simulator evidence only",
        }


def run_ladder_game(
    seed: int = 42,
    max_loops: int = 6000,
    replay_dir: Optional[Path] = None,
    mode_model: Optional[object] = None,
) -> LadderGameReport:
    """Run one complete macro-to-victory game through the simulator."""

    scenario = build_ladder_game_scenario(seed=seed, max_loops=max_loops)
    policy = LadderAI(mode_model=mode_model)
    pressure = LadderPressureOverlay()
    replay_path: Optional[Path] = None
    replay_html_path: Optional[Path] = None
    if replay_dir is not None:
        seed_dir = Path(replay_dir) / f"seed-{int(seed)}"
        replay_path = seed_dir / "replay.jsonl"
        replay_html_path = seed_dir / "state-driven-player.html"
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
        replay_log_path=replay_path,
        simulator_overlay=pressure,
    )
    replay_frame_count = 0
    if replay_path is not None and replay_html_path is not None:
        records = load_replay(replay_path)
        replay_frame_count = sum(
            1
            for record in records
            if record.get("record_type") == "frame"
            or "entities_by_player" in record
        )
        render_player_html(records, replay_path, replay_html_path)
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
        replay_path=str(replay_path) if replay_path is not None else "",
        replay_html_path=(
            str(replay_html_path) if replay_html_path is not None else ""
        ),
        replay_frame_count=replay_frame_count,
        ml_decision_count=policy.ml_decision_count,
    )


def run_ladder_batch(
    seeds: Iterable[int] = (42, 7, 99),
    max_loops: int = 6000,
    replay_dir: Optional[Path] = None,
    mode_model: Optional[object] = None,
) -> dict:
    reports = [
        run_ladder_game(
            seed=int(seed),
            max_loops=max_loops,
            replay_dir=replay_dir,
            mode_model=mode_model,
        )
        for seed in seeds
    ]
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
    parser.add_argument(
        "--replay-dir",
        type=Path,
        default=DEFAULT_REPLAY_DIR,
        help="输出 JSONL 回放和 state-driven-player.html 的目录（默认开启）",
    )
    parser.add_argument(
        "--no-replay",
        action="store_true",
        help="关闭默认回放输出",
    )
    args = parser.parse_args(argv)
    replay_dir = None if args.no_replay else args.replay_dir
    report = (
        run_ladder_batch(max_loops=args.max_loops, replay_dir=replay_dir)
        if args.batch
        else run_ladder_game(
            args.seed,
            args.max_loops,
            replay_dir=replay_dir,
        ).to_dict()
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
