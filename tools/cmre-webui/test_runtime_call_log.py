import json
import threading
import urllib.request

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
