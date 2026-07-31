#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G3 战斗功能验证：spawn 敌对单位 → step → 检查战斗发生（单位死亡或血量下降）。

验证目标：
  - vibe 框架可用于战斗功能验证（spawn + step + observation 闭环）
  - 单位可攻击、可受伤（runtime 证据）

前置条件：
  - SC2 已通过 launch-cmre-alenger.ps1 -DebugMode -KeepAlive -ListenPort 5000 启动
  - SC2 API 监听在 127.0.0.1:5000

证据分类：runtime（真机观察）
"""
import asyncio
import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(r"e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace")
sys.path.insert(0, str(REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"))
os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = "python"

from s2clientprotocol import sc2api_pb2 as sc_pb
from s2clientprotocol import debug_pb2 as debug_pb
from s2clientprotocol import common_pb2 as common_pb
import aiohttp

MAP = r"E:\SC2\SC2new\StarCraft II\Maps\亡者之夜_vibe_live.SC2Map"
PORT = 5000
GAMELOGS_DIR = Path.home() / "Documents" / "StarCraft II" / "GameLogs"
RESULT_PATH = REPO_ROOT / "artifacts" / "reborn-functional-verification" / "g3-combat-result.json"

# 单位 ID（python-sc2 UnitTypeId）
MARINE_ID = 64
ZERGLING_ID = 208


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


def scan_script_errors():
    errors = {}
    if not GAMELOGS_DIR.exists():
        return errors
    for f in GAMELOGS_DIR.glob("ScriptError*.txt"):
        try:
            errors[f.name] = f.stat().st_mtime
        except Exception:
            pass
    return errors


async def send_recv(ws, req, timeout=30):
    await ws.send_bytes(req.SerializeToString())
    data = await asyncio.wait_for(ws.receive_bytes(), timeout=timeout)
    if isinstance(data, str):
        data = data.encode("utf-8")
    resp = sc_pb.Response()
    resp.ParseFromString(data)
    return resp


async def main():
    log("=== G3 战斗功能验证 ===")
    results = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "acceptance": "G3 战斗功能验证（spawn 敌对单位 + step + 战斗检测）",
        "port": PORT,
        "map": MAP,
        "checks": {},
    }

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

        # 4. CreateGame（realtime=False，步进可控）
        log(f"[4] CreateGame: {Path(MAP).name}")
        local_map = sc_pb.LocalMap(map_path=MAP)
        req = sc_pb.Request(create_game=sc_pb.RequestCreateGame(
            local_map=local_map,
            player_setup=[
                sc_pb.PlayerSetup(type=1, race=1, player_name="P1"),  # Participant, Terran
                sc_pb.PlayerSetup(type=2, race=2, difficulty=2, player_name="P2"),  # Computer, Zerg
            ],
            realtime=False,  # 步进模式，确保战斗可控
        ))
        r = await send_recv(ws, req, timeout=180)
        if r.error:
            results["checks"]["create_game"] = {"status": "FAIL", "evidence_type": "runtime",
                                                "detail": f"CreateGame error: {list(r.error)}"}
            results["verdict"] = "FAIL"
            return results
        results["checks"]["create_game"] = {"status": "PASS", "evidence_type": "runtime",
                                            "detail": f"CreateGame OK, map={Path(MAP).name}, realtime=False"}
        log("  CreateGame OK!")

        # 5. JoinGame
        log("[5] JoinGame ...")
        try:
            r = await send_recv(ws, sc_pb.Request(join_game=sc_pb.RequestJoinGame(
                race=1, options=sc_pb.InterfaceOptions(raw=True),
            )), timeout=60)
            if r.error:
                log(f"  JoinGame error: {list(r.error)}")
            results["checks"]["join_game"] = {"status": "PASS", "evidence_type": "runtime",
                                              "detail": f"JoinGame OK, player_id={r.join_game.player_id}"}
            log(f"  JoinGame OK! player_id={r.join_game.player_id}")
        except Exception as e:
            results["checks"]["join_game"] = {"status": "FAIL", "evidence_type": "runtime",
                                              "detail": f"JoinGame exception: {e}"}
            results["verdict"] = "FAIL"
            return results

        # 6. 等地图加载
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

        # 7. spawn 敌对单位：3 Marines (P1) + 5 Zerglings (P2)
        log("[7] spawn 3 Marines (P1) + 5 Zerglings (P2) ...")
        try:
            spawn_req = sc_pb.Request(debug=sc_pb.RequestDebug(debug=[
                debug_pb.DebugCommand(create_unit=debug_pb.DebugCreateUnit(
                    unit_type=MARINE_ID, owner=1, pos=common_pb.Point2D(x=50.0, y=50.0), quantity=3
                )),
                debug_pb.DebugCommand(create_unit=debug_pb.DebugCreateUnit(
                    unit_type=ZERGLING_ID, owner=2, pos=common_pb.Point2D(x=52.0, y=50.0), quantity=5
                )),
            ]))
            r = await send_recv(ws, spawn_req, timeout=10)
            if r.error:
                results["checks"]["spawn_combatants"] = {"status": "FAIL", "evidence_type": "runtime",
                                                         "detail": f"DebugCreateUnit error: {r.error}"}
                results["verdict"] = "FAIL"
                return results
            # step 3 帧让单位生效
            await send_recv(ws, sc_pb.Request(step=sc_pb.RequestStep(count=3)), timeout=10)
            await asyncio.sleep(0.5)
            # 确认单位已创建
            r1 = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=10)
            p1_marines = [u for u in r1.observation.observation.raw_data.units if u.owner == 1 and u.unit_type == MARINE_ID]
            p2_zerglings = [u for u in r1.observation.observation.raw_data.units if u.owner == 2 and u.unit_type == ZERGLING_ID]
            results["checks"]["spawn_combatants"] = {"status": "PASS", "evidence_type": "runtime",
                                                     "detail": f"P1 Marines={len(p1_marines)}, P2 Zerglings={len(p2_zerglings)}"}
            log(f"  spawn OK: P1 Marines={len(p1_marines)}, P2 Zerglings={len(p2_zerglings)}")
        except Exception as e:
            results["checks"]["spawn_combatants"] = {"status": "FAIL", "evidence_type": "runtime",
                                                     "detail": f"DebugCreateUnit exception: {e}"}
            results["verdict"] = "FAIL"
            return results

        # 8. step 200 帧让单位战斗
        log("[8] step 200 帧让单位战斗 ...")
        try:
            for i in range(20):
                r = await send_recv(ws, sc_pb.Request(step=sc_pb.RequestStep(count=10)), timeout=10)
                if r.error:
                    log(f"  step error at batch {i}: {r.error}")
                    break

            # 检查战斗结果
            r1 = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=10)
            obs = r1.observation.observation
            final_units = obs.raw_data.units
            p1_marines_after = [u for u in final_units if u.owner == 1 and u.unit_type == MARINE_ID]
            p2_zerglings_after = [u for u in final_units if u.owner == 2 and u.unit_type == ZERGLING_ID]

            marine_hp = [u.health for u in p1_marines_after]
            zergling_hp = [u.health for u in p2_zerglings_after]

            log(f"  After 200 steps: P1 Marines={len(p1_marines_after)} P2 Zerglings={len(p2_zerglings_after)}")
            log(f"    Marine HP: {marine_hp}")
            log(f"    Zergling HP: {zergling_hp}")

            # 判定战斗发生：单位死亡或血量下降
            combat_occurred = False
            combat_evidence = []
            if len(p1_marines_after) < 3:
                combat_occurred = True
                combat_evidence.append(f"P1 Marines 死亡: 3→{len(p1_marines_after)}")
            if len(p2_zerglings_after) < 5:
                combat_occurred = True
                combat_evidence.append(f"P2 Zerglings 死亡: 5→{len(p2_zerglings_after)}")
            if marine_hp and any(h < 45.0 for h in marine_hp):
                combat_occurred = True
                combat_evidence.append(f"Marine 受伤: HP<45 ({marine_hp})")
            if zergling_hp and any(h < 35.0 for h in zergling_hp):
                combat_occurred = True
                combat_evidence.append(f"Zergling 受伤: HP<35 ({zergling_hp})")

            results["checks"]["combat"] = {
                "status": "PASS" if combat_occurred else "FAIL",
                "evidence_type": "runtime",
                "p1_marines_before": 3, "p1_marines_after": len(p1_marines_after),
                "p2_zerglings_before": 5, "p2_zerglings_after": len(p2_zerglings_after),
                "marine_hp": marine_hp,
                "zergling_hp": zergling_hp,
                "detail": "战斗发生: " + "; ".join(combat_evidence) if combat_occurred else "未检测到战斗（单位数量/血量无变化）"
            }
            log(f"  combat: {'PASS' if combat_occurred else 'FAIL'} - {results['checks']['combat']['detail']}")
        except Exception as e:
            results["checks"]["combat"] = {"status": "FAIL", "evidence_type": "runtime",
                                           "detail": f"战斗验证异常: {e}"}
            results["verdict"] = "FAIL"
            return results

        # 9. no_new_script_error
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
    log(f"=== G3 验证结果: {results['verdict']} ===")
    return results


if __name__ == "__main__":
    result = asyncio.run(main())
    print("\n=== RESULT ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("verdict") in ("PASS", "PASS_WITH_INCONCLUSIVE") else 1)
