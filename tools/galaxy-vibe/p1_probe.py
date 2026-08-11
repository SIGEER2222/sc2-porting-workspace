#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""p1_probe.py — Vibe Kernel P1 真机验证：RPC 真的**改变了游戏世界**。

P0 只证明了传输层通（system.ping 拿到 pong）。P1 要证明的是更强的东西：
Host 发一条 RPC，Kernel 在 Galaxy 侧真的执行了引擎 native，并且这个副作用
能被**第三方独立观测**到。

三方交叉验证（缺一不可，避免自证）：
    ① Kernel 响应      response/<rid> 里 error_code=OK 且 payload.created=N
    ② SC2 raw observation  玩家 1 的单位数恰好 +N，且增量类型 = 请求的类型
    ③ Kernel 自查      再发一条 query.units，Kernel 侧数出来的数量与 ② 一致

只有 ①②③ 同时成立才判 P1 PASS。②是关键——它绕开 Bank/Kernel 自身，
用 SC2API 原始观测做 ground truth，这是 src/lib/cmlib_runtime_test.py
验证过的方法论（可观测单位 > 日志/bank 自述）。

用法:
    python p1_probe.py --map "E:/SC2/.../VibeDeadOfNight.SC2Map" \
        [--unit-type Marine] [--count 5] [--player 1]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
# s2clientprotocol 是 vendored 在 reference/ 下的，不是 pip 包。
# 少了这一行会在 import 时直接 ModuleNotFoundError（p0_probe_v3 有、这里原先漏了）。
sys.path.insert(0, str(REPO / "reference" / "SC2-Neuro-API-Integration"))
sys.path.insert(0, str(REPO / "src" / "lib"))
sys.path.insert(0, str(HERE))

from s2clientprotocol import sc2api_pb2 as sc_pb          # noqa: E402
from s2clientprotocol import common_pb2 as sc_common      # noqa: E402
from sc2_api_conn import acquire_launched, api_url        # noqa: E402
from p0_probe_v2 import BANK_NAME, clear_banks, snapshot  # noqa: E402
from host.vibe_host import RpcRequest, write_bank_request  # noqa: E402

SESSION = "p1probe"


def _sub_err(resp, field: str):
    """proto2 optional enum 坑：未设置时读出来 = 枚举首项 = 1。只能靠 HasField。"""
    if not resp.HasField(field):
        return None
    sub = getattr(resp, field)
    return int(sub.error) if sub.HasField("error") else None


def owned_counts(client, names: dict[int, str], player: int) -> dict[str, int]:
    """按类型名统计某玩家存活单位。"""
    obs = client.send(sc_pb.Request(observation=sc_pb.RequestObservation()), 120)
    out: dict[str, int] = {}
    for u in obs.observation.observation.raw_data.units:
        if u.owner != player:
            continue
        n = names.get(u.unit_type, str(u.unit_type))
        out[n] = out.get(n, 0) + 1
    return out


def rpc(operation: str, rpc_args: dict, sequence: int, wait: float) -> tuple[bool, dict]:
    """写一条 RPC 请求，轮询 Bank 等 response/<rid>。返回 (ok, 解析后的响应)。"""
    rid = uuid.uuid4().hex[:12]
    req = RpcRequest(session_id=SESSION, request_id=rid, sequence=sequence,
                     operation=operation, args=rpc_args)
    write_bank_request(BANK_NAME, rid, req)
    print(f"    -> {operation} rid={rid} args={rpc_args}")
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(1.5)
        _, keys = snapshot()
        raw = keys.get(f"response/{rid}")
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return False, {"_raw": raw, "_error": "响应不是合法 JSON"}
        print(f"    <- error_code={data.get('error_code')} payload={data.get('payload')}")
        return data.get("error_code") == "OK", data
    return False, {"_error": f"{wait}s 内无 response/{rid}"}


def run(args) -> dict:
    res: dict = {"map": args.map, "session": SESSION, "steps": [],
                 "verdict": {"p1a_kernel_side_ok": False,
                             "p1b_observation_delta_ok": False,
                             "p1c_kernel_query_consistent": False,
                             "p1_pass": False}}

    def step(name, ok, detail=""):
        res["steps"].append({"step": name, "ok": bool(ok), "detail": detail})
        print(f"[{'OK' if ok else 'X'}] {name}" + (f" — {detail}" if detail else ""))

    map_path = Path(args.map)
    if not map_path.is_file():
        step("map_exists", False, str(map_path))
        return res
    md = map_path.read_bytes()
    step("map_exists", True, f"{len(md)} bytes")

    url = api_url()
    print(f"[i] SC2 API = {url}")
    client = acquire_launched(url)
    step("acquire_launched", True, "SC2 处于 launched 态")
    step("clear_bank", True, f"清掉 {len(clear_banks())} 个旧 bank")

    r = client.send(sc_pb.Request(create_game=sc_pb.RequestCreateGame(
        local_map=sc_pb.LocalMap(map_data=md),
        player_setup=[sc_pb.PlayerSetup(type=1, race=sc_common.Terran, player_name="P1")],
        realtime=True)), 240)
    if r.error or _sub_err(r, "create_game") is not None:
        step("create_game", False, f"top={list(r.error)} sub={_sub_err(r, 'create_game')}")
        client.close()
        return res
    step("create_game", True, "地图字节直传成功")

    # 3s 而非 1s：create 后 SC2 还在 init_game，太快 join 会把 ws 打断
    # （实测报 WSMessageTypeError 257:None，看起来像地图故障，其实是竞态）
    time.sleep(3.0)
    r = client.send(sc_pb.Request(join_game=sc_pb.RequestJoinGame(
        race=sc_common.Terran, options=sc_pb.InterfaceOptions(raw=True))), 180)
    if r.error or _sub_err(r, "join_game") is not None:
        step("join_game", False, f"top={list(r.error)} sub={_sub_err(r, 'join_game')}")
        client.leave()
        client.close()
        return res
    step("join_game", True, f"player_id={r.join_game.player_id}")

    data = client.send(sc_pb.Request(data=sc_pb.RequestData(unit_type_id=True)), 120)
    names = {u.unit_id: u.name for u in data.data.units}

    # ---- 等内核注册（P0 的前置，这里只作门禁） ----
    deadline = time.time() + args.wait
    ready = False
    while time.time() < deadline:
        time.sleep(2.0)
        _, keys = snapshot()
        if keys.get("index/kernel_initialized") == "1":
            ready = True
            break
    if not ready:
        step("kernel_ready", False, f"{args.wait}s 内 kernel_initialized 未出现")
        return res
    step("kernel_ready", True, "kernel_initialized=1")

    # ---- 基线观测 ----
    before = owned_counts(client, names, args.player)
    res["baseline"] = before
    step("baseline_observation", True,
         f"玩家{args.player} 共 {sum(before.values())} 单位, {args.unit_type}={before.get(args.unit_type, 0)}")

    # ---- ① Kernel 侧：unit.spawn ----
    ok, spawn_resp = rpc("unit.spawn",
                         {"unit_type": args.unit_type, "count": args.count, "player": args.player},
                         1, args.rpc_wait)
    res["spawn_response"] = spawn_resp
    created = (spawn_resp.get("payload") or {}).get("created")
    p1a = ok and created == args.count
    res["verdict"]["p1a_kernel_side_ok"] = p1a
    step("P1-A Kernel 执行 unit.spawn", p1a,
         f"error_code={spawn_resp.get('error_code')} created={created} (期望 {args.count})")

    # ---- ② 第三方观测：SC2 raw observation 增量 ----
    time.sleep(2.0)
    after = owned_counts(client, names, args.player)
    res["after"] = after
    delta = {k: after.get(k, 0) - before.get(k, 0)
             for k in set(before) | set(after) if after.get(k, 0) != before.get(k, 0)}
    res["delta"] = delta
    got = after.get(args.unit_type, 0) - before.get(args.unit_type, 0)
    p1b = got == args.count
    res["verdict"]["p1b_observation_delta_ok"] = p1b
    step("P1-B SC2 观测增量", p1b, f"{args.unit_type} +{got} (期望 +{args.count}), 全量 delta={delta}")

    # ---- ③ Kernel 自查：query.units ----
    ok3, q_resp = rpc("query.units", {"player": args.player, "unit_type": args.unit_type},
                      2, args.rpc_wait)
    res["query_response"] = q_resp
    kcount = (q_resp.get("payload") or {}).get("count")
    p1c = ok3 and kcount == after.get(args.unit_type, 0)
    res["verdict"]["p1c_kernel_query_consistent"] = p1c
    step("P1-C Kernel 自查一致", p1c,
         f"Kernel 数出 {kcount}, 观测 {after.get(args.unit_type, 0)}")

    _, keys = snapshot()
    res["bank_keys"] = keys

    client.leave()
    client.close()

    res["verdict"]["p1_pass"] = p1a and p1b and p1c
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Vibe Kernel P1 真机验证（RPC 真改变游戏世界）")
    ap.add_argument("--map", default=r"E:/SC2/SC2new/StarCraft II/Maps/VibeDeadOfNight.SC2Map")
    ap.add_argument("--unit-type", default="Marine")
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--player", type=int, default=1)
    ap.add_argument("--wait", type=float, default=45.0, help="等待内核注册的秒数")
    ap.add_argument("--rpc-wait", type=float, default=30.0, help="等单条 RPC 响应的秒数")
    ap.add_argument("--out", default=str(REPO / "artifacts" / "galaxy-vibe" / "p1-probe-verdict.json"))
    a = ap.parse_args()

    res = run(a)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    v = res["verdict"]
    print("\n=================== VERDICT ===================")
    print(f"  P1-A Kernel 执行 : {'PASS' if v['p1a_kernel_side_ok'] else 'FAIL'}")
    print(f"  P1-B 观测增量    : {'PASS' if v['p1b_observation_delta_ok'] else 'FAIL'}")
    print(f"  P1-C 自查一致    : {'PASS' if v['p1c_kernel_query_consistent'] else 'FAIL'}")
    print(f"  P1 总体          : {'PASS' if v['p1_pass'] else 'FAIL'}")
    print(f"  verdict -> {out}")
    return 0 if v["p1_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
