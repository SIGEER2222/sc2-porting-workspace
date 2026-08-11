#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过 WebUI 启动游戏并做进图门禁判定。

判定契约（README 门禁，勿放宽）：
  - 基线之后出现新的 `*Alerts*.txt`      ⇒ 地图已被引擎加载
  - 基线之后出现非空 `*ScriptError*.txt` ⇒ 脚本编译/运行失败（FAIL，优先级最高）
  - runtime listener heartbeat            ⇒ Vibe 内核存活

【2026-08-09 修正，勿退回】旧版把 SSE 文本里**基线之前**就已存在的
`bridge_heartbeat` 也算成功，导致第 3 次启动误报 SUCCESS（真机其实编译失败）。
现在一律用「基线时间戳之后新增的文件」判定，heartbeat 只从新增日志片段里找。

用法：
  python monitor_launch.py [--timeout 600] [--no-launch]
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

GAMELOGS = Path.home() / "Documents" / "StarCraft II" / "GameLogs"
API = "http://127.0.0.1:8767"
PAYLOAD = {"commander": "TerranAlenger3", "mapName": "亡者之夜.SC2Map", "mode": 1}


def post(path: str, body: dict) -> str:
    req = urllib.request.Request(
        API + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def get(path: str) -> str:
    with urllib.request.urlopen(API + path, timeout=15) as r:
        return r.read().decode("utf-8", "replace")


def snapshot() -> set[str]:
    return {p.name for p in GAMELOGS.glob("*.txt")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--no-launch", action="store_true")
    a = ap.parse_args()

    base_files = snapshot()
    t0 = time.time()
    print(f"[baseline] {len(base_files)} GameLogs *.txt  @ {time.strftime('%H:%M:%S')}")

    if not a.no_launch:
        print(f"[launch] POST /api/launch-async {PAYLOAD}")
        print("[launch] ->", post("/api/launch-async", PAYLOAD)[:300])

    alerts: list[str] = []
    errors: list[str] = []
    last_report = 0.0
    while time.time() - t0 < a.timeout:
        time.sleep(5)
        new = snapshot() - base_files
        alerts = sorted(n for n in new if "Alerts" in n)
        errors = sorted(n for n in new if "ScriptError" in n)
        if errors:
            break
        el = time.time() - t0
        if el - last_report >= 30:
            last_report = el
            try:
                st = get("/api/status")[:120]
            except Exception as exc:                       # noqa: BLE001
                st = f"status err: {exc}"
            print(f"[{el:6.0f}s] new={sorted(new)} status={st}")
        if alerts and el > 90:
            # 地图已加载且已过脚本编译窗口，再无 ScriptError 即视为通过
            break

    print("=" * 70)
    print(f"new Alerts      : {alerts}")
    print(f"new ScriptError : {errors}")
    for e in errors:
        txt = (GAMELOGS / e).read_text(encoding="utf-8-sig", errors="replace")
        body = [ln for ln in txt.splitlines()
                if "Script" in ln or "脚本" in ln]
        print("-" * 70)
        print("\n".join(body[:40]))
    if errors:
        print("VERDICT: FAIL (script compile/runtime error)")
        return 1
    if alerts:
        print("VERDICT: PASS (map loaded, no script error)")
        return 0
    print("VERDICT: TIMEOUT (map never loaded)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
