import json
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import asyncio

import server


def test_runtime_call_log_persists_runtime_function_arguments_results_and_errors(tmp_path):
    console = server.RuntimeConsole(tmp_path / "runtime-call-log.jsonl")
    console._session_id = "repl_test"
    console._port = 5896

    passed = console._record_runtime_call(
        "douququ.unit.spawn",
        {"unit_type": "Reaver", "owner": 1, "x": 20.0, "y": 20.0},
        {"kind": "result", "error_code": "OK", "payload": {"tag": 101}},
        origin="vm",
        duration_ms=12.5,
    )
    failed = console._record_runtime_call(
        "douququ.unit.set_life",
        {"unit_tag": 999, "life": 20.0},
        {"kind": "error", "error_code": "UNIT_NOT_FOUND", "payload": {}},
        origin="api",
        duration_ms=4.0,
    )

    payload = console.call_log()
    assert payload["schema_version"] == "douququ-runtime-call-log.v1"
    assert payload["count"] == 2
    assert payload["total_count"] == 2
    assert payload["records"] == [passed, failed]
    assert passed["timestamp"].endswith("Z")
    assert passed["session_id"] == "repl_test"
    assert passed["port"] == 5896
    assert passed["origin"] == "vm"
    assert passed["error"] is None
    assert failed["error"]["error_code"] == "UNIT_NOT_FOUND"
    assert json.loads((tmp_path / "runtime-call-log.jsonl").read_text(encoding="utf-8").splitlines()[0])["function_id"] == "douququ.unit.spawn"


def test_runtime_call_log_http_endpoint_is_read_only(tmp_path, monkeypatch):
    console = server.RuntimeConsole(tmp_path / "runtime-call-log.jsonl")
    console._record_runtime_call(
        "douququ.runtime.status",
        {},
        {"kind": "result", "error_code": "OK", "payload": {"active": True}},
        origin="connect",
    )
    monkeypatch.setattr(server, "_runtime_console", console)
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.CmreWebUIHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{httpd.server_port}/api/vibe/call-log?limit=1",
            timeout=5,
        ) as response:
            payload = json.loads(response.read())
        assert response.status == 200
        assert payload["count"] == 1
        assert payload["total_count"] == 1
        assert payload["records"][0]["function_id"] == "douququ.runtime.status"
        assert payload["records"][0]["origin"] == "connect"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_runtime_console_serializes_overlapping_vm_api_and_observe_calls(tmp_path, monkeypatch):
    console = server.RuntimeConsole(tmp_path / "runtime-call-log.jsonl")
    state = {"active": 0, "peak": 0, "operations": []}

    async def transact(name, result):
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        state["operations"].append(name)
        try:
            await asyncio.sleep(0.03)
            return result
        finally:
            state["active"] -= 1

    async def fake_invoke(function_id, args, origin="api"):
        return await transact(
            f"{origin}:{function_id}",
            {"function_id": function_id, "result": {"error_code": "OK"}},
        )

    async def fake_observe():
        return await transact("observe", {"error_code": "OK"})

    async def fake_vm(program):
        return await transact("vm", {"success": True, "status": "passed"})

    monkeypatch.setattr(console, "_invoke_unlocked", fake_invoke)
    monkeypatch.setattr(console, "_observe_unlocked", fake_observe)
    monkeypatch.setattr(console, "_run_vm_unlocked", fake_vm)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(console.invoke, "douququ.runtime.status", {}),
            pool.submit(console.observe),
            pool.submit(console.run_vm, {"version": "vibe-debug/1", "instructions": []}),
        ]
        results = [future.result(timeout=5) for future in futures]

    assert results[0]["result"]["error_code"] == "OK"
    assert results[1]["error_code"] == "OK"
    assert results[2]["status"] == "passed"
    assert state["peak"] == 1
    assert sorted(state["operations"]) == [
        "api:douququ.runtime.status",
        "observe",
        "vm",
    ]
    assert console.status()["running"] == ""


def test_runtime_vm_program_asserts_death_mine_spawn_tags_not_transient_visibility():
    program_path = Path(__file__).with_name("dou_ququ_runtime_full.json")
    steps = json.loads(program_path.read_text(encoding="utf-8"))["steps"]

    assert sum(
        step.get("op") == "assert"
        and step.get("source") == "$vars.vultureDeath"
        and step.get("path", "").startswith("spawned.")
        for step in steps
    ) == 3
    assert not any(step.get("source") == "$vars.mineSnapshot" for step in steps)
