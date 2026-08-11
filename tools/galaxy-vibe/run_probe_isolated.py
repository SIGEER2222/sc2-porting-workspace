#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_probe_isolated.py — 在**独立 SC2 实例**上跑 P0/P1 真机探针，绝不碰用户实例。

背景：p0/p1 探针默认通过 sc2_api_conn.discover_api_port() 找 SC2，会命中
用户正在玩的那个实例（端口 5000），一旦 create_game 就把他的对局换掉。

本脚本：
  1) 假设调用方已自行启动一个独立 SC2（默认 ws://127.0.0.1:5001/sc2api，
     用 SC2Switcher 起、不杀任何进程）；
  2) monkeypatch sc2_api_conn，把所有连接硬路由到该隔离实例，并把 ensure_sc2
     改成**永不 kill、永远返回隔离 url**——彻底堵死误杀外部 owner 的路径；
  3) 顺序跑 p0_probe_v3（bank 传输层）+ p1_probe（unit.spawn 真改世界），
     地图用调用方传入的 --map（默认 C:/tmp/VibeT5.sc2map）。

这等于把"外部 owner 占用槽位 → blocked"的保守假设推翻：用户授权自备地图测，
于是起隔离实例自测，既拿到真机证据，又不干扰用户。
"""
from __future__ import annotations

import argparse
import importlib
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

import sc2_api_conn  # noqa: E402

DEFAULT_URL = os.environ.get("VIBE_PROBE_URL", "ws://127.0.0.1:5001/sc2api")


def _safe_ensure_sc2(port=5001, boot_wait=90, kill_stale=False, force=False):
    # 关键：永不 kill，永远返回隔离实例 url。
    return DEFAULT_URL


def _safe_discover(default=5001):
    return 5001


def _safe_api_url(port=None):
    return DEFAULT_URL


# 必须在 import 探针模块之前打补丁：探针顶层 `from sc2_api_conn import ...`
# 会绑定到补丁后的对象。
sc2_api_conn.ensure_sc2 = _safe_ensure_sc2
sc2_api_conn.discover_api_port = _safe_discover
sc2_api_conn.api_url = _safe_api_url

# 运行时可改的 url（main 里用 --api-url 覆盖）
_STATE = {"url": DEFAULT_URL}


def _patch(url: str) -> None:
    _STATE["url"] = url
    sc2_api_conn.api_url = lambda port=None: _STATE["url"]
    sc2_api_conn.ensure_sc2 = lambda *a, **k: _STATE["url"]


def _run_module(modname: str, argv: list[str]) -> int:
    mod = importlib.import_module(modname)
    saved = sys.argv
    sys.argv = [modname + ".py"] + argv
    try:
        mod.main()
    except SystemExit as e:
        return int(getattr(e, "code", 0) or 0)
    finally:
        sys.argv = saved
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="隔离实例跑 P0/P1 真机探针")
    ap.add_argument("--api-url", default=DEFAULT_URL, help="隔离 SC2 ws url")
    ap.add_argument("--map", default=r"C:/tmp/VibeT5.sc2map", help="测试地图")
    ap.add_argument("--skip-p0", action="store_true")
    ap.add_argument("--skip-p1", action="store_true")
    ap.add_argument("--unit-type", default="Marine")
    ap.add_argument("--count", type=int, default=5)
    a = ap.parse_args()

    _patch(a.api_url)
    print(f"[i] 隔离 SC2 = {_STATE['url']}  地图 = {a.map}")

    rc = 0
    if not a.skip_p0:
        print("\n########## P0 探针 ##########")
        rc |= (_run_module("p0_probe_v3", ["--map", a.map]) != 0) << 0
    if not a.skip_p1:
        print("\n########## P1 探针 ##########")
        rc |= (_run_module("p1_probe", ["--map", a.map,
                                        "--unit-type", a.unit_type,
                                        "--count", str(a.count)]) != 0) << 1
    print(f"\n[i] 汇总 rc={rc}  (bit0=P0, bit1=P1; 0=PASS)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
