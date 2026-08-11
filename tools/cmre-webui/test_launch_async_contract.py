#!/usr/bin/env python3
"""回归测试：异步 launcher 失败时先保留真实输出，再记录退出码。"""

from collections import deque
import base64
import io
import json
import threading
from pathlib import Path

import server


WEBUI_APP = Path(__file__).parent / "webui" / "app.js"


def test_launcher_prefers_powershell_core(monkeypatch):
    monkeypatch.setattr(server.shutil, "which", lambda name: {
        "pwsh": r"C:\Program Files\PowerShell\7\pwsh.exe",
        "powershell": r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    }.get(name))

    assert server._resolve_powershell_executable().endswith("pwsh.exe")


def test_launcher_falls_back_to_windows_powershell(monkeypatch):
    monkeypatch.setattr(server.shutil, "which", lambda name: (
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        if name == "powershell" else None
    ))

    assert server._resolve_powershell_executable().endswith("powershell.exe")


def test_cmre_launch_args_preserve_webui_map_and_commander(monkeypatch):
    monkeypatch.setattr(server, "_resolve_powershell_executable", lambda: "powershell.exe")
    handler = server.CmreWebUIHandler.__new__(server.CmreWebUIHandler)

    context = handler._build_launch_args(
        {
            "mapName": "亡者之夜.SC2Map",
            "commander": "ZergAlenger6",
            "mode": 1,
            "difficultyBase": 0,
            "difficultyPlus": 0,
        }
    )

    args = context["args"]
    assert args[args.index("-MapName") + 1] == "亡者之夜.SC2Map"
    assert args[args.index("-Commander") + 1] == "ZergAlenger6"
    assert context["commander"] == "ZergAlenger6"


def test_webui_defaults_to_player_map_launch(monkeypatch):
    monkeypatch.setattr(server, "_resolve_powershell_executable", lambda: "powershell.exe")
    handler = server.CmreWebUIHandler.__new__(server.CmreWebUIHandler)

    context = handler._build_launch_args({})

    command = " ".join(context["args"])
    assert "-PlayerMode" in command
    assert "-ListenPort" not in command
    assert WEBUI_APP.read_text(encoding="utf-8").count("apiMode: false") == 2


def _detached_records(runtime_pid=202):
    launcher = str(server.LAUNCH_SCRIPT)
    lease = {
        "schemaVersion": 1,
        "ownerPid": 101,
        "ownerSessionId": "cmre_alenger-webui-test",
        "runtimePid": runtime_pid,
        "state": "detached",
        "mapName": "亡者之夜.SC2Map",
        "commander": "TerranAlenger3",
        "launcher": launcher,
    }
    intent = {
        "schemaVersion": 1,
        "launcherPid": 101,
        "launcher": launcher,
        "mapName": "亡者之夜.SC2Map",
        "commander": "TerranAlenger3",
        "leaseOwnerSessionId": "cmre_alenger-webui-test",
        "runtimePid": runtime_pid,
        "runtimeCreationDate": "2026-08-10T19:45:10.141267+08:00",
    }
    return lease, intent


def _write_record(path, record):
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


def test_force_stop_leaves_untracked_sc2_sessions_alone(monkeypatch, tmp_path):
    previous_launcher = server._launcher_process
    calls = []
    monkeypatch.setattr(server, "SC2_RUNTIME_LEASE_PATH", tmp_path / "sc2-runtime-lease.json")
    monkeypatch.setattr(server, "WEBUI_SESSION_LEASE_PATH", tmp_path / "cmre-webui-session.json")
    monkeypatch.setattr(server, "_list_game_processes", lambda: [(321, "SC2_x64.exe")])
    monkeypatch.setattr(
        server,
        "_force_kill_process_tree",
        lambda pid: calls.append(pid) or True,
    )
    try:
        server._launcher_process = None

        assert server._force_stop_current_game() == []
        assert calls == []
    finally:
        server._launcher_process = previous_launcher


def test_launch_async_rejects_unowned_sc2_before_starting_launcher(monkeypatch):
    handler = server.CmreWebUIHandler.__new__(server.CmreWebUIHandler)
    response = {}
    handler._read_body = lambda: {}
    handler._build_launch_args = lambda body: {
        "args": ["powershell.exe", "-File", "launcher.ps1"],
        "commander": "TerranAlenger3",
    }
    handler._send_json = lambda data, status=200: response.update(data=data, status=status)

    monkeypatch.setattr(server, "_force_stop_current_game", lambda: [])
    monkeypatch.setattr(server, "_has_live_bound_webui_session", lambda: False)
    monkeypatch.setattr(server, "_list_game_processes", lambda: [(321, "SC2_x64.exe")])
    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("launcher must not start")),
    )

    handler._handle_launch_async()

    assert response["status"] == 409
    assert response["data"]["success"] is False
    assert response["data"]["processes"] == [{"pid": 321, "name": "SC2_x64.exe"}]


def test_force_stop_cleans_only_bound_webui_detached_session(monkeypatch, tmp_path):
    runtime_lease = tmp_path / "sc2-runtime-lease.json"
    webui_lease = tmp_path / "cmre-webui-session.json"
    lease, intent = _detached_records()
    _write_record(runtime_lease, lease)
    _write_record(webui_lease, intent)
    killed = []
    monkeypatch.setattr(server, "SC2_RUNTIME_LEASE_PATH", runtime_lease)
    monkeypatch.setattr(server, "WEBUI_SESSION_LEASE_PATH", webui_lease)
    monkeypatch.setattr(
        server,
        "_get_process_info",
        lambda pid: None if pid == 101 else {
            "Name": "SC2_x64.exe",
            "CommandLine": '"E:/SC2/SC2_x64.exe" "E:/SC2/Maps/亡者之夜.SC2Map"',
            "CreationDate": "2026-08-10T19:45:10.141267+08:00",
        },
    )
    monkeypatch.setattr(server, "_force_kill_process_tree", lambda pid: killed.append(pid) or True)

    assert server._force_stop_current_game() == ["sc2:202"]
    assert killed == [202]
    assert not runtime_lease.exists()
    assert not webui_lease.exists()


def test_force_stop_refuses_detached_lease_without_webui_intent(monkeypatch, tmp_path):
    runtime_lease = tmp_path / "sc2-runtime-lease.json"
    webui_lease = tmp_path / "cmre-webui-session.json"
    lease, _ = _detached_records()
    _write_record(runtime_lease, lease)
    killed = []
    monkeypatch.setattr(server, "SC2_RUNTIME_LEASE_PATH", runtime_lease)
    monkeypatch.setattr(server, "WEBUI_SESSION_LEASE_PATH", webui_lease)
    monkeypatch.setattr(server, "_force_kill_process_tree", lambda pid: killed.append(pid) or True)

    assert server._force_stop_current_game() == []
    assert killed == []
    assert runtime_lease.exists()


def test_force_stop_refuses_mismatched_webui_runtime_pid(monkeypatch, tmp_path):
    runtime_lease = tmp_path / "sc2-runtime-lease.json"
    webui_lease = tmp_path / "cmre-webui-session.json"
    lease, intent = _detached_records()
    intent["runtimePid"] = 203
    _write_record(runtime_lease, lease)
    _write_record(webui_lease, intent)
    killed = []
    monkeypatch.setattr(server, "SC2_RUNTIME_LEASE_PATH", runtime_lease)
    monkeypatch.setattr(server, "WEBUI_SESSION_LEASE_PATH", webui_lease)
    monkeypatch.setattr(server, "_force_kill_process_tree", lambda pid: killed.append(pid) or True)

    assert server._force_stop_current_game() == []
    assert killed == []
    assert runtime_lease.exists()
    assert webui_lease.exists()


def test_force_stop_refuses_mismatched_map_command_line(monkeypatch, tmp_path):
    runtime_lease = tmp_path / "sc2-runtime-lease.json"
    webui_lease = tmp_path / "cmre-webui-session.json"
    lease, intent = _detached_records()
    _write_record(runtime_lease, lease)
    _write_record(webui_lease, intent)
    killed = []
    monkeypatch.setattr(server, "SC2_RUNTIME_LEASE_PATH", runtime_lease)
    monkeypatch.setattr(server, "WEBUI_SESSION_LEASE_PATH", webui_lease)
    monkeypatch.setattr(
        server,
        "_get_process_info",
        lambda pid: None if pid == 101 else {
            "Name": "SC2_x64.exe",
            "CommandLine": '"E:/SC2/SC2_x64.exe" "E:/SC2/Maps/虚空撕裂.SC2Map"',
            "CreationDate": "2026-08-10T19:45:10.141267+08:00",
        },
    )
    monkeypatch.setattr(server, "_force_kill_process_tree", lambda pid: killed.append(pid) or True)

    assert server._force_stop_current_game() == []
    assert killed == []
    assert runtime_lease.exists()
    assert webui_lease.exists()


def test_process_info_decodes_utf16_command_line_from_powershell(monkeypatch):
    command_line = '"E:/SC2/SC2_x64.exe" "E:/SC2/Maps/亡者之夜.SC2Map"'
    payload = {
        "ProcessId": 202,
        "Name": "SC2_x64.exe",
        "CommandLineUtf16": base64.b64encode(command_line.encode("utf-16-le")).decode("ascii"),
        "CreationDate": "2026-08-11T08:10:38.423769+08:00",
    }

    class _Completed:
        stdout = json.dumps(payload)

    monkeypatch.setattr(server, "_resolve_powershell_executable", lambda: "powershell.exe")
    monkeypatch.setattr(server.subprocess, "run", lambda *args, **kwargs: _Completed())

    info = server._get_process_info(202)

    assert info["CommandLine"] == command_line


def test_wait_discards_failed_unbound_webui_launch_intent(monkeypatch, tmp_path):
    webui_lease = tmp_path / "cmre-webui-session.json"
    _write_record(webui_lease, {"launcherPid": 202, "mapName": "亡者之夜.SC2Map"})
    monkeypatch.setattr(server, "WEBUI_SESSION_LEASE_PATH", webui_lease)
    monkeypatch.setattr(server, "_bind_webui_runtime_lease", lambda launcher_pid: False)

    class _FailedProcess:
        pid = 202

        def wait(self):
            return 1

    server._wait_for_process(_FailedProcess())

    assert not webui_lease.exists()


class _FinishedProcess:
    def wait(self):
        return 4294967295


def test_launcher_failure_preserves_pipe_output_before_exit_code():
    with server._log_lock:
        previous = list(server._log_lines)
        server._log_lines.clear()
    try:
        output_tail = {"stdout": deque(maxlen=80), "stderr": deque(maxlen=80)}
        tail_lock = threading.Lock()
        readers = [
            threading.Thread(
                target=server._read_pipe,
                args=(io.StringIO("staging started\n"), ""),
                kwargs={"output_tail": output_tail, "tail_lock": tail_lock, "stream_name": "stdout"},
            ),
            threading.Thread(
                target=server._read_pipe,
                args=(io.StringIO("SwarmStory campaign not found\n"), "[stderr] "),
                kwargs={"output_tail": output_tail, "tail_lock": tail_lock, "stream_name": "stderr"},
            ),
        ]
        for reader in readers:
            reader.start()
        server._wait_for_process(_FinishedProcess(), readers, output_tail, tail_lock)

        with server._log_lock:
            fresh = list(server._log_lines)
        error_index = next(i for i, line in enumerate(fresh) if "SwarmStory campaign not found" in line)
        exit_index = next(i for i, line in enumerate(fresh) if "launcher 进程结束" in line)
        assert error_index < exit_index
        assert "exit=4294967295 (signed=-1)" in fresh[exit_index]
    finally:
        with server._log_lock:
            server._log_lines[:] = previous
