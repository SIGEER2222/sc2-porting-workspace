#!/usr/bin/env python3
"""MVP contract test for the browser runtime-debug surface.

This deliberately runs without SC2: it proves the WebUI reaches the real
catalog/session handlers and reports the real disconnected error instead of
pretending a function invocation succeeded.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parent


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _get(base, path):
    return json.loads(urllib.request.urlopen(base + path, timeout=5).read())


def _post(base, path, payload):
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(request, timeout=5)


def _wait_ready(base, process):
    deadline = time.time() + 15
    while time.time() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(f"server exited: {stdout} {stderr}")
        try:
            _get(base, "/api/vibe/status")
            return
        except Exception:
            time.sleep(0.1)
    raise AssertionError("runtime WebUI did not become ready")


def test_runtime_debug_console_contract():
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ)
    env["CMRE_WEBUI_DRY_RUN"] = "1"
    process = subprocess.Popen(
        [sys.executable, "server.py", "--port", str(port), "--no-browser"],
        cwd=str(SERVER_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        _wait_ready(base, process)

        catalog = _get(base, "/api/vibe/catalog")
        functions = catalog.get("functions")
        assert isinstance(functions, list) and functions
        assert all(item.get("function_id") for item in functions)

        sessions = _get(base, "/api/vibe/sessions")
        assert isinstance(sessions.get("sessions"), list)

        status = _get(base, "/api/vibe/status")
        assert status.get("status") in {"disconnected", "error"}

        page = urllib.request.urlopen(base + "/", timeout=5).read().decode("utf-8")
        assert 'data-tab="runtime"' in page
        assert 'id="runtime-function-list"' in page
        assert 'id="runtime-vm-program"' in page
        assert 'id="runtime-trace-body"' in page

        try:
            _post(base, "/api/vibe/invoke", {"functionId": "vibe.test.ping", "args": {}})
        except urllib.error.HTTPError as error:
            assert error.code == 502
            payload = json.loads(error.read())
            assert payload.get("success") is False
            assert payload.get("error")
        else:
            raise AssertionError("disconnected invoke unexpectedly succeeded")

        try:
            _post(base, "/api/vibe/run-vm", {"program": {"steps": []}})
        except urllib.error.HTTPError as error:
            assert error.code == 502
        else:
            raise AssertionError("disconnected VM unexpectedly succeeded")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
