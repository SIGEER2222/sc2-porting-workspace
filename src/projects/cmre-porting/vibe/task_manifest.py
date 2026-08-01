"""Vibe task manifest generator.

This module turns project-side static map extraction into one manifest that can
feed the local simulator lane and the live Galaxy Vibe runtime lane.

Evidence boundary:
- generated scenario/tasks/manifest are static artifacts;
- optional simulator smoke evidence is simulator evidence;
- live tasks and .vtest files are executable runtime contracts, not runtime
  evidence until launched through the approved launcher + ScriptError gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = REPO_ROOT / "src" / "projects" / "cmre-porting"
DEFAULT_MAP_DIR = PROJECT_ROOT / "packages" / "Maps" / "亡者之夜.SC2Map"
DEFAULT_OUT_DIR = REPO_ROOT / "artifacts" / "projects" / "cmre-porting" / "stage12-vibe-task-manifest"


def _ensure_project_imports() -> None:
    project_path = str(PROJECT_ROOT)
    if project_path not in sys.path:
        sys.path.insert(0, project_path)


_ensure_project_imports()

try:
    from .map_extractor import MapData, extract_dead_of_night
    from .sc2_calibration import TaskContract
except ImportError:  # direct script execution
    from vibe.map_extractor import MapData, extract_dead_of_night  # type: ignore
    from vibe.sc2_calibration import TaskContract  # type: ignore


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rel(path: str | Path) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def stable_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(data: Any) -> str:
    return hashlib.sha256(stable_json(data).encode("utf-8")).hexdigest()


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Counter):
        return dict(value)
    if is_dataclass(value):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    return value


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_runtime_recipe(manifest_id: str) -> dict[str, Any]:
    """Build a live-runtime smoke recipe consumed by assertion_runner-style tools.

    This deliberately bootstraps a tiny deterministic fixture instead of claiming
    that simulator-injected starting units already exist in the real map.
    """

    return {
        "recipe_id": f"{manifest_id}-runtime-smoke",
        "schemaVersion": 1,
        "description": "Runtime smoke fixture for Galaxy Vibe launcher/SC2API lane; not runtime evidence until launched.",
        "evidence_type": "runtime-pending",
        "requires_launcher": True,
        "script_error_check_required": True,
        "steps": [
            {"action": "reset", "request_id": "manifest-reset"},
            {"action": "spawn", "unit_type": "Marine", "count": 1, "player": 1, "request_id": "manifest-spawn-marine"},
            {
                "action": "assert",
                "kind": "count",
                "unit_type": "Marine",
                "player": 1,
                "expected": 1,
                "request_id": "manifest-spawn-marine",
                "id": "manifest-assert-marine-count",
                "expected_verdict": "passed",
            },
            {
                "action": "assert",
                "kind": "exists",
                "unit_type": "Marine",
                "player": 1,
                "request_id": "manifest-spawn-marine",
                "id": "manifest-assert-marine-exists",
                "expected_verdict": "passed",
            },
            {"action": "kill", "unit_type": "Marine", "player": 1, "all": True, "request_id": "manifest-cleanup-marine"},
        ],
    }


def build_vtest(manifest_id: str, recipe_path: str) -> str:
    return "\n".join(
        [
            f"# {manifest_id}.vtest — generated runtime smoke contract",
            "# Evidence boundary: executable live contract only; runtime evidence requires launch-galaxy-vibe.ps1 + ScriptError check.",
            f"# Source recipe: {recipe_path}",
            "",
            "ping",
            "spawn marine 1 1",
            "assert count marine == 1 --player 1",
            "assert exists marine --player 1",
            "kill marine --player 1",
            "",
        ]
    )


def build_task_contracts(
    *,
    manifest_id: str,
    scenario_rel_path: str,
    scenario: dict[str, Any],
    catalog: str,
    seed: int,
    simulator_loops: int,
    live_loops: int,
) -> dict[str, dict[str, Any]]:
    # Keep the smoke task cheap and deterministic. It proves the generated
    # scenario can be loaded and stepped without asserting full mission outcomes.
    smoke_assertions = [
        {
            "op": "assert.count",
            "args": {"owner_player_id": 1, "unit_type_id": "CommandCenter", "expected": 1},
        },
        {
            "op": "assert.count",
            "args": {"owner_player_id": 1, "unit_type_id": "Marine", "expected": 8},
        },
    ]
    simulator = TaskContract(
        task_id=f"{manifest_id}-simulator-smoke",
        backend="simulator",
        scenario_dict=None,
        scenario_path=scenario_rel_path,
        catalog=catalog,
        patches=[],
        ops=[{"op": "scenario.step", "args": {"loops": simulator_loops, "n": simulator_loops}}],
        assertions=smoke_assertions,
        max_loops=simulator_loops,
        seed=seed,
    ).to_dict()
    sc2_stub = TaskContract(
        task_id=f"{manifest_id}-sc2-stub-smoke",
        backend="sc2-stub",
        scenario_dict=None,
        scenario_path=scenario_rel_path,
        catalog=catalog,
        patches=[],
        ops=[{"op": "scenario.step", "args": {"loops": simulator_loops, "n": simulator_loops}}],
        assertions=smoke_assertions,
        max_loops=simulator_loops,
        seed=seed,
    ).to_dict()
    live = TaskContract(
        task_id=f"{manifest_id}-live-contract",
        backend="sc2",
        scenario_dict=None,
        scenario_path=scenario_rel_path,
        catalog=catalog,
        patches=[],
        ops=[{"op": "scenario.run", "args": {"max_loops": live_loops}}],
        assertions=[],
        max_loops=live_loops,
        seed=seed,
    ).to_dict()
    live["requires_launcher"] = True
    live["script_error_check_required"] = True
    live["runtime_status"] = "not_run"
    live["evidence_type"] = "runtime-pending"
    live["launcher"] = "tools/galaxy-vibe/launch-galaxy-vibe.ps1"
    live["notes"] = "Do not treat this as runtime evidence until launched through the approved launcher and checked for new ScriptError logs."

    # Include a tiny source summary so task consumers can reason without opening
    # the full manifest.
    for task in (simulator, sc2_stub, live):
        task["schemaVersion"] = 1
        task["source_manifest_id"] = manifest_id
        task["scenario_name"] = scenario.get("name")
    return {"simulator": simulator, "sc2_stub": sc2_stub, "live": live}


def build_manifest(
    *,
    data: MapData,
    map_dir: Path,
    out_dir: Path,
    manifest_id: str,
    catalog: str,
    seed: int,
    simulator_loops: int,
    live_loops: int,
) -> dict[str, Any]:
    scenario = dict(data.scenario)
    scenario["seed"] = seed
    scenario["max_loops"] = live_loops
    scenario["manifest_id"] = manifest_id

    scenario_path = out_dir / "scenario.json"
    regions_path = out_dir / "regions.json"
    runtime_recipe_path = out_dir / "runtime-recipe.json"
    vtest_path = out_dir / "scenario.vtest"
    simulator_task_path = out_dir / "task.simulator.json"
    sc2_stub_task_path = out_dir / "task.sc2-stub.json"
    live_task_path = out_dir / "task.live.json"
    summary_path = out_dir / "summary.json"
    manifest_path = out_dir / "manifest.json"

    scenario_rel = rel(scenario_path)
    tasks = build_task_contracts(
        manifest_id=manifest_id,
        scenario_rel_path=scenario_rel,
        scenario=scenario,
        catalog=catalog,
        seed=seed,
        simulator_loops=simulator_loops,
        live_loops=live_loops,
    )
    runtime_recipe = build_runtime_recipe(manifest_id)

    stats = to_jsonable(data.stats)
    unit_counts = stats.get("unit_type_counter", {})
    player_counts = stats.get("player_counter", {})
    output_paths = {
        "manifest": rel(manifest_path),
        "scenario": scenario_rel,
        "regions": rel(regions_path),
        "summary": rel(summary_path),
        "tasks": {
            "simulator": rel(simulator_task_path),
            "sc2_stub": rel(sc2_stub_task_path),
            "live": rel(live_task_path),
        },
        "runtime": {
            "recipe": rel(runtime_recipe_path),
            "vtest": rel(vtest_path),
        },
    }

    manifest = {
        "schemaVersion": 1,
        "manifest_id": manifest_id,
        "generated_at": utcnow(),
        "evidence_type": "static",
        "purpose": "Unified SC2 Vibe task manifest for simulator smoke, SC2 stub parity, and live runtime contract generation.",
        "source": {
            "kind": "map_extractor",
            "map_path": rel(map_dir),
            "map_name": scenario.get("name"),
            "evidence_type": "static",
        },
        "scenario": {
            "path": scenario_rel,
            "hash_sha256": sha256_json(scenario),
            "catalog": catalog,
            "seed": seed,
            "max_loops": live_loops,
            "strict": scenario.get("strict", False),
            "players": len(scenario.get("players", [])),
            "spawns": len(scenario.get("spawns", [])),
            "commands": len(scenario.get("commands", [])),
            "win_condition": scenario.get("win_condition"),
        },
        "tasks": {
            "simulator": {
                "path": rel(simulator_task_path),
                "backend": "simulator",
                "evidence_type": "simulator-pending",
                "max_loops": simulator_loops,
                "purpose": "cheap deterministic load/step/assert smoke",
            },
            "sc2_stub": {
                "path": rel(sc2_stub_task_path),
                "backend": "sc2-stub",
                "evidence_type": "inference-pending",
                "purpose": "same TaskContract shape as live backend without claiming runtime evidence",
            },
            "live": {
                "path": rel(live_task_path),
                "backend": "sc2",
                "evidence_type": "runtime-pending",
                "requires_launcher": True,
                "script_error_check_required": True,
                "purpose": "live runtime contract for approved launcher execution",
            },
        },
        "runtime": {
            "recipe_path": rel(runtime_recipe_path),
            "vtest_path": rel(vtest_path),
            "requires_launcher": True,
            "launcher": "tools/galaxy-vibe/launch-galaxy-vibe.ps1",
            "script_error_check_required": True,
            "status": "not_run",
        },
        "extraction": {
            "stats": stats,
            "regions_count": len(data.regions),
            "map_bounds": to_jsonable(data.map_bounds),
            "wave_timing": to_jsonable(data.wave_timing),
            "top_units": sorted(unit_counts.items(), key=lambda kv: kv[1], reverse=True)[:20],
            "player_counts": player_counts,
        },
        "outputs": output_paths,
        "next_runtime_command": (
            "powershell -File tools/galaxy-vibe/launch-galaxy-vibe.ps1 "
            f"-Verify {rel(vtest_path)}"
        ),
    }

    summary = {
        "schemaVersion": 1,
        "manifest_id": manifest_id,
        "status": "generated",
        "evidence_type": "static",
        "scenario_hash_sha256": manifest["scenario"]["hash_sha256"],
        "outputs": output_paths,
        "counts": {
            "players": manifest["scenario"]["players"],
            "spawns": manifest["scenario"]["spawns"],
            "regions": len(data.regions),
            "mapped_units": stats.get("units_mapped", 0),
            "unsupported_units": stats.get("units_unsupported", 0),
        },
        "warnings": [
            "live task and .vtest are runtime-pending until approved launcher execution and ScriptError validation",
        ],
    }

    write_json(scenario_path, scenario)
    write_json(regions_path, data.regions)
    write_json(runtime_recipe_path, runtime_recipe)
    write_text(vtest_path, build_vtest(manifest_id, rel(runtime_recipe_path)))
    write_json(simulator_task_path, tasks["simulator"])
    write_json(sc2_stub_task_path, tasks["sc2_stub"])
    write_json(live_task_path, tasks["live"])
    write_json(summary_path, summary)
    write_json(manifest_path, manifest)
    return manifest


def generate_manifest(
    *,
    map_dir: Path = DEFAULT_MAP_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
    manifest_id: str = "dead-of-night-vibe",
    catalog: str = "m7",
    seed: int = 42,
    simulator_loops: int = 1,
    live_loops: int = 30000,
    run_simulator_smoke: bool = False,
) -> dict[str, Any]:
    data = extract_dead_of_night(map_dir)
    manifest = build_manifest(
        data=data,
        map_dir=map_dir,
        out_dir=out_dir,
        manifest_id=manifest_id,
        catalog=catalog,
        seed=seed,
        simulator_loops=simulator_loops,
        live_loops=live_loops,
    )
    if run_simulator_smoke:
        sim_task = json.loads((REPO_ROOT / manifest["tasks"]["simulator"]["path"]).read_text(encoding="utf-8"))
        result = run_simulator_smoke_task(sim_task)
        smoke_path = out_dir / "simulator-smoke-result.json"
        write_json(smoke_path, result)
        manifest["tasks"]["simulator"]["evidence_type"] = "simulator"
        manifest["tasks"]["simulator"]["smoke_result_path"] = rel(smoke_path)
        manifest["tasks"]["simulator"]["smoke_verdict"] = result.get("verdict")
        manifest["verification"] = {
            "simulator_smoke": {
                "command": f"python {rel(Path(__file__))} --run-simulator-smoke",
                "result": result.get("verdict"),
                "evidence_type": "simulator",
                "artifact": rel(smoke_path),
            }
        }
        write_json(out_dir / "manifest.json", manifest)
        summary_path = out_dir / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["status"] = "generated-and-smoke-tested"
        summary["simulator_smoke"] = {
            "verdict": result.get("verdict"),
            "artifact": rel(smoke_path),
            "evidence_type": "simulator",
        }
        write_json(summary_path, summary)
    return manifest


def run_simulator_smoke_task(task: dict[str, Any]) -> dict[str, Any]:
    """Run a compact local simulator smoke without writing full snapshots.

    The older task_runner evidence bundle is useful for small scenarios, but this
    extracted map has 1k+ spawns and produces a very large final_snapshot.json.
    Stage 12 only needs proof that the manifest scenario can load, step, and
    satisfy its declared smoke assertions, so this keeps evidence compact.
    """

    try:
        from .contracts import SnapshotHandle, TraceHandle
        from .sc2_calibration import _apply_op, _run_assertion
        from .simulator_session import SimulatorSession
    except ImportError:
        from vibe.contracts import SnapshotHandle, TraceHandle  # type: ignore
        from vibe.sc2_calibration import _apply_op, _run_assertion  # type: ignore
        from vibe.simulator_session import SimulatorSession  # type: ignore

    scenario_dict = task.get("scenario_dict")
    if scenario_dict is None:
        scenario_path = task.get("scenario_path")
        if not scenario_path:
            raise ValueError("simulator smoke task requires scenario_dict or scenario_path")
        scenario_dict = json.loads((REPO_ROOT / scenario_path).read_text(encoding="utf-8"))
    if task.get("seed") is not None:
        scenario_dict = dict(scenario_dict)
        scenario_dict["seed"] = task["seed"]

    session = SimulatorSession()
    load_info = session.scenario_load(scenario_dict=scenario_dict, catalog=task.get("catalog", "m7"))
    reset_info = session.scenario_reset()

    op_results = []
    for op_spec in task.get("ops", []):
        op = op_spec["op"]
        args = op_spec.get("args", {})
        try:
            before = session.world.clock.now.loop if session.world is not None else 0
            _apply_op(session, op, args)
            after = session.world.clock.now.loop if session.world is not None else before
            op_results.append({"op": op, "args": args, "ok": True, "loop_before": before, "loop_after": after})
        except Exception as exc:  # noqa: BLE001 - evidence should record unexpected smoke failure
            op_results.append({"op": op, "args": args, "ok": False, "error": str(exc)})

    assertion_results = []
    for assertion in task.get("assertions", []):
        op = assertion["op"]
        args = assertion.get("args", {})
        result = _run_assertion(session, op, args)
        assertion_results.append({"op": op, "args": args, **result})

    final_snapshot_hash = SnapshotHandle.from_world(session.world).hash if session.world is not None else ""
    trace_hash = TraceHandle.from_world(session.world).hash if session.world is not None else ""
    all_ops_ok = all(r.get("ok") for r in op_results)
    all_assertions_ok = all(a.get("ok") for a in assertion_results) if assertion_results else True
    return {
        "task_id": task.get("task_id"),
        "backend": "simulator",
        "executed_at": utcnow(),
        "scenario_name": load_info.get("scenario_name"),
        "catalog_hash": load_info.get("catalog_hash"),
        "initial_entity_count": reset_info.get("entity_count"),
        "final_loop": session.world.clock.now.loop if session.world is not None else 0,
        "ops_total": len(op_results),
        "ops_failed": sum(1 for r in op_results if not r.get("ok")),
        "op_results": op_results,
        "assertions_total": len(assertion_results),
        "assertions_passed": sum(1 for a in assertion_results if a.get("ok")),
        "all_assertions_passed": all_assertions_ok,
        "assertion_results": assertion_results,
        "trace_hash": trace_hash,
        "final_snapshot_hash": final_snapshot_hash,
        "evidence_class": "simulator",
        "verdict": "PASS" if all_ops_ok and all_assertions_ok else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate unified SC2 Vibe task manifest artifacts")
    parser.add_argument("--map-dir", default=str(DEFAULT_MAP_DIR), help="Unpacked .SC2Map directory")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output artifact directory")
    parser.add_argument("--manifest-id", default="dead-of-night-vibe")
    parser.add_argument("--catalog", default="m7")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--simulator-loops", type=int, default=1)
    parser.add_argument("--live-loops", type=int, default=30000)
    parser.add_argument("--run-simulator-smoke", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print full manifest JSON")
    args = parser.parse_args(argv)

    manifest = generate_manifest(
        map_dir=Path(args.map_dir),
        out_dir=Path(args.out_dir),
        manifest_id=args.manifest_id,
        catalog=args.catalog,
        seed=args.seed,
        simulator_loops=args.simulator_loops,
        live_loops=args.live_loops,
        run_simulator_smoke=args.run_simulator_smoke,
    )
    if args.json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    else:
        print(
            "manifest generated: "
            f"{manifest['outputs']['manifest']} "
            f"spawns={manifest['scenario']['spawns']} "
            f"regions={manifest['extraction']['regions_count']}"
        )
        sim = manifest["tasks"]["simulator"]
        if sim.get("smoke_verdict"):
            print(f"simulator smoke: {sim['smoke_verdict']} ({sim.get('smoke_result_path')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
