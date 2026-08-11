#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""独立复核一张已打包 .SC2Map 的 `ResolveFuncref` 静态表是否全部合法。

【为什么需要一个「独立」复核器】`symbol_repair` 的 Stage C 既做裁剪又做判定，
自己证明自己不算数。本工具从**成品 MPQ** 出发，用 `compile_unit.resolve()`
重新解析真实 include 闭包（跨 MPQ + 磁盘 mod + 暴雪库），再逐条核对表里
每个 funcref 目标，与打包器完全独立取证。

【判定规则】funcref 目标必须在编译单元内存在一个 **void(int) 实现体**：
  - native 声明（`native void X(int);`）不合法 —— Galaxy 禁止对 native 取
    funcref，引擎绑定没有脚本地址；写了就是编译错误 ⇒ SC2 **静默丢弃整个
    MapScript**（不报错、不写 ScriptError、InitMap 从不执行）。
  - 孤儿原型（只有 `void X(int);` 没有实现体）同样不合法。
  - 返回类型或参数表不匹配 `libVibeInvoke_gp_VoidIntProto` 的不合法。

【坑，勿踩】不要用 `compile_unit` 的 `sym_owner[name]` 去定位实现体再判定。
`sym_owner` 是 `setdefault` 写入的，Galaxy 库普遍「`Lib*_h.galaxy` 放原型、
`Lib*.galaxy` 放实现」，于是 owner 几乎总是指向 `_h` 原型文件 —— 按它取文本
必然找不到 `) {`，会把大批**完全合法**的目标误报为「未定义/无实现」。
2026-08-08 实测这个写法在 VibeGen-F1 上产生 26 个假阳性。
正确做法：扫**编译单元全部文件**的实现体并集（本文件 `impl_index()` 的做法）。

用法：
    python verify_funcref.py <map.SC2Map>
退出码 0 = 全部合法；1 = 存在非法条目（该图会被 SC2 静默丢弃）。
"""
from __future__ import annotations

import ctypes
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compile_unit import resolve                       # noqa: E402
from mpq_build_gen_map import read_mpq_galaxy          # noqa: E402
from mpq_patch_kernel import STREAM_FLAG_READ_ONLY, load_storm  # noqa: E402

COMMON_KEY = "Base.SC2Data\\LibVibeInvokeCommon.galaxy"

BRANCH_RE = re.compile(r'if \(name == "(\w+)"\) \{ return (\w+); \}')
DROPPED_RE = re.compile(r"\[symbol-repair\] funcref dropped")
# 实现体：`) {` 收尾。native 与孤儿原型都以 `;` 结束，天然出局。
IMPL_RE = re.compile(r"^[ \t]*(\w+)[ \t]+(\w+)[ \t]*\(([^)]*)\)[ \t]*\{", re.M)
NATIVE_RE = re.compile(r"^[ \t]*native[ \t]+(\w+)[ \t]+(\w+)[ \t]*\(", re.M)
_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_STRING_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"')


def strip_noncode(text: str) -> str:
    """注释与字符串字面量里的同名标识符会污染判定，先抹掉（保持行数不变）。"""
    def _blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))
    return _STRING_RE.sub(_blank, _COMMENT_RE.sub(_blank, text))


def read_unit_texts(u, mpq_texts: dict[str, str]) -> dict[str, str]:
    """取编译单元内每个文件的文本（MPQ 内名直查，`disk:` 前缀读磁盘）。"""
    out: dict[str, str] = {}
    for f in u.files:
        if f.startswith("disk:"):
            try:
                out[f] = Path(f[5:]).read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
        elif f in mpq_texts:
            out[f] = mpq_texts[f]
    return out


def impl_index(texts: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """返回 (void(int) 实现体 -> 文件, native 声明 -> 文件)。"""
    impls: dict[str, str] = {}
    natives: dict[str, str] = {}
    for fname, raw in texts.items():
        t = strip_noncode(raw)
        for ret, name, args in IMPL_RE.findall(t):
            if ret != "void":
                continue
            parts = [a.strip() for a in args.split(",") if a.strip()]
            if len(parts) == 1 and parts[0].split()[0] == "int":
                impls.setdefault(name, fname)
        for _ret, name in NATIVE_RE.findall(t):
            natives.setdefault(name, fname)
    return impls, natives


def main() -> int:
    map_path = Path(sys.argv[1] if len(sys.argv) > 1
                    else r"C:\tmp\VibeDeadOfNight-Gen.SC2Map")
    if not map_path.exists():
        print(f"[FAIL] 地图不存在: {map_path}")
        return 2

    # 【顺序要紧】必须先跑 compile_unit.resolve() 再自己开 MPQ。反过来的话，
    # 本进程残留的 StormLib 句柄状态会让 resolve 内部的 SFileOpenArchive 读到
    # 残缺 `(listfile)`，闭包从 285 文件塌成 120、unresolved 从 0 涨到 33
    # —— 判定依据被悄悄削弱，却不会报错。2026-08-08 实测。
    unit = resolve(map_path, verbose=False)

    dll = load_storm()
    h = ctypes.c_void_p()
    if not dll.SFileOpenArchive(str(map_path), 0, STREAM_FLAG_READ_ONLY, ctypes.byref(h)):
        print(f"[FAIL] 无法打开 MPQ: {map_path}")
        return 2
    try:
        mpq_texts = read_mpq_galaxy(dll, h)
    finally:
        dll.SFileCloseArchive(h)

    common = mpq_texts.get(COMMON_KEY)
    if common is None:
        print(f"[SKIP] MPQ 内无 {COMMON_KEY}（这张图没有 funcref 表）")
        return 0

    branches = BRANCH_RE.findall(common)
    dropped = len(DROPPED_RE.findall(common))
    texts = read_unit_texts(unit, mpq_texts)
    impls, natives = impl_index(texts)

    print(f"[unit] {len(unit.files)} 文件 / {len(unit.symbols)} 符号 / "
          f"unresolved {len(unit.unresolved)}")
    print(f"[tbl ] 保留分支 {len(branches)} / Stage C 已删 {dropped} "
          f"/ 单元内 void(int) 实现体 {len(impls)}")

    bad_native, bad_missing = [], []
    for _key, target in branches:
        if target in impls:
            continue                       # 有实现体即合法（native 不会有实现体）
        (bad_native if target in natives else bad_missing).append(target)

    if bad_native:
        print(f"[BAD ] native 目标 {len(bad_native)}: {sorted(bad_native)[:10]}")
    if bad_missing:
        print(f"[BAD ] 无 void(int) 实现体 {len(bad_missing)}: "
              f"{sorted(bad_missing)[:10]}")
    if bad_native or bad_missing:
        print(f"[VERDICT] FAIL —— {len(bad_native) + len(bad_missing)} 条非法 funcref，"
              f"该图会被 SC2 静默丢弃整个 MapScript")
        return 1
    print(f"[VERDICT] PASS —— {len(branches)} 条 funcref 全部指向单元内 void(int) 实现体")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
