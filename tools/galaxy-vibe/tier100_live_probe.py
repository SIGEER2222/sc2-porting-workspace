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
  ⑤ function.invoke gen.1 → 代表型 gen.*（AIAbilityFixed(int,string,string)->fixed）：
                            带参派发 + 返回值回传，证明生成 adapter 真机执行。
                            注：这是**只读 catalog 查询**，无副作用（旧注释写"对 Marine
                            发 Stop 指令、带副作用"是错的，AIAbilityFixed 不下指令）。
  ⑥ function.invoke gen.<noarg> → 无参只读 getter 兜底派发证明（编号动态选取，
                            见 pick_noarg_gen；写死编号会随重新生成漂移失效）

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
    read_bank, write_bank_request, bank_request_landed, RpcRequest, DEFAULT_BANK_DIR,
)

BANK_NAME = "GalaxyVibe"
DEFAULT_MAP = r"E:/SC2/SC2new/StarCraft II/Maps/VibeDeadOfNight.SC2Map"
REG_MARKERS = ["kernel_initialized", "register_entrypoints_done"]

# 【2026-08-08 修】gen.N 编号会随每次重新生成整体重排，写死编号必然漂移失效。
# 事故：原 NOARG_GEN = "gen.11800"（StartHeartbeat），在 callable 收紧到 11795 之后
# 已越界不存在，第 ⑥ 步永远返回 UNKNOWN_FUNCTION —— 而这是个"静默降级"：兜底证明
# 失效但探针照样跑完，只在 g1 也失败时才暴露。改为从 invoke-plan.json 按**函数形状**
# 动态选取，并允许 --noarg-gen 显式覆盖。
INVOKE_PLAN = (REPO_ROOT / "artifacts" / "projects" / "cmre-porting"
               / "stage26-full-function-invoke" / "invoke-plan.json")
# plan 不可读时的保底（仍可能漂移，故仅作最后退路，选取失败会被显式记录）。
NOARG_GEN_FALLBACK = "gen.211"


def pick_noarg_gen(plan_path: Path = INVOKE_PLAN) -> tuple[str, str]:
    """从 invoke-plan 选一个"无参 + 有返回值 + basic 返回类"的 gen.*。

    选无参**有返回值**的只读 getter，而不是无参 void：
      - 返回值本身就是"函数体真的跑了并把值回传"的证据；void 只能证明"没报错"。
      - getter 天然零副作用，不污染真机对局状态（探针铁律：只读、不改局）。
    返回 (function_id, 说明)。
    """
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return NOARG_GEN_FALLBACK, f"plan 不可读({e})，回退常量"
    cands = [f for f in plan.get("functions", [])
             if not f.get("params")
             and f.get("return_type") not in (None, "void")
             and f.get("return_class") == "basic"]
    if not cands:
        return NOARG_GEN_FALLBACK, "plan 中无无参 getter，回退常量"

    def _rank(f: dict) -> tuple:
        name = f["name"]
        # 名字语义门：Get*/Is*/Has*/Num*/Count* 才是可证明零副作用的纯读取。
        # 反例 AIChooseSubState —— 返回 int 但 "Choose" 暗示会改 AI 状态机，
        # 探针铁律要求不改真机对局状态，这类必须排在后面。
        pure = any(t in name for t in ("Get", "Total", "Num", "Count", "Is", "Has"))
        return (pure, len(f.get("available_in") or []), -f["id"])

    best = max(cands, key=_rank)
    pure = _rank(best)[0]
    return best["function_id"], (
        f"{best['name']} -> {best['return_type']}（无参"
        f"{'纯只读 getter' if pure else '返回值函数(语义未证纯读)'}，"
        f"scope={len(best.get('available_in') or [])}）")

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
    if not (map_path.is_file() or map_path.is_dir()):
        out["errors"].append(f"map not found: {map_path}")
        return out
    # 单文件 .SC2Map -> map_data 字节；解包目录地图 -> map_path（SC2 本地读取）
    is_dir_map = map_path.is_dir()
    md = map_path.read_bytes() if not is_dir_map else b""
    out["map_bytes"] = len(md) if md else -1
    out["map_is_dir"] = is_dir_map

    async def _send(ws, req, timeout: float = 30):
        # 【2026-08-08 修】join_game 对"大图"会超过 30s：F1 图 5.4MB、内含上万个
        # gen.* adapter，SC2 要完整编译整张 MapScript 才返回 join。原硬编码 30s 会
        # 在编译途中抛 TimeoutError，看起来像"地图坏了"，实际只是探针没等够 ——
        # 典型的把"慢"误判成"死"。故 create_game / join_game 单独放宽。
        await ws.send_bytes(req.SerializeToString())
        data = await asyncio.wait_for(ws.receive_bytes(), timeout=timeout)
        if isinstance(data, str):
            data = data.encode("utf-8")
        resp = sc_pb.Response()
        resp.ParseFromString(data)
        return resp

    # total=None：会话总时长不设限，超时全部由每次 _send 的显式 timeout 控制。
    # 否则 session 级 300s 会先于 load_timeout 触发，超时归因错乱。
    async with aiohttp.ClientSession(trust_env=False,
                                     timeout=aiohttp.ClientTimeout(total=None)) as sess:
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

        # 【2026-08-08】fresh-bank：kernel_initialized 是 Bank 持久 key，会跨地图
        # 加载残留 —— 即便新地图 MapScript 被 SC2 静默丢弃（编译失败），旧值仍在，
        # 导致 kernel_registered 假阳性。--fresh-bank 在 create_game 前把 Bank 文件
        # 移走，使 "标记出现" 成为 "本次加载确实编译并运行了内核" 的无歧义证据。
        if getattr(opts, "fresh_bank", False):
            bp = DEFAULT_BANK_DIR / f"{BANK_NAME}.SC2Bank"
            if bp.exists():
                arch = bp.with_suffix(f".SC2Bank.stale-{int(time.time())}")
                bp.replace(arch)
                out["probes"]["fresh_bank"] = {"archived": str(arch)}
            else:
                out["probes"]["fresh_bank"] = {"archived": None}

        local_map = sc_pb.LocalMap()
        if is_dir_map:
            local_map.map_path = str(map_path)
        else:
            local_map.map_data = md
        r = await _send(ws, sc_pb.Request(create_game=sc_pb.RequestCreateGame(
            local_map=local_map,
            player_setup=[sc_pb.PlayerSetup(type=1, race=sc_common.Terran,
                                            player_name="P1")],
            realtime=True)), timeout=opts.load_timeout)
        cg_err = _sub_err(r, "create_game")
        out["probes"]["create_game"] = {
            "top_error": [int(e) for e in r.error] if r.error else [],
            "sub_error": cg_err}
        if r.error or cg_err is not None:
            out["errors"].append(f"create_game failed: top={r.error} sub={cg_err}")
            return out

        await asyncio.sleep(3.0)  # init_game 完成再 join，避免 ws 竞态
        r = await _send(ws, sc_pb.Request(join_game=sc_pb.RequestJoinGame(
            race=sc_common.Terran, options=sc_pb.InterfaceOptions(raw=True))),
            timeout=opts.load_timeout)
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
        # 宽限轮询：kernel_initialized 先到，register_entrypoints_done 由 watchdog
        # 稍后写入；多等 6s 把两个标记都收全，便于区分"编译成功但注册未完成"。
        if reg_seen and len(reg_seen) < len(REG_MARKERS):
            for _ in range(30):
                bk = read_bank(BANK_NAME)
                for mk in REG_MARKERS:
                    v = bk.get("index", {}).get(mk)
                    if v is not None and str(v).strip() in {"1", "1.0"}:
                        reg_seen[mk] = 1
                if len(reg_seen) == len(REG_MARKERS):
                    break
                await asyncio.sleep(0.2)
        out["probes"]["registration"] = reg_seen
        out["verdict"]["kernel_registered"] = bool(reg_seen)
        if not reg_seen:
            out["verdict"]["note"] = "Kernel 未注册：Bank 无 kernel_initialized。" \
                "Vibe Kernel 地图可能未编译 RegisterEntryPoints，或 BankLoad 缓存(CMRE-RUNTIME-003)。"
            return out

        # ---- bank-poll RPC 工具 ----
        async def bank_call(operation, args, timeout=12.0, reassert_sec=2.0):
            """Bank-poll RPC：写请求 → 轮询 response，期间按需重发（at-least-once）。

            ！！！铁律 VIBE_GEN_007（2026-08-09 真机取证）！！！
            Bank 通道是有损的：Host 与 Galaxy 都对同一个文件做全量覆盖写，没有锁。
            内核在 `ReloadBank()` 之后、下一次 `BankSave()` 之前落盘的 Host 请求会被
            内核内存态整份抹掉；Dispatch 越重窗口越宽。gen 图上 `vibe.query.units`
            紧跟重量级 `unit.spawn` 发出，恰好落在这个窗口里，于是稳定丢失 ——
            没有 response、没有 HANDLER_ABORTED、state_version 也不 bump
            （spawn=1 → gen.1=2，中间的 query.units 完全没留下痕迹）。
            standalone 旧内核把快照写放在 ReloadBank 紧后面，窗口≈0，所以不复现。

            修法：发出后不再假定送达。每 `reassert_sec` 回读一次，若请求已从任一
            候选 Bank 上消失（`bank_request_landed` 为假）且仍无 response，就用同一
            个 rid 重发。rid 不变，内核靠 `lastPolledRequestId` 去重，重复投递不会
            导致重复执行，语义安全。
            """
            rid = f"t100_{operation.replace('.','_')}_{int(time.time()*1000)}_{os.getpid()}"
            req = RpcRequest(session_id="tier100", request_id=rid, sequence=1,
                             operation=operation, args=args)
            if not write_bank_request(BANK_NAME, rid, req, player=1):
                return {"ok": False, "error": "write_bank_request failed"}
            t0 = time.time()
            last_assert = t0
            reasserts = 0
            while time.time() - t0 < timeout:
                raw = read_bank(BANK_NAME).get("response", {}).get(rid)
                if raw:
                    return {"ok": True, "raw": raw,
                            "latency": round(time.time() - t0, 3),
                            "reasserts": reasserts}
                now = time.time()
                if now - last_assert >= reassert_sec:
                    last_assert = now
                    # 只在"请求确实不在盘上"时重发，避免无谓地覆盖内核刚写的
                    # response（write_bank_request 现在以最新候选为基底，即便重发
                    # 也会把内核状态带上，不会回滚）。
                    if not bank_request_landed(BANK_NAME, rid):
                        write_bank_request(BANK_NAME, rid, req, player=1)
                        reasserts += 1
                await asyncio.sleep(0.1)
            return {"ok": False, "error": "timeout waiting response", "rid": rid,
                    "reasserts": reasserts}

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

        # ⑥ function.invoke gen.<noarg>（兜底派发证明；编号动态选取，见 pick_noarg_gen）
        noarg_gen, noarg_why = (opts.noarg_gen, "命令行显式指定") if opts.noarg_gen \
            else pick_noarg_gen()
        out["noarg_gen"] = {"function_id": noarg_gen, "picked_by": noarg_why}
        gen0_args = {"function_id": noarg_gen, "args": {}}
        g0 = await bank_call("function.invoke", gen0_args, timeout=15.0)
        out["calls"]["gen_noarg_invoke"] = {"fid": noarg_gen, **g0}
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
        ok_chain = "gen.1(AIAbilityFixed 只读 catalog 查询)" if g1_ok else (
            f"{noarg_gen}(无参只读 getter 兜底)" if g0_ok else "NONE")
        # 编号漂移显式暴露：UNKNOWN_FUNCTION 说明选取的 gen.* 根本不在 catalog 里，
        # 这是探针自身的 bug，不是被测地图的问题 —— 必须区分于 FUNCTION_NOT_IN_MAP。
        if "UNKNOWN_FUNCTION" in (g0.get("raw", "") or ""):
            out["errors"].append(
                f"探针 bug：{noarg_gen} 不在 invoke catalog 中（编号漂移），兜底证明无效")
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
    ap.add_argument("--load-timeout", type=float, default=300.0,
                    help="create_game/join_game 等待上限秒（大图整表编译很慢，默认 300）")
    ap.add_argument("--noarg-gen", default="",
                    help="显式指定第⑥步的无参 gen.*（留空=从 invoke-plan 动态选取）")
    ap.add_argument("--fresh-bank", action="store_true",
                    help="create_game 前把 GalaxyVibe.SC2Bank 移走，消除 "
                         "kernel_initialized 跨加载残留造成的注册假阳性")
    ap.add_argument("--tag", default="",
                    help="输出文件名后缀，便于阶梯实验区分多次 run")
    ap.add_argument("--out-dir",
                    default=str(REPO_ROOT / "artifacts" / "galaxy-vibe"))
    a = ap.parse_args()
    res = asyncio.run(a_main(a))
    res["map"] = str(a.map)
    res["fresh_bank"] = bool(a.fresh_bank)
    o = Path(a.out_dir)
    o.mkdir(parents=True, exist_ok=True)
    suffix = f"-{a.tag}" if a.tag else ""
    p = o / f"tier100-live-verdict{suffix}.json"
    p.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    rc = 0 if res.get("verdict", {}).get("tier100_pass") else (
        1 if res.get("verdict", {}).get("connect") else 2)
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
