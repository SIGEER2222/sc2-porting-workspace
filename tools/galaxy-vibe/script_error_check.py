#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SC2 ScriptError 复核器 — 验收闸门自动化（P0/P1/P2/P4 共用）。

扫描 SC2 的 GameLogs 目录，找出「某次启动之后」新增的 `ScriptError*.txt`，输出 verdict JSON。
这是所有阶段「通过」判定的硬条件之一（"本次启动无新增 ScriptError.*.txt"），原靠人工翻目录，
现自动化。

用法：
  python script_error_check.py                       # 读 launcher 写的 marker 判定
  python script_error_check.py --since <epoch>       # 显式给定启动时间（秒）
  python script_error_check.py --logs-dir <path>     # 指定 GameLogs 目录

退出码：无新增=0（闸门通过）；有新增=1（闸门失败，可直接接 CI / 冷循环门禁）。

证据分类：扫描的是真机 GameLogs 文件（runtime 证据），本脚本本身只做判定。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOGS = Path.home() / "Documents" / "StarCraft II" / "GameLogs"
# launcher 在游戏就绪后写入的启动标记（含 launched_at epoch）
DEFAULT_MARKER = Path.home() / "Documents" / "StarCraft II" / "galaxy-vibe-launch.json"
ERROR_GLOB = "ScriptError*.txt"
DEFAULT_OUT = REPO_ROOT / "artifacts" / "galaxy-vibe" / "script-error-verdict.json"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_launch_time(marker: Path) -> float:
    """从 launcher 写的 marker 读启动时间（epoch 秒）；缺失或损坏返回 0（即不滤历史）。"""
    if not marker.exists():
        return 0.0
    try:
        data = json.loads(marker.read_text(encoding="utf-8-sig"))
        return float(data.get("launched_at", 0.0))
    except Exception:
        return 0.0


def scan(logs_dir: Path, since: float, head_lines: int = 40):
    """返回 (新增 ScriptError 列表, note)。新增 = mtime > since。"""
    if not logs_dir.exists():
        return [], f"目录不存在: {logs_dir}"
    files = sorted(logs_dir.glob(ERROR_GLOB), key=lambda p: p.stat().st_mtime)
    new = []
    for p in files:
        mtime = p.stat().st_mtime
        if mtime > since:
            try:
                head = "\n".join(
                    p.read_text(encoding="utf-8", errors="replace").splitlines()[:head_lines]
                )
            except Exception:
                head = ""
            new.append(
                {
                    "path": str(p),
                    "mtime": mtime,
                    "mtime_iso": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
                    "size": p.stat().st_size,
                    "head": head,
                }
            )
    return new, ""


def main():
    ap = argparse.ArgumentParser(description="SC2 ScriptError 复核器（验收闸门）")
    ap.add_argument("--logs-dir", default=str(DEFAULT_LOGS), help="GameLogs 目录")
    ap.add_argument("--since", type=float, default=None, help="启动时间 epoch 秒；缺省读 marker")
    ap.add_argument("--marker", default=str(DEFAULT_MARKER), help="launcher 写的启动标记路径")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="verdict JSON 输出路径")
    a = ap.parse_args()

    since = a.since if a.since is not None else load_launch_time(Path(a.marker))
    new, note = scan(Path(a.logs_dir), since)
    verdict = {
        "launched_at": since,
        "launched_at_iso": (
            datetime.fromtimestamp(since, tz=timezone.utc).isoformat() if since else None
        ),
        "has_new_errors": bool(new),
        "count": len(new),
        "files": new,
        "scan_dir": a.logs_dir,
        "generated_at": utcnow(),
        "note": note,
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")

    if new:
        print(f"[ScriptError] 发现 {len(new)} 个新增错误 -> {out}")
        for f in new[:5]:
            print(f"   {f['path']} ({f['mtime_iso']})")
        raise SystemExit(1)
    print(f"[ScriptError] 无新增错误 -> {out}")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
