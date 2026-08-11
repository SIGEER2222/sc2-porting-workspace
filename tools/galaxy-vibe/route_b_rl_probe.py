#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""route_b_rl_probe.py — route B tier1 真机验证：gen 图当 RL 训练场

背景（2026-08-09 定稿归因）
--------------------------
N5b live RL 一直卡在移植图 `亡者之夜_live_packed.SC2Map`：内核注册标记有、0 ScriptError，
但 RPC 5/5 timeout、玩家 own=1(type4051)/minerals=0/enemy=0。反证来自模块④——gen 图
同为亡者之夜衍生、同样 PRESELECTED=false 却稳定 tier100 PASS；唯一结构差 = gen 图经
`mpq_build_gen_map.py` 已剥离战役触发器栈、立即真 in_game，而 packed 图完整保留 CMRE
launcher + 战役逻辑、**从未真正开局**。内核注册标记写在 init 首个 `Wait` 之前（所以有），
PollLoop 每轮依赖 `Wait` 后游戏钟推进（所以死）。
→ 「RPC 死」与「阵营未初始化」是同一根因的两个表征，`run_live_rl` 12/12 action_errors
  是其下游。

route B（本脚本要证的东西）
--------------------------
RL 环境从移植图切到已 live-green 的 gen 图，构成 **spawn → order → observe** 闭环：

  · 动作-建场（episode 级）：Bank RPC `unit.spawn` —— gen 图剥了触发器栈，玩家开局
    什么都没有，靠内核凭空造兵摆场景。这是 raw API 做不到的（raw API 只能指挥已有单位）。
  · 动作-控制（step 级）：SC2 raw API `ActionRawUnitCommand` —— Bank 通道是有损+慢
    （单次 RPC 12s 超时窗），绝不能当每步动作通道；raw API 才是 per-step 控制面。
  · 观测：SC2 raw observation —— 第三方独立，绕开 Kernel 自述。

判据（tier1）
------------
  ① kernel_registered           内核在 gen 图真机注册
  ② bank_spawn_ok               Bank RPC 造出 >=2 个 Marine（raw obs 独立确认）
  ③ raw_action_accepted         raw API MOVE 指令被接受（无 action error）
  ④ actor_displacement >= 3.0   被下令单位真的走了（raw obs 前后位移）
  ⑤ control_displacement < 1.5  **反向对照**：同批 spawn、未下令的单位basically没动
                                 —— 没有它，④ 无法排除"单位本来就在飘"的假阳性
  ⑥ script_errors == 0          同窗口无 ScriptError

tier1_pass = ①②③④⑤⑥ 全真。

前置：SC2 已 API 模式启动（SC2Switcher_x64.exe -listen 127.0.0.1 -port <port> -debug）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe"))

from s2clientprotocol import sc2api_pb2 as sc_pb  # noqa: E402
from s2clientprotocol import common_pb2 as sc_common  # noqa: E402
from s2clientprotocol import raw_pb2 as sc_raw  # noqa: E402
import aiohttp  # noqa: E402
from host.vibe_host import (  # noqa: E402
    read_bank, write_bank_request, bank_request_landed, RpcRequest, DEFAULT_BANK_DIR,
)
from live_lock import add_lock_args, acquire_from_args, LiveLockBusy  # noqa: E402

BANK_NAME = "GalaxyVibe"
DEFAULT_MAP = r"C:/tmp/VibeDeadOfNight-Gen.SC2Map"
REG_MARKERS = ["kernel_initialized", "register_entrypoints_done"]
ABILITY_MOVE = 16

# 位移门槛：Marine 基础移动速度 ~3.15/s；给 6s 观察窗，走 12 格目标，
# 3.0 格是"确实在走"的保守下界，1.5 格是"没动"的宽松上界（含 spawn 后微调/避让抖动）。
ACTOR_MIN_DISPLACEMENT = 3.0
CONTROL_MAX_DISPLACEMENT = 1.5

SCRIPT_ERROR_DIRS = [
    Path(os.path.expanduser("~")) / "Documents" / "StarCraft II" / "Logs",
]


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sub_err(resp, field: str):
    sub = getattr(resp, field)
    if not sub.HasField("error"):
        return None
    return int(sub.error)


def _script_error_files_since(since: float) -> list[str]:
    hits: list[str] = []
    for d in SCRIPT_ERROR_DIRS:
        if not d.is_dir():
            continue
        for p in d.glob("**/ScriptError*.txt"):
            try:
                if p.stat().st_mtime >= since:
                    hits.append(str(p))
            except OSError:
                pass
    return hits


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


async def a_main(opts) -> dict:
    out = {
        "schemaVersion": 1,
        "probe": "route_b_rl_probe",
        "generatedAt": utcnow(),
        "port": opts.port,
        "map": opts.map,
        "tag": opts.tag,
        "thresholds": {
            "actor_min_displacement": ACTOR_MIN_DISPLACEMENT,
            "control_max_displacement": CONTROL_MAX_DISPLACEMENT,
        },
        "probes": {},
        "steps": {},
        "verdict": {
            "connect": False, "kernel_registered": False,
            "bank_spawn_ok": False, "raw_action_accepted": False,
            "actor_moved": False, "control_static": False,
            "script_errors_clean": False, "tier1_pass": False,
        },
        "errors": [],
    }
    api_url = f"ws://127.0.0.1:{opts.port}/sc2api"
    map_path = Path(opts.map)
    if not (map_path.is_file() or map_path.is_dir()):
        out["errors"].append(f"map not found: {map_path}")
        return out
    is_dir_map = map_path.is_dir()
    md = map_path.read_bytes() if not is_dir_map else b""
    out["map_bytes"] = len(md) if md else -1

    async def _send(ws, req, timeout: float = 30):
        await ws.send_bytes(req.SerializeToString())
        data = await asyncio.wait_for(ws.receive_bytes(), timeout=timeout)
        if isinstance(data, str):
            data = data.encode("utf-8")
        resp = sc_pb.Response()
        resp.ParseFromString(data)
        return resp

    async with aiohttp.ClientSession(trust_env=False,
                                     timeout=aiohttp.ClientTimeout(total=None)) as sess:
        window_start = time.time()

        # fresh bank：让 kernel_initialized 成为"本次加载确实编译并运行内核"的无歧义证据
        if opts.fresh_bank:
            bp = DEFAULT_BANK_DIR / f"{BANK_NAME}.SC2Bank"
            if bp.exists():
                arch = bp.with_suffix(f".SC2Bank.stale-{int(time.time())}")
                bp.replace(arch)
                out["probes"]["fresh_bank"] = {"archived": str(arch)}

        local_map = sc_pb.LocalMap()
        if is_dir_map:
            local_map.map_path = str(map_path)
        else:
            local_map.map_data = md

        # SC2 在加载 5.4MB gen 图（内含上万 adapter）期间**会自重启进程**，旧 ws 直接被
        # 关闭，表现为 `WSMessageTypeError: Received message 257`（257=WSMsgType.CLOSED）。
        # 那不是"地图坏了"，是连接死了。故 connect→create→join 整段可重试：每次重试
        # 重新握手 ws，等端口回来再继续。没有这层，探针会把"引擎重启"误报成"加载失败"。
        ws = None
        attempts = max(1, int(opts.connect_attempts))
        load_trace = []
        for attempt in range(1, attempts + 1):
            try:
                ws = await asyncio.wait_for(
                    sess.ws_connect(api_url, max_msg_size=0), timeout=30)
                out["verdict"]["connect"] = True

                r = await _send(ws, sc_pb.Request(create_game=sc_pb.RequestCreateGame(
                    local_map=local_map,
                    player_setup=[sc_pb.PlayerSetup(type=1, race=sc_common.Terran,
                                                    player_name="P1")],
                    realtime=True)), timeout=opts.load_timeout)
                cg_err = _sub_err(r, "create_game")
                out["probes"]["create_game"] = {
                    "attempt": attempt,
                    "top_error": [int(e) for e in r.error] if r.error else [],
                    "sub_error": cg_err}
                if r.error or cg_err is not None:
                    raise RuntimeError(f"create_game top={r.error} sub={cg_err}")

                await asyncio.sleep(3.0)
                r = await _send(ws, sc_pb.Request(join_game=sc_pb.RequestJoinGame(
                    race=sc_common.Terran,
                    options=sc_pb.InterfaceOptions(raw=True))),
                    timeout=opts.load_timeout)
                jg_err = _sub_err(r, "join_game")
                out["probes"]["join_game"] = {
                    "attempt": attempt,
                    "top_error": [int(e) for e in r.error] if r.error else [],
                    "sub_error": jg_err,
                    "player_id": getattr(r.join_game, "player_id", None)}
                if r.error or jg_err is not None:
                    raise RuntimeError(f"join_game top={r.error} sub={jg_err}")
                break
            except Exception as e:  # noqa: BLE001
                load_trace.append(f"attempt{attempt}: {type(e).__name__}: {e}")
                if ws is not None:
                    try:
                        await ws.close()
                    except Exception:  # noqa: BLE001
                        pass
                    ws = None
                if attempt >= attempts:
                    out["probes"]["load_trace"] = load_trace
                    out["errors"].append(
                        f"create/join failed after {attempts} attempts: {load_trace}")
                    return out
                # 引擎自重启后端口要几十秒才回来，慢慢等
                await asyncio.sleep(opts.reconnect_wait)
        out["probes"]["load_trace"] = load_trace

        data = await _send(ws, sc_pb.Request(data=sc_pb.RequestData(unit_type_id=True)))
        names = {u.unit_id: u.name for u in data.data.units}

        gi = await _send(ws, sc_pb.Request(game_info=sc_pb.RequestGameInfo()))
        pa = gi.game_info.start_raw.playable_area
        center = ((pa.p0.x + pa.p1.x) / 2.0, (pa.p0.y + pa.p1.y) / 2.0)
        out["probes"]["playable_area"] = {
            "p0": [pa.p0.x, pa.p0.y], "p1": [pa.p1.x, pa.p1.y],
            "center": list(center)}

        async def marines(player: int = 1) -> dict[int, tuple[float, float]]:
            o = await _send(ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
            res: dict[int, tuple[float, float]] = {}
            for u in o.observation.observation.raw_data.units:
                if u.owner != player:
                    continue
                if names.get(u.unit_type) != "Marine":
                    continue
                res[u.tag] = (u.pos.x, u.pos.y)
            return res

        # ---- 内核注册 ----
        reg_seen: dict[str, int] = {}
        for _ in range(200):
            if (DEFAULT_BANK_DIR / f"{BANK_NAME}.SC2Bank").exists():
                bk = read_bank(BANK_NAME)
                for mk in REG_MARKERS:
                    v = bk.get("index", {}).get(mk)
                    if v is not None and str(v).strip() in {"1", "1.0"}:
                        reg_seen[mk] = 1
            if reg_seen:
                break
            await asyncio.sleep(0.2)
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
            out["errors"].append("kernel not registered on gen map")
            return out

        # ---- Bank RPC ----
        async def bank_call(operation, args, timeout=12.0, reassert_sec=2.0):
            rid = f"rtb_{operation.replace('.', '_')}_{int(time.time()*1000)}_{os.getpid()}"
            req = RpcRequest(session_id="route_b", request_id=rid, sequence=1,
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
                    if not bank_request_landed(BANK_NAME, rid):
                        write_bank_request(BANK_NAME, rid, req, player=1)
                        reasserts += 1
                await asyncio.sleep(0.1)
            return {"ok": False, "error": "timeout waiting response", "rid": rid,
                    "reasserts": reasserts}

        ping = await bank_call("system.ping", {}, timeout=8.0)
        out["steps"]["system_ping"] = {
            "ok": bool(ping.get("ok") and '"pong":true' in ping.get("raw", "")),
            "latency": ping.get("latency"), "reasserts": ping.get("reasserts")}

        # ---- ② Bank RPC 建场：spawn 2 个 Marine ----
        before = await marines(1)
        spawn_x, spawn_y = opts.spawn_x, opts.spawn_y
        spawn = await bank_call("unit.spawn",
                                {"count": str(opts.spawn_count), "player": "1",
                                 "unit_type": "Marine",
                                 "x": str(spawn_x), "y": str(spawn_y)},
                                timeout=15.0)
        out["steps"]["bank_spawn"] = {"ok": spawn.get("ok"),
                                      "latency": spawn.get("latency"),
                                      "reasserts": spawn.get("reasserts"),
                                      "raw": (spawn.get("raw") or "")[:400]}
        await asyncio.sleep(1.5)
        after = await marines(1)
        new_tags = [t for t in after if t not in before]
        out["steps"]["spawn_observation"] = {
            "before": len(before), "after": len(after),
            "new_tags": [str(t) for t in new_tags],
            "new_count": len(new_tags)}
        if len(new_tags) < 2:
            out["errors"].append(
                f"need >=2 spawned marines for actor/control split, got {len(new_tags)}")
            out["verdict"]["bank_spawn_ok"] = len(new_tags) >= 1
            return out
        out["verdict"]["bank_spawn_ok"] = True

        actor_tag, control_tag = new_tags[0], new_tags[1]
        actor_p0, control_p0 = after[actor_tag], after[control_tag]

        # 目标点：从 spawn 点朝可玩区中心推 opts.move_dist 格（保证在可行走区内）
        vx, vy = center[0] - actor_p0[0], center[1] - actor_p0[1]
        norm = math.hypot(vx, vy) or 1.0
        target = (actor_p0[0] + vx / norm * opts.move_dist,
                  actor_p0[1] + vy / norm * opts.move_dist)
        out["steps"]["move_plan"] = {
            "actor_tag": str(actor_tag), "control_tag": str(control_tag),
            "actor_p0": list(actor_p0), "control_p0": list(control_p0),
            "target": list(target),
            "planned_distance": round(_dist(actor_p0, target), 2)}

        # ---- ③ raw API MOVE（step 级控制面）----
        cmd = sc_raw.ActionRawUnitCommand(
            ability_id=ABILITY_MOVE, unit_tags=[actor_tag], queue_command=False)
        cmd.target_world_space_pos.CopyFrom(
            sc_common.Point2D(x=float(target[0]), y=float(target[1])))
        act = await _send(ws, sc_pb.Request(action=sc_pb.RequestAction(
            actions=[sc_pb.Action(action_raw=sc_raw.ActionRaw(unit_command=cmd))])))
        results = [int(x) for x in act.action.result]
        # ActionResult.Success == 1
        accepted = bool(results) and all(x == 1 for x in results)
        out["steps"]["raw_action"] = {"results": results, "accepted": accepted}
        out["verdict"]["raw_action_accepted"] = accepted

        # ---- ④⑤ 观察位移（含反向对照）----
        trace = []
        actor_d = control_d = 0.0
        deadline = time.time() + opts.observe_seconds
        while time.time() < deadline:
            await asyncio.sleep(1.0)
            snap = await marines(1)
            ap = snap.get(actor_tag)
            cp = snap.get(control_tag)
            if ap:
                actor_d = _dist(actor_p0, ap)
            if cp:
                control_d = _dist(control_p0, cp)
            trace.append({"t": round(time.time() - (deadline - opts.observe_seconds), 1),
                          "actor": list(ap) if ap else None,
                          "control": list(cp) if cp else None,
                          "actor_d": round(actor_d, 2),
                          "control_d": round(control_d, 2)})
            if actor_d >= ACTOR_MIN_DISPLACEMENT:
                break
        out["steps"]["displacement"] = {
            "actor_displacement": round(actor_d, 2),
            "control_displacement": round(control_d, 2),
            "trace": trace}
        out["verdict"]["actor_moved"] = actor_d >= ACTOR_MIN_DISPLACEMENT
        out["verdict"]["control_static"] = control_d < CONTROL_MAX_DISPLACEMENT

        # ---- ⑥ ScriptError ----
        se = _script_error_files_since(window_start)
        out["steps"]["script_errors"] = se
        out["verdict"]["script_errors_clean"] = not se

        v = out["verdict"]
        v["tier1_pass"] = all([
            v["kernel_registered"], v["bank_spawn_ok"], v["raw_action_accepted"],
            v["actor_moved"], v["control_static"], v["script_errors_clean"]])
        if v["tier1_pass"]:
            v["note"] = (
                "route B tier1 闭环：gen 图上 Bank RPC 建场（spawn）+ raw API 控制（MOVE）"
                f"+ raw obs 观测（actor 位移 {actor_d:.2f} 格 ≥ {ACTOR_MIN_DISPLACEMENT}，"
                f"未下令对照 {control_d:.2f} 格 < {CONTROL_MAX_DISPLACEMENT}）"
                " → RL 环境可在 gen 图上跑 spawn→order→observe。")
        else:
            fails = [k for k in ("kernel_registered", "bank_spawn_ok",
                                 "raw_action_accepted", "actor_moved",
                                 "control_static", "script_errors_clean")
                     if not v[k]]
            v["note"] = f"route B tier1 未通过，失败判据：{fails}"

        if opts.leave:
            try:
                await _send(ws, sc_pb.Request(leave_game=sc_pb.RequestLeaveGame()),
                            timeout=15)
            except Exception:  # noqa: BLE001
                pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="route B tier1: gen 图 RL 动作/观测闭环")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--map", default=DEFAULT_MAP)
    ap.add_argument("--tag", default="")
    ap.add_argument("--spawn-count", type=int, default=3)
    ap.add_argument("--spawn-x", type=float, default=10.0)
    ap.add_argument("--spawn-y", type=float, default=10.0)
    ap.add_argument("--move-dist", type=float, default=12.0)
    ap.add_argument("--observe-seconds", type=float, default=12.0)
    ap.add_argument("--load-timeout", type=float, default=300.0)
    ap.add_argument("--connect-attempts", type=int, default=3,
                    help="connect→create→join 整段重试次数（应对 SC2 加载期自重启）")
    ap.add_argument("--reconnect-wait", type=float, default=25.0,
                    help="重试前等待秒数，等引擎重启后端口回来")
    ap.add_argument("--fresh-bank", action="store_true")
    ap.add_argument("--leave", action="store_true",
                    help="跑完主动 leave_game，把 SC2 还回菜单态")
    ap.add_argument("--out", default="")
    add_lock_args(ap)
    opts = ap.parse_args()

    lock = None
    try:
        lock = acquire_from_args(opts, "route_b_rl_probe",
                                 note=f"map={Path(opts.map).name}")
    except LiveLockBusy as exc:
        print(f"[live-lock] {exc}", file=sys.stderr)
        print(json.dumps({"verdict": {"tier1_pass": False, "connect": False},
                          "error": "live_lock_busy", "holder": exc.holder_info},
                         ensure_ascii=False, indent=2))
        return 3

    try:
        res = asyncio.run(a_main(opts))
    finally:
        if lock is not None:
            lock.release()
    tag = f"-{opts.tag}" if opts.tag else ""
    out_path = Path(opts.out) if opts.out else (
        REPO_ROOT / "artifacts" / "galaxy-vibe" / f"route-b-tier1-verdict{tag}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print(f"\n[route_b] verdict -> {out_path}")
    return 0 if res["verdict"]["tier1_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
