import json
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import xml.etree.ElementTree as ET

import asyncio

import server
from runtime_script import RuntimeScriptError, compile_runtime_rules, compile_runtime_script


def _write_event_bank(path: Path, session: str, events: list[dict]) -> None:
    root = ET.Element("Bank", version="1")
    index = ET.SubElement(root, "Section", name="index")
    key = ET.SubElement(index, "Key", name="event_session")
    ET.SubElement(key, "Value", string=session)
    events_section = ET.SubElement(root, "Section", name="events")
    for event in events:
        event_key = ET.SubElement(
            events_section,
            "Key",
            name=str(event["eventId"]),
        )
        ET.SubElement(
            event_key,
            "Value",
            string=json.dumps(event, separators=(",", ":")),
        )
    path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))


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


def test_event_bank_parser_reads_session_and_wrapped_events(tmp_path):
    bank = tmp_path / "GalaxyVibeEvents.SC2Bank"
    event = {
        "schemaVersion": 1,
        "eventId": 7,
        "eventSession": "session-a",
        "eventType": "unit_attacked",
        "payload": {"attackerType": "Reaver", "attackerTag": 11, "targetTag": 22},
    }
    _write_event_bank(bank, "session-a", [event])

    parsed = server.parse_runtime_event_bank(bank)

    assert parsed["event_session"] == "session-a"
    assert parsed["last_event_id"] == 7
    assert parsed["events"] == [event]


def test_event_dispatch_builds_typed_auto_vm_arguments_and_correlation():
    event = {
        "eventId": 3,
        "eventSession": "session-a",
        "eventType": "unit_died",
        "payload": {
            "killerTag": 101,
            "killerType": "Hydralisk",
            "victimTag": 202,
            "victimType": "Marine",
            "victimOwner": 2,
            "victimX": 40.5,
            "victimY": 41.5,
        },
    }

    function_id, args = server.RuntimeConsole._event_dispatch(
        event,
        "auto-vm:repl_test:session-a:3",
    )

    assert function_id == "douququ.auto.death"
    assert args == {
        "correlation_id": "auto-vm:repl_test:session-a:3",
        "killer_tag": 101,
        "victim_owner": 2,
        "victim_tag": 202,
        "victim_type": "Marine",
        "victim_x": 40.5,
        "victim_y": 41.5,
    }


def test_event_pump_consumes_current_session_once_and_records_auto_vm_origin(tmp_path):
    bank = tmp_path / "GalaxyVibeEvents.SC2Bank"
    first = {
        "schemaVersion": 1,
        "eventId": 1,
        "eventSession": "session-a",
        "eventType": "unit_attacked",
        "payload": {
            "attackerType": "Reaver",
            "attackerTag": 11,
            "targetTag": 22,
        },
    }
    ignored = {
        "schemaVersion": 1,
        "eventId": 2,
        "eventSession": "session-a",
        "eventType": "unit_attacked",
        "payload": {
            "attackerType": "Marine",
            "attackerTag": 12,
            "targetTag": 23,
        },
    }
    _write_event_bank(bank, "session-a", [first, ignored])
    console = server.RuntimeConsole(
        tmp_path / "calls.jsonl",
        tmp_path / "events.jsonl",
        tmp_path,
    )
    console._session_id = "repl_test"
    console._status = "connected"
    seen = []

    async def fake_run_vm(program, *, origin="vm"):
        seen.append((origin, program["steps"][0]["fn"], program["steps"][0]["args"]))
        return {"status": "passed", "trace": []}

    console._run_vm_unlocked = fake_run_vm

    async def exercise():
        first_batch = await console._poll_events_unlocked()
        second_batch = await console._poll_events_unlocked()
        return first_batch, second_batch

    first_batch, second_batch = asyncio.run(exercise())

    assert [item["status"] for item in first_batch] == ["passed", "ignored"]
    assert second_batch == []
    assert seen[0][0] == "auto-vm"
    assert seen[0][1] == "douququ.auto.attack"
    assert seen[0][2]["correlation_id"] == "auto-vm:repl_test:session-a:1"
    logged = console.event_log()["records"]
    assert logged[0]["event_session"] == "session-a"
    assert logged[0]["dispatch_function_id"] == "douququ.auto.attack"
    assert logged[1]["dispatch_function_id"] == ""


def test_event_session_change_resets_cursor_without_replaying_old_session(tmp_path):
    bank = tmp_path / "GalaxyVibeEvents.SC2Bank"
    event = {
        "schemaVersion": 1,
        "eventId": 1,
        "eventSession": "session-a",
        "eventType": "periodic",
        "payload": {"seconds": 1.0},
    }
    _write_event_bank(bank, "session-a", [event])
    console = server.RuntimeConsole(
        tmp_path / "calls.jsonl",
        tmp_path / "events.jsonl",
        tmp_path,
    )
    console._session_id = "repl_test"
    calls = []

    async def fake_run_vm(program, *, origin="vm"):
        calls.append(program["steps"][0]["args"]["correlation_id"])
        return {"status": "passed", "trace": []}

    console._run_vm_unlocked = fake_run_vm

    async def poll_once():
        return await console._poll_events_unlocked()

    assert len(asyncio.run(poll_once())) == 1
    assert asyncio.run(poll_once()) == []
    event["eventSession"] = "session-b"
    _write_event_bank(bank, "session-b", [event])
    assert len(asyncio.run(poll_once())) == 1
    assert calls == [
        "auto-vm:repl_test:session-a:1",
        "auto-vm:repl_test:session-b:1",
    ]


def test_runtime_call_log_http_endpoint_is_read_only(tmp_path, monkeypatch):
    console = server.RuntimeConsole(
        call_log_path=tmp_path / "runtime-call-log.jsonl",
        event_log_path=tmp_path / "runtime-event-log.jsonl",
    )
    console._record_runtime_call(
        "douququ.runtime.status",
        {},
        {"kind": "result", "error_code": "OK", "payload": {"active": True}},
        origin="connect",
    )
    console._record_runtime_event({
        "schema_version": "douququ-runtime-event.v1",
        "event_type": "unit_attacked",
        "status": "ignored",
    })
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
        with urllib.request.urlopen(
            f"http://127.0.0.1:{httpd.server_port}/api/vibe/event-log?limit=1",
            timeout=5,
        ) as response:
            event_payload = json.loads(response.read())
        assert response.status == 200
        assert event_payload["count"] == 1
        assert event_payload["records"][0]["event_type"] == "unit_attacked"
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


def test_runtime_script_compiles_galaxy_like_text_to_debug_vm():
    compiled = compile_runtime_script(
        '''
        let status = RuntimeStatus();
        assert status.active == true;
        let vulture = UnitCreate(1, "Vulture", 50.0, 48.0);
        call douququ.vulture.consume {"unit_tag":"$vars.vulture.tag","count":2};
        Step(8);
        let snapshot = Snapshot();
        assert snapshot.mineCount >= 0;
        '''
    )

    assert compiled["schema_version"] == "douququ-runtime-script.v1"
    assert compiled["compile_boundary"] == "current_vibe_session"
    assert compiled["galaxy_compile_boundary"] == "next_sc2_map_load"
    steps = compiled["program"]["steps"]
    assert steps[0] == {"op": "call", "fn": "douququ.runtime.status", "args": {}, "save": "status"}
    assert steps[2] == {
        "op": "call",
        "fn": "douququ.unit.spawn",
        "args": {"owner": 1, "unit_type": "Vulture", "x": 50.0, "y": 48.0},
        "save": "vulture",
    }
    assert steps[3]["fn"] == "douququ.vulture.consume"
    assert steps[4] == {"op": "step", "loops": 8}

def test_runtime_script_compiles_scarab_projectile_replacement_to_catalog_mutation():
    compiled = compile_runtime_script('ReplaceScarabProjectile("ScarabWeapon");')

    assert compiled["program"]["steps"] == [
        {
            "op": "call",
            "fn": "vibe.catalog.set",
            "args": {
                "catalog": "effect",
                "entry": "ScarabLM",
                "field": "AmmoUnit",
                "player": 1,
                "value": "ScarabWeapon",
            },
        }
    ]


def test_runtime_script_registry_discovers_map_mod_and_dependency_scripts(tmp_path, monkeypatch):
    root = tmp_path / "sources"
    map_root = root / "Maps" / "Demo.SC2Map"
    mod_root = root / "Mods" / "Demo.SC2Mod"
    map_root.mkdir(parents=True)
    mod_root.mkdir(parents=True)
    (map_root / "DocumentInfo").write_text(
        "<DocInfo><Dependencies><Value>file:Mods/Demo.SC2Mod</Value></Dependencies></DocInfo>",
        encoding="utf-8",
    )
    (mod_root / "DocumentInfo").write_text("<DocInfo />", encoding="utf-8")
    (map_root / "MapScript.galaxy").write_text('include "MapLib"\nvoid InitMap(){}', encoding="utf-8")
    (mod_root / "Base.SC2Data").mkdir()
    (mod_root / "Base.SC2Data" / "ModLib.galaxy").write_text('include "TriggerLibs/NativeLib"', encoding="utf-8")

    monkeypatch.setattr(server, "_resolve_map_detail_source", lambda map_name, package_id: (map_root, root))
    monkeypatch.setattr(server, "_canonical_map_detail_name", lambda map_name, package_id: map_name)
    monkeypatch.setattr(server, "_dependency_candidate_roots", lambda map_root_arg, source_root_arg: [root])
    server._SCRIPT_REGISTRY_CACHE.clear()

    registry = server.build_runtime_script_registry("Demo.SC2Map")

    assert registry["schema_version"] == "douququ-runtime-script-registry.v1"
    assert registry["package_count"] == 2
    assert registry["script_count"] == 2
    assert {item["path"] for item in registry["scripts"]} == {"MapScript.galaxy", "Base.SC2Data/ModLib.galaxy"}
    assert registry["dependencies"][0]["status"] == "resolved"

def test_runtime_script_registry_http_endpoint_returns_discovered_scripts(tmp_path, monkeypatch):
    root = tmp_path / "sources"
    map_root = root / "Maps" / "Demo.SC2Map"
    mod_root = root / "Mods" / "Demo.SC2Mod"
    map_root.mkdir(parents=True)
    mod_root.mkdir(parents=True)
    (map_root / "DocumentInfo").write_text(
        "<DocInfo><Dependencies><Value>file:Mods/Demo.SC2Mod</Value></Dependencies></DocInfo>",
        encoding="utf-8",
    )
    (mod_root / "DocumentInfo").write_text("<DocInfo />", encoding="utf-8")
    (map_root / "MapScript.galaxy").write_text('include "MapLib"\nvoid InitMap(){}', encoding="utf-8")
    (mod_root / "Base.SC2Data").mkdir()
    (mod_root / "Base.SC2Data" / "ModLib.galaxy").write_text('include "TriggerLibs/NativeLib"', encoding="utf-8")

    monkeypatch.setattr(server, "_resolve_map_detail_source", lambda map_name, package_id: (map_root, root))
    monkeypatch.setattr(server, "_canonical_map_detail_name", lambda map_name, package_id: map_name)
    monkeypatch.setattr(server, "_dependency_candidate_roots", lambda map_root_arg, source_root_arg: [root])
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.CmreWebUIHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{httpd.server_port}/api/vibe/scripts?mapName=Demo.SC2Map&mapPackage=cmre&commander=TerranAlenger3",
            timeout=5,
        ) as response:
            payload = json.loads(response.read())
        assert response.status == 200
        assert payload["schema_version"] == "douququ-runtime-script-registry.v1"
        assert payload["script_count"] == 2
        assert {item["path"] for item in payload["scripts"]} == {"MapScript.galaxy", "Base.SC2Data/ModLib.galaxy"}
        assert payload["dependencies"][0]["status"] == "resolved"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)



def test_runtime_rules_compile_event_conditions_and_payload_templates():
    compiled = compile_runtime_rules(
        '''
        rule "vulture death adapter" on unit_died where payload.victimType == "Vulture" and payload.victimOwner >= 1 {
          call douququ.auto.death {"correlation_id":"$correlation_id","victim_tag":"$payload.victimTag"};
        }
        '''
    )

    assert compiled["schema_version"] == "douququ-runtime-rules.v1"
    assert compiled["rule_count"] == 1
    rule = compiled["rules"][0]
    assert rule["id"] == "vulture death adapter"
    assert rule["event_type"] == "unit_died"
    assert rule["conditions"] == [
        {"path": "payload.victimType", "op": "==", "value": "Vulture"},
        {"path": "payload.victimOwner", "op": ">=", "value": 1},
    ]
    assert rule["program"]["steps"][0]["args"] == {
        "correlation_id": "$correlation_id",
        "victim_tag": "$payload.victimTag",
    }


def test_event_pump_runs_matching_dynamic_rule_instead_of_builtin_dispatch(tmp_path):
    bank = tmp_path / "GalaxyVibeEvents.SC2Bank"
    event = {
        "schemaVersion": 1,
        "eventId": 4,
        "eventSession": "session-a",
        "eventType": "unit_died",
        "payload": {
            "killerTag": 101,
            "killerType": "Hydralisk",
            "victimTag": 202,
            "victimType": "Vulture",
            "victimOwner": 2,
            "victimX": 40.5,
            "victimY": 41.5,
        },
    }
    _write_event_bank(bank, "session-a", [event])
    console = server.RuntimeConsole(
        tmp_path / "calls.jsonl",
        tmp_path / "events.jsonl",
        tmp_path,
    )
    console._session_id = "repl_test"
    console.set_rules(compile_runtime_rules(
        '''
        rule "custom vulture death" on unit_died where payload.victimType == "Vulture" {
          call douququ.auto.death {"correlation_id":"$correlation_id","victim_tag":"$payload.victimTag","victim_type":"$payload.victimType"};
        }
        '''
    ))
    seen = []

    async def fake_run_vm(program, *, origin="vm"):
        seen.append((origin, program["steps"][0]["fn"], program["steps"][0]["args"]))
        return {"status": "passed", "trace": []}

    console._run_vm_unlocked = fake_run_vm

    async def poll_once():
        return await console._poll_events_unlocked()

    batch = asyncio.run(poll_once())

    assert batch[0]["status"] == "passed"
    assert batch[0]["dispatch_function_id"] == "dynamic-rules"
    assert batch[0]["dispatch_args"] == {"rule_ids": ["custom vulture death"]}
    assert batch[0]["rule_results"][0]["status"] == "passed"
    assert seen == [
        (
            "rule-vm",
            "douququ.auto.death",
            {
                "correlation_id": "auto-vm:repl_test:session-a:4",
                "victim_tag": 202,
                "victim_type": "Vulture",
            },
        )
    ]


def test_runtime_rules_http_endpoint_registers_and_clears_rules(monkeypatch):
    console = server.RuntimeConsole()
    monkeypatch.setattr(server, "_runtime_console", console)
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.CmreWebUIHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        source = 'rule "periodic status" on periodic { call douququ.runtime.status {}; }'
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_port}/api/vibe/rules",
            data=json.dumps({"source": source}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read())
        assert response.status == 200
        assert payload["success"] is True
        assert payload["rules"]["rule_count"] == 1
        assert console.rules()["rules"][0]["id"] == "periodic status"

        clear = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_port}/api/vibe/rules/clear",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(clear, timeout=5) as response:
            cleared = json.loads(response.read())
        assert response.status == 200
        assert cleared["rules"]["rule_count"] == 0
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

def test_runtime_script_rejects_unknown_galaxy_functions():
    try:
        compile_runtime_script('TriggerCreate("Bad");')
    except RuntimeScriptError as exc:
        assert "unknown script function" in str(exc)
    else:
        raise AssertionError("expected RuntimeScriptError")


def test_runtime_script_http_endpoint_runs_compiled_program(tmp_path, monkeypatch):
    class FakeConsole:
        def __init__(self):
            self.program = None

        def run_vm(self, program):
            self.program = program
            return {"status": "passed", "trace": [], "instructions_executed": len(program["steps"])}

        def status(self):
            return {"status": "connected", "session_id": "repl_test"}

    fake = FakeConsole()
    monkeypatch.setattr(server, "_runtime_console", fake)
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.CmreWebUIHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_port}/api/vibe/run-script",
            data=json.dumps({"source": 'let marine = UnitCreate(1, "Marine", 90.0, 90.0);'}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read())
        assert response.status == 200
        assert payload["success"] is True
        assert payload["compiled"]["program"] == fake.program
        assert fake.program["steps"][0]["fn"] == "douququ.unit.spawn"
        assert payload["status"]["session_id"] == "repl_test"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
