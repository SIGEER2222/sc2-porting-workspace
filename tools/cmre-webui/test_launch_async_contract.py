#!/usr/bin/env python3
"""回归测试：异步 launcher 失败时先保留真实输出，再记录退出码。"""

from collections import deque
import io
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


def test_force_stop_leaves_untracked_sc2_sessions_alone(monkeypatch):
    previous_launcher = server._launcher_process
    calls = []
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
