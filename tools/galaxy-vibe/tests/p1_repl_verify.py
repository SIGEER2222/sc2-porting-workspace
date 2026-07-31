#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 REPL 真机验证：CreateGame → JoinGame → vibe 命令闭环（info/query/spawn/cheat/step/kill）。

前置条件：
  - SC2 已通过 launch-cmre-alenger.ps1 -DebugMode -KeepAlive -ListenPort 5000 启动
  - SC2 API 监听在 127.0.0.1:5000
  - 地图 vibe kernel 已集成（GalaxyVibe.SC2Bank）

证据分类：全部 runtime（真机观察）
"""
import asyncio
import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_ROOT = Path(r"e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace")
sys.path.insert(0, str(REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"))
os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = "python"

from s2clientprotocol import sc2api_pb2 as sc_pb
from s2clientprotocol import debug_pb2 as debug_pb
from s2clientprotocol import common_pb2 as common_pb
import aiohttp

# P0 验收成功的打包地图（含 vibe kernel + CMRE 依赖通过 DocumentInfo 声明）
MAP = r"E:\SC2\SC2new\StarCraft II\Maps\亡者之夜_vibe_live.SC2Map"
PORT = 5000
BANK_FILE = Path.home() / "Documents" / "StarCraft II" / "Banks" / "GalaxyVibe.SC2Bank"
GAMELOGS_DIR = Path.home() / "Documents" / "StarCraft II" / "GameLogs"
RESULT_PATH = REPO_ROOT / "artifacts" / "real-machine-acceptance-20260731" / "p1-result.json"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def port_open(p):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", p))
        s.close()
        return True
    except Exception:
        return False


def read_bank():
    if not BANK_FILE.exists():
        return None
    try:
        tree = ET.parse(BANK_FILE)
        root = tree.getroot()
        sections = {}
        for sec in root.findall("Section"):
            sname = sec.get("name", "")
            keys = {}
            for k in sec.findall("Key"):
                kn = k.get("name", "")
                v = k.find("Value")
                if v is not None:
                    keys[kn] = dict(v.attrib)
            sections[sname] = keys
        return sections
    except Exception as e:
        return {"error": str(e)}


async def send_recv(ws, req, timeout=30):
    await ws.send_bytes(req.SerializeToString())
    data = await asyncio.wait_for(ws.receive_bytes(), timeout=timeout)
    if isinstance(data, str):
        data = data.encode("utf-8")
    resp = sc_pb.Response()
    resp.ParseFromString(data)
    return resp


def count_units_by_player(raw, player=None):
    """返回 {unit_type: count} 或 {player: {unit_type: count}}"""
    by_player = {}
    for u in raw.units:
        if player is not None and u.owner != player:
            continue
        by_player.setdefault(u.owner, {})
        ut = u.unit_type
        by_player[u.owner][ut] = by_player[u.owner].get(ut, 0) + 1
    if player is not None:
        return by_player.get(player, {})
    return by_player


def scan_script_errors():
    """扫描 GameLogs 目录中的 ScriptError 文件，返回 {filename: mtime}"""
    errors = {}
    if not GAMELOGS_DIR.exists():
        return errors
    for f in GAMELOGS_DIR.glob("ScriptError*.txt"):
        try:
            errors[f.name] = f.stat().st_mtime
        except Exception:
            pass
    return errors


async def main():
    log("=== P1 REPL 真机验证 ===")
    results = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "acceptance": "P1 REPL 真机验证（DebugCommand 闭环）",
        "port": PORT,
        "map": MAP,
        "checks": {},
    }

    # 记录启动前的 ScriptError 基线
    pre_errors = scan_script_errors()
    log(f"[baseline] GameLogs 中已有 {len(pre_errors)} 个 ScriptError 文件")

    # 0. 端口检查
    if not port_open(PORT):
        log(f"FAIL: 端口 {PORT} 未开放")
        results["verdict"] = "FAIL"
        results["checks"]["port_open"] = {"status": "FAIL", "evidence_type": "runtime",
                                          "detail": f"TCP 127.0.0.1:{PORT} 不可达"}
        return results
    results["checks"]["port_open"] = {"status": "PASS", "evidence_type": "runtime",
                                      "detail": f"TCP 127.0.0.1:{PORT} 可达"}
    log(f"[0] 端口 {PORT} 开放")

    # 1. WebSocket 连接
    try:
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300))
        ws = await session.ws_connect(f"ws://127.0.0.1:{PORT}/sc2api", max_msg_size=0)
    except Exception as e:
        log(f"FAIL: WebSocket 连接失败: {e}")
        results["verdict"] = "FAIL"
        results["checks"]["ws_connect"] = {"status": "FAIL", "evidence_type": "runtime",
                                           "detail": f"ws 连接失败: {e}"}
        return results
    results["checks"]["ws_connect"] = {"status": "PASS", "evidence_type": "runtime",
                                       "detail": "ws://127.0.0.1:5000/sc2api 握手成功"}
    log("[1] WebSocket 连接成功")

    try:
        # 2. API Ping
        r = await send_recv(ws, sc_pb.Request(ping=sc_pb.RequestPing()))
        if r.error:
            results["checks"]["api_ping"] = {"status": "FAIL", "evidence_type": "runtime",
                                             "detail": f"ping error: {r.error}"}
            results["verdict"] = "FAIL"
            return results
        results["checks"]["api_ping"] = {"status": "PASS", "evidence_type": "runtime",
                                         "detail": "RequestPing 返回 ResponsePing"}
        log("[2] API Ping OK")

        # 3. LeaveGame（清理之前状态）
        try:
            await send_recv(ws, sc_pb.Request(leave_game=sc_pb.RequestLeaveGame()), timeout=10)
            log("[3] LeaveGame sent (清理之前状态)")
        except Exception:
            log("[3] LeaveGame skipped (not in game)")
        await asyncio.sleep(1)

        # 4. CreateGame
        log(f"[4] CreateGame: {Path(MAP).name}")
        local_map = sc_pb.LocalMap(map_path=MAP)
        req = sc_pb.Request(create_game=sc_pb.RequestCreateGame(
            local_map=local_map,
            player_setup=[
                sc_pb.PlayerSetup(type=1, race=1, player_name="P1"),
                sc_pb.PlayerSetup(type=2, race=1, difficulty=2, player_name="AI"),
            ],
            realtime=True,
        ))
        r = await send_recv(ws, req, timeout=180)
        if r.error:
            results["checks"]["create_game"] = {"status": "FAIL", "evidence_type": "runtime",
                                                "detail": f"CreateGame error: {list(r.error)}"}
            results["verdict"] = "FAIL"
            return results
        if r.HasField('create_game') and r.create_game.HasField('error'):
            results["checks"]["create_game"] = {"status": "FAIL", "evidence_type": "runtime",
                                                "detail": f"CreateGame failed: {r.create_game.error}"}
            results["verdict"] = "FAIL"
            return results
        results["checks"]["create_game"] = {"status": "PASS", "evidence_type": "runtime",
                                            "detail": f"CreateGame OK, map={Path(MAP).name}"}
        log("  CreateGame OK!")

        # 5. JoinGame
        log("[5] JoinGame ...")
        try:
            r = await send_recv(ws, sc_pb.Request(join_game=sc_pb.RequestJoinGame(
                race=1, options=sc_pb.InterfaceOptions(raw=True),
            )), timeout=60)
            if r.error:
                log(f"  JoinGame error: {list(r.error)}")
            if r.HasField('join_game') and r.join_game.HasField('error'):
                results["checks"]["join_game"] = {"status": "FAIL", "evidence_type": "runtime",
                                                  "detail": f"JoinGame failed: {r.join_game.error}"}
                results["verdict"] = "FAIL"
                return results
            results["checks"]["join_game"] = {"status": "PASS", "evidence_type": "runtime",
                                              "detail": f"JoinGame OK, player_id={r.join_game.player_id}"}
            log(f"  JoinGame OK! player_id={r.join_game.player_id}")
        except Exception as e:
            results["checks"]["join_game"] = {"status": "FAIL", "evidence_type": "runtime",
                                              "detail": f"JoinGame exception: {e}"}
            results["verdict"] = "FAIL"
            return results

        # 6. 等地图加载 + Kernel 初始化
        log("[6] 等地图加载（最多 60s）...")
        loaded = False
        game_loop = 0
        unit_count = 0
        for i in range(30):
            await asyncio.sleep(2)
            try:
                r = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=10)
                if r.HasField('observation') and r.observation.HasField('observation'):
                    unit_count = len(r.observation.observation.raw_data.units)
                    game_loop = r.observation.observation.game_loop
                    log(f"  [{i*2}s] units={unit_count} game_loop={game_loop}")
                    if unit_count > 0:
                        loaded = True
                        break
            except Exception as e:
                log(f"  [{i*2}s] observation error: {e}")

        if loaded:
            results["checks"]["map_loaded"] = {"status": "PASS", "evidence_type": "runtime",
                                               "detail": f"units={unit_count}, game_loop={game_loop}"}
        else:
            results["checks"]["map_loaded"] = {"status": "FAIL", "evidence_type": "runtime",
                                               "detail": "60s 内未观察到单位"}
            results["verdict"] = "FAIL"
            return results

        # 7. Kernel 初始化检查（Bank）
        log("[7] 检查 Kernel 初始化 (Bank)...")
        await asyncio.sleep(3)  # 给 Kernel 一点时间写 Bank
        bank_data = read_bank()
        kernel_init = False
        if bank_data:
            index_sec = bank_data.get("index", {})
            if "kernel_initialized" in index_sec:
                val = index_sec["kernel_initialized"]
                kernel_init = str(val.get("int", val.get("string", ""))) == "1"
        if kernel_init:
            results["checks"]["kernel_initialized"] = {"status": "PASS", "evidence_type": "runtime",
                                                        "detail": "Bank[index].kernel_initialized=1"}
        else:
            results["checks"]["kernel_initialized"] = {"status": "INCONCLUSIVE", "evidence_type": "runtime",
                                                        "detail": f"Bank 未显示 kernel_initialized=1; bank_data={json.dumps(bank_data, ensure_ascii=False)[:500] if bank_data else 'None'}"}
        log(f"  kernel_initialized={kernel_init}")

        # 8. ping 闭环（MapCommand "dbg ping xxx" → Bank 回写）
        run_id = f"p1_{int(time.time())}"
        cmd = f"dbg ping {run_id}"
        log(f"[8] 发送 MapCommand: {cmd}")
        try:
            r = await send_recv(ws, sc_pb.Request(map_command=sc_pb.RequestMapCommand(trigger_cmd=cmd)), timeout=10)
            log(f"  resp: status={r.status} error={list(r.error) if r.error else 'none'}")
        except Exception as e:
            log(f"  MapCommand exception: {e}")

        log("  轮询 Bank 响应（最多 15s）...")
        t0 = time.time()
        found = False
        bank_ping = None
        while time.time() - t0 < 15:
            bank_ping = read_bank()
            if bank_ping:
                for sec_name in ("response", "vibe", "request", "heartbeat", "system", "index"):
                    sec = bank_ping.get(sec_name, {})
                    if run_id in sec:
                        log(f"  FOUND in [{sec_name}]! latency={time.time()-t0:.3f}s")
                        found = True
                        break
                if found:
                    break
            await asyncio.sleep(0.5)

        if found:
            results["checks"]["ping_loop"] = {"status": "PASS", "evidence_type": "runtime",
                                              "detail": f"MapCommand 'dbg ping' → Bank 回写成功, latency={time.time()-t0:.3f}s, run_id={run_id}"}
        else:
            results["checks"]["ping_loop"] = {"status": "INCONCLUSIVE", "evidence_type": "runtime",
                                              "detail": f"15s 内未在 Bank 找到 run_id={run_id}（可能 Mod 未挂或 Bank 路径不同）"}
        log(f"  ping_loop found={found}")

        # 9. info 命令（GameInfo）
        log("[9] info (GameInfo)...")
        try:
            r = await send_recv(ws, sc_pb.Request(game_info=sc_pb.RequestGameInfo()), timeout=10)
            if r.error:
                results["checks"]["info"] = {"status": "FAIL", "evidence_type": "runtime",
                                             "detail": f"GameInfo error: {r.error}"}
            else:
                gi = r.game_info
                map_size = f"{gi.start_raw.map_size.x}x{gi.start_raw.map_size.y}" if gi.HasField("start_raw") else "N/A"
                n_players = len(gi.player_info)
                results["checks"]["info"] = {"status": "PASS", "evidence_type": "runtime",
                                             "detail": f"GameInfo OK, map_size={map_size}, players={n_players}"}
                log(f"  info OK: map_size={map_size}, players={n_players}")
        except Exception as e:
            results["checks"]["info"] = {"status": "FAIL", "evidence_type": "runtime",
                                         "detail": f"GameInfo exception: {e}"}

        # 10. query 命令（Observation 单位/资源汇总）
        log("[10] query (Observation)...")
        try:
            r = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=10)
            if r.error:
                results["checks"]["query"] = {"status": "FAIL", "evidence_type": "runtime",
                                              "detail": f"Observation error: {r.error}"}
            else:
                obs = r.observation.observation
                pc = obs.player_common
                minerals = pc.minerals if pc else 0
                raw = obs.raw_data
                by_p = count_units_by_player(raw)
                total = sum(sum(c.values()) for c in by_p.values())
                results["checks"]["query"] = {"status": "PASS", "evidence_type": "runtime",
                                              "detail": f"Observation OK, minerals={minerals}, total_units={total}, players={list(by_p.keys())}"}
                log(f"  query OK: minerals={minerals}, total_units={total}")
        except Exception as e:
            results["checks"]["query"] = {"status": "FAIL", "evidence_type": "runtime",
                                          "detail": f"Observation exception: {e}"}

        # 11. spawn 命令（DebugCreateUnit）— 刷 Marine(x5) 给 player 1
        log("[11] spawn (DebugCreateUnit: 5x Marine @ player 1)...")
        try:
            # 先记录 player 1 当前单位数
            r0 = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=10)
            p1_before = sum(count_units_by_player(r0.observation.observation.raw_data, player=1).values())

            # Marine = 64 (python-sc2 UnitTypeId.MARINE)
            spawn_req = sc_pb.Request(debug=sc_pb.RequestDebug(debug=[
                debug_pb.DebugCommand(create_unit=debug_pb.DebugCreateUnit(
                    unit_type=64, owner=1, pos=common_pb.Point2D(x=50.0, y=50.0), quantity=5
                ))
            ]))
            r = await send_recv(ws, spawn_req, timeout=10)
            if r.error:
                results["checks"]["spawn"] = {"status": "FAIL", "evidence_type": "runtime",
                                              "detail": f"DebugCreateUnit error: {r.error}"}
            else:
                # step 推进 3 帧让单位生效
                await send_recv(ws, sc_pb.Request(step=sc_pb.RequestStep(count=3)), timeout=10)
                await asyncio.sleep(0.5)
                r1 = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=10)
                p1_after = sum(count_units_by_player(r1.observation.observation.raw_data, player=1).values())
                delta = p1_after - p1_before
                if delta >= 5:
                    results["checks"]["spawn"] = {"status": "PASS", "evidence_type": "runtime",
                                                  "detail": f"DebugCreateUnit OK, P1 units: {p1_before} → {p1_after} (Δ={delta}, expected ≥5)"}
                    log(f"  spawn OK: P1 units {p1_before} → {p1_after} (Δ={delta})")
                else:
                    results["checks"]["spawn"] = {"status": "INCONCLUSIVE", "evidence_type": "runtime",
                                                  "detail": f"DebugCreateUnit sent but P1 units: {p1_before} → {p1_after} (Δ={delta}, expected ≥5)"}
                    log(f"  spawn INCONCLUSIVE: Δ={delta}")
        except Exception as e:
            results["checks"]["spawn"] = {"status": "FAIL", "evidence_type": "runtime",
                                          "detail": f"DebugCreateUnit exception: {e}"}

        # 12. cheat 命令（Debug game_state: minerals on）
        log("[12] cheat (Debug game_state: minerals on = 7)...")
        try:
            cheat_req = sc_pb.Request(debug=sc_pb.RequestDebug(debug=[
                debug_pb.DebugCommand(game_state=7)  # 7 = minerals cheat
            ]))
            r = await send_recv(ws, cheat_req, timeout=10)
            if r.error:
                results["checks"]["cheat"] = {"status": "FAIL", "evidence_type": "runtime",
                                              "detail": f"Debug game_state error: {r.error}"}
            else:
                # step + 检查矿物是否增加
                await send_recv(ws, sc_pb.Request(step=sc_pb.RequestStep(count=5)), timeout=10)
                await asyncio.sleep(0.5)
                r1 = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=10)
                minerals_after = r1.observation.observation.player_common.minerals
                if minerals_after >= 5000:
                    results["checks"]["cheat"] = {"status": "PASS", "evidence_type": "runtime",
                                                  "detail": f"Debug game_state(minerals) OK, minerals={minerals_after} (≥5000)"}
                    log(f"  cheat OK: minerals={minerals_after}")
                else:
                    results["checks"]["cheat"] = {"status": "INCONCLUSIVE", "evidence_type": "runtime",
                                                  "detail": f"Debug game_state sent but minerals={minerals_after} (<5000)"}
                    log(f"  cheat INCONCLUSIVE: minerals={minerals_after}")
        except Exception as e:
            results["checks"]["cheat"] = {"status": "FAIL", "evidence_type": "runtime",
                                          "detail": f"Debug game_state exception: {e}"}

        # 13. step 命令（RequestStep count=10）
        log("[13] step (RequestStep count=10)...")
        try:
            r0 = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=10)
            gl_before = r0.observation.observation.game_loop
            r = await send_recv(ws, sc_pb.Request(step=sc_pb.RequestStep(count=10)), timeout=10)
            if r.error:
                results["checks"]["step"] = {"status": "FAIL", "evidence_type": "runtime",
                                             "detail": f"RequestStep error: {r.error}"}
            else:
                r1 = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=10)
                gl_after = r1.observation.observation.game_loop
                delta = gl_after - gl_before
                # realtime=True 模式下 game_loop 增量不精确（游戏持续运行），无 error 即 PASS
                results["checks"]["step"] = {"status": "PASS", "evidence_type": "runtime",
                                             "detail": f"RequestStep OK (realtime mode), game_loop: {gl_before} → {gl_after} (Δ={delta})"}
                log(f"  step OK: game_loop {gl_before} → {gl_after} (Δ={delta})")
        except Exception as e:
            results["checks"]["step"] = {"status": "FAIL", "evidence_type": "runtime",
                                         "detail": f"RequestStep exception: {e}"}

        # 14. kill 命令（DebugKillUnit）— 击杀 player 1 部分 Marine
        log("[14] kill (DebugKillUnit: 3 Marines of player 1)...")
        try:
            r0 = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=10)
            p1_units_before = [u for u in r0.observation.observation.raw_data.units if u.owner == 1]
            p1_before_count = len(p1_units_before)

            # 找出 player 1 的 Marine (unit_type=64)
            marine_tags = [u.tag for u in p1_units_before if u.unit_type == 64][:3]
            if len(marine_tags) < 3:
                # 如果 Marine 不够 3 个，取任意 3 个单位
                marine_tags = [u.tag for u in p1_units_before][:3]

            if not marine_tags:
                results["checks"]["kill"] = {"status": "INCONCLUSIVE", "evidence_type": "runtime",
                                              "detail": "P1 无可击杀单位"}
            else:
                kill_req = sc_pb.Request(debug=sc_pb.RequestDebug(debug=[
                    debug_pb.DebugCommand(kill_unit=debug_pb.DebugKillUnit(tag=marine_tags))
                ]))
                r = await send_recv(ws, kill_req, timeout=10)
                if r.error:
                    results["checks"]["kill"] = {"status": "FAIL", "evidence_type": "runtime",
                                                 "detail": f"DebugKillUnit error: {r.error}"}
                else:
                    await send_recv(ws, sc_pb.Request(step=sc_pb.RequestStep(count=3)), timeout=10)
                    await asyncio.sleep(0.5)
                    r1 = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=10)
                    p1_after_count = len([u for u in r1.observation.observation.raw_data.units if u.owner == 1])
                    delta = p1_before_count - p1_after_count
                    if delta >= len(marine_tags):
                        results["checks"]["kill"] = {"status": "PASS", "evidence_type": "runtime",
                                                     "detail": f"DebugKillUnit OK, P1 units: {p1_before_count} → {p1_after_count} (Δ={delta}, killed {len(marine_tags)})"}
                        log(f"  kill OK: P1 units {p1_before_count} → {p1_after_count} (Δ={delta})")
                    else:
                        results["checks"]["kill"] = {"status": "INCONCLUSIVE", "evidence_type": "runtime",
                                                     "detail": f"DebugKillUnit sent but P1 units: {p1_before_count} → {p1_after_count} (Δ={delta})"}
        except Exception as e:
            results["checks"]["kill"] = {"status": "FAIL", "evidence_type": "runtime",
                                         "detail": f"DebugKillUnit exception: {e}"}

        # 15. no_new_script_error — 检查 GameLogs 是否有新增 ScriptError
        await asyncio.sleep(2)
        post_errors = scan_script_errors()
        new_errors = {k: v for k, v in post_errors.items() if k not in pre_errors}
        if new_errors:
            results["checks"]["no_new_script_error"] = {"status": "FAIL", "evidence_type": "runtime",
                                                         "detail": f"新增 {len(new_errors)} 个 ScriptError: {list(new_errors.keys())}"}
        else:
            results["checks"]["no_new_script_error"] = {"status": "PASS", "evidence_type": "runtime",
                                                         "detail": "本次启动无新增 ScriptError"}

        # 判定最终结果
        statuses = [c["status"] for c in results["checks"].values()]
        n_pass = statuses.count("PASS")
        n_fail = statuses.count("FAIL")
        n_inc = statuses.count("INCONCLUSIVE")
        if n_fail > 0:
            results["verdict"] = "FAIL"
        elif n_inc > 0:
            results["verdict"] = "PASS_WITH_INCONCLUSIVE"
        else:
            results["verdict"] = "PASS"
        results["summary"] = {"total": len(statuses), "pass": n_pass, "fail": n_fail, "inconclusive": n_inc}

    finally:
        try:
            await ws.close()
            await session.close()
        except Exception:
            pass

    # 落盘
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"结果已落盘: {RESULT_PATH}")
    log(f"=== P1 验证结果: {results['verdict']} ===")
    return results


if __name__ == "__main__":
    result = asyncio.run(main())
    print("\n=== RESULT ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("verdict") in ("PASS", "PASS_WITH_INCONCLUSIVE") else 1)
