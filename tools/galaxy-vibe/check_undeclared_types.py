#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""未声明类型检查器 —— 抓「静态 lint 全绿但 SC2 静默丢弃整个 MapScript」的头号杀手。

背景（2026-08-08 实测）：
    generated/LibVibeInvokeCommon.galaxy 用 `CMPE_PlayerEventFunc` 作 ResolveFuncref
    的返回类型，LibVibeInvoke_03.galaxy 又用它声明局部变量 —— 但这个类型在**任何源
    文件里都没有 struct/typedef 声明**（生成器 FUNCREF_TYPE 常量凭空造的名字）。
    Galaxy 编译器遇到未声明类型 → 编译失败 → SC2 **静默丢弃整个 MapScript**，
    不报错、不写 ScriptError.txt、InitMap() 根本不被调用。
    而 galaxy-lint 只做语法/符号级检查，**看不到跨文件类型闭包**，所以照样 0 error。

对照实验（negative control，已跑过）：
    libCOTF_gs_HistogramData → LibCOTF_h.galaxy:52 有 `struct ... {`  ✅ 找得到
    CMPE_PlayerEventFunc     → 全源文件零声明                        ❌ 找不到
    → 证明本检查器的「声明集」扫描方法有效，不是搜漏。

用法：
    # 检查生成产物，声明集取整个地图 Base.SC2Data
    python check_undeclared_types.py \
        --scan  src/projects/cmre-porting/packages/Maps/亡者之夜.SC2Map/Base.SC2Data/generated \
        --decl  src/projects/cmre-porting/packages/Maps/亡者之夜.SC2Map/Base.SC2Data \
        --decl  reference/sc2-galaxy-toolkit/.../core.sc2mod/base.sc2data/TriggerLibs

退出码：0 = 无未声明类型；1 = 发现未声明类型（门禁失败）；2 = 参数/路径错误。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Galaxy 内置类型（含 handle 类）。少列 = 误报，多列 = 漏报，宁可少列后人工确认。
# ---------------------------------------------------------------------------
BUILTIN_TYPES = {
    # 基础
    "void", "bool", "int", "byte", "char", "fixed", "string", "text",
    # handle 家族
    "abilcmd", "actor", "actorscope", "aifilter", "bank", "bitmask", "camerainfo",
    "color", "doodad", "generichandle", "handle", "marker", "objective", "order",
    "planetpanelcanvascallback", "playergroup", "point", "portrait", "region",
    "revealer", "sound", "soundlink", "timer", "transmissionsource", "trigger",
    "unit", "unitfilter", "unitgroup", "unitref", "wave", "waveinfo", "wavetarget",
    "texttag", "effecthistory", "datetime", "gamelink", "cameraobject",
}

# 类型位置上不可能是类型的关键字
KEYWORDS = {
    "return", "if", "else", "while", "for", "do", "break", "continue",
    "include", "const", "static", "native", "struct", "typedef",
    "funcref", "structref", "arrayref", "new", "delete", "true", "false", "null",
}

# 声明式
RE_STRUCT_DECL = re.compile(r"\bstruct\s+(\w+)\s*\{")
# typedef <whatever> Name;   例：typedef funcref<Proto> CMLib_PlayerVisitor;
RE_TYPEDEF_DECL = re.compile(r"\btypedef\b[^;]*?\b(\w+)\s*;")

# 使用式：函数定义/原型的返回类型  ——  `Type name (args)` 位于行首
RE_FUNC_RET = re.compile(r"^\s*(?:static\s+|native\s+)?([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*\(")
# 使用式：局部/全局变量声明  ——  `Type name;`
RE_VAR_DECL = re.compile(r"^\s*(?:const\s+|static\s+)?([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*(?:=[^;]*)?;")


def iter_galaxy(paths: list[Path]):
    for base in paths:
        if base.is_file() and base.suffix == ".galaxy":
            yield base
        elif base.is_dir():
            yield from sorted(base.rglob("*.galaxy"))


def collect_declared(paths: list[Path]) -> set[str]:
    """扫描声明集，收集所有 struct / typedef 出来的类型名。"""
    declared: set[str] = set()
    for f in iter_galaxy(paths):
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        declared.update(RE_STRUCT_DECL.findall(src))
        declared.update(RE_TYPEDEF_DECL.findall(src))
    return declared


def collect_used(paths: list[Path]) -> dict[str, list[tuple[Path, int, str]]]:
    """扫描目标集，收集所有出现在**类型位置**的标识符及其出处。"""
    used: dict[str, list[tuple[Path, int, str]]] = {}

    def record(tname: str, f: Path, lineno: int, line: str):
        if tname in BUILTIN_TYPES or tname in KEYWORDS:
            return
        used.setdefault(tname, []).append((f, lineno, line.strip()[:120]))

    for f in iter_galaxy(paths):
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(src.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("//") or stripped.startswith("/*"):
                continue
            m = RE_FUNC_RET.match(line)
            if m:
                record(m.group(1), f, lineno, line)
                continue
            m = RE_VAR_DECL.match(line)
            if m:
                record(m.group(1), f, lineno, line)
    return used


def main() -> int:
    ap = argparse.ArgumentParser(description="Galaxy 未声明类型检查器")
    ap.add_argument("--scan", action="append", required=True,
                    help="被检查的文件/目录（可重复）")
    ap.add_argument("--decl", action="append", default=[],
                    help="提供类型声明的文件/目录（可重复）。目标集自身总是自动纳入。")
    ap.add_argument("--allow", action="append", default=[],
                    help="白名单类型名（可重复），用于已知由引擎提供的类型")
    ap.add_argument("--max-report", type=int, default=20, help="每个类型最多打印几处出处")
    args = ap.parse_args()

    scan_paths = [Path(p) for p in args.scan]
    decl_paths = [Path(p) for p in args.decl]
    for p in scan_paths + decl_paths:
        if not p.exists():
            print(f"[ERROR] path not found: {p}", file=sys.stderr)
            return 2

    # 目标集自身也可能声明类型，必须纳入声明集
    declared = collect_declared(decl_paths + scan_paths)
    declared |= set(args.allow)
    used = collect_used(scan_paths)

    undeclared = {t: locs for t, locs in used.items() if t not in declared}

    print(f"[check_undeclared_types] scanned={len(list(iter_galaxy(scan_paths)))} files")
    print(f"[check_undeclared_types] declared types known = {len(declared)}")
    print(f"[check_undeclared_types] type-position identifiers used = {len(used)}")

    if not undeclared:
        print("[PASS] no undeclared types found")
        return 0

    print(f"\n[FAIL] {len(undeclared)} undeclared type(s) found "
          f"— these make SC2 SILENTLY DISCARD the whole MapScript:\n")
    for tname in sorted(undeclared):
        locs = undeclared[tname]
        print(f"  ✗ {tname}  ({len(locs)} occurrence(s))")
        for f, lineno, text in locs[: args.max_report]:
            print(f"      {f}:{lineno}: {text}")
        if len(locs) > args.max_report:
            print(f"      ... and {len(locs) - args.max_report} more")
        print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
