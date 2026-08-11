#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""round21 扫描器：找出「对 string 类型变量/参数做 null 比较」的位置。

背景（round21 真机实证）：Galaxy 里空串与 null 等价 —— `"" == null` 为 true。
因此：
  * `str != null` **不能**用来判"非空"（永远等价于 `str != ""`）；
  * `if (s == null) return;` 形式的守卫会连带拦掉空串（多数场景恰是想要的，不算 bug）；
  * 但凡语义是"区分 未设置 vs 空串"的代码，都是错的 —— 本扫描器就是找这类。

输出：每处命中的 文件:行号、被比较的标识符、其声明类型、判定（OK / SUSPECT）。
"""
import re
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parent / "scripts" / "cmlib"

# 形如  string lp_x   /  string lv_y;  的声明（含参数表内）
DECL_RE = re.compile(r"\bstring\s+(l[pv]_\w+|gv_\w+)\b")
NULLCMP_RE = re.compile(r"\b(l[pv]_\w+|gv_\w+)\s*(==|!=)\s*null\b")


def scan_file(path: Path):
    """按函数体粗粒度收集 string 声明，再匹配 null 比较。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    # 收集整文件范围内被声明为 string 的标识符（库内命名唯一性足够高，
    # 且我们只做"提示"，误报由人工复核 —— 宁可多报不可漏报）
    string_ids = set(DECL_RE.findall(text))

    hits = []
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        for ident, op in NULLCMP_RE.findall(line):
            if ident in string_ids:
                hits.append((i, ident, op, stripped))
    return hits


def main() -> int:
    if not LIB.is_dir():
        print(f"[scan] 找不到库目录: {LIB}")
        return 2

    total = 0
    for path in sorted(LIB.glob("*.galaxy")):
        hits = scan_file(path)
        if not hits:
            continue
        print(f"\n=== {path.name} ===")
        for lineno, ident, op, src in hits:
            total += 1
            print(f"  L{lineno:<5d} {ident} {op} null   |  {src[:110]}")

    print(f"\n[scan] string 型 null 比较命中 = {total} 处")
    if total == 0:
        print("[scan] 干净：库内没有对 string 做 null 比较，不受 '\"\"==null' 引擎语义影响")
    else:
        print("[scan] 逐处复核：若语义是『区分 未设置 vs 空串』则必错，"
              "若只是『空即跳过』则等价、可保留（建议统一改成 == \"\" 以免误导）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
