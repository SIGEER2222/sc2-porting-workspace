"""Run the Stage 23 typed full-structure clearance controller in live SC2.

The controller observes the native map, declares the same objective players as
the Dead of Night simulator (3, 4, and 5), and uses only the typed Vibe
functions to allocate temporary attackers to live hostile structures. A zero
target result is required for a runtime victory; timeouts remain partial.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe" / "host"))

from vibe_host import VibeHost, read_bank  # noqa: E402


OBJECTIVE_PLAYERS = frozenset({3, 4, 5})
ENEMY_ALLIANCE = 4
ATTACKER_TYPE = "Battlecruiser"
DEFAULT_ATTACKER_COUNT = 192
DEFAULT_MAX_RETRIES = 2
DEFAULT_STEP_SIZE = 112
DEFAULT_MAX_LOOPS = 6000
DEFAULT_DEFENDER_COUNT = 32
DEFAULT_REINFORCEMENT_COUNT = 32
DEFAULT_MAX_REINFORCEMENTS = 2
# Each bank-poll request advances the non-realtime game. Sending several
# requests to one target in the same batch can kill it before later requests
# are consumed, producing avoidable stale-tag errors. Reconcile next loop
# instead of concentrating sequential requests on one target.
DEFAULT_MAX_NO_PROGRESS = 64
DEFAULT_ATTACKERS_PER_TARGET = 1
POLL_STEP_COUNT = 8
SCV_UNIT_TYPE = 45


def _response(resp) -> dict[str, Any]:
    return {
        "kind": resp.kind,
        "request_id": resp.request_id,
        "sequence": resp.sequence,
        "operation": resp.operation,
        "error_code": resp.error_code,
        "state_version": resp.state_version,
        "payload": resp.payload,
        "ok": resp.is_ok,
    }


def _tag32(tag: int) -> int:
    return tag if tag <= 0x7FFFFFFF else tag - 0x100000000


def _canonical_tag(tag: int) -> int:
    return _tag32(int(tag))


def _error_code_name(error_code: Any) -> str:
    """Normalize Host/Galaxy error representations for controller policy."""
    return str(error_code).strip().upper()


def _observe(host: VibeHost) -> dict[str, Any]:
    if host.client is None:
        raise RuntimeError("SC2 client is not connected")
    resp = host.client.observation(timeout=30.0)
    if resp is None or resp.error or not resp.HasField("observation"):
        detail = list(resp.error) if resp is not None else "no response"
        raise RuntimeError(f"observation failed: {detail}")
    obs = resp.observation.observation
    units: list[dict[str, Any]] = []
    for unit in obs.raw_data.units:
        item: dict[str, Any] = {
            "tag": int(unit.tag),
            "canonical_tag": _canonical_tag(unit.tag),
            "owner": int(unit.owner),
            "unit_type": int(unit.unit_type),
            "alliance": int(unit.alliance),
            "health": float(unit.health),
            "health_max": float(unit.health_max),
        }
        if unit.HasField("pos"):
            item["x"] = float(unit.pos.x)
            item["y"] = float(unit.pos.y)
        units.append(item)
    return {
        "loop": int(obs.game_loop),
        "unit_count": len(units),
        "units": units,
        "player_results": [
            int(item.result) for item in resp.observation.player_result
        ],
    }


def _debug_status(bank_name: str) -> dict[str, Any]:
    return dict(read_bank(bank_name).get("debug", {}))


def _launch_profile() -> dict[str, Any]:
    return dict(read_bank("CMCoopLaunchProfile").get("CMUI|LaunchProfile", {}))


def _native_counts(
    host: VibeHost,
    observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    command_center = host.invoke_function(
        "vibe.query.units", {"player": 1, "unit_type": "CommandCenter"}
    )
    scv = host.invoke_function("vibe.query.units", {"player": 1, "unit_type": "SCV"})
    counts = {
        "CommandCenter": command_center.payload.get("count") if command_center.is_ok else None,
        "SCV": scv.payload.get("count") if scv.is_ok else None,
    }
    if observation is not None:
        raw_counts = {
            "CommandCenter": sum(
                1 for unit in observation.get("units", [])
                if int(unit.get("owner", 0)) == 1
                and int(unit.get("unit_type", 0)) == 18
                and float(unit.get("health", 0.0)) > 0.0
            ),
            "SCV": sum(
                1 for unit in observation.get("units", [])
                if int(unit.get("owner", 0)) == 1
                and int(unit.get("unit_type", 0)) == SCV_UNIT_TYPE
                and float(unit.get("health", 0.0)) > 0.0
            ),
        }
        for key, value in raw_counts.items():
            if counts[key] is None:
                counts[key] = value
    return {
        **counts,
        "responses": {
            "CommandCenter": _response(command_center),
            "SCV": _response(scv),
        },
    }


def _objective_targets(
    census_payload: dict[str, Any], observation: dict[str, Any]
) -> dict[int, dict[str, Any]]:
    """Project census rows onto live hostile objective structures.

    The typed census is authoritative for structure identity, while the raw
    observation proves that a tag is still live and hostile in this frame.
    Requiring both prevents stale/dead tags from entering the action planner.
    """
    visible = {
        _canonical_tag(int(unit.get("canonical_tag", unit.get("tag", 0)))): unit
        for unit in observation.get("units", [])
        if float(unit.get("health", 0.0)) > 0.0
    }
    result: dict[int, dict[str, Any]] = {}
    for item in census_payload.get("structures", []):
        owner = int(item.get("owner", 0))
        tag = _canonical_tag(int(item.get("unit_tag", 0)))
        observed = visible.get(tag)
        if (
            owner not in OBJECTIVE_PLAYERS
            or tag <= 0
            or observed is None
            or int(observed.get("owner", 0)) != owner
            or int(observed.get("alliance", 0)) != ENEMY_ALLIANCE
        ):
            continue
        result[tag] = {
            "owner": owner,
            "unit_type": str(item.get("unit_type", "")),
            "unit_tag": tag,
        }
    return result


@dataclass
class ClearanceAllocator:
    """Bounded attacker/target allocation with explicit stale-state handling."""

    max_retries: int = DEFAULT_MAX_RETRIES
    assignments: dict[int, int] = field(default_factory=dict)
    target_attempts: Counter[int] = field(default_factory=Counter)
    blocked_targets: set[int] = field(default_factory=set)
    stats: Counter[str] = field(default_factory=Counter)

    def reconcile(self, live_attackers: set[int], live_targets: set[int]) -> None:
        # INVALID_ARGS can be a race: one of several attackers may have
        # destroyed a target before the next queued attack reaches Galaxy.
        # Retry limits therefore apply within a census window. A target that
        # is still live in the next typed census gets a fresh bounded window.
        for target in list(self.blocked_targets):
            if target in live_targets:
                self.blocked_targets.remove(target)
                self.target_attempts[target] = 0
                self.stats["retry_window_reset"] += 1
        for attacker, target in list(self.assignments.items()):
            if attacker not in live_attackers:
                del self.assignments[attacker]
                self.stats["attacker_lost"] += 1
            elif target not in live_targets:
                del self.assignments[attacker]
                self.stats["target_destroyed"] += 1

    def idle_attackers(self, live_attackers: set[int]) -> list[int]:
        assigned = set(self.assignments)
        return sorted(live_attackers - assigned)

    def available_targets(self, live_targets: set[int]) -> list[int]:
        assigned = set(self.assignments.values())
        return sorted(live_targets - assigned - self.blocked_targets)

    def retryable_targets(self, live_targets: set[int]) -> list[int]:
        """Return live targets eligible for a bounded no-progress retry.

        A target may already have an attacker assignment while that attacker
        is dead, stuck, or no longer producing damage. Keeping retry selection
        separate from ``available_targets`` lets idle attackers reinforce a
        live target without bypassing stale-tag blocking.
        """
        return sorted(set(live_targets) - self.blocked_targets)

    def assign(self, attacker: int, target: int) -> None:
        self.assignments[attacker] = target
        self.stats["allocations"] += 1

    def record_attack_result(self, attacker: int, target: int, ok: bool, error_code: str = "") -> None:
        if ok:
            self.stats["attack_ok"] += 1
            return
        self.stats["attack_rejected"] += 1
        if self.assignments.get(attacker) == target:
            del self.assignments[attacker]
        if _error_code_name(error_code) == "INVALID_ARGS":
            self.stats["stale_or_invalid"] += 1
            self.target_attempts[target] += 1
            if self.target_attempts[target] >= max(1, self.max_retries):
                self.blocked_targets.add(target)
                self.stats["bounded_retry_exhausted"] += 1

    def summary(self) -> dict[str, Any]:
        return {
            **dict(self.stats),
            "active_assignments": len(self.assignments),
            "blocked_target_count": len(self.blocked_targets),
            "target_attempts": {str(k): v for k, v in sorted(self.target_attempts.items())},
        }


def _live_attackers(observation: dict[str, Any], known_tags: set[int]) -> set[int]:
    return {
        int(unit["canonical_tag"])
        for unit in observation.get("units", [])
        if int(unit.get("canonical_tag", 0)) in known_tags
        and int(unit.get("owner", 0)) == 1
        and float(unit.get("health", 0.0)) > 0.0
    }


def _base_anchor(observation: dict[str, Any]) -> tuple[float, float]:
    """Use the observed native base location for temporary support staging."""
    units = [
        unit for unit in observation.get("units", [])
        if int(unit.get("owner", 0)) == 1
        and int(unit.get("unit_type", 0)) != SCV_UNIT_TYPE
        and float(unit.get("health", 0.0)) > 0.0
        and "x" in unit and "y" in unit
    ]
    preferred = next((unit for unit in units if int(unit.get("unit_type", 0)) == 18), None)
    anchor = preferred or (units[0] if units else None)
    return (float(anchor["x"]), float(anchor["y"])) if anchor else (0.0, 0.0)


def _new_spawned_tags(
    observation: dict[str, Any],
    before_tags: set[int],
    *,
    owner: int = 1,
) -> set[int]:
    return {
        int(unit["canonical_tag"])
        for unit in observation.get("units", [])
        if int(unit.get("owner", 0)) == owner
        and int(unit.get("canonical_tag", 0)) not in before_tags
        and float(unit.get("health", 0.0)) > 0.0
    }


def _target_identity(targets: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    return [targets[tag] for tag in sorted(targets)]


def _declared_targets_in_observation(
    declared_targets: dict[int, dict[str, Any]],
    observation: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    """Find declared objective tags that remain live in a terminal observation."""
    visible = {
        _canonical_tag(int(unit.get("canonical_tag", unit.get("tag", 0)))): unit
        for unit in observation.get("units", [])
        if float(unit.get("health", 0.0)) > 0.0
    }
    return {
        tag: target for tag, target in declared_targets.items()
        if tag in visible
        and int(visible[tag].get("owner", 0)) == int(target["owner"])
        and int(visible[tag].get("alliance", 0)) == ENEMY_ALLIANCE
    }


def _declared_targets_in_census(
    declared_targets: dict[int, dict[str, Any]],
    census_payload: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    """Keep declared targets present in a successful typed census.

    Raw observations can lose visibility when a game transitions to its end
    state. A typed census row for a previously declared tag is still evidence
    that the target was not cleared, so it must prevent a false zero verdict.
    """
    live_rows = {
        _canonical_tag(int(item.get("unit_tag", 0))): item
        for item in census_payload.get("structures", [])
    }
    return {
        tag: target
        for tag, target in declared_targets.items()
        if tag in live_rows
        and int(live_rows[tag].get("owner", 0)) == int(target["owner"])
    }


def _project_final_targets(
    census_payload: dict[str, Any] | None,
    observation: dict[str, Any],
    last_known_targets: dict[int, dict[str, Any]],
) -> tuple[dict[int, dict[str, Any]], bool]:
    """Keep the last successful census visible when final transport fails.

    An unavailable final census is not evidence that no targets remain. The
    fallback preserves the last known hostile set while the separate boolean
    keeps the zero-target check tied to a successful final observation.
    """
    if census_payload is None:
        return dict(last_known_targets), False
    return _objective_targets(census_payload, observation), True


def _correlation_check(action_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate the request/response identity carried by every typed result."""
    action_results = [item for item in action_results if item.get("kind") == "attack"]
    operations = [
        item.get("response", {}).get("operation", "")
        for item in action_results
    ]
    request_ids = [
        item.get("response", {}).get("request_id", "")
        for item in action_results
    ]
    state_versions = [
        int(item.get("response", {}).get("state_version", -1))
        for item in action_results
    ]
    valid_ids = all(isinstance(request_id, str) and request_id for request_id in request_ids)
    unique_ids = len(request_ids) == len(set(request_ids))
    valid_operations = all(operation == "function.invoke" for operation in operations)
    valid_versions = all(version >= 0 for version in state_versions)
    return {
        "status": "PASS" if action_results and valid_ids and unique_ids and valid_operations and valid_versions else "FAIL",
        "result_count": len(action_results),
        "unique_request_ids": unique_ids,
        "operations_are_function_invoke": valid_operations,
        "state_versions_nonnegative": valid_versions,
    }


def _finalize(result: dict[str, Any], allocator: ClearanceAllocator) -> dict[str, Any]:
    result["target_allocation_summary"] = allocator.summary()
    result.setdefault("declared_objective_count", 0)
    result["completed_at"] = time.time()
    checks = result.get("checks", {})
    result["verdict"] = "PASS" if result.get("end_reason") == "all_objectives_success" and checks and all(
        item.get("status") == "PASS" for item in checks.values()
    ) else "PARTIAL"
    return result


def _run(args: argparse.Namespace) -> dict[str, Any]:
    map_path = args.map.resolve()
    host = VibeHost(
        sc2_port=args.port,
        bank_name=args.bank_name,
        runtime_bank_name=args.runtime_bank_name,
        artifacts_dir=args.output.parent,
        require_initialization=True,
        realtime=False,
        poll_step_count=POLL_STEP_COUNT,
    )
    result: dict[str, Any] = {
        "stage_id": "23-runtime-full-structure-clearance",
        "evidence_type": "runtime",
        "port": args.port,
        "map_path": str(args.map),
        "objective_definition": {
            "enemy_player_ids": sorted(OBJECTIVE_PLAYERS),
            "required_alliance": ENEMY_ALLIANCE,
            "attacker_type": ATTACKER_TYPE,
            "attacker_count_requested": args.attacker_count,
        },
        "checks": {},
        "responses": {},
        "census_history": [],
        "action_results": [],
        "no_progress_iterations": 0,
    }
    allocator = ClearanceAllocator(max_retries=args.max_retries)
    declared_targets: dict[int, dict[str, Any]] = {}
    loop_before = 0
    started = time.monotonic()

    try:
        connected = host.connect_sc2(map_path=str(map_path))
        result["checks"]["create_game_join_game"] = {
            "status": "PASS" if connected else "FAIL",
            "detail": "VibeHost completed CreateGame + JoinGame" if connected else host.initialization_error,
        }
        if not connected:
            result["end_reason"] = "create_game_join_game_failed"
            return _finalize(result, allocator)

        result["checks"]["initialization_gate"] = {
            "status": "PASS" if host.initialization_complete else "FAIL",
            "status_values": host.initialization_status,
        }
        if not host.initialization_complete:
            result["end_reason"] = "initialization_gate_failed"
            return _finalize(result, allocator)

        native_before = _native_counts(host)
        profile_before = _launch_profile()
        result["native_before"] = native_before
        result["launch_profile_before"] = profile_before
        result["checks"]["native_initialization_observed"] = {
            "status": "PASS" if native_before["CommandCenter"] == 1 and native_before["SCV"] == 12 else "FAIL",
            "CommandCenter": native_before["CommandCenter"],
            "SCV": native_before["SCV"],
        }
        if result["checks"]["native_initialization_observed"]["status"] != "PASS":
            result["end_reason"] = "native_initialization_failed"
            return _finalize(result, allocator)

        initial_observation = _observe(host)
        initial_p1_tags = {
            int(unit["canonical_tag"])
            for unit in initial_observation["units"]
            if int(unit.get("owner", 0)) == 1
        }
        result["observation_before"] = initial_observation
        result["heartbeat_before"] = _debug_status(host.runtime_bank_name).get("bridge_heartbeat", 0)

        census = host.query_structures()
        result["responses"]["census_before"] = _response(census)
        if not census.is_ok:
            result["checks"]["initial_structure_census"] = {"status": "FAIL", "error_code": census.error_code}
            result["end_reason"] = "initial_census_failed"
            return _finalize(result, allocator)
        current_targets = _objective_targets(census.payload, initial_observation)
        declared_targets.update(current_targets)
        result["census_history"].append({
            "loop": initial_observation["loop"],
            "live_objective_count": len(current_targets),
            "targets": _target_identity(current_targets),
        })
        result["checks"]["initial_structure_census"] = {
            "status": "PASS" if current_targets else "FAIL",
            "live_objective_count": len(current_targets),
            "enemy_owners_observed": sorted({item["owner"] for item in current_targets.values()}),
        }
        if not current_targets:
            result["end_reason"] = "no_declared_objective_targets"
            return _finalize(result, allocator)

        anchor_x, anchor_y = _base_anchor(initial_observation)
        result["support_anchor"] = {"x": anchor_x, "y": anchor_y, "source": "native_p1_structure_observation"}
        result["defender_count_requested"] = min(args.defender_count, args.attacker_count)
        spawn = host.invoke_function("vibe.unit.spawn", {
            "unit_type": ATTACKER_TYPE,
            "count": args.attacker_count,
            "player": 1,
            "x": anchor_x,
            "y": anchor_y,
        })
        result["responses"]["attacker_spawn"] = _response(spawn)
        created = int(spawn.payload.get("created", 0)) if spawn.is_ok else 0
        if not spawn.is_ok or created <= 0:
            result["checks"]["temporary_attacker_discovery"] = {
                "status": "FAIL", "created": created, "error_code": spawn.error_code,
            }
            result["end_reason"] = "temporary_attacker_spawn_failed"
            return _finalize(result, allocator)

        if host.client is None or not host.client.step(1, timeout=30.0):
            result["checks"]["temporary_attacker_discovery"] = {"status": "FAIL", "detail": "spawn frame did not advance"}
            result["end_reason"] = "spawn_frame_failed"
            return _finalize(result, allocator)
        after_spawn = _observe(host)
        spawned_tags = {
            int(unit["canonical_tag"])
            for unit in after_spawn["units"]
            if int(unit.get("owner", 0)) == 1
            and int(unit.get("canonical_tag", 0)) not in initial_p1_tags
            and float(unit.get("health", 0.0)) > 0.0
        }
        # The response contains the first created tag even when observation
        # has not exposed all created units yet; retain it as a fallback.
        response_tag = int(spawn.payload.get("unit_tag", 0)) if spawn.is_ok else 0
        if response_tag > 0:
            spawned_tags.add(_canonical_tag(response_tag))
        result["attacker_tags"] = sorted(spawned_tags)
        result["checks"]["temporary_attacker_discovery"] = {
            "status": "PASS" if len(spawned_tags) >= min(created, args.min_attackers) else "FAIL",
            "created": created,
            "observed": len(spawned_tags),
            "minimum_required": min(created, args.min_attackers),
        }
        if result["checks"]["temporary_attacker_discovery"]["status"] != "PASS":
            result["end_reason"] = "temporary_attacker_discovery_failed"
            return _finalize(result, allocator)

        known_attackers = set(spawned_tags)
        defender_tags = set(sorted(known_attackers)[: min(args.defender_count, len(known_attackers))])
        result["defender_tags"] = sorted(defender_tags)
        result["combat_attacker_count"] = len(known_attackers - defender_tags)
        reinforcement_results: list[dict[str, Any]] = []
        terminal_observation: dict[str, Any] | None = None
        terminal_clearance = False
        terminal_census = None
        terminal_native_after: dict[str, Any] | None = None
        loop_before = after_spawn["loop"]
        last_loop = loop_before
        previous_target_count: int | None = None
        last_known_targets = dict(current_targets)
        while last_loop < args.max_loops and time.monotonic() - started < args.wall_time_budget_sec:
            observation = _observe(host)
            live_attackers = _live_attackers(observation, known_attackers)
            live_defenders = live_attackers & defender_tags
            combat_attackers = live_attackers - defender_tags
            census = host.query_structures()
            result["action_results"].append({
                "kind": "census",
                "loop": observation["loop"],
                "response": _response(census),
            })
            if not census.is_ok:
                result["end_reason"] = "census_failed"
                break
            current_targets = _objective_targets(census.payload, observation)
            for tag, target in current_targets.items():
                if tag not in declared_targets:
                    declared_targets[tag] = target
                    allocator.stats["reinforcements_seen"] += 1
            live_target_tags = set(current_targets)
            current_target_count = len(live_target_tags)
            last_known_targets = dict(current_targets)
            if previous_target_count is not None and current_target_count >= previous_target_count:
                result["no_progress_iterations"] += 1
            else:
                result["no_progress_iterations"] = 0
            result["census_history"].append({
                "loop": observation["loop"],
                "live_objective_count": current_target_count,
                "delta_from_previous": (
                    None if previous_target_count is None
                    else current_target_count - previous_target_count
                ),
                "no_progress_iterations": result["no_progress_iterations"],
                "state_version": census.state_version,
                "target_types": dict(Counter(item["unit_type"] for item in current_targets.values())),
            })
            allocator.reconcile(combat_attackers, live_target_tags)
            if not live_target_tags:
                result["end_reason"] = "all_objectives_success"
                # This census is the authoritative zero-target observation.
                # Preserve it before the mission can transition to an end
                # state that rejects subsequent API requests.
                terminal_observation = observation
                terminal_census = census
                terminal_native_after = _native_counts(host, observation)
                last_loop = observation["loop"]
                break
            if result["no_progress_iterations"] >= args.max_no_progress:
                result["end_reason"] = "no_progress_budget_exceeded"
                break
            previous_target_count = current_target_count

            idle_attackers = allocator.idle_attackers(combat_attackers)
            available_targets = allocator.available_targets(live_target_tags)
            # Concentrate a bounded group on each target. A one-attacker-per-
            # building spread leaves the native base exposed while scattered
            # structures survive for thousands of simulation frames.
            target_capacity = max(
                1,
                min(
                    len(available_targets),
                    (len(idle_attackers) + args.attackers_per_target - 1)
                    // args.attackers_per_target,
                ),
            ) if available_targets else 0
            target_slots = available_targets[:target_capacity]
            if result["no_progress_iterations"] > 0 and idle_attackers:
                # Reuse idle attackers against a target that still has a live
                # assignment. This is a retry of the typed attack order, not
                # a force-delete path, and remains bounded per census window.
                retry_capacity = max(
                    1,
                    (len(idle_attackers) + args.attackers_per_target - 1)
                    // args.attackers_per_target,
                )
                selected = set(target_slots)
                for target in allocator.retryable_targets(live_target_tags):
                    if target in selected:
                        continue
                    target_slots.append(target)
                    selected.add(target)
                    if len(target_slots) >= retry_capacity:
                        break
            for index, attacker in enumerate(idle_attackers):
                if not target_slots or index >= len(target_slots) * args.attackers_per_target:
                    break
                target = target_slots[index % len(target_slots)]
                allocator.assign(attacker, target)
                attack = host.attack_unit(attacker, target)
                result["action_results"].append({
                    "kind": "attack",
                    "loop": observation["loop"],
                    "attacker_tag": attacker,
                    "target_tag": target,
                    "response": _response(attack),
                })
                allocator.record_attack_result(attacker, target, attack.is_ok, attack.error_code)

            # Keep a bounded reserve available when the map's hostile waves
            # kill the temporary push. The reserve is spawned at the native
            # base anchor and remains outside the native CommandCenter/SCV
            # census, so this cannot mask an initialization regression.
            if (
                not combat_attackers
                and live_target_tags
                and len(reinforcement_results) < args.max_reinforcements
            ):
                before_tags = {int(unit["canonical_tag"]) for unit in observation["units"]}
                reinforcement = host.invoke_function("vibe.unit.spawn", {
                    "unit_type": ATTACKER_TYPE,
                    "count": min(args.reinforcement_count, 200),
                    "player": 1,
                    "x": anchor_x,
                    "y": anchor_y,
                })
                if host.client is not None and reinforcement.is_ok:
                    host.client.step(1, timeout=30.0)
                reinforcement_observation = _observe(host)
                created_tags = _new_spawned_tags(reinforcement_observation, before_tags)
                known_attackers.update(created_tags)
                reinforcement_results.append({
                    "response": _response(reinforcement),
                    "created": int(reinforcement.payload.get("created", 0)) if reinforcement.is_ok else 0,
                    "observed": len(created_tags),
                })

            if host.client is None:
                result["end_reason"] = "client_disconnected"
                break
            if not host.client.step(args.step_size, timeout=30.0):
                # The final objective can end the mission immediately, closing
                # RequestStep before a typed post-step census is available.
                # Preserve the same-window observation and verify every
                # declared tag is absent instead of treating a failed census
                # as an implicit zero.
                try:
                    terminal_observation = _observe(host)
                except Exception:
                    terminal_observation = None
                terminal_remaining = (
                    _declared_targets_in_observation(declared_targets, terminal_observation)
                    if terminal_observation is not None else declared_targets
                )
                terminal_clearance = bool(
                    terminal_observation is not None
                    and current_target_count > 0
                    and not terminal_remaining
                    and terminal_observation.get("player_results")
                )
                if terminal_clearance:
                    result["end_reason"] = "all_objectives_success"
                    result["terminal_clearance"] = {
                        "status": "PASS",
                        "mode": "terminal_observation_after_request_step_close",
                        "last_typed_census_count": current_target_count,
                        "remaining_declared_tags": [],
                        "player_results": terminal_observation.get("player_results", []),
                    }
                else:
                    result["end_reason"] = "request_step_failed"
                break
            last_loop = _observe(host)["loop"]

        if "end_reason" not in result:
            result["end_reason"] = "time_budget_exceeded"

        if terminal_census is not None:
            final_observation = terminal_observation
            final_census = terminal_census
        else:
            final_observation = terminal_observation or _observe(host)
            final_census = host.query_structures()
        result["responses"]["census_after"] = _response(final_census)
        if final_census.is_ok:
            final_targets = _objective_targets(final_census.payload, final_observation)
            final_census_verified = True
            zero_target_mode = "typed_final_census"
            typed_declared_targets = _declared_targets_in_census(
                declared_targets,
                final_census.payload,
            )
            if typed_declared_targets:
                final_targets = typed_declared_targets
                zero_target_mode = "typed_census_declared_targets_remaining"
        elif terminal_clearance:
            final_targets = _declared_targets_in_observation(declared_targets, final_observation)
            final_census_verified = True
            zero_target_mode = "terminal_observation_after_request_step_close"
        else:
            final_targets, final_census_verified = _project_final_targets(
                None,
                final_observation,
                last_known_targets,
            )
            zero_target_mode = "unverified_census_failure"
        result["observation_after"] = final_observation
        result["reinforcement_results"] = reinforcement_results
        result["remaining_targets"] = _target_identity(final_targets)
        result["remaining_objective_count"] = len(final_targets)
        result["loop_before"] = loop_before
        result["loop_after"] = final_observation["loop"]
        result["checks"]["frames_advanced"] = {
            "status": "PASS" if final_observation["loop"] > loop_before else "FAIL",
            "loop_before": loop_before,
            "loop_after": final_observation["loop"],
        }
        result["checks"]["zero_declared_objective_targets"] = {
            "status": "PASS" if final_census_verified and not final_targets else "FAIL",
            "census_verified": final_census_verified,
            "remaining_count": len(final_targets),
            "remaining": _target_identity(final_targets),
            "verification_mode": zero_target_mode,
        }
        result["checks"]["typed_action_results_correlated"] = {
            **_correlation_check(result["action_results"]),
            "attack_results": sum(item["kind"] == "attack" for item in result["action_results"]),
        }

        native_after = terminal_native_after or _native_counts(host, final_observation)
        profile_after = _launch_profile()
        result["native_after"] = native_after
        result["launch_profile_after"] = profile_after
        replacement_keys = (
            "CreateStartingUnitsP1", "CreateStartingUnitsP2",
            "EnsurePreventDefeatP1", "EnsurePreventDefeatP2", "VanillaRemovalCount",
        )
        profile_clean = all(
            str(profile_before.get(key, "0")) == "0"
            and str(profile_after.get(key, "0")) == "0"
            for key in replacement_keys
        )
        native_preserved = (
            native_after["CommandCenter"] == native_before["CommandCenter"] == 1
            and native_after["SCV"] == native_before["SCV"] == 12
            and profile_clean
        )
        result["checks"]["native_initialization_preserved"] = {
            "status": "PASS" if native_preserved else "FAIL",
            "before": {"CommandCenter": native_before["CommandCenter"], "SCV": native_before["SCV"]},
            "after": {"CommandCenter": native_after["CommandCenter"], "SCV": native_after["SCV"]},
            "replacement_flags_before": {key: profile_before.get(key, 0) for key in replacement_keys},
            "replacement_flags_after": {key: profile_after.get(key, 0) for key in replacement_keys},
        }
        result["heartbeat_after"] = _debug_status(host.runtime_bank_name).get("bridge_heartbeat", 0)
        result["checks"]["heartbeat_observed"] = {
            "status": "PASS" if result["heartbeat_after"] >= result["heartbeat_before"] > 0 else "FAIL",
            "before": result["heartbeat_before"],
            "after": result["heartbeat_after"],
        }
    except Exception as exc:
        result["end_reason"] = "controller_exception"
        result["exception"] = f"{type(exc).__name__}: {exc}"
    finally:
        host.close()

    result["declared_objective_count"] = len(declared_targets)
    return _finalize(result, allocator)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bank-name", default="GalaxyVibe")
    parser.add_argument("--runtime-bank-name", default="CMRERebornDebug")
    parser.add_argument("--attacker-count", type=int, default=DEFAULT_ATTACKER_COUNT)
    parser.add_argument("--defender-count", type=int, default=DEFAULT_DEFENDER_COUNT)
    parser.add_argument("--reinforcement-count", type=int, default=DEFAULT_REINFORCEMENT_COUNT)
    parser.add_argument("--max-reinforcements", type=int, default=DEFAULT_MAX_REINFORCEMENTS)
    parser.add_argument("--min-attackers", type=int, default=8)
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    parser.add_argument("--max-no-progress", type=int, default=DEFAULT_MAX_NO_PROGRESS)
    parser.add_argument("--step-size", type=int, default=DEFAULT_STEP_SIZE)
    parser.add_argument("--max-loops", type=int, default=DEFAULT_MAX_LOOPS)
    parser.add_argument("--wall-time-budget-sec", type=float, default=240.0)
    parser.add_argument("--attackers-per-target", type=int, default=DEFAULT_ATTACKERS_PER_TARGET)
    args = parser.parse_args()
    if not 1 <= args.attacker_count <= 200:
        parser.error("--attacker-count must be between 1 and 200")
    if not 0 <= args.defender_count <= args.attacker_count:
        parser.error("--defender-count must be between 0 and --attacker-count")
    if not 1 <= args.reinforcement_count <= 200:
        parser.error("--reinforcement-count must be between 1 and 200")
    if args.max_reinforcements < 0:
        parser.error("--max-reinforcements must be non-negative")
    if args.max_no_progress < 1:
        parser.error("--max-no-progress must be positive")
    if args.attackers_per_target < 1:
        parser.error("--attackers-per-target must be positive")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = _run(args)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
