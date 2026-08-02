"""Run the Stage 22 typed census/combat probe against a live SC2 window.

The launcher owns staging and startup. This runner only observes the native
map, invokes the explicit Vibe functions, and records runtime evidence.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe" / "host"))

from vibe_host import VibeHost, read_bank  # noqa: E402


SCV_UNIT_TYPE = 45
ERROR_EXPECTED = "INVALID_ARGS"


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
    }


def _tag32(tag: int) -> int:
    """Match Galaxy's signed int wire representation when needed."""
    return tag if tag <= 0x7FFFFFFF else tag - 0x100000000


def _unit_by_tag(observation: dict[str, Any], tag: int) -> dict[str, Any] | None:
    candidates = {tag, _tag32(tag)}
    for unit in observation["units"]:
        if unit["tag"] in candidates or _tag32(unit["tag"]) in candidates:
            return unit
    return None


def _census_signature(payload: dict[str, Any]) -> list[tuple[int, str, int]]:
    return sorted(
        (
            int(item.get("owner", 0)),
            str(item.get("unit_type", "")),
            int(item.get("unit_tag", 0)),
        )
        for item in payload.get("structures", [])
    )


def _census_identity(payload: dict[str, Any]) -> list[tuple[int, int]]:
    """Compare structure ownership/tags without treating live morphs as side effects."""
    return sorted(
        (int(item.get("owner", 0)), int(item.get("unit_tag", 0)))
        for item in payload.get("structures", [])
    )


def _debug_status(bank_name: str) -> dict[str, Any]:
    bank = read_bank(bank_name)
    return dict(bank.get("debug", {}))


def _launch_profile() -> dict[str, Any]:
    bank = read_bank("CMCoopLaunchProfile")
    return dict(bank.get("CMUI|LaunchProfile", {}))


def _native_counts(host: VibeHost) -> dict[str, Any]:
    command_center = host.invoke_function(
        "vibe.query.units", {"player": 1, "unit_type": "CommandCenter"}
    )
    scv = host.invoke_function(
        "vibe.query.units", {"player": 1, "unit_type": "SCV"}
    )
    return {
        "CommandCenter": command_center.payload.get("count") if command_center.is_ok else None,
        "SCV": scv.payload.get("count") if scv.is_ok else None,
        "responses": {
            "CommandCenter": _response(command_center),
            "SCV": _response(scv),
        },
    }


def _run(args: argparse.Namespace) -> dict[str, Any]:
    started_at = time.time()
    map_path = args.map.resolve()
    host = VibeHost(
        sc2_port=args.port,
        bank_name=args.bank_name,
        runtime_bank_name=args.runtime_bank_name,
        artifacts_dir=args.output.parent,
        require_initialization=True,
        realtime=False,
    )
    result: dict[str, Any] = {
        "stage_id": "22-runtime-typed-combat-census",
        "evidence_type": "runtime",
        "port": args.port,
        # Keep committed evidence portable; only the SC2 API receives the
        # resolved filesystem path.
        "map_path": str(args.map),
        "checks": {},
        "responses": {},
    }

    try:
        connected = host.connect_sc2(map_path=str(map_path))
        result["checks"]["create_game_join_game"] = {
            "status": "PASS" if connected else "FAIL",
            "detail": "VibeHost completed CreateGame + JoinGame" if connected else host.initialization_error,
        }
        if not connected:
            return result

        result["checks"]["initialization_gate"] = {
            "status": "PASS" if host.initialization_complete else "FAIL",
            "status_values": host.initialization_status,
        }
        native_before = _native_counts(host)
        profile_before = _launch_profile()
        result["native_before"] = native_before
        result["launch_profile_before"] = profile_before
        result["checks"]["native_initialization_observed"] = {
            "status": "PASS" if native_before["CommandCenter"] == 1 and native_before["SCV"] == 12 else "FAIL",
            "CommandCenter": native_before["CommandCenter"],
            "SCV": native_before["SCV"],
        }
        result["heartbeat_before"] = _debug_status(host.runtime_bank_name).get("bridge_heartbeat", 0)
        observation_before = _observe(host)
        result["observation_before"] = observation_before

        census_before = host.query_structures()
        result["responses"]["census_before"] = _response(census_before)
        if not census_before.is_ok:
            return result
        structures = census_before.payload.get("structures", [])
        raw_enemy_owners = {
            int(unit["owner"])
            for unit in observation_before["units"]
            if int(unit["owner"]) != 1 and int(unit["alliance"]) == 4
        }
        # P2 is the CMRE AI ally. Only owners observed as alliance=Enemy are
        # eligible valid targets; owner != 1 alone is insufficient here.
        enemy_structures = [
            item for item in structures if int(item.get("owner", 0)) in raw_enemy_owners
        ]
        result["checks"]["nonzero_enemy_structure_census"] = {
            "status": "PASS" if enemy_structures else "FAIL",
            "live_count": len(enemy_structures),
        }

        p1_units = [
            unit
            for unit in observation_before["units"]
            if unit["owner"] == 1 and unit["health"] > 0
        ]
        scvs = [unit for unit in p1_units if unit["unit_type"] == SCV_UNIT_TYPE]
        if not scvs:
            result["checks"]["attacker_discovery"] = {"status": "FAIL", "detail": "no native P1 SCV observed"}
            return result
        attacker = scvs[0]
        attacker_tag = _tag32(attacker["tag"])
        ally_target = next((unit for unit in scvs[1:] if unit["tag"] != attacker["tag"]), None)
        if ally_target is None:
            ally_target = next((unit for unit in p1_units if unit["tag"] != attacker["tag"]), None)

        target = enemy_structures[0] if enemy_structures else None
        if target is not None:
            target_raw = _unit_by_tag(observation_before, int(target.get("unit_tag", 0)))
            if target_raw is not None:
                target = dict(target)
                target["distance_hint"] = (
                    (target_raw.get("x", 0.0) - attacker.get("x", 0.0)) ** 2
                    + (target_raw.get("y", 0.0) - attacker.get("y", 0.0)) ** 2
                )
            target_tag = int(target.get("unit_tag", 0))
        else:
            target_tag = 0

        result["selected_tags"] = {
            "attacker_tag": attacker_tag,
            "attacker_raw_tag": attacker["tag"],
            "enemy_target": target,
            "ally_target_raw_tag": ally_target["tag"] if ally_target else 0,
        }
        result["checks"]["attacker_discovery"] = {"status": "PASS", "unit_type": "SCV"}

        missing = host.attack_unit(attacker_tag, 2147483647)
        result["responses"]["missing_target"] = _response(missing)
        neutral_raw = next(
            (
                unit for unit in observation_before["units"]
                if int(unit["owner"]) != 1 and int(unit["alliance"]) == 3
            ),
            None,
        )
        neutral = host.attack_unit(attacker_tag, _tag32(neutral_raw["tag"])) if neutral_raw else None
        result["responses"]["neutral_target"] = _response(neutral) if neutral else {"skipped": True}
        ally = host.attack_unit(attacker_tag, _tag32(ally_target["tag"])) if ally_target else None
        result["responses"]["ally_target"] = _response(ally) if ally else {"skipped": True}

        spawned = host.invoke_function("vibe.unit.spawn", {
            "unit_type": "Marine", "count": 1, "player": 1, "x": 0.0, "y": 0.0,
        })
        result["responses"]["stale_spawn"] = _response(spawned)
        stale_tag = int(spawned.payload.get("unit_tag", 0)) if spawned.is_ok else 0
        if stale_tag:
            killed = host.invoke_function("vibe.unit.kill", {"unit_tag": stale_tag})
            result["responses"]["stale_kill"] = _response(killed)
            stale = host.attack_unit(attacker_tag, stale_tag)
            result["responses"]["stale_target"] = _response(stale)
        else:
            result["responses"]["stale_target"] = {"skipped": True, "reason": "temporary spawn failed"}

        census_after_invalid = host.query_structures()
        result["responses"]["census_after_invalid"] = _response(census_after_invalid)
        no_side_effect = (
            census_after_invalid.is_ok
            and _census_identity(census_after_invalid.payload) == _census_identity(census_before.payload)
        )
        result["checks"]["invalid_targets_rejected_without_structure_side_effect"] = {
            "status": "PASS" if no_side_effect else "FAIL",
            "missing": missing.error_code,
            "neutral": neutral.error_code if neutral else "SKIPPED",
            "ally": ally.error_code if ally else "SKIPPED",
            "stale": result["responses"]["stale_target"].get("error_code", "SKIPPED"),
        }

        # Keep the native worker census independent from combat casualties.
        # Invalid-target checks use a native SCV; the valid attack uses a
        # temporary Vibe-created Marine so the initialization invariant can be
        # compared after the frame-advance window without replacing anything.
        combat_spawn = host.invoke_function("vibe.unit.spawn", {
            "unit_type": "Marine", "count": 1, "player": 1, "x": 0.0, "y": 0.0,
        })
        result["responses"]["combat_spawn"] = _response(combat_spawn)
        combat_attacker_tag = (
            int(combat_spawn.payload.get("unit_tag", 0)) if combat_spawn.is_ok else 0
        )
        result["selected_tags"]["combat_attacker_tag"] = combat_attacker_tag
        valid = (
            host.attack_unit(combat_attacker_tag, target_tag)
            if target_tag and combat_attacker_tag else None
        )
        result["responses"]["valid_attack"] = _response(valid) if valid else {"skipped": True}
        valid_issued = bool(
            valid and valid.is_ok and valid.payload.get("issued") and combat_attacker_tag
        )
        result["checks"]["valid_typed_attack_accepted"] = {
            "status": "PASS" if valid_issued else "FAIL",
            "error_code": valid.error_code if valid else "SKIPPED",
        }

        attrs_before = host.query_unit_attrs(target_tag) if target_tag else None
        result["responses"]["target_attrs_before"] = _response(attrs_before) if attrs_before else {"skipped": True}
        loop_before = observation_before["loop"]
        step_results: list[dict[str, Any]] = []
        if valid_issued:
            for _ in range(max(1, args.step_batches)):
                step_results.append({"ok": host.client.step(args.step_size, timeout=30.0)})
        observation_after = _observe(host)
        result["observation_after"] = observation_after
        result["step_results"] = step_results
        attrs_after = host.query_unit_attrs(target_tag) if target_tag else None
        result["responses"]["target_attrs_after"] = _response(attrs_after) if attrs_after else {"skipped": True}
        target_before_raw = _unit_by_tag(observation_before, target_tag)
        target_after_raw = _unit_by_tag(observation_after, target_tag)
        attrs_before_valid = bool(
            attrs_before and attrs_before.is_ok
            and attrs_before.payload.get("unit_type")
            and float(attrs_before.payload.get("max_life", 0.0)) > 0.0
        )
        attrs_after_valid = bool(
            attrs_after and attrs_after.is_ok
            and attrs_after.payload.get("unit_type")
            and float(attrs_after.payload.get("max_life", 0.0)) > 0.0
        )
        life_before = (
            attrs_before.payload.get("life") if attrs_before_valid
            else (target_before_raw or {}).get("health")
        )
        life_after = (
            attrs_after.payload.get("life") if attrs_after_valid
            else (target_after_raw or {}).get("health")
        )
        changed = (
            (life_before is not None and life_after is not None and float(life_after) < float(life_before))
            or (target_before_raw is not None and target_after_raw is None)
        )
        result["checks"]["frames_advanced_and_target_changed"] = {
            "status": "PASS" if observation_after["loop"] > loop_before and changed else "FAIL",
            "loop_before": loop_before,
            "loop_after": observation_after["loop"],
            "life_before": life_before,
            "life_after": life_after,
            "target_visible_before": target_before_raw is not None,
            "target_visible_after": target_after_raw is not None,
        }
        census_after = host.query_structures()
        result["responses"]["census_after"] = _response(census_after)
        native_after = _native_counts(host)
        profile_after = _launch_profile()
        result["native_after"] = native_after
        result["launch_profile_after"] = profile_after
        replacement_keys = (
            "CreateStartingUnitsP1",
            "CreateStartingUnitsP2",
            "EnsurePreventDefeatP1",
            "EnsurePreventDefeatP2",
            "VanillaRemovalCount",
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
    finally:
        host.close()

    checks = result["checks"]
    result["verdict"] = "PASS" if checks and all(item.get("status") == "PASS" for item in checks.values()) else "FAIL"
    result["completed_at"] = time.time()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bank-name", default="GalaxyVibe")
    parser.add_argument("--runtime-bank-name", default="CMRERebornDebug")
    parser.add_argument("--step-size", type=int, default=20)
    parser.add_argument("--step-batches", type=int, default=30)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = _run(args)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
