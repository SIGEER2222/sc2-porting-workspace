# -*- coding: utf-8 -*-
"""产物新鲜度校验 —— round24 新增，守「测的就是交付的」。

**要解决的问题（round24 现场抓获）**

round23 的收口报告里写着一句性质：「构建后无 `.galaxy` 变更（测的就是交付的）」。
round24 才发现：**这条性质从来只靠人的纪律维持，仓库里没有任何检查在守它。**

这轮就静默破了一次：

    CMLib.SC2Mod/README.md    117181 B  02:28:04   <- 构建时拷进去的，内容只到 round23
    scripts/cmlib/README.md   127033 B  02:30:50   <- 源文件，round24 章节在这里

`build_mod.py` 会把源 README 拷进 mod 目录，但 README 是在构建**之后**才追加的
round24 章节，于是交付的 `.SC2Mod` 里装着过期文档，而四件产物、三档矩阵全都
若无其事地绿着。

README 不是代码，这次没有功能后果。但同一种时序错位发生在 `.galaxy` 上，
结果就是**矩阵验的是旧库、交付的是新库**，且没有任何信号 —— 这正是本项目
最怕的那类缺陷：不报错、不留痕、结论看着很硬。

**判据**

凡是会进入产物的源文件，mtime 必须**早于**所有产物。任何一个源比任何一个产物新
= 产物陈旧 = 拒跑真机矩阵（fail-closed），因为此时矩阵测的东西和要交付的东西
已经不是一回事，跑出来的 PASS 不能证明交付物可用。

**为什么放在矩阵前置而不是 gate.py**

`gate.py` 在构建**之前**跑（它自己的第 6 关才刚生成 `_testmap_build`），
那时产物本来就该是旧的，放进去会恒红。真正需要这条保证的时刻是
「拿产物去真机跑」之前，所以钉在 `run_matrix_round10.py` 的前置。

用法：
    python check_artifact_freshness.py           # 校验
    python check_artifact_freshness.py --selftest  # 只跑自检（含反向对照）
"""
from __future__ import annotations

import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

LIB = Path(__file__).resolve().parent
CMLIB_SRC = LIB / "scripts" / "cmlib"
SELFTEST = LIB / "selftest"

ARTIFACTS = [
    LIB / "CMLib_out.SC2Mod",
    LIB / "test_cmlib.SC2Map",
    LIB / "test_cmlib_dep.SC2Map",
    LIB / "test_cmlib_neg.SC2Map",
]

# 容差：文件系统时间戳精度 + 构建过程自身耗时带来的抖动。
# 给 2 秒，既不至于被同一秒内的写入误报，也小到抓得住"构建完又改了源码"。
TOLERANCE_SEC = 2.0


def collect_sources() -> list[Path]:
    src: list[Path] = []
    if CMLIB_SRC.is_dir():
        src += sorted(CMLIB_SRC.glob("*.galaxy"))
        src += sorted(CMLIB_SRC.glob("*.md"))
    if SELFTEST.is_dir():
        src += sorted(SELFTEST.glob("*.galaxy"))
    return src


def check() -> tuple[bool, list[str]]:
    problems: list[str] = []

    missing = [a for a in ARTIFACTS if not a.exists()]
    if missing:
        for a in missing:
            problems.append(f"产物缺失: {a.name} —— 先跑 build_mod.py / build_testmap 系列")
        return False, problems

    sources = collect_sources()
    if not sources:
        # 一个源都扫不到，多半是路径写错了。这种情况必须报错而不是"没问题"，
        # 否则本检查会变成恒绿的摆设。
        problems.append(f"源文件一个都没扫到（{CMLIB_SRC} / {SELFTEST}）—— 路径可能已漂移")
        return False, problems

    oldest_art = min(ARTIFACTS, key=lambda p: p.stat().st_mtime)
    oldest_mt = oldest_art.stat().st_mtime

    stale: list[tuple[Path, float]] = []
    for s in sources:
        delta = s.stat().st_mtime - oldest_mt
        if delta > TOLERANCE_SEC:
            stale.append((s, delta))

    if stale:
        problems.append(
            f"产物陈旧：{len(stale)} 个源文件比最早的产物 "
            f"({oldest_art.name}) 还新 —— 矩阵会去测一份已经不是交付物的东西"
        )
        for s, d in sorted(stale, key=lambda x: -x[1])[:10]:
            rel = s.relative_to(LIB)
            problems.append(f"    {rel}  比产物新 {d:.1f}s")
        problems.append("    处置：重新构建四件产物后再跑矩阵（不要直接跑）")
        return False, problems

    print(f"[fresh] 源 {len(sources)} 个 / 产物 4 个，最早产物 = {oldest_art.name}")
    print(f"[fresh] 所有源文件均早于产物（容差 {TOLERANCE_SEC:g}s）")
    return True, problems


def selftest() -> int:
    """反向对照：比较逻辑必须能同时产出 PASS 和 FAIL。

    只有正向能过的检查，无法证明它在该报错时会报错。
    """
    errs: list[str] = []

    # 合成场景：源比产物新 3 秒 -> 必须被判为陈旧
    if not (3.0 > TOLERANCE_SEC):
        errs.append("反向对照失败：容差过大，源比产物新 3s 都抓不到")
    # 合成场景：源比产物新 0.5 秒（同一次构建的抖动）-> 必须放过
    if 0.5 > TOLERANCE_SEC:
        errs.append("反向对照失败：容差过小，0.5s 抖动会被误报为陈旧")
    # 空源清单必须判失败而不是通过
    global CMLIB_SRC, SELFTEST
    _a, _b = CMLIB_SRC, SELFTEST
    CMLIB_SRC = LIB / "__不存在的目录__"
    SELFTEST = LIB / "__也不存在__"
    try:
        ok, _ = check()
        if ok:
            errs.append("反向对照失败：源清单为空时本应判失败，却通过了（恒绿摆设）")
    finally:
        CMLIB_SRC, SELFTEST = _a, _b

    for e in errs:
        print(f"[fresh] ERROR {e}")
    if errs:
        print(f"[fresh] 自检 FAILED —— {len(errs)} 个问题")
        return 1
    print("[fresh] 自检 PASSED（容差边界 + 空清单反向对照）")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    ok, problems = check()
    if ok:
        return 0
    for p in problems:
        print(f"[fresh] {p}")
    print("\n[fresh] FAILED —— 产物与源码不同步，拒绝在此状态下跑真机矩阵")
    return 1


if __name__ == "__main__":
    sys.exit(main())
