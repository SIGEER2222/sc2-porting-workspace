# -*- coding: utf-8 -*-
"""
test_ledger_sources.py — 台账门禁的门禁（round26）

## 为什么需要这个

`check_native_ledger.py` 是用来治「人肉名单会漏」的。round26 发现它自己
也栽在同一件事上：族全集只从**一个人肉指定的文件**读，于是
`AISetFilterEnergy`（声明在 natives_missing.galaxy）压根没进全集，
门禁自报「24 个符号全部有交代 / PASSED」—— 一个输入残缺的绿灯。

> 校验器自身要有校验器。恒绿等于没有校验器。

所以本文件专门盯住「族全集的来源必须是多源并集」这一条性质。它不检查
库代码，只检查**门禁的取数方式**有没有退化回单一来源。

## 三条断言 + 一条反向对照

    1. 并集必须能看见「只有 .galaxy 声明、且不在 TacticalAI.galaxy 里」的符号
       代表值：AISetFilterEnergy（round25 实际漏掉的那个）
    2. 并集必须能看见「只有 <FlagNative/> 背书、连 .galaxy 声明都没有」的符号
       代表值：AISetStockAlias / AISetStockFree
    3. FAMILIES 配置里不许再出现文件路径 —— 一旦有人把「族 -> 文件」的写法
       加回来，盲区就会复活
    4. 反向对照：用 round25 的旧算法（单文件）重算 aifilter 族，
       它**必须**看不到 AISetFilterEnergy。
       如果旧算法也能看到，说明本测试根本没测在点子上（同义反复的假绿）。

第 4 条是这个测试有没有牙的证明：失败必须精确落在被测判据上，
而不是靠崩溃或超时。

## 用法
    python test_ledger_sources.py
退出码: 0 = 性质成立, 1 = 门禁的取数方式已退化
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import check_native_ledger as ledger  # noqa: E402

# round25 盲区的两类代表值。
# 选它们不是随手挑的：这两个就是真实漏过的形态，
# 拿真实漏项当断言，比拿构造样例更能防复发。
ONLY_IN_OTHER_GALAXY = "AISetFilterEnergy"      # 在 natives_missing.galaxy
ONLY_IN_FLAG_NATIVE = ["AISetStockAlias", "AISetStockFree"]  # 无 .galaxy 声明

OLD_SINGLE_FILE = (ledger.TRIG / "Tactical" / "TacticalAI.galaxy")


def check(cond: bool, ok_msg: str, fail_msg: str, problems: list[str]) -> None:
    if cond:
        print("  ok    " + ok_msg)
    else:
        print("  FAIL  " + fail_msg)
        problems.append(fail_msg)


def main() -> int:
    problems: list[str] = []
    print("=" * 78)
    print("[ledger-src] 台账门禁的取数方式自检：族全集必须是多源并集")
    print("=" * 78)

    universe, decl, flag = ledger.engine_symbol_universe()
    print(f"  .galaxy 声明 {len(decl)} / <FlagNative/> {len(flag)} / "
          f"并集 {len(universe)}\n")

    # --- 1. 跨 .galaxy 文件 ---------------------------------------------------
    check(
        ONLY_IN_OTHER_GALAXY in universe,
        f"并集看得见跨文件符号 {ONLY_IN_OTHER_GALAXY}",
        f"并集里没有 {ONLY_IN_OTHER_GALAXY} —— 声明源扫描退化了，"
        f"round25 的跨文件盲区已复活",
        problems,
    )

    # --- 2. 仅 FlagNative 背书 ------------------------------------------------
    for s in ONLY_IN_FLAG_NATIVE:
        check(
            s in universe and s not in decl,
            f"并集看得见仅 <FlagNative/> 背书的 {s}",
            f"{s} 不在并集里（或已混进 .galaxy 声明，代表值失效需更换）"
            f" —— FlagNative 源被丢掉了",
            problems,
        )

    # --- 3. FAMILIES 里不许出现路径 -------------------------------------------
    # 注意别把正则里的转义反斜杠（`\w`）当成路径分隔符 —— 第一版就是这么
    # 误报的。真正的路径特征只有三种：值不是字符串（曾经是 tuple 配置）、
    # 含正斜杠、或直接写了文件名。
    path_like = [
        f"{fam}={val!r}"
        for fam, val in ledger.FAMILIES.items()
        if (not isinstance(val, str)
            or "/" in val
            or ".galaxy" in val
            or ".TriggerLib" in val)
    ]
    check(
        not path_like,
        "FAMILIES 只含正则、不含任何文件路径",
        "FAMILIES 里出现了文件路径配置（" + "; ".join(path_like) +
        "）—— 单一来源盲区会随之回来",
        problems,
    )

    # --- 4. 反向对照：旧算法必须看不到 ----------------------------------------
    old_pat = re.compile(r"^\s*native\s+\w+\s+(AI(?:Set)?Filter\w*)\s*\(")
    old_syms: set[str] = set()
    if OLD_SINGLE_FILE.exists():
        for line in OLD_SINGLE_FILE.read_text(encoding="utf-8",
                                              errors="replace").splitlines():
            m = old_pat.match(line)
            if m:
                old_syms.add(m.group(1))
    check(
        old_syms and ONLY_IN_OTHER_GALAXY not in old_syms,
        f"反向对照成立：round25 的单文件算法确实看不到 "
        f"{ONLY_IN_OTHER_GALAXY}（旧全集 {len(old_syms)} 个）",
        f"反向对照不成立 —— 单文件算法也能看到 {ONLY_IN_OTHER_GALAXY}，"
        f"说明本测试选的代表值没有区分力，是同义反复",
        problems,
    )

    # 顺带把差额报出来，让「多源并集多捞了多少」是可见的数字而不是信念。
    rx = re.compile(ledger.FAMILIES["aifilter"])
    new_syms = {s for s in universe if rx.match(s)}
    print(f"\n  aifilter 族：旧单文件算法 {len(old_syms)} 个 -> "
          f"多源并集 {len(new_syms)} 个（差额 {len(new_syms) - len(old_syms)}）")

    print()
    if problems:
        print("[ledger-src] FAILED —— 台账门禁的输入源已退化，"
              "它的绿灯不再可信")
        return 1
    print("[ledger-src] PASSED —— 族全集取数为多源并集，round25 盲区已封死")
    return 0


if __name__ == "__main__":
    sys.exit(main())
