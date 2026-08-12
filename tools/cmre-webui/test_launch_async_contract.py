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


def test_maps_and_extra_mods_use_all_owned_package_roots():
    cmre = server.load_maps()
    reborn = server.load_reborn_maps()
    revolution = server.load_revolution_maps()

    assert any(item["id"] == "亡者之夜.SC2Map" and item["packageId"] == "cmre" for item in cmre)
    assert any(item["id"] == "zexpedition03.SC2Map" and item["packageId"] == "reborn" for item in reborn)
    assert any(item["id"] == "thorner03.SC2Map" and item["packageId"] == "revolution-overdrive" for item in revolution)
    assert any(item["id"] == "AbathurAlenger" for item in server.load_extra_mods("Alenger3"))


def test_all_current_map_display_names_are_explicit_chinese_and_ids_stay_internal():
    maps = server.load_maps() + server.load_reborn_maps() + server.load_revolution_maps()

    assert len(maps) == 66
    assert all(item["id"].endswith(".SC2Map") for item in maps)
    assert all(item["name"] for item in maps)
    assert all(not any("A" <= char <= "Z" or "a" <= char <= "z" for char in item["name"]) for item in maps)
    assert server._map_display_name("zexpedition03.SC2Map", "reborn") == "[虫心] 合相"
    assert server._map_display_name("thorner03.SC2Map", "revolution-overdrive") == "[起义狂潮] 毁灭引擎"


def test_all_current_maps_expose_real_preview_sources():
    maps = server.load_maps() + server.load_reborn_maps() + server.load_revolution_maps()

    assert len(maps) == 66
    assert all(item["preview"] for item in maps)
    assert sum(item["packageId"] == "cmre" for item in maps) == 15
    assert sum(item["packageId"] == "reborn" for item in maps) == 20
    assert sum(item["packageId"] == "revolution-overdrive" for item in maps) == 31
    assert all(item["preview"].startswith("MapPreview/reborn/") for item in maps if item["packageId"] == "reborn")
    assert all(item["preview"].startswith("MapPreview/revolution-overdrive/") for item in maps if item["packageId"] == "revolution-overdrive")
    assert all(item["previewSource"] == "official-loading-art" for item in maps if item["packageId"] != "cmre")
    assert all(not item["preview"].endswith("Minimap.tga") for item in maps)


def test_bound_map_preview_paths_resolve_to_read_only_sources():
    reborn = server.load_reborn_maps()[0]
    revolution = server.load_revolution_maps()[0]

    reborn_path = server.find_asset_file(reborn["preview"])
    revolution_path = server.find_asset_file(revolution["preview"])
    assert reborn_path and reborn_path.suffix.lower() == ".dds"
    assert revolution_path and revolution_path.suffix.lower() == ".dds"
    assert reborn_path.name == "ui_hots_loading_missionselect_zchar01.dds"
    assert revolution_path.name == "loading-lostviking.dds"


def test_minimap_preview_paths_are_rejected():
    assert server.find_asset_file("MapPreview/reborn/zchar01.SC2Map/Minimap.tga") is None
    assert server.find_asset_file("MapPreview/revolution-overdrive/thanson01.SC2Map/Minimap.tga") is None


def test_map_preview_conversion_writes_only_to_artifact_cache(tmp_path):
    source = server.find_asset_file(server.load_reborn_maps()[0]["preview"])
    target = tmp_path / "preview.png"

    assert source is not None
    assert server.convert_image_to_png(source, target)
    assert target.is_file() and target.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_map_display_registry_covers_every_owned_map_source():
    assert set(server.MAP_DISPLAY_NAMES["cmre"]) == {
        item["id"] for item in server.load_maps()
    }
    assert set(server.MAP_DISPLAY_NAMES["reborn"]) == {
        item["id"] for item in server.load_reborn_maps()
    }
    assert set(server.MAP_DISPLAY_NAMES["revolution-overdrive"]) == {
        item["id"] for item in server.load_revolution_maps()
    }


def test_cross_category_matrix_args_preserve_map_and_commander_identity(monkeypatch):
    monkeypatch.setattr(server, "_resolve_powershell_executable", lambda: "powershell.exe")
    handler = server.CmreWebUIHandler.__new__(server.CmreWebUIHandler)

    reborn_map = handler._build_launch_args({
        "mapPackage": "reborn",
        "mapName": "zexpedition03.SC2Map",
        "commander": "TerranRaynor",
        "commanderPackage": "cmre",
    })
    reborn_args = reborn_map["args"]
    assert "-MapSourceOverride" in reborn_args
    assert "-EnableReborn" in reborn_args
    assert "-RebornCommander" not in reborn_args

    revolution_map = handler._build_launch_args({
        "mapPackage": "revolution-overdrive",
        "mapName": "thorner03.SC2Map",
        "commander": "TerranAlenger3",
        "commanderPackage": "cmre",
    })
    revolution_args = revolution_map["args"]
    assert revolution_args[revolution_args.index("-MapDependencyRootOverride") + 1].endswith(
        "src\\projects\\revolution-overdrive-porting\\packages"
    )
    assert revolution_args[revolution_args.index("-Commander") + 1] == "TerranAlenger3"

    reborn_commander = handler._build_launch_args({
        "mapPackage": "revolution-overdrive",
        "mapName": "thorner03.SC2Map",
        "commander": "ZergAbathur",
        "commanderPackage": "cmre",
        "enableReborn": True,
        "rebornCommander": "Abathur",
    })
    reborn_commander_args = reborn_commander["args"]
    assert reborn_commander_args.count("-EnableReborn") == 1
    assert reborn_commander_args[reborn_commander_args.index("-RebornCommander") + 1] == "Abathur"


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
    monkeypatch.setattr(server, "_wait_for_process_exit", lambda pid: True)

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


def test_force_stop_cleans_failed_webui_staging_child(monkeypatch, tmp_path):
    runtime_lease = tmp_path / "sc2-runtime-lease.json"
    webui_lease = tmp_path / "cmre-webui-session.json"
    lease = {
        "schemaVersion": 1,
        "ownerPid": 101,
        "ownerSessionId": "cmre_alenger-webui-staging-test",
        "state": "staging",
        "mapName": "zexpedition03.SC2Map",
        "commander": "TerranRaynor",
        "launcher": str(server.LAUNCH_SCRIPT),
        "startedAt": "2026-08-12T12:26:08.097244+08:00",
    }
    intent = {
        "schemaVersion": 1,
        "launcherPid": 101,
        "launcher": str(server.LAUNCH_SCRIPT),
        "mapName": "zexpedition03.SC2Map",
        "commander": "TerranRaynor",
        "createdAt": 1775964368.0,
    }
    _write_record(runtime_lease, lease)
    _write_record(webui_lease, intent)
    killed = []
    monkeypatch.setattr(server, "SC2_RUNTIME_LEASE_PATH", runtime_lease)
    monkeypatch.setattr(server, "WEBUI_SESSION_LEASE_PATH", webui_lease)
    monkeypatch.setattr(server, "_get_process_info", lambda pid: {
        101: None,
        303: {
            "Name": "SC2_x64.exe",
            "CommandLine": '"E:/SC2/SC2_x64.exe" "E:/SC2/Maps/zexpedition03.SC2Map"',
            "CreationDate": "2026-08-12T12:26:14.000000+08:00",
        },
    }.get(pid))
    monkeypatch.setattr(server, "_list_game_processes", lambda: [(303, "SC2_x64.exe")])
    monkeypatch.setattr(server, "_force_kill_process_tree", lambda pid: killed.append(pid) or True)
    monkeypatch.setattr(server, "_wait_for_process_exit", lambda pid: True)

    assert server._force_stop_current_game() == ["sc2:303"]
    assert killed == [303]
    assert not runtime_lease.exists()
    assert not webui_lease.exists()


def test_force_stop_waits_for_killed_runtime_before_removing_lease(monkeypatch, tmp_path):
    runtime_lease = tmp_path / "sc2-runtime-lease.json"
    webui_lease = tmp_path / "cmre-webui-session.json"
    lease, intent = _detached_records()
    _write_record(runtime_lease, lease)
    _write_record(webui_lease, intent)
    state = {"killed": False, "checks": 0}
    process_info = {
        "Name": "SC2_x64.exe",
        "CommandLine": '"E:/SC2/SC2_x64.exe" "E:/SC2/Maps/亡者之夜.SC2Map"',
        "CreationDate": "2026-08-10T19:45:10.141267+08:00",
    }

    def get_process_info(pid):
        if pid == 101:
            return None
        if pid != 202:
            return None
        if not state["killed"]:
            return process_info
        state["checks"] += 1
        return process_info if state["checks"] == 1 else None

    monkeypatch.setattr(server, "SC2_RUNTIME_LEASE_PATH", runtime_lease)
    monkeypatch.setattr(server, "WEBUI_SESSION_LEASE_PATH", webui_lease)
    monkeypatch.setattr(server, "_get_process_info", get_process_info)
    monkeypatch.setattr(server, "_force_kill_process_tree", lambda pid: state.update(killed=True) or True)

    assert server._force_stop_current_game() == ["sc2:202"]
    assert state["checks"] == 2
    assert not runtime_lease.exists()
    assert not webui_lease.exists()


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
