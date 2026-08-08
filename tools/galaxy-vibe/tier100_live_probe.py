#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tier100_live_probe.py — tier100 真机验证：function.invoke / gen.* 派发到真机原生

单连接、自包含：连已运行 SC2（ws://127.0.0.1:<port>/sc2api）→ 加载 Vibe Kernel 地图
（VibeDeadOfNight.SC2Map，字节直传，绕开 Maps 目录与账号态）→ join → 轮询 Bank 标记
kernel_initialized（证明 Kernel 自注册 / PollLoop 运行）→ 经 Bank-poll RPC 真实调用：

  ① system.ping          → 传输闭环（Kernel 写回 pong）
  ② vibe.unit.spawn      → 刷一个 Marine，证明 vibe.* handler 真实执行
  ③ SC2 raw observation  → 第三方独立观测：玩家1 单位 +1（绕开 Bank/Kernel 自述）
  ④ vibe.query.units     → Kernel 自查：数出的数量与 ③ 一致
  ⑤ function.invoke gen.1 → 代表型 gen.*（AIAbilityFixed）：对刷出的 Marine 发 Stop 指令，
                            证明生成 adapter 派发到真机原生且执行（带副作用）
  ⑥ function.invoke gen.<noarg> → 无参 gen.* 兜底派发证明

写 tier100-live-verdict.json 并打印。判定 tier100_pass = ①②③④ + (⑤ 或 ⑥)。

前置：SC2 已以 API 模式启动（SC2Switcher_x64.exe -listen 127.0.0.1 -port <port> -debug），
处于菜单态。本脚本自己 create_game，不自备地图。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe"))
sys.path.insert(0, str(REPO_ROOT / "src" / "projects" / "cmre-porting"))

from s2clientprotocol import sc2api_pb2 as sc_pb  # noqa: E402
from s2clientprotocol import common_pb2 as sc_common  # noqa: E402
import aiohttp  # noqa: E402
from host.vibe_host import (  # noqa: E402
    read_bank, write_bank_request, RpcRequest, DEFAULT_BANK_DIR,
)

BANK_NAME = "GalaxyVibe"
DEFAULT_MAP = r"E:/SC2/SC2new/StarCraft II/Maps/VibeDeadOfNight.SC2Map"
# 一个无参 gen.*（StartHeartbeat，不依赖任何外部状态，纯派发证明）
NOARG_GEN = "gen.11800"
REG_MARKERS = ["kernel_initialized", "register_entrypoints_done"]

# 计划强制：每个 runtime 结论必须带同窗口 ScriptError verdict。
GAMELOGS_DIR = Path.home() / "Documents" / "StarCraft II" / "GameLogs"


def _script_error_files_since(since: float) -> list[str]:
    """返回 since 之后新增的非空 *ScriptError*.txt（同窗口门）。"""
    if not GAMELOGS_DIR.exists():
        return []
    out = []
    for p in GAMELOGS_DIR.rglob("*ScriptError*.txt"):
        try:
            if p.stat().st_mtime >= since and p.stat().st_size > 0:
                out.append(str(p))
        except OSError:
            continue
    return sorted(out)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sub_err(resp, field: str):
    """proto2 optional enum 坑：未设置读出默认首项=1；仅 HasField 可靠。"""
    if not resp.HasField(field):
        return None
    sub = getattr(resp, field)
    if not sub.HasField("error"):
        return None
    return int(sub.error)


async def a_main(opts) -> dict:
    out = {
        "schemaVersion": 1,
        "generatedAt": utcnow(),
        "port": opts.port,
        "map": opts.map,
        "probes": {},
        "calls": {},
        "verdict": {"connect": False, "kernel_registered": False,
                    "p0_pass": False, "tier100_pass": False},
        "errors": [],
    }
    api_url = f"ws://127.0.0.1:{opts.port}/sc2api"
    map_path = Path(opts.map)
    if not map_path.is_file():
        out["errors"].append(f"map not found: {map_path}")
        return out
    md = map_path.read_bytes()
    out["map_bytes"] = len(md)

    async def _send(ws, req):
        await ws.send_bytes(req.SerializeToString())
        data = await asyncio.wait_for(ws.receive_bytes(), timeout=30)
        if isinstance(data, str):
            data = data.encode("utf-8")
        resp = sc_pb.Response()
        resp.ParseFromString(data)
        return resp

    async with aiohttp.ClientSession(trust_env=False,
                                     timeout=aiohttp.ClientTimeout(total=300)) as sess:
        try:
            ws = await asyncio.wait_for(
                sess.ws_connect(api_url, max_msg_size=0), timeout=15)
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"ws_connect failed: {e}")
            return out
        out["verdict"]["connect"] = True

        # ping
        try:
            await _send(ws, sc_pb.Request(ping=sc_pb.RequestPing()))
            out["probes"]["ping"] = True
        except Exception as e:  # noqa: BLE001
            out["probes"]["ping"] = False
            out["errors"].append(f"ping failed: {e}")

        # ---- create_game（自加载 Vibe Kernel 地图）----
        window_start = time.time()  # 同窗口 ScriptError 门起点
        r = await _send(ws, sc_pb.Request(create_game=sc_pb.RequestCreateGame(
            local_map=sc_pb.LocalMap(map_data=md),
            player_setup=[sc_pb.PlayerSetup(type=1, race=sc_common.Terran,
                                            player_name="P1")],
            realtime=True)))
        cg_err = _sub_err(r, "create_game")
        out["probes"]["create_game"] = {
            "top_error": [int(e) for e in r.error] if r.error else [],
            "sub_error": cg_err}
        if r.error or cg_err is not None:
            out["errors"].append(f"create_game failed: top={r.error} sub={cg_err}")
            return out

        await asyncio.sleep(3.0)  # init_game 完成再 join，避免 ws 竞态
        r = await _send(ws, sc_pb.Request(join_game=sc_pb.RequestJoinGame(
            race=sc_common.Terran, options=sc_pb.InterfaceOptions(raw=True))))
        jg_err = _sub_err(r, "join_game")
        out["probes"]["join_game"] = {
            "top_error": [int(e) for e in r.error] if r.error else [],
            "sub_error": jg_err,
            "player_id": getattr(r.join_game, "player_id", None)}
        if r.error or jg_err is not None:
            out["errors"].append(f"join_game failed: top={r.error} sub={jg_err}")
            return out

        # 单位类型名
        data = await _send(ws, sc_pb.Request(
            data=sc_pb.RequestData(unit_type_id=True)))
        names = {u.unit_id: u.name for u in data.data.units}

        async def owned_counts(player: int) -> dict[str, int]:
            o = await _send(ws, sc_pb.Request(
                observation=sc_pb.RequestObservation()))
            cnt: dict[str, int] = {}
            for u in o.observation.observation.raw_data.units:
                if u.owner != player:
                    continue
                n = names.get(u.unit_type, str(u.unit_type))
                cnt[n] = cnt.get(n, 0) + 1
            return cnt

        # ---- 轮询 Kernel 注册标记 ----
        reg_seen = {}
        for _ in range(200):  # ~40s
            if (DEFAULT_BANK_DIR / f"{BANK_NAME}.SC2Bank").exists():
                bk = read_bank(BANK_NAME)
                for mk in REG_MARKERS:
                    v = bk.get("index", {}).get(mk)
                    if v is not None:
                        try:
                            if int(v) == 1:
                                reg_seen[mk] = 1
                        except (TypeError, ValueError):
                            pass
            if reg_seen:
                break
            await asyncio.sleep(0.2)
        out["probes"]["registration"] = reg_seen
        out["verdict"]["kernel_registered"] = bool(reg_seen)
        if not reg_seen:
            out["verdict"]["note"] = "Kernel 未注册：Bank 无 kernel_initialized。" \
                "Vibe Kernel 地图可能未编译 RegisterEntryPoints，或 BankLoad 缓存(CMRE-RUNTIME-003)。"
            return out

        # ---- bank-poll RPC 工具 ----
        async def bank_call(operation, args, timeout=12.0):
            rid = f"t100_{operation.replace('.','_')}_{int(time.time()*1000)}_{os.getpid()}"
            req = RpcRequest(session_id="tier100", request_id=rid, sequence=1,
                             operation=operation, args=args)
            if not write_bank_request(BANK_NAME, rid, req, player=1):
                return {"ok": False, "error": "write_bank_request failed"}
            t0 = time.time()
            while time.time() - t0 < timeout:
                raw = read_bank(BANK_NAME).get("response", {}).get(rid)
                if raw:
                    return {"ok": True, "raw": raw,
                            "latency": round(time.time() - t0, 3)}
                await asyncio.sleep(0.1)
            return {"ok": False, "error": "timeout waiting response", "rid": rid}

        # ① system.ping
        pings, acks = 0, 0
        for _ in range(opts.runs):
            res = await bank_call("system.ping", {}, timeout=8.0)
            if res.get("ok") and '"pong":true' in res.get("raw", ""):
                acks += 1
            pings += 1
        out["calls"]["system_ping"] = {"runs": pings, "acks": acks,
                                       "all_ack": acks == pings}

        # ② vibe.unit.spawn（刷 Marine）
        before = await owned_counts(1)
        spawn = await bank_call("unit.spawn",
                                {"count": "1", "player": "1",
                                 "unit_type": "Marine", "x": "10", "y": "10"},
                                timeout=12.0)
        out["calls"]["vibe_unit_spawn"] = spawn
        tag = None
        if spawn.get("ok"):
            try:
                j = json.loads(spawn["raw"])
                uv = j.get("payload", {}).get("value")
                if isinstance(uv, str):
                    uv = json.loads(uv)
                tag = (uv or {}).get("unit_tag")
            except Exception:  # noqa: BLE001
                pass

        # ③ SC2 raw observation（第三方观测）
        await asyncio.sleep(1.0)
        after = await owned_counts(1)
        got = after.get("Marine", 0) - before.get("Marine", 0)
        out["calls"]["observation_delta"] = {
            "before_marine": before.get("Marine", 0),
            "after_marine": after.get("Marine", 0),
            "delta": got, "tag": tag}
        p1b = got >= 1

        # ④ vibe.query.units（Kernel 自查）
        q = await bank_call("query.units", {"player": "1", "unit_type": "Marine"},
                            timeout=12.0)
        kcount = None
        if q.get("ok"):
            try:
                kcount = json.loads(q["raw"]).get("payload", {}).get("count")
            except Exception:  # noqa: BLE001
                pass
        out["calls"]["vibe_query_units"] = q
        p1c = (kcount is not None and kcount == after.get("Marine", 0))

        # ⑤ function.invoke gen.1（代表型，对刷出 Marine 发 Stop）
        gen1_args = {"function_id": "gen.1",
                     "args": {"p0": 1, "p1": "Stop", "p2": str(tag or 0)}}
        g1 = await bank_call("function.invoke", gen1_args, timeout=15.0)
        out["calls"]["gen_1_invoke"] = g1
        g1_ok = False
        if g1.get("ok"):
            try:
                g1_ok = (json.loads(g1["raw"]).get("error_code") == "OK")
            except Exception:  # noqa: BLE001
                pass

        # ⑥ function.invoke gen.<noarg>（兜底派发证明）
        gen0_args = {"function_id": NOARG_GEN, "args": {}}
        g0 = await bank_call("function.invoke", gen0_args, timeout=15.0)
        out["calls"]["gen_noarg_invoke"] = {"fid": NOARG_GEN, **g0}
        g0_ok = False
        if g0.get("ok"):
            try:
                g0_ok = (json.loads(g0["raw"]).get("error_code") == "OK")
            except Exception:  # noqa: BLE001
                pass

        out["verdict"]["gen_1_ok"] = bool(g1_ok)
        out["verdict"]["gen_noarg_ok"] = bool(g0_ok)
        # 计划强制：同窗口 ScriptError 门（create_game 之后新增的非空 ScriptError）
        se = _script_error_files_since(window_start)
        out["verdict"]["script_error"] = {
            "gate": "no_new_nonempty" if not se else "FAILED",
            "files": se,
        }
        out["verdict"]["p0_pass"] = (
            out["calls"]["system_ping"]["all_ack"] and spawn.get("ok")
            and p1b and p1c)
        out["verdict"]["tier100_pass"] = (
            out["verdict"]["p0_pass"] and (g1_ok or g0_ok)
            and not se)
        ok_chain = "gen.1(AIAbilityFixed 副作用)" if g1_ok else (
            f"{NOARG_GEN}(无参兜底)" if g0_ok else "NONE")
        if out["verdict"]["tier100_pass"]:
            out["verdict"]["note"] = (
                f"tier100 真机闭环：Kernel 已注册 + system.ping 闭环 + vibe.unit.spawn "
                f"经 SC2 观测确认(+{got} Marine) + Kernel 自查一致(count={kcount}) + "
                f"function.invoke/gen.* 派发到真机原生成功（{ok_chain}）")
        else:
            not_in_map = "FUNCTION_NOT_IN_MAP" in (g1.get("raw", "") + g0.get("raw", ""))
            out["verdict"]["note"] = (
                "transport + function.invoke 路由已实证（Kernel 收到 gen.* 并返回结构化响应），"
                "但当前地图未挂载生成 adapter 包（gen.* 返回 FUNCTION_NOT_IN_MAP），"
                "gen.* 真机原生执行未达成；需加载带 -InvokeTier 生成包的地图。"
                if not_in_map else
                "部分环节未达成，见 calls。")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--map", default=DEFAULT_MAP)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out-dir",
                    default=str(REPO_ROOT / "artifacts" / "galaxy-vibe"))
    a = ap.parse_args()
    res = asyncio.run(a_main(a))
    o = Path(a.out_dir)
    o.mkdir(parents=True, exist_ok=True)
    p = o / "tier100-live-verdict.json"
    p.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    rc = 0 if res.get("verdict", {}).get("tier100_pass") else (
        1 if res.get("verdict", {}).get("connect") else 2)
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
