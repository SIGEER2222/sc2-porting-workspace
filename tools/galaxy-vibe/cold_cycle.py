#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P4 冷循环 — 变更感知 + 场景重建编排。

冷循环解决：改了 Galaxy/XML 后，如何判断是否需要重编译、并重建确定性场景重新验收。
本工具负责「变更分类」与「场景重建脚本生成」两块（**离线可验**）；重编译 Galaxy 需人工在
Galaxy Editor 保存（冷循环不能自动编译），其余由现有 `-Verify` 链路收口。

命令：
  --snapshot <MOD_DIR>      对 mod 源文件（.galaxy/.xml）算指纹并存储
  --check <MOD_DIR>         比对当前 vs 存储指纹，输出变更 JSON，退出码 changed?1:0
  --emit-reset [--out ...]  生成场景重建脚本 reset.vtest（kill all + 复位资源）

真机冷循环节奏：
  1) 改了 Galaxy/XML
  2) `python cold_cycle.py --check <mod_dir>`  → 若有变更，提示需去编辑器重存 Mod
  3) 编辑器保存 Mod（重编译）
  4) `python cold_cycle.py --emit-reset`       → 生成 reset.vtest
  5) `powershell -File launch-galaxy-vibe.ps1 -Verify reset.vtest`  → 重建场景并验收

证据分类：指纹比对是文件系统事实（static/runtime 之间偏 static 校验）；本脚本只做判定与生成。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORE = REPO_ROOT / "artifacts" / "galaxy-vibe" / "mod-fingerprint.json"
DEFAULT_RESET = REPO_ROOT / "artifacts" / "galaxy-vibe" / "reset.vtest"
SCAN_EXT = (".galaxy", ".xml")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_file(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def compute_fingerprint(mod_dir: Path) -> dict:
    fp: dict = {}
    for p in sorted(mod_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in SCAN_EXT:
            rel = p.relative_to(mod_dir).as_posix()
            fp[rel] = {
                "mtime": p.stat().st_mtime,
                "size": p.stat().st_size,
                "sha256": _hash_file(p),
            }
    return fp


def detect_changes(prev: dict, cur: dict):
    added, modified, deleted = [], [], []
    for k in cur:
        if k not in prev:
            added.append(k)
        elif cur[k]["sha256"] != prev[k]["sha256"]:
            modified.append(k)
    for k in prev:
        if k not in cur:
            deleted.append(k)
    return {
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "changed": bool(added or modified or deleted),
    }


def build_reset_script() -> str:
    return (
        "# reset.vtest — 场景重建（冷循环入口）\n"
        "# 清场 + 复位资源，使下一轮 scenario 从干净状态开始\n"
        "kill all\n"
        "cheat minerals on\n"
        "cheat gas on\n"
        "# 如需基准单位，在这里加 spawn，例如：\n"
        "# spawn marine 5 1\n"
    )


def main():
    ap = argparse.ArgumentParser(description="P4 冷循环：变更感知 + 场景重建")
    ap.add_argument("--snapshot", metavar="MOD_DIR", help="对 mod 源文件算指纹并存储")
    ap.add_argument("--check", metavar="MOD_DIR", help="比对当前 vs 存储指纹")
    ap.add_argument("--store", default=str(DEFAULT_STORE), help="指纹存储路径")
    ap.add_argument("--emit-reset", action="store_true", help="生成场景重建脚本 reset.vtest")
    ap.add_argument("--out", default=str(DEFAULT_RESET), help="reset.vtest 输出路径")
    a = ap.parse_args()

    if a.snapshot:
        d = Path(a.snapshot)
        if not d.exists():
            print(f"MOD_DIR 不存在: {d}")
            raise SystemExit(2)
        fp = compute_fingerprint(d)
        Path(a.store).parent.mkdir(parents=True, exist_ok=True)
        Path(a.store).write_text(
            json.dumps({"generated_at": utcnow(), "fingerprint": fp}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"[cold] snapshot {len(fp)} files -> {a.store}")
        raise SystemExit(0)

    if a.check:
        d = Path(a.check)
        cur = compute_fingerprint(d) if d.exists() else {}
        prev: dict = {}
        if Path(a.store).exists():
            try:
                prev = json.loads(Path(a.store).read_text(encoding="utf-8")).get("fingerprint", {})
            except Exception:
                prev = {}
        ch = detect_changes(prev, cur)
        verdict = {
            "changed": ch["changed"],
            "added": ch["added"],
            "modified": ch["modified"],
            "deleted": ch["deleted"],
            "checked_at": utcnow(),
        }
        print(json.dumps(verdict, indent=2, ensure_ascii=False))
        raise SystemExit(1 if ch["changed"] else 0)

    if a.emit_reset:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(build_reset_script(), encoding="utf-8")
        print(f"[cold] reset script -> {a.out}")
        raise SystemExit(0)

    ap.print_help()
    raise SystemExit(2)


if __name__ == "__main__":
    main()
