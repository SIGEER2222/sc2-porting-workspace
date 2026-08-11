#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_tier100_clean.py — 用已验证的 tier100 模式跑一次真机验证，并确保善后。

为什么不用 p0/p1 探针：它们的 create_game 后只 sleep 1s 再 join，会在 SC2
仍在 init_game 时把 WS 打断（257 错误）；且失败路径不 leave_game，留下
in-game 孤儿态导致 SC2 反复重启。tier100 用原生 aiohttp + sleep 3 已验证可用。

本脚本：
  1) 跑 tier100_live_probe.a_main(map=VibeT5) 拿真机证据；
  2) 无论成败，最后 reconnect 发 leave_game，把 SC2 还原成 launched(idle)，
     绝不留孤儿态。

用法: python run_tier100_clean.py --map C:/tmp/VibeT5.sc2map --port 5000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for p in (REPO / "reference" / "SC2-Neuro-API-Integration",
          REPO / "src" / "lib",
          HERE):
    sys.path.insert(0, str(p))

import tier100_live_probe as t  # noqa: E402
from s2clientprotocol import sc2api_pb2 as sc_pb  # noqa: E402
import aiohttp  # noqa: E402


async def _leave(port: int) -> None:
    url = f"ws://127.0.0.1:{port}/sc2api"
    try:
        async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)) as s:
            ws = await s.ws_connect(url, max_msg_size=0)
            await ws.send_bytes(
                sc_pb.Request(leave_game=sc_pb.RequestLeaveGame())
                .SerializeToString())
            try:
                await ws.receive_bytes()
            except Exception:
                pass
            await ws.close()
        print("[cleanup] leave_game 已发送，SC2 应回到 launched")
    except Exception as e:
        print(f"[cleanup] leave 失败（非致命）: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--map", default=r"C:/tmp/VibeT5.sc2map")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--fresh-bank", action="store_true")
    ap.add_argument("--tag", default="vibet5")
    a = ap.parse_args()

    # 构造 tier100 需要的 opts 对象（属性访问）
    opts = argparse.Namespace(
        port=a.port, map=a.map, runs=a.runs,
        fresh_bank=a.fresh_bank, tag=a.tag,
        out_dir=str(REPO / "artifacts" / "galaxy-vibe"))

    # finally 保证无论 a_main 成功/异常，都落盘 + leave，绝不留孤儿 in-game 态
    res = {}
    try:
        res = asyncio.run(t.a_main(opts))
    finally:
        # 落盘 verdict（a_main 只返回 dict，写文件在 main() 里，这里补上）
        out_dir = Path(REPO / "artifacts" / "galaxy-vibe")
        out_dir.mkdir(parents=True, exist_ok=True)
        vpath = out_dir / f"tier100-live-verdict-{a.tag}.json"
        vpath.write_text(json.dumps(res, ensure_ascii=False, indent=2),
                         encoding="utf-8")
        print(f"[i] verdict -> {vpath}")
        # 善后：把 SC2 还原成 idle，绝不留孤儿 in-game 态
        asyncio.run(_leave(a.port))

    v = res.get("verdict", {}) if res else {}
    rc = 0 if v.get("tier100_pass") else (1 if v.get("connect") else 2)
    print(f"[i] kernel_registered={v.get('kernel_registered')} "
          f"p0_pass={v.get('p0_pass')} tier100_pass={v.get('tier100_pass')} "
          f"rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
