"""Simulator-first P2 native task strategy.

This runner is intentionally separate from the map-derived replay.  The map
replay proves source fidelity; this scenario proves that the project-owned P2
policy can use the simulator's real economy, construction, production, and
combat state transitions without debug injection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .contracts import Observation
from .defend_policy import DefendAction, DefendBasePolicy
from .sim_path import ensure_simulator_on_path
from .simulator_session import SimulatorSession

ensure_simulator_on_path()


P1_PLAYER_ID = 1
P2_PLAYER_ID = 2
ENEMY_PLAYER_ID = 3
P2_BASE = (85.0, 94.0)


def build_native_task_scenario(seed: int = 42, max_loops: int = 320) -> dict:
    """Build a deterministic P1/P2/Enemy scenario with a real P2 economy."""

    base_x, base_y = P2_BASE
    spawns = [
        {"unit_type_id": "CommandCenter", "owner_player_id": P1_PLAYER_ID, "x": 68.0, "y": base_y},
        {"unit_type_id": "Marine", "owner_player_id": P1_PLAYER_ID, "x": 70.0, "y": base_y},
        {"unit_type_id": "CommandCenter", "owner_player_id": P2_PLAYER_ID, "x": base_x, "y": base_y},
    ]
    for index, (dx, dy) in enumerate(
        [(-2.0, -1.0), (-1.0, -1.0), (0.0, -1.0), (1.0, -1.0), (2.0, -1.0), (0.0, 1.0)]
    ):
        spawns.append({
            "unit_type_id": "SCV",
            "owner_player_id": P2_PLAYER_ID,
            "x": base_x + dx,
            "y": base_y + dy,
        })
    # The enemy is outside the opening's base radius but becomes visible to a
    # freshly trained Marine, forcing a real P2 attack decision after opening.
    spawns.append({
        "unit_type_id": "Zergling",
        "owner_player_id": ENEMY_PLAYER_ID,
        "x": 98.0,
        "y": base_y,
    })
    for index, (dx, dy) in enumerate(
        [(-6.0, -4.0), (-4.0, -4.0), (-2.0, -4.0), (2.0, -4.0), (4.0, -4.0), (6.0, -4.0)]
    ):
        spawns.append({
            "unit_type_id": "MineralField",
            "owner_player_id": 0,
            "x": base_x + dx,
            "y": base_y + dy,
            "resource_amount": 1800,
        })
    spawns.append({
        "unit_type_id": "VespeneGeyser",
        "owner_player_id": 0,
        "x": base_x,
        "y": base_y + 6.0,
        "resource_amount": 2500,
    })
    return {
        "schema_version": "m7",
        "name": "stage25-p2-native-task",
        "players": [
            {"id": P1_PLAYER_ID, "name": "Player", "race": "terran", "allies": [P2_PLAYER_ID], "is_ai": False},
            {"id": P2_PLAYER_ID, "name": "AI Ally", "race": "terran", "allies": [P1_PLAYER_ID], "is_ai": True},
            {"id": ENEMY_PLAYER_ID, "name": "Enemy", "race": "zerg", "allies": [], "is_ai": True},
            {"id": 0, "name": "Neutral", "race": "neutral", "allies": [], "is_ai": True},
        ],
        "spawns": spawns,
        "commands": [],
        "max_loops": max(1, int(max_loops)),
        "seed": int(seed),
        "strict": True,
        "win_condition": "custom",
        # The simulator charges construction at completion (matching its
        # deferred-resource contract), so the native opening needs enough
        # observed bank to cover the depot, gas, barracks, and first Marine.
        "initial_minerals": 500,
        "initial_vespene": 0,
    }


def build_native_recovery_scenario(seed: int = 42, max_loops: int = 640) -> dict:
    """Build a native-economy scenario with a real enemy reinforcement wave.

    P2's initial Marine/Medivac are ordinary scenario starting units, while
    replacement Marines must come from the policy's Barracks train queue.  The
    overlay below only issues enemy attack orders; it never creates or removes
    P2 entities and never edits P2 resources.
    """

    scenario = build_native_task_scenario(seed=seed, max_loops=max_loops)
    scenario["name"] = "stage25-p2-native-tactical-recovery"
    scenario["initial_minerals"] = 3000
    scenario["initial_vespene"] = 1000
    scenario["spawns"] = [
        spawn for spawn in scenario["spawns"]
        if not (
            spawn["unit_type_id"] == "Zergling"
            and int(spawn["owner_player_id"]) == ENEMY_PLAYER_ID
        )
    ]
    scenario["spawns"].extend([
        {
            "unit_type_id": "Marine",
            "owner_player_id": P2_PLAYER_ID,
            # Keep the starting tactical force in open space.  The P2
            # production ring is intentionally exercised separately and
            # should not trap a retreating Marine behind its footprints.
            "x": 60.0,
            "y": P2_BASE[1],
            "health_override": 20.0,
        },
        {
            "unit_type_id": "Marine",
            "owner_player_id": P2_PLAYER_ID,
            "x": 61.0,
            "y": P2_BASE[1],
        },
        {
            "unit_type_id": "Medivac",
            "owner_player_id": P2_PLAYER_ID,
            "x": 60.0,
            "y": P2_BASE[1] + 2.0,
        },
    ])
    for index, (dx, dy) in enumerate(((-2.0, 0.0), (0.0, 0.0), (2.0, 0.0), (0.0, 2.0))):
        scenario["spawns"].append({
            "unit_type_id": "Roach",
            "owner_player_id": ENEMY_PLAYER_ID,
            "x": 70.0 + dx,
            "y": P2_BASE[1] + dy,
        })
    return scenario


class NativeRecoveryWaveOverlay:
    """Issue pre-existing enemy attack orders at deterministic wave loops."""

    def __init__(self, attack_loops: Iterable[int] = (120, 300)) -> None:
        self.attack_loops = frozenset(int(loop) for loop in attack_loops)
        self.wave_count = 0
        self.attack_order_count = 0
        self.wave_records: list[dict] = []

    def start(self, session: SimulatorSession, scenario: dict) -> None:
        self.wave_count = 0
        self.attack_order_count = 0
        self.wave_records = []

    def before_step(self, session: SimulatorSession, loop: int) -> list[dict]:
        if int(loop) not in self.attack_loops:
            return []
        world = session.world
        p2_targets = [
            entity for entity in world.entities.values()
            if entity.is_alive
            and int(entity.owner_player_id) == P2_PLAYER_ID
            and entity.unit_type_id in {
                "Marine", "Marauder", "Hellion", "SiegeTank", "Viking"
            }
        ]
        attackers = [
            entity for entity in world.entities.values()
            if entity.is_alive
            and int(entity.owner_player_id) == ENEMY_PLAYER_ID
            and entity.unit_type_id == "Roach"
        ]
        if not p2_targets or not attackers:
            return [{
                "loop": int(loop),
                "kind": "recovery_wave_skipped",
                "reason": "no_live_target_or_attacker",
            }]
        target = min(
            p2_targets,
            key=lambda entity: (
                int(entity.health.raw),
                int(entity.entity_id),
            ),
        )
        issued_ids: list[int] = []
        for attacker in sorted(attackers, key=lambda entity: entity.entity_id):
            session.unit_order(
                [attacker.entity_id],
                "attack_unit",
                int(attacker.owner_player_id),
                target_entity_id=target.entity_id,
            )
            issued_ids.append(int(attacker.entity_id))
        self.wave_count += 1
        self.attack_order_count += len(issued_ids)
        record = {
            "loop": int(loop),
            "kind": "recovery_wave_attack_ordered",
            "attacker_entity_ids": issued_ids,
            "target_entity_id": int(target.entity_id),
            "target_unit_type_id": str(target.unit_type_id),
        }
        self.wave_records.append(record)
        return [record]

    def summary(self) -> dict:
        return {
            "overlay": "native_recovery_wave",
            "wave_count": self.wave_count,
            "enemy_attack_orders": self.attack_order_count,
            "wave_records": list(self.wave_records),
            "p2_injection": False,
        }


@dataclass(frozen=True)
class NativeTaskReport:
    status: str
    end_loop: int
    checks: dict[str, bool]
    action_trace: list[dict]
    event_kinds: list[str]
    initial_resources: dict
    final_resources: dict
    final_units_by_type: dict[str, int]
    error_counts: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "evidence_type": "simulator",
            "runtime_claim": "none; simulator evidence only",
            "end_loop": self.end_loop,
            "checks": self.checks,
            "action_trace": self.action_trace,
            "event_kinds": self.event_kinds,
            "initial_resources": self.initial_resources,
            "final_resources": self.final_resources,
            "final_units_by_type": self.final_units_by_type,
            "error_counts": self.error_counts,
        }


def _nearest_mineral(obs: Observation, unit: dict) -> int:
    if not obs.mineral_fields:
        return 0
    return min(
        obs.mineral_fields,
        key=lambda resource: (
            (float(resource["x"]) - float(unit["x"])) ** 2
            + (float(resource["y"]) - float(unit["y"])) ** 2,
            int(resource["entity_id"]),
        ),
    )["entity_id"]


def _dispatch_action(
    session: SimulatorSession,
    observation: Observation,
    action: DefendAction,
    player_id: int,
) -> dict:
    """Dispatch one policy action and return a state-accounting record."""

    world = session.world
    assert world is not None
    unit = world.get_entity(action.entity_id)
    record: dict[str, Any] = {
        "kind": action.kind,
        "entity_id": action.entity_id,
        "unit_type_id": unit.unit_type_id if unit is not None else "",
        "issuer_player_id": player_id,
        "source_owner": unit.owner_player_id if unit is not None else 0,
        "unit_type_command": action.unit_type_id,
        "target_entity_id": action.target_entity_id,
        "reason": action.reason,
    }
    if unit is None or not unit.is_alive:
        record["result"] = "unit_missing"
        return record
    if unit.owner_player_id != player_id:
        record["result"] = "not_owned"
        return record

    target_entity_id = action.target_entity_id
    if action.kind == "gather" and target_entity_id == 0:
        target_entity_id = _nearest_mineral(observation, {
            "x": unit.x.to_float(),
            "y": unit.y.to_float(),
        })
        if target_entity_id == 0:
            record["result"] = "no_mineral"
            return record
    if action.kind == "attack":
        target = world.get_entity(target_entity_id)
        if target is None or not target.is_alive:
            record["result"] = "stale_target"
            return record
        if not world.players.is_enemy(player_id, target.owner_player_id):
            record["result"] = "friendly_fire_blocked"
            return record

    command_kind = {
        "attack": "attack_unit",
        "move": "move",
        "gather": "smart",
        "train": "train",
        "build": "build",
        "research": "research",
    }.get(action.kind)
    if command_kind is None:
        record["result"] = "ignored"
        return record

    before_results = len(world.command_results)
    try:
        session.unit_order(
            [action.entity_id],
            command_kind,
            player_id,
            target_entity_id=target_entity_id,
            target_x=action.target_x,
            target_y=action.target_y,
            unit_type_id=action.unit_type_id,
        )
    except Exception as exc:  # pragma: no cover - defensive accounting path
        record["result"] = f"exception:{type(exc).__name__}"
        return record
    results = world.command_results[before_results:]
    result = next((item for item in results if item.entity_id == action.entity_id), None)
    record["result"] = "OK" if result is not None and result.ok else (
        getattr(getattr(result, "code", None), "name", "UNKNOWN")
    )
    return record


def run_native_task(seed: int = 42, max_loops: int = 320) -> NativeTaskReport:
    """Run the P2 native economy and tactical loop through SimulatorSession."""

    scenario = build_native_task_scenario(seed, max_loops=max_loops)
    session = SimulatorSession()
    session.scenario_load(scenario_dict=scenario, catalog="m7")
    session.scenario_reset()
    policy = DefendBasePolicy(
        player_id=P2_PLAYER_ID,
        # Keep the opening enemy outside the CommandCenter defense ring.  It
        # remains close enough to be discovered by the Barracks/Marine and
        # therefore exercises the tactical branch after the economy opens.
        base_region=(*P2_BASE, 8.0),
        command_interval=1,
        econ_interval=1,
    )
    initial_resources = session.query_player(P2_PLAYER_ID)["resources"]
    action_trace: list[dict] = []
    event_cursor = 0
    error_counts: dict[str, int] = {}

    for _ in range(max(1, int(max_loops))):
        world = session.world
        assert world is not None
        observation = Observation.from_world(world, P2_PLAYER_ID)
        resources = session.query_player(P2_PLAYER_ID)["resources"]
        resources["vespene_geysers"] = observation.vespene_geysers
        actions = policy.decide(observation, world.clock.now.loop, resources=resources)
        for action in actions:
            if action.kind == "hold":
                continue
            record = _dispatch_action(session, observation, action, P2_PLAYER_ID)
            action_trace.append({"loop": world.clock.now.loop, **record})
            result = record["result"]
            if result != "OK":
                error_counts[result] = error_counts.get(result, 0) + 1
        session.scenario_step(1, snapshot=False)
        if world.clock.now.loop >= max_loops:
            break

    world = session.world
    assert world is not None
    events = world.events.emitted
    event_kinds = [str(getattr(event, "kind", "")) for event in events]
    final_resources = session.query_player(P2_PLAYER_ID)["resources"]
    final_units = [
        entity for entity in world.entities.values()
        if entity.is_alive and entity.owner_player_id == P2_PLAYER_ID
    ]
    final_units_by_type: dict[str, int] = {}
    for entity in final_units:
        final_units_by_type[entity.unit_type_id] = final_units_by_type.get(entity.unit_type_id, 0) + 1

    successful = [record for record in action_trace if record["result"] == "OK"]
    checks = {
        "p2_only_issuer": all(record["issuer_player_id"] == P2_PLAYER_ID for record in action_trace),
        "p2_only_sources": all(record["source_owner"] == P2_PLAYER_ID for record in action_trace),
        "scv_never_attacks": not any(
            record["kind"] == "attack" and record["unit_type_id"] == "SCV"
            for record in action_trace
        ),
        "barracks_built": any(
            record["kind"] == "build"
            and record["unit_type_command"] == "Barracks"
            and record["result"] == "OK"
            for record in action_trace
        ) and "build_completed" in event_kinds,
        "refinery_built": any(
            record["kind"] == "build"
            and record["unit_type_command"] == "Refinery"
            and record["result"] == "OK"
            for record in action_trace
        ) and "build_completed" in event_kinds,
        "marine_trained": any(
            record["kind"] == "train"
            and record["unit_type_command"] == "Marine"
            and record["result"] == "OK"
            for record in action_trace
        ) and "train_completed" in event_kinds and final_units_by_type.get("Marine", 0) > 0,
        "mineral_gathered": "mineral_deposited" in event_kinds,
        "vespene_gathered": "vespene_deposited" in event_kinds,
        "tactical_attack": any(
            record["kind"] == "attack" and record["unit_type_id"] == "Marine" and record["result"] == "OK"
            for record in action_trace
        ),
        "no_debug_injection": not any(
            record["kind"] in {"spawn", "set_resource", "kill"}
            for record in action_trace
        ),
        "successful_dispatch": bool(successful),
    }
    return NativeTaskReport(
        status="PASS" if all(checks.values()) else "FAIL",
        end_loop=world.clock.now.loop,
        checks=checks,
        action_trace=action_trace,
        event_kinds=event_kinds,
        initial_resources=initial_resources,
        final_resources=final_resources,
        final_units_by_type=final_units_by_type,
        error_counts=error_counts,
    )


__all__ = ["NativeTaskReport", "build_native_task_scenario", "run_native_task"]
