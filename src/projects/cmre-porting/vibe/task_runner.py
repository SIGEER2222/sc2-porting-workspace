"""task.json 加载 + 端到端执行 + 证据包生成。

task.json schema（P1 最小）：
{
  "task_id": "...",
  "backend": "simulator",
  "scenario_path": "..." | "scenario_dict": {...},
  "catalog": "m7" | "m2" | "m3" | null,
  "ops": [ {"op": "scenario.reset"}, {"op": "scenario.run"}, ... ],
  "assertions": [ {"op": "assert.count", "args": {...}}, ... ]
}

证据包输出到 artifacts/galaxy-vibe/<task_id>/：
  task.json, catalog.snapshot.json, capabilities.json,
  initial_snapshot.json, final_snapshot.json, events.jsonl,
  assertions.json, result.json
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import protocol
from .simulator_transport import SimulatorTransport

REPO_ROOT = Path(__file__).resolve().parents[4]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "galaxy-vibe"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_task(task_path: str) -> dict:
    """执行一个 task.json，产出证据包，返回 result dict。"""
    task_file = Path(task_path)
    if not task_file.is_absolute():
        task_file = REPO_ROOT / task_file
    task = json.loads(task_file.read_text(encoding="utf-8"))
    task_id = task.get("task_id", task_file.stem)
    out_dir = ARTIFACT_ROOT / task_id
    out_dir.mkdir(parents=True, exist_ok=True)

    sid = f"task-{task_id}"
    transport = SimulatorTransport()
    transport.open_session(sid)
    session = transport.session
    assert session is not None

    # 1) 加载场景 + catalog
    load_args = {}
    if task.get("scenario_path"):
        load_args["scenario_path"] = task["scenario_path"]
    elif task.get("scenario_dict"):
        load_args["scenario_dict"] = task["scenario_dict"]
    if task.get("catalog"):
        load_args["catalog"] = task["catalog"]
    seq = 0
    seq += 1
    load_resp = transport.send(protocol.make_request(sid, "load", seq, "scenario.load", load_args))
    if load_resp.error_code != 0:
        raise RuntimeError(f"scenario.load failed: {load_resp.payload}")

    # 2) reset
    seq += 1
    transport.send(protocol.make_request(sid, "reset", seq, "scenario.reset"))
    initial_snap = session._initial_snapshot  # noqa: SLF001

    # 3) 执行 ops（如 scenario.run / step / unit.* 等）
    op_results = []
    for i, op_spec in enumerate(task.get("ops", [])):
        seq += 1
        op = op_spec["op"]
        args = op_spec.get("args", {})
        r = transport.send(protocol.make_request(sid, f"op-{i}", seq, op, args))
        op_results.append({"op": op, "args": args, "error_code": r.error_code,
                           "payload": r.payload, "state_version": r.state_version})

    # 4) assertions
    assertion_results = []
    for i, a_spec in enumerate(task.get("assertions", [])):
        seq += 1
        op = a_spec["op"]
        args = a_spec.get("args", {})
        r = transport.send(protocol.make_request(sid, f"assert-{i}", seq, op, args))
        assertion_results.append({"op": op, "args": args, **r.payload})

    # 5) 产出证据包
    final_snap = None
    trace_h = ""
    if session.world is not None:
        from .contracts import SnapshotHandle, TraceHandle
        final_snap = SnapshotHandle.from_world(session.world)
        trace_h = TraceHandle.from_world(session.world).hash

    # 写 task.json
    (out_dir / "task.json").write_text(json.dumps(task, indent=2, ensure_ascii=False), encoding="utf-8")
    # catalog.snapshot.json
    if session.catalog:
        (out_dir / "catalog.snapshot.json").write_text(
            json.dumps({"schema_version": session.catalog.schema_version,
                        "content_hash": session.catalog.content_hash,
                        "source": session.catalog.source,
                        "unit_count": len(session.catalog.snapshot.units)}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    # capabilities.json
    if session.catalog:
        from .contracts import CapabilityReport
        cap = CapabilityReport.from_catalog(session.catalog)
        (out_dir / "capabilities.json").write_text(
            json.dumps({"catalog_hash": cap.catalog_hash, "schema_version": cap.schema_version,
                        "fidelity_summary": _fidelity_summary(session.catalog),
                        "fidelity": cap.fidelity}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    # initial/final snapshot
    if initial_snap:
        (out_dir / "initial_snapshot.json").write_text(
            json.dumps({"hash": initial_snap.hash, "loop": initial_snap.loop}, indent=2, ensure_ascii=False),
            encoding="utf-8")
    if final_snap:
        (out_dir / "final_snapshot.json").write_text(
            json.dumps(final_snap.data, indent=2, ensure_ascii=False), encoding="utf-8")
    # events.jsonl
    if session.world is not None:
        from sc2_simulator.reporting.trace import write_trace
        th = write_trace(session.world, out_dir / "events.jsonl")
        trace_h = th
    # assertions.json
    (out_dir / "assertions.json").write_text(
        json.dumps(assertion_results, indent=2, ensure_ascii=False), encoding="utf-8")
    # result.json
    all_asserts_ok = all(a.get("ok") for a in assertion_results) if assertion_results else True
    result = {
        "task_id": task_id,
        "backend": "simulator",
        "executed_at": utcnow(),
        "ops_total": len(op_results),
        "ops_failed": sum(1 for r in op_results if r["error_code"] != 0),
        "assertions_total": len(assertion_results),
        "assertions_passed": sum(1 for a in assertion_results if a.get("ok")),
        "all_assertions_passed": all_asserts_ok,
        "trace_hash": trace_h,
        "evidence_class": "simulator",
        "evidence_dir": str(out_dir.relative_to(REPO_ROOT)).replace("\\", "/"),
        "verdict": "PASS" if all_asserts_ok else "FAIL",
    }
    (out_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def _fidelity_summary(cat) -> dict:
    from collections import Counter
    return dict(Counter(cat.fidelity.values()))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m src.projects.cmre-porting.vibe.task_runner <task.json>", file=sys.stderr)
        sys.exit(2)
    r = run_task(sys.argv[1])
    print(json.dumps(r, indent=2, ensure_ascii=False))
    sys.exit(0 if r["verdict"] == "PASS" else 1)
