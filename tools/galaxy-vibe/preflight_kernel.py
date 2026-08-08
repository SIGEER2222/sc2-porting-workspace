#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preflight_kernel.py — 实机扫描前的 60 秒预检。

回答三个问题，一个都不能猜：
  1. SC2 API 端点通不通？当前 status 是什么？加载的是哪张图？
  2. Bank 里 kernel_initialized 有没有？pollloop 心跳在不在动？
  3. 一次 system.ping RPC 能不能在几秒内闭环？

只读，不 join、不 create_game、不清 bank。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from real_machine_vm_sweep import api_url, sc_pb, snapshot, Rpc  # noqa: E402

sys.path.insert(0, str(HERE.parents[1] / "src" / "lib"))
from sc2_api_conn import Client  # noqa: E402


def main() -> int:
    url = api_url()
    print(f"[1] endpoint = {url}")
    try:
        c = Client(url).connect()
    except Exception as exc:                                   # noqa: BLE001
        print(f"    X 连不上: {exc}")
        return 2

    ping = c.send(sc_pb.Request(ping=sc_pb.RequestPing()), 30)
    print(f"    OK ping game_version={ping.ping.game_version} "
          f"data_build={ping.ping.data_build}")

    st = c.send(sc_pb.Request(ping=sc_pb.RequestPing()), 30)
    print(f"    status = {sc_pb.Status.Name(st.status)}")

    try:
        gi = c.send(sc_pb.Request(game_info=sc_pb.RequestGameInfo()), 60)
        print(f"[2] map_name  = {gi.game_info.map_name!r}")
        print(f"    local_map = {gi.game_info.local_map_path!r}")
        print(f"    players   = {len(gi.game_info.player_info)}")
    except Exception as exc:                                   # noqa: BLE001
        print(f"[2] X RequestGameInfo 失败: {exc}")

    print("[3] bank index:")
    _, keys = snapshot()
    idx = {k: v for k, v in keys.items() if k.startswith("index/")}
    if not idx:
        print("    X bank 里没有 index/* —— Kernel 没起来或 bank 未落盘")
    for k, v in sorted(idx.items()):
        print(f"    {k} = {v}")

    hb0 = idx.get("index/heartbeat") or idx.get("index/poll_ticks")
    time.sleep(3.0)
    _, keys2 = snapshot()
    idx2 = {k: v for k, v in keys2.items() if k.startswith("index/")}
    hb1 = idx2.get("index/heartbeat") or idx2.get("index/poll_ticks")
    print(f"    heartbeat: {hb0} -> {hb1}  "
          f"({'跳动中' if hb0 != hb1 else '未变化(可能无心跳字段)'})")

    print("[4] system.ping RPC 闭环测试 (12s 上限)")
    rpc = Rpc(12.0, 0.4)
    t0 = time.time()
    resp = rpc.call("system.ping", {})
    dt = round(time.time() - t0, 2)
    ok = resp.get("status") == "ok" or (resp.get("payload") or {}).get("pong")
    print(f"    {'OK' if ok else 'X '} {dt}s  {resp}")

    c.close()
    print("\n预检结论: " + ("KERNEL 活着，可以开扫" if ok else
                            "KERNEL 不可达，扫描没有意义"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
