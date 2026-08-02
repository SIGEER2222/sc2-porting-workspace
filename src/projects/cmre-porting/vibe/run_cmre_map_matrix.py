"""Run a bounded simulator tactical probe for every CMRE cooperative map.

This command is intentionally a matrix/probe, not a native mission emulator.
It proves that a map-derived coordinate model can drive the existing P2
economy, production, scouting, movement, and hostile-target filters.  The
map's mission objective contract is carried in the replay and summary, while
native SC2 mission completion remains a separate runtime task.

Examples::

    PYTHONPATH=src/projects/cmre-porting py -3.13 -m vibe.run_cmre_map_matrix
    PYTHONPATH=src/projects/cmre-porting py -3.13 -m vibe.run_cmre_map_matrix --map 亡者之夜 --max-loops 640
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from .cmre_map_catalog import (
    MAP_ROOT,
    build_cooperative_map_scenario,
    list_cmre_maps,
    write_map_inventory,
)
from .ladder_ai import LadderAI
from .replay_player import load_replay, render_player_html
from .consumers.ally_ai import run_ally_scenario


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "artifacts"
    / "projects"
    / "cmre-porting"
    / "stage25-ai-ally-capability-completion"
    / "cmre-map-matrix-20260802"
)


def _leader_entity_id(scenario: dict, player_id: int = 1) -> int:
    for index, spawn in enumerate(scenario.get("spawns", []), start=1):
        if int(spawn.get("owner_player_id", -1)) == player_id:
            return index
    return 0


def run_map_probe(
    map_dir: str | Path,
    *,
    seed: int = 42,
    max_loops: int = 320,
    output_dir: Optional[str | Path] = None,
    max_enemy_per_player: int = 16,
) -> dict:
    data, profile, geometry = build_cooperative_map_scenario(
        map_dir,
        seed=seed,
        max_enemy_per_player=max_enemy_per_player,
    )
    scenario = data.scenario
    map_name = str(scenario.get("map_name") or scenario["name"])
    root = Path(output_dir).resolve() if output_dir is not None else None
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
        replay_path = root / "replay.jsonl"
        html_path = root / "state-driven-player.html"
        source_path = root / "map-scenario-source.json"
    else:
        replay_path = html_path = source_path = None

    policy = LadderAI(
        player_id=2,
        leader_entity_id=_leader_entity_id(scenario),
        leader_player_id=1,
        command_interval=4,
        max_workers=16,
        army_threshold=6,
        base_position=geometry.base_position,
        expansion_position=geometry.expansion_position,
        attack_points=geometry.attack_points,
        scout_route=geometry.scout_route,
        base_radius=14.0,
        allow_expansion=False,
        build_offsets=geometry.build_offsets,
    )
    result = run_ally_scenario(
        scenario,
        policy,
        ally_player_id=2,
        leader_player_id=1,
        max_loops=max(1, int(max_loops)),
        safety_window=max(80, min(320, int(max_loops))),
        deadlock_threshold=100,
        storm_threshold=40,
        latency_loops=1,
        require_cooperative_roster=True,
        replay_log_path=replay_path,
        replay_log_interval=8,
    )
    frame_count = 0
    if replay_path is not None and html_path is not None:
        records = load_replay(replay_path)
        frame_count = sum(1 for record in records if record.get("record_type") == "frame")
        render_player_html(records, replay_path, html_path)
    if source_path is not None:
        source_path.write_text(
            json.dumps(
                {
                    "map_metadata": scenario["_map_metadata"],
                    "scenario": scenario,
                    "regions": data.regions,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    action_counts = dict(result.action_kind_counts)
    checks = {
        "map_extracted": scenario["_map_metadata"]["native_object_count"] > 0,
        "objective_profile_present": bool(profile.objectives),
        "geometry_is_map_derived": bool(geometry.evidence),
        "cooperative_roster": result.roster_ready,
        "p2_dispatched_actions": result.total_dispatched > 0,
        "movement_or_attack": action_counts.get("move", 0) + action_counts.get("attack", 0) > 0,
        "economy_or_production": action_counts.get("gather", 0) + action_counts.get("train", 0) + action_counts.get("build", 0) > 0,
        "no_hidden_state": result.hidden_state_access_violations == 0,
        "no_friendly_fire": result.friendly_fire_rejections == 0,
        "no_dispatch_errors": result.total_dispatch_errors == 0,
        "no_deadlock": not result.deadlock_detected,
        "no_command_storm": not result.command_storm_detected,
    }
    summary = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "probe_status": "TACTICAL_PASS" if all(checks.values()) else "TACTICAL_FAIL",
        "evidence_type": "simulator",
        "runtime_claim": "none; native SC2 mission completion not exercised",
        "map_name": map_name,
        "map_path": scenario["_map_metadata"]["map_path"],
        "map_hash": scenario["_map_metadata"]["map_hash"],
        "profile": {"archetype": profile.archetype, "features": list(profile.features), "objectives": [asdict(item) for item in profile.objectives]},
        "geometry": asdict(geometry),
        "seed": int(seed),
        "end_loop": result.end_loop,
        "end_reason": result.end_reason,
        "victory": result.end_reason == "enemy_elimination",
        "checks": checks,
        "action_kind_counts": action_counts,
        "action_reason_counts": policy.action_reason_counts,
        "phase_history": policy.phase_history,
        "error_breakdown": result.error_breakdown,
        "friendly_fire_rejections": result.friendly_fire_rejections,
        "native_object_count": scenario["_map_metadata"]["native_object_count"],
        "native_spawn_count": scenario["_map_metadata"]["native_spawn_count"],
        "simulator_spawn_count": len(scenario["spawns"]),
        "replay_path": str(replay_path.relative_to(REPO_ROOT).as_posix()) if replay_path is not None else "",
        "replay_html_path": str(html_path.relative_to(REPO_ROOT).as_posix()) if html_path is not None else "",
        "replay_frame_count": frame_count,
    }
    if root is not None:
        (root / "run-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return summary


def run_matrix(
    *,
    maps_root: Optional[str | Path] = None,
    map_name: Optional[str] = None,
    seed: int = 42,
    max_loops: int = 320,
    output_dir: str | Path = DEFAULT_OUTPUT,
    max_enemy_per_player: int = 16,
) -> dict:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    inventory = write_map_inventory(root / "map-inventory.json", maps_root)
    paths = list_cmre_maps(maps_root)
    if map_name:
        paths = [path for path in paths if path.stem == map_name or path.name == map_name or path.stem.startswith(map_name)]
    runs = []
    for path in paths:
        map_output = root / path.stem
        try:
            runs.append(run_map_probe(path, seed=seed, max_loops=max_loops, output_dir=map_output, max_enemy_per_player=max_enemy_per_player))
        except Exception as exc:  # keep the matrix truthful and continue other maps
            runs.append({
                "status": "ERROR",
                "probe_status": "TACTICAL_ERROR",
                "evidence_type": "simulator",
                "runtime_claim": "none",
                "map_name": path.stem,
                "map_path": path.as_posix(),
                "error": f"{type(exc).__name__}: {exc}",
            })
    payload = {
        "schema_version": "cmre-map-matrix.v1",
        "status": "PASS" if runs and all(run.get("status") == "PASS" for run in runs) else "FAIL",
        "evidence_type": "simulator",
        "runtime_claim": "none; this matrix is simulator-only",
        "map_count": len(runs),
        "inventory_map_count": inventory["map_count"],
        "seed": int(seed),
        "max_loops": int(max_loops),
        "runs": runs,
    }
    (root / "matrix-summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run map-derived CMRE tactical probes")
    parser.add_argument("--map", dest="map_name", default=None, help="只运行一张图的中文名")
    parser.add_argument("--maps-root", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-loops", type=int, default=320)
    parser.add_argument("--max-enemy-per-player", type=int, default=16)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    payload = run_matrix(
        maps_root=args.maps_root,
        map_name=args.map_name,
        seed=args.seed,
        max_loops=args.max_loops,
        output_dir=args.output_dir,
        max_enemy_per_player=max(1, args.max_enemy_per_player),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
