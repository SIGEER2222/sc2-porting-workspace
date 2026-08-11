"""在单个 .galaxy 实现文件内部做函数级二分，定位真机编译失败的那一段。

背景：sc2-galaxy-lang 的独立 checker 会漏报一些真实引擎才会拒绝的写法
（例如引用了未 include 的库符号、或某些 checker 不覆盖的语义）。
真机是唯一权威。本脚本把目标文件按**顶层定义**切块，保留前 N 块生成
一个临时实现文件，丢进真机探针二分，直接指出第一个出错的块。

前置：header（含全部函数原型）单独 include 必须能通过——Galaxy 允许
      "只有原型没有实现"，所以截断实现是安全的。

用法：
  python bisect_galaxy_file.py cmlib_ai
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
REPO = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace")
sys.path.insert(0, str(REPO / "reference" / "SC2-Neuro-API-Integration"))
LIB = REPO / "src" / "lib"
sys.path.insert(0, str(LIB))

import probe_modules as pm    # noqa: E402

CMLIB_SRC = LIB / "scripts" / "cmlib"

# 顶层定义的起始行：`[static ][const ]<type> Name(` 或 `[static ][const ]<type> Name =`
TOP_DEF = re.compile(
    r"^(static\s+)?(const\s+)?"
    r"(void|bool|int|fixed|string|text|point|unit|unitgroup|playergroup|"
    r"region|wave|order|abilcmd|marker|bank|color|timer|trigger|actor|"
    r"unitfilter|revealer|doodad|camerainfo|transmissionsource|soundlink)\s+"
    r"[A-Za-z_][A-Za-z0-9_]*\s*[(=]")


def split_chunks(text):
    """按顶层定义切块；文件开头的 include / 注释归到第 0 块（永远保留）。"""
    lines = text.splitlines(keepends=True)
    starts = [i for i, ln in enumerate(lines) if TOP_DEF.match(ln)]
    if not starts:
        return ["".join(lines)], []
    preamble = "".join(lines[:starts[0]])
    chunks, names = [], []
    for idx, s in enumerate(starts):
        e = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        chunks.append("".join(lines[s:e]))
        m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*[(=]", lines[s])
        names.append(m.group(1) if m else f"chunk{idx}")
    return [preamble] + chunks, names


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    mod = sys.argv[1]                       # 例如 cmlib_ai
    impl = CMLIB_SRC / f"{mod}.galaxy"
    backup = CMLIB_SRC / f"{mod}.galaxy.bak"
    text = impl.read_text(encoding="utf-8")
    chunks, names = split_chunks(text)
    preamble, bodies = chunks[0], chunks[1:]
    print(f"[bisect] {mod}.galaxy 切出 {len(bodies)} 个顶层定义")

    base_inc = ["scripts/cmlib/cmlib_core_h", "scripts/cmlib/cmlib_core",
                f"scripts/cmlib/{mod}_h", f"scripts/cmlib/{mod}"]
    shutil.copy(impl, backup)
    try:
        def test(n):
            impl.write_text(preamble + "".join(bodies[:n]), encoding="utf-8")
            pm.build_map(base_inc)
            return pm.probe_retry()

        if test(len(bodies)):
            print("[bisect] 完整文件竟然通过了——请确认探针环境")
            return 0

        lo, hi, first_bad = 0, len(bodies), None
        while lo <= hi:
            mid = (lo + hi) // 2
            ok = test(mid)
            label = "(空)" if mid == 0 else names[mid - 1]
            print(f"[bisect] 前 {mid:2d} 个定义 (…{label}) -> "
                  f"{'PASS' if ok else 'FAIL'}", flush=True)
            if ok:
                lo = mid + 1
            else:
                first_bad = mid
                hi = mid - 1

        print("\n[bisect] ==== 结论 ====")
        if first_bad is None or first_bad == 0:
            print("[bisect] 连 preamble(include 段) 都编译不过")
            return 1
        bad = names[first_bad - 1]
        print(f"[bisect] 第一个导致真机编译失败的定义: {bad} (第 {first_bad} 个)")
        print("-" * 60)
        print(bodies[first_bad - 1].rstrip())
        print("-" * 60)
        return 1
    finally:
        shutil.move(backup, impl)


if __name__ == "__main__":
    sys.exit(main())
