#!/usr/bin/env python3
"""回归测试：异步 launcher 失败时先保留真实输出，再记录退出码。"""

import asyncio
from collections import deque
import base64
import io
import json
import threading
import inspect
from pathlib import Path
import pytest

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


def test_revolution_map_routes_all_commander_groups_to_its_runtime_launcher(monkeypatch):
    monkeypatch.setattr(server, "_resolve_powershell_executable", lambda: "powershell.exe")
    handler = server.CmreWebUIHandler.__new__(server.CmreWebUIHandler)

    for commander in ("TerranRaynor", "TerranAlenger3", "RebornTerranTosh", "RevolutionOverdriveIron"):
        context = handler._build_launch_args({
            "packageId": "revolution-overdrive",
            "mapPackage": "revolution-overdrive",
            "mapName": "thanson01.SC2Map",
            "commander": commander,
            "commanderPackage": "cmre",
            "faction": "Iron" if commander == "RevolutionOverdriveIron" else "",
        })
        assert context["kind"] == "revolution-overdrive"
        args = context["args"]
        assert "launch-revolution-overdrive.ps1" in " ".join(args)
        assert args[args.index("-Commander") + 1] == commander
        if commander == "RevolutionOverdriveIron":
            assert args[args.index("-Faction") + 1] == "Iron"
        else:
            assert "-Faction" not in args


def test_cmre_launcher_rejects_revolution_commander_before_subprocess(monkeypatch):
    monkeypatch.setattr(server, "_resolve_powershell_executable", lambda: "powershell.exe")
    handler = server.CmreWebUIHandler.__new__(server.CmreWebUIHandler)
    sent = {}
    handler._send_json = lambda payload, status=200: sent.update(payload=payload, status=status)

    assert handler._build_launch_args({
        "mapPackage": "cmre",
        "mapName": "虚空降临.SC2Map",
        "commander": "RevolutionOverdriveCoverts",
        "commanderPackage": "revolution-overdrive",
    }) is None

    assert sent["status"] == 400
    assert "起义狂潮专属指挥官只能与起义狂潮地图一起启动" in sent["payload"]["error"]


def test_launch_async_rejects_revolution_commander_without_spawning(monkeypatch):
    handler = server.CmreWebUIHandler.__new__(server.CmreWebUIHandler)
    sent = {}
    handler._read_body = lambda: {
        "mapPackage": "cmre",
        "mapName": "虚空降临.SC2Map",
        "commander": "RevolutionOverdriveCoverts",
        "commanderPackage": "revolution-overdrive",
    }
    handler._send_json = lambda payload, status=200: sent.update(payload=payload, status=status)
    monkeypatch.setattr(server.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("launcher spawned")))

    handler._handle_launch_async()

    assert sent["status"] == 400
    assert "起义狂潮专属指挥官" in sent["payload"]["error"]


def test_webui_blocks_revolution_commander_on_non_revolution_map():
    app = WEBUI_APP.read_text(encoding="utf-8")
    assert 'cmdrMeta.group === "revolution-overdrive" && s.mapPackage !== "revolution-overdrive"' in app
    assert "起义狂潮专属指挥官只能与起义狂潮地图一起启动" in app

def test_revolution_map_rejects_tarcade_entry_flow(monkeypatch):
    monkeypatch.setattr(server, "_resolve_powershell_executable", lambda: "powershell.exe")
    handler = server.CmreWebUIHandler.__new__(server.CmreWebUIHandler)
    sent = {}
    handler._send_json = lambda payload, status=200: sent.update(payload=payload, status=status)

    assert handler._build_launch_args({
        "packageId": "revolution-overdrive",
        "mapName": "tarcade.SC2Map",
        "commander": "TerranRaynor",
    }) is None
    assert sent["status"] == 400
    assert "入口流" in sent["payload"]["error"]


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
    assert "launch-revolution-overdrive.ps1" in " ".join(revolution_args)
    assert "-MapDependencyRootOverride" not in revolution_args
    assert revolution_args[revolution_args.index("-Commander") + 1] == "TerranAlenger3"

    reborn_commander = handler._build_launch_args({
        "mapPackage": "revolution-overdrive",
        "mapName": "thorner03.SC2Map",
        "commander": "RebornZergAbathur",
        "commanderPackage": "reborn",
    })
    reborn_commander_args = reborn_commander["args"]
    assert reborn_commander_args[reborn_commander_args.index("-Commander") + 1] == "RebornZergAbathur"
    assert "-EnableReborn" not in reborn_commander_args


def test_webui_defaults_to_player_map_launch(monkeypatch):
    monkeypatch.setattr(server, "_resolve_powershell_executable", lambda: "powershell.exe")
    handler = server.CmreWebUIHandler.__new__(server.CmreWebUIHandler)

    context = handler._build_launch_args({})

    command = " ".join(context["args"])
    assert "-PlayerMode" in command
    assert "-ListenPort" not in command
    app = WEBUI_APP.read_text(encoding="utf-8")
    assert 'mapPackage: "dou-ququ"' in app
    assert 'apiMode: true' in app
    assert 'preferAiOpponent: state.selected.mapPackage === "dou-ququ"' in app
    assert 'id="runtime-join-wait"' in (WEBUI_APP.parent / "index.html").read_text(encoding="utf-8")
    assert 'joinWait: Math.max(0, Math.min(120, parseFloat($("runtime-join-wait").value) || 15))' in app
    assert 'loadRuntimeSessions();' in app
    assert 'm.runtimeMapPath || m.runtimeSource || ""' in app
    assert 'const latest = sessions[0];' not in app


def test_runtime_session_candidates_do_not_treat_sequence_as_recency():
    source = inspect.getsource(server.RuntimeConsole.sessions)
    assert 'key=lambda item: item["session_id"]' in source
    assert 'item["sequence"], reverse=True' not in source


def test_runtime_connect_probes_expired_session_before_accepting_current_one(monkeypatch):
    attempts = []

    class FakeRepl:
        def __init__(self, port, resolve, name_lookup, **kwargs):
            self.rpc_session_id = kwargs.get("rpc_session_id") or "repl_new"
            self.rpc_sequence = 0
            self.ws = object()

        async def connect(self):
            return True

        async def close(self):
            return None

        async def invoke_function_request(self, function_id, args):
            attempts.append(self.rpc_session_id)
            if self.rpc_session_id == "dou-ququ-runtime-stale":
                return {"error_code": "SESSION_EXPIRED"}
            return {"error_code": "OK", "payload": {"active": True}}

    console = server.RuntimeConsole()
    monkeypatch.setattr(
        console,
        "_imports",
        lambda: (FakeRepl, lambda: object(), lambda: object(), None, None, None),
    )
    monkeypatch.setattr(
        console,
        "sessions",
        lambda: [
            {"session_id": "dou-ququ-runtime-stale", "sequence": 39},
            {"session_id": "repl_current", "sequence": 7},
        ],
    )
    async def fake_readiness(repl):
        return {"status": 3, "status_name": "in_game", "game_loop": 8}
    monkeypatch.setattr(console, "_probe_live_readiness", fake_readiness)

    result = asyncio.run(console._connect({"port": 5896, "rpc_session_id": "dou-ququ-runtime-stale"}))

    assert result["status"] == "connected"
    assert result["session_id"] == "repl_current"
    assert attempts[:2] == ["dou-ququ-runtime-stale", "repl_current"]
    assert result["session_recovery"] == [
        {
            "session_id": "dou-ququ-runtime-stale",
            "error_code": "SESSION_EXPIRED",
            "status": 3,
            "status_name": "in_game",
            "game_loop": 8,
        },
        {
            "session_id": "repl_current",
            "error_code": "OK",
            "status": 3,
            "status_name": "in_game",
            "game_loop": 8,
            "accepted": True,
        },
    ]
    assert result["readiness"] == {"status": 3, "status_name": "in_game", "game_loop": 8}


def test_runtime_connect_rejects_non_ok_probe_even_when_game_is_in_game(monkeypatch):
    class FakeRepl:
        def __init__(self, port, resolve, name_lookup, **kwargs):
            self.rpc_session_id = kwargs.get("rpc_session_id") or "repl_new"
            self.rpc_sequence = 0
            self.ws = object()

        async def connect(self):
            return True

        async def close(self):
            return None

        async def invoke_function_request(self, function_id, args):
            return {"kind": "error", "error_code": "INTERNAL_ERROR", "payload": {}}

    console = server.RuntimeConsole()
    monkeypatch.setattr(
        console,
        "_imports",
        lambda: (FakeRepl, lambda: object(), lambda: object(), None, None, None),
    )
    monkeypatch.setattr(console, "sessions", lambda: [])

    async def fake_readiness(repl):
        return {"status": 3, "status_name": "in_game", "game_loop": 12}
    monkeypatch.setattr(console, "_probe_live_readiness", fake_readiness)

    with pytest.raises(RuntimeError, match="没有可用的当前 Vibe session"):
        asyncio.run(console._connect({"port": 5896, "rpc_session_id": "repl_bad"}))
    assert console.status()["status"] == "error"
    assert "INTERNAL_ERROR" in console.status()["error"]


def test_dou_ququ_launch_mounts_live_runtime_module(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "_resolve_powershell_executable", lambda: "powershell.exe")
    source = tmp_path / "dou-ququ.SC2Map"
    source.mkdir()
    monkeypatch.setattr(server, "DOU_QUQU_MAP_SOURCE", source)
    monkeypatch.setattr(server, "_dou_ququ_map_root", lambda: source)
    handler = server.CmreWebUIHandler.__new__(server.CmreWebUIHandler)

    context = handler._build_launch_args({
        "mapPackage": "dou-ququ",
        "mapName": "dou-ququ.SC2Map",
        "commander": "ProtossAlarak",
        "listenPort": 5896,
    })

    assert "-EnableDouQuquBehavior" not in context["args"]
    assert "-EnableDouQuquRuntime" in context["args"]
    assert context["enable_douququ_runtime"] is True
    assert context["api_minimal"] is True


def test_dou_ququ_map_name_recovers_runtime_package_when_payload_omits_package(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "_resolve_powershell_executable", lambda: "powershell.exe")
    source = tmp_path / "地图调试和斗蛐蛐工具（完整功能版).SC2Map"
    source.mkdir()
    monkeypatch.setattr(server, "DOU_QUQU_MAP_SOURCE", source)
    monkeypatch.setattr(server, "_dou_ququ_map_root", lambda: source)
    handler = server.CmreWebUIHandler.__new__(server.CmreWebUIHandler)

    context = handler._build_launch_args({
        "mapName": source.name,
        "commander": "ProtossAlarak",
        "listenPort": 5896,
    })

    assert context["map_package"] == "dou-ququ"
    assert "-EnableDouQuquRuntime" in context["args"]


def test_webui_api_launch_keeps_runtime_alive(monkeypatch):
    monkeypatch.setattr(server, "_resolve_powershell_executable", lambda: "powershell.exe")
    handler = server.CmreWebUIHandler.__new__(server.CmreWebUIHandler)

    context = handler._build_launch_args({
        "mapName": "亡者之夜.SC2Map",
        "commander": "TerranAlenger3",
        "listenPort": 5015,
        "apiMinimal": True,
    })

    args = context["args"]
    assert args[args.index("-ListenPort") + 1] == "5015"
    assert "-KeepAlive" in args


def test_webui_groups_commanders_and_maps_and_loads_extra_mods_on_demand():
    app = WEBUI_APP.read_text(encoding="utf-8")
    html = (WEBUI_APP.parent / "index.html").read_text(encoding="utf-8")
    styles = (WEBUI_APP.parent / "styles.css").read_text(encoding="utf-8")

    assert 'class="commander-groups" id="commander-grid"' in html
    assert 'class="map-groups" id="map-list"' in html
    assert 'id="load-extra-mods"' in html
    assert 'data-group="revolution-overdrive"' in html
    assert 'className = "commander-group"' in app
    assert 'className = "map-group"' in app
    assert 'if (targetId === "advanced-body") loadExtraMods();' in app
    assert 'if (isExtraModsPanelOpen()) loadExtraMods(true);' in app
    assert '.commander-groups, .map-groups' in styles

    init_start = app.index("async function init()")
    init_end = app.index("init();", init_start)
    init_block = app[init_start:init_end]
    assert "loadExtraMods()" not in init_block
    card_start = app.index("function renderCommanderCard()")
    card_end = app.index("/* === 突变因子列表渲染 === */", card_start)
    assert "loadExtraMods()" not in app[card_start:card_end]


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


def test_force_stop_all_game_processes_kills_untracked_sc2_sessions(monkeypatch):
    calls = []
    process_lists = iter([[(321, "SC2_x64.exe")], []])
    monkeypatch.setattr(server, "_list_game_processes", lambda: next(process_lists))
    monkeypatch.setattr(server, "_force_kill_process_tree", lambda pid: calls.append(pid) or True)
    monkeypatch.setattr(server, "_wait_for_process_exit", lambda pid: True)

    assert server._force_stop_all_game_processes() == ["SC2_x64.exe:321"]
    assert calls == [321]


def test_launch_async_kills_unowned_sc2_before_starting_launcher(monkeypatch):
    handler = server.CmreWebUIHandler.__new__(server.CmreWebUIHandler)
    response = {}
    stopped = []
    previous_launcher = server._launcher_process

    class _Pipe:
        def __iter__(self):
            return iter(())

        def close(self):
            pass

    class _Process:
        pid = 456
        stdout = _Pipe()
        stderr = _Pipe()

    class _NoopThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    handler._read_body = lambda: {}
    handler._build_launch_args = lambda body: {
        "args": ["powershell.exe", "-File", "launcher.ps1"],
        "commander": "TerranAlenger3",
    }
    handler._send_json = lambda data, status=200: response.update(data=data, status=status)

    monkeypatch.setattr(server, "_force_stop_current_game", lambda: [])
    monkeypatch.setattr(
        server,
        "_force_stop_all_game_processes",
        lambda: stopped.append(True) or ["SC2_x64.exe:321"],
    )
    monkeypatch.setattr(server.subprocess, "Popen", lambda *args, **kwargs: _Process())
    monkeypatch.setattr(server.threading, "Thread", _NoopThread)
    try:
        handler._handle_launch_async()
    finally:
        server._launcher_process = previous_launcher

    assert stopped == [True]
    assert response["status"] == 200
    assert response["data"]["success"] is True


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


def test_force_stop_cleans_webui_keepalive_api_session(monkeypatch, tmp_path):
    runtime_lease = tmp_path / "sc2-runtime-lease.json"
    webui_lease = tmp_path / "cmre-webui-session.json"
    launcher = str(server.LAUNCH_SCRIPT)
    _write_record(runtime_lease, {
        "schemaVersion": 1,
        "ownerPid": 101,
        "ownerSessionId": "cmre_alenger-webui-keepalive-test",
        "runtimePid": 202,
        "port": 5015,
        "state": "keepalive",
        "mapName": "zzerus03.SC2Map",
        "commander": "TerranAlenger3",
        "launcher": launcher,
    })
    _write_record(webui_lease, {
        "schemaVersion": 1,
        "launcherPid": 101,
        "launcher": launcher,
        "mapName": "zzerus03.SC2Map",
        "commander": "TerranAlenger3",
    })
    killed = []
    monkeypatch.setattr(server, "SC2_RUNTIME_LEASE_PATH", runtime_lease)
    monkeypatch.setattr(server, "WEBUI_SESSION_LEASE_PATH", webui_lease)
    monkeypatch.setattr(server, "_get_process_info", lambda pid: {
        101: None,
        202: {"Name": "SC2_x64.exe", "CommandLine": '"E:/SC2/SC2_x64.exe" -listen 127.0.0.1 -port 5015'},
    }.get(pid))
    monkeypatch.setattr(server, "_force_kill_process_tree", lambda pid: killed.append(pid) or True)
    monkeypatch.setattr(server, "_wait_for_process_exit", lambda pid: True)

    assert server._force_stop_current_game() == ["sc2:202"]
    assert killed == [202]
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
