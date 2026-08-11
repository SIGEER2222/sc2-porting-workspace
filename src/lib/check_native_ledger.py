# -*- coding: utf-8 -*-
"""
check_native_ledger.py — 原生符号台账门禁（round25 建立，round26 修盲区并扩族）

## 为什么要有这个门禁

round24 在 `cmlib_ai_h.galaxy` 里手工维护了三份清单：
「已验可用」「未获证据故意不封装」「坐实不可用」。round25 复查时发现
`AISetFilterMelee` **三份清单里一份都没有** —— 它在探针的 callall 档里其实被
调用过，只是记录的时候整个漏掉了。

讽刺的是补测之后它成了整个 aifilter 族里**唯一拿到双向证据**的条件。
一个证据最硬的符号，因为手工记账漏项，白白多等了一轮才入库。

> 这和 round9 那条「模块清单一律从聚合入口自动推导，禁止手抄」是同一条铁律，
> 只不过那次漏的是模块，这次漏的是 native。**凡是手工维护的清单都会漏，
> 区别只在什么时候漏、漏了多久才被发现。**

## round26 修的盲区：门禁自己也在用人肉名单

round25 版本的 FAMILIES 给每个族配了**一个**引擎声明文件：

    "aifilter": (GAMEDATA/"TriggerLibs"/"Tactical"/"TacticalAI.galaxy", ...)

于是门禁自报「引擎 24 个 / 全部有交代 / PASSED」。但 aifilter 族真实是 **25** 个 ——
`AISetFilterEnergy` 声明在 `natives_missing.galaxy`，不在配置的那个文件里，
门禁**根本没把它算进全集**，自然也就不会报它是幽灵项。

治「人肉名单会漏」的门禁，自己的输入源清单是人肉写的，于是同样漏了。
判据的输入不全，结论就是假绿 —— **恒绿等于没有校验器**。

更狠的是来源不止一处会漏：`AISetStockAlias` / `AISetStockFree` 连 `.galaxy`
的 `native` 声明都没有，只在 `NativeLib.TriggerLib` 里带 `<FlagNative/>`
（round22 已确认：SC2 的 native 符号表是引擎内建的，`.galaxy` 的 `native`
声明只是编辑器/lint 元数据）。只扫 `.galaxy` 一样会漏。

所以 round26 起：**族全集 = 全部引擎 .galaxy 声明 ∪ 全部 `<FlagNative/>`**，
FAMILIES 里不再出现任何文件路径，只留正则。想漏都没地方漏。
这条性质由 `test_ledger_sources.py`（门禁的门禁）钉住。

## 判据

对每个受管的 native 族，把三个集合摆出来：

    A = 引擎声明的族全集      <- 多源并集自动推导
    B = CMLib 实现里实际调用的 <- 从 scripts/cmlib/*.galaxy 自动推导
    C = 头文件里显式登记「拒绝封装」的  <- 唯一需要人写的部分

要求：**A == B ∪ C 且 B ∩ C == ∅**。展开成四条可报告的失败：

    ghost      属于 A，却既不在 B 也不在 C  -> 幽灵项，正是 round25/26 踩的坑
    conflict   同时在 B 和 C 里             -> 说了拒绝又调用了，台账自相矛盾
    stale      在 C 里却不属于任何受管族 A   -> 引擎侧已无此符号，清单过期
    blank      登记了却没写理由              -> 等于没登记

只有 C 需要人维护，而门禁强制 C 必须精确覆盖 A\\B —— 想漏记都漏不掉：
新增一个 native 却不封装也不登记，立刻报 ghost。

## 受管范围的诚实边界

只纳管「CMLib 已经有成员入库」且「缺口小到每一行 reject 都值得动脑子」的族。
一个族引擎有 300 个符号、库只封了 40 个，剩下 260 行 reject 没人会认真读，
写的时候就是复制粘贴 —— 那就是把 round25 要治的病换个文件放。
未纳管的族诚实留在 `ledger_survey.py` 的报告里，不假装闭环。

## 登记语法

在任意 `_h.galaxy` 头文件里写机器可解析的一行（理由给人看，但必须非空）：

    // @ledger-reject AISetFilterCanAttackEnemy 非单调响应，语义不可预测（round25 §12.2）

## 用法

    python check_native_ledger.py
退出码: 0 = 通过, 1 = 台账有洞
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
REPO = HERE.parent.parent
CMLIB = HERE / "scripts" / "cmlib"
GAMEDATA = (REPO / "reference" / "sc2mapster" / "SC2GameData" / "mods"
            / "core.sc2mod" / "base.sc2data")
TRIG = GAMEDATA / "TriggerLibs"

# 受管族：族名 -> 符号正则。
#
# 注意这里**没有文件路径** —— 那正是 round25 的盲区所在。族全集一律由
# engine_family_symbols() 从多源并集里筛，配置只负责回答「哪些名字算这一族」。
FAMILIES: dict[str, str] = {
    # 面板效果主线：计分板 / 胜利面板 / 任务目标 / 计时器窗口
    "board":     r"^Board\w+$",
    "vpanel":    r"^VictoryPanel\w+$",
    "objective": r"^Objective\w+$",
    "timer":     r"^Timer\w+$",
    # AI 主线
    "aifilter":  r"^AI(?:Set)?Filter\w*$",
    "aistock":   r"^AI(?:Enable|Clear|Set|Get)Stock\w*$",
    # 单位/建筑主线的下达与目录反射
    "order":     r"^Order\w+$",
    "catalog":   r"^Catalog\w+$",
    # 几何
    "point":     r"^Point\w+$",
    "region":    r"^Region\w+$",
    # 文本与叙事
    "string":    r"^String\w+$",
    "cinematic": r"^Cinematic\w+$",
    "transmiss": r"^Transmission\w+$",
    "statevent": r"^StatEvent\w+$",
}

NATIVE_RE = re.compile(r"^\s*native\s+[\w\[\]<>]+\s+(\w+)\s*\(")
REJECT_RE = re.compile(r"//\s*@ledger-reject\s+(\w+)\s+(.+?)\s*$")

# 源完整性下限。低于这个数说明参考树没铺开 / 路径写错，
# 此时族全集会缩水成一个「看起来全绿」的子集 —— 必须 fail-closed，
# 因为一个输入残缺的门禁比没有门禁更危险（它会给人已经检查过的错觉）。
MIN_DECL_SYMBOLS = 2000
MIN_FLAG_SYMBOLS = 2000


def _decl_sources() -> list[Path]:
    srcs: list[Path] = [TRIG / "natives.galaxy", TRIG / "natives_missing.galaxy"]
    srcs += sorted((TRIG / "GameData").glob("*.galaxy"))
    srcs += sorted(TRIG.glob("*.galaxy"))
    srcs += sorted((TRIG / "Tactical").glob("*.galaxy"))
    return srcs


def declared_natives() -> set[str]:
    """来源一：所有官方 .galaxy 里的 `native` 声明。"""
    out: set[str] = set()
    for p in _decl_sources():
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = NATIVE_RE.match(line)
            if m:
                out.add(m.group(1))
    return out


def flag_natives() -> set[str]:
    """来源二：NativeLib.TriggerLib 里带 <FlagNative/> 的 FunctionDef。

    round22 的结论：native 符号表是**引擎内建**的，`.galaxy` 的 `native`
    声明只是编辑器/lint 元数据。所以有些符号只有 FlagNative 背书而没有
    .galaxy 声明（如 AISetStockAlias / AISetStockFree），照样能调用。
    """
    p = TRIG / "NativeLib.TriggerLib"
    if not p.exists():
        return set()
    txt = p.read_text(encoding="utf-8", errors="replace")
    out: set[str] = set()
    for block in re.findall(r'<Element[^>]*Type="FunctionDef"[^>]*>(.*?)</Element>',
                            txt, re.S):
        if "<FlagNative" not in block:
            continue
        m = re.search(r"<Identifier>(\w+)</Identifier>", block)
        if m:
            out.add(m.group(1))
    return out


def engine_symbol_universe() -> tuple[set[str], set[str], set[str]]:
    """返回 (并集, 仅声明源, 仅 FlagNative 源)。"""
    decl = declared_natives()
    flag = flag_natives()
    return decl | flag, decl, flag


def called_symbols(symbols: set[str]) -> set[str]:
    """扫 CMLib 实现（不含 _h 头文件），看哪些符号真的被调用了。

    只认「符号名紧跟左括号」的形态，避免把注释里提到的名字算成调用 ——
    注释恰恰是最容易和事实脱节的地方，拿它当证据等于没门禁。
    """
    out: set[str] = set()
    for f in sorted(CMLIB.glob("*.galaxy")):
        if f.name.endswith("_h.galaxy"):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        body = "\n".join(ln.split("//", 1)[0] for ln in text.splitlines())
        for s in symbols:
            if s in out:
                continue
            if re.search(r"\b" + re.escape(s) + r"\s*\(", body):
                out.add(s)
    return out


def registered_rejects() -> dict[str, tuple[str, str]]:
    """扫描全部头文件收集拒绝登记 -> {符号: (理由, 出处文件名)}。

    不限定「哪个族必须登记在哪个头文件」—— 那种形式约束只会制造误报，
    而判定强度完全来自集合等式，与登记写在哪个文件无关。
    """
    out: dict[str, tuple[str, str]] = {}
    for f in sorted(CMLIB.glob("*_h.galaxy")):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = REJECT_RE.search(line)
            if m:
                out[m.group(1)] = (m.group(2).strip(), f.name)
    return out


def main() -> int:
    problems: list[str] = []
    print("=" * 78)
    print("[ledger] 原生符号台账：族内每个 native 必须"
          "「已封装」或「显式登记拒绝」，二选一")
    print("=" * 78)

    universe, decl, flag = engine_symbol_universe()
    print(f"  引擎符号来源：.galaxy 声明 {len(decl)} 个 ∪ "
          f"<FlagNative/> {len(flag)} 个 = 并集 {len(universe)} 个")

    # 源完整性 fail-closed —— 输入残缺的门禁比没门禁更危险。
    if len(decl) < MIN_DECL_SYMBOLS:
        problems.append(f"[源] .galaxy native 声明只读到 {len(decl)} 个"
                        f"（下限 {MIN_DECL_SYMBOLS}），参考树可能没铺开")
    if len(flag) < MIN_FLAG_SYMBOLS:
        problems.append(f"[源] <FlagNative/> 只读到 {len(flag)} 个"
                        f"（下限 {MIN_FLAG_SYMBOLS}），NativeLib.TriggerLib 可能缺失")
    if problems:
        print()
        for p in problems:
            print("FAIL  " + p)
        print("[ledger] FAILED —— 引擎符号来源不完整，fail-closed")
        return 1

    rejects = registered_rejects()
    all_family_syms: set[str] = set()
    total_engine = total_called = total_reject = 0

    print()
    print(f"  {'族':<11}{'引擎':>5}{'已封装':>7}{'拒绝':>5}{'覆盖':>8}  跨源补充")
    print("  " + "-" * 74)

    for fam in sorted(FAMILIES):
        rx = re.compile(FAMILIES[fam])
        fam_syms = {s for s in universe if rx.match(s)}
        if not fam_syms:
            problems.append(f"[{fam}] 正则在引擎符号并集里一个都没匹配到"
                            f" —— 族定义失效，fail-closed")
            continue
        all_family_syms |= fam_syms

        called = called_symbols(fam_syms)
        fam_rejects = {s: v for s, v in rejects.items() if s in fam_syms}

        ghost = sorted(fam_syms - called - set(fam_rejects))
        conflict = sorted(called & set(fam_rejects))
        blank = sorted(s for s, (why, _) in fam_rejects.items() if not why)

        # 跨源补充：只靠单一来源会漏掉的那些，正是 round25 的盲区形态。
        only_flag = sorted(fam_syms - decl)
        cover = 100.0 * len(called) / len(fam_syms)
        note = ("+" + ",".join(only_flag)) if only_flag else ""
        print(f"  {fam:<11}{len(fam_syms):>5}{len(called):>7}"
              f"{len(fam_rejects):>5}{cover:>7.1f}%  {note}")

        total_engine += len(fam_syms)
        total_called += len(called)
        total_reject += len(fam_rejects)

        if ghost:
            problems.append(f"[{fam}] 幽灵项 {len(ghost)} 个"
                            f"（既没封装也没登记拒绝）：" + ", ".join(ghost))
        if conflict:
            problems.append(f"[{fam}] 台账自相矛盾 {len(conflict)} 个"
                            f"（登记了拒绝却又在实现里调用）：" + ", ".join(conflict))
        if blank:
            problems.append(f"[{fam}] 拒绝理由为空 {len(blank)} 个"
                            f"（登记必须写明理由）：" + ", ".join(blank))

    # 登记了却不属于任何受管族 —— 引擎改名/删符号，或族正则写窄了。
    stale = sorted(set(rejects) - all_family_syms)
    if stale:
        problems.append("[全局] 过期登记 " + str(len(stale)) +
                        " 个（不属于任何受管族的引擎符号）：" + ", ".join(stale))

    print("  " + "-" * 74)
    print(f"  合计  受管 {len(FAMILIES)} 族 / 引擎 {total_engine} 个符号 / "
          f"已封装 {total_called} / 登记拒绝 {total_reject}")

    print()
    if problems:
        print("-" * 78)
        for p in problems:
            print("FAIL  " + p)
        print("-" * 78)
        print("[ledger] FAILED —— 台账有洞。要么封装它，"
              "要么加一行 // @ledger-reject <符号> <理由>")
        return 1
    print("[ledger] PASSED —— 受管族内无幽灵项、无矛盾、无过期登记")
    return 0


if __name__ == "__main__":
    sys.exit(main())
