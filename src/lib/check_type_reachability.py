# -*- coding: utf-8 -*-
"""
check_type_reachability.py — 句柄类型可达性门禁（round27 建立）

## 起因：一个两道门禁都看不见的洞

round25 把 `AISetFilterMarker` / `AISetFilterLifePerMarker` 封装入库，
签名里收 `marker` 句柄：

    void CMLib_AIFilterMarkerCount(aifilter f, int min, int max, marker m);
    void CMLib_AIFilterLifePerMarker(aifilter f, fixed each, marker m);

问题是 —— **整个公开 API 里没有任何一个函数返回 `marker`**。
引擎的 marker 生产端（`Marker` / `MarkerCastingUnit` / `MarkerCastingPlayer`
/ `UnitMarker` / `DataTableGetMarker`）一个都没封。

于是这两个函数只能被喂 `null`，而它们的守门恰好是「marker 为 null 就忽略」。
调用方无论怎么用都只会拿到一条告警日志。**封装存在、接口可编译、永远无效**
—— 这是 round23「可调用 ≠ 可用」的第三种形态：**可编译 ≠ 可达**。

更要命的是覆盖它的两条 selftest 断言也是恒绿的：

    CMLib_AIFilterMarkerCount(f, 0, 1000, null);   // 断言结果不变
    CMLib_AIFilterLifePerMarker(f, 100.0, null);   // 断言结果不变

真机 selftest 环境里从没放置过任何 mark，所以「库跳过了调用」和
「库调了但引擎零标记时本就是空操作」**结果完全一样**，断言分不出来。
守门被删掉它也照样绿 —— 判据坏死形态②（同义反复），自己的方法论笔记里写过。

## 为什么已有的两道门禁抓不到

| 门禁 | 视角 | 为什么漏 |
|---|---|---|
| `check_native_ledger.py` | 族**内**逐符号：每个 native 要么封装要么登记拒绝 | 它只问「族里的符号有没有交代」。marker 族压根没纳管，不在它视野里 |
| `ledger_survey.py` | 按族**缺口大小**决定纳不纳管（gap <= 12） | marker 族 gap=17 被判「暂不纳管」。可它的两个**消费端已经入库了** —— 缺口大小这个维度看不见跨族依赖 |

两道门禁都是**沿着「族」这条轴**切的，而这个洞是**沿着「类型」这条轴**的：
> 已封装函数的形参类型，库自己造得出来吗？

轴不对，再密的网也漏。

## 判据

    A = 公开 API 形参里出现的引擎句柄类型
    B = 公开 API 返回值里出现的引擎句柄类型          <- 库自己的生产端
    C = 头文件显式登记「由调用方自备」的类型          <- 唯一需要人写的部分

要求 **A ⊆ B ∪ C**。落空的就是不可达类型。

沿用 `check_native_ledger.py` 被验证过的结构：两个集合自动推导、
一个集合人写，且强制人写的那个精确覆盖差集 —— 想漏都漏不掉。

「引擎句柄类型」不靠人肉名单，而是从官方 native 签名里取全部类型名
再减掉 Galaxy 基本类型，纯机械。

## 登记语法

    // @type-external unit 调用方从事件响应 / UnitCreate 带入，库不负责生产

## 报告里为什么要带「引擎生产端 N 个 / 库已封 M 个」

这是给人做判断的证据，决定一个洞该往哪边收口：

* `marker`：引擎 5 个生产端、库封 0 个  -> 该补封装（真洞）
* `unit`  ：引擎几十个生产端，调用方本来就随手可得 -> 该登记 external

没有这两列，人只能拍脑袋，而拍脑袋的清单就会变回 round25 要治的那种。

## 用法

    python check_type_reachability.py
退出码: 0 = 通过, 1 = 存在未交代的不可达类型
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

# Galaxy 基本类型。除此之外出现在 native 签名里的都算引擎句柄类型。
# 不写「句柄有哪些」而写「基本类型有哪些」—— 前者会随引擎版本漂移且必然漏记，
# 后者是语言层面的、封闭且稳定的。
PRIMITIVES = {"void", "int", "fixed", "bool", "string", "byte", "char"}

NATIVE_RE = re.compile(r"^\s*native\s+([\w\[\]<>]+)\s+(\w+)\s*\(([^;]*)\)\s*;")
DECL_RE = re.compile(r"(\w+)\s+(CMLib_\w+)\s*\(([^)]*)\)\s*;", re.S)
EXTERNAL_RE = re.compile(r"//\s*@type-external\s+(\w+)\s+(.+?)\s*$")

# 源完整性下限：读不到足量 native 说明参考树没铺开，
# 此时「句柄类型全集」会缩水成一个看起来全绿的子集 —— 必须 fail-closed。
MIN_NATIVES = 2000


def _strip_comments(text: str) -> str:
    return "\n".join(ln.split("//", 1)[0] for ln in text.splitlines())


def _decl_sources() -> list[Path]:
    srcs = [TRIG / "natives.galaxy", TRIG / "natives_missing.galaxy"]
    srcs += sorted((TRIG / "GameData").glob("*.galaxy"))
    srcs += sorted(TRIG.glob("*.galaxy"))
    srcs += sorted((TRIG / "Tactical").glob("*.galaxy"))
    return srcs


def engine_natives() -> list[tuple[str, str, list[str]]]:
    """返回 [(返回类型, 符号名, [形参类型...])]，跨全部官方声明源去重。"""
    seen: set[str] = set()
    out: list[tuple[str, str, list[str]]] = []
    for p in _decl_sources():
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = NATIVE_RE.match(line)
            if not m:
                continue
            ret, name, raw = m.group(1), m.group(2), m.group(3)
            if name in seen:
                continue
            seen.add(name)
            ptypes = []
            for chunk in raw.split(","):
                toks = chunk.split()
                if len(toks) >= 2:
                    ptypes.append(toks[0])
            out.append((ret, name, ptypes))
    return out


def handle_types(natives: list[tuple[str, str, list[str]]]) -> set[str]:
    """引擎句柄类型全集 = native 签名里出现的所有类型 - Galaxy 基本类型。"""
    out: set[str] = set()
    for ret, _name, ptypes in natives:
        for t in [ret] + ptypes:
            if t not in PRIMITIVES:
                out.add(t)
    return out


def public_api() -> list[tuple[str, str, list[str], str]]:
    """扫全部 _h 头文件，返回 [(返回类型, 函数名, [形参类型...], 文件名)]。

    声明可能跨行（形参表换行），所以先剥注释再对整篇文本做正则，
    不能逐行匹配 —— 逐行会把跨行声明整条漏掉，而漏掉的恰恰是形参最多的那些。
    """
    out: list[tuple[str, str, list[str], str]] = []
    for f in sorted(CMLIB.glob("*_h.galaxy")):
        body = _strip_comments(f.read_text(encoding="utf-8", errors="replace"))
        for m in DECL_RE.finditer(body):
            ret, name, raw = m.group(1), m.group(2), m.group(3)
            ptypes = []
            for chunk in raw.split(","):
                toks = chunk.split()
                if len(toks) >= 2:
                    ptypes.append(toks[0])
            out.append((ret, name, ptypes, f.name))
    return out


def wrapped_natives(symbols: set[str]) -> set[str]:
    """哪些 native 真的在实现里被调用了（口径与 check_native_ledger 一致）。"""
    out: set[str] = set()
    for f in sorted(CMLIB.glob("*.galaxy")):
        if f.name.endswith("_h.galaxy"):
            continue
        body = _strip_comments(f.read_text(encoding="utf-8", errors="replace"))
        for s in symbols:
            if s in out:
                continue
            if re.search(r"\b" + re.escape(s) + r"\s*\(", body):
                out.add(s)
    return out


def registered_external() -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for f in sorted(CMLIB.glob("*_h.galaxy")):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = EXTERNAL_RE.search(line)
            if m:
                out[m.group(1)] = (m.group(2).strip(), f.name)
    return out


def main() -> int:
    print("=" * 78)
    print("[types] 句柄类型可达性：公开 API 收的每种句柄，"
          "库自己造得出来 或 显式登记调用方自备")
    print("=" * 78)

    natives = engine_natives()
    if len(natives) < MIN_NATIVES:
        print(f"\nFAIL  [源] 只读到 {len(natives)} 个 native"
              f"（下限 {MIN_NATIVES}），参考树可能没铺开")
        print("[types] FAILED —— 输入不完整，fail-closed")
        return 1

    handles = handle_types(natives)
    api = public_api()
    print(f"  引擎 native {len(natives)} 个 / 句柄类型 {len(handles)} 种 / "
          f"公开 API {len(api)} 个函数")

    consumed: dict[str, list[str]] = {}
    produced: set[str] = set()
    for ret, name, ptypes, _f in api:
        if ret in handles:
            produced.add(ret)
        for t in ptypes:
            if t in handles:
                consumed.setdefault(t, []).append(name)

    external = registered_external()
    holes = sorted(set(consumed) - produced - set(external))
    blank = sorted(t for t, (why, _) in external.items()
                   if t in consumed and not why)
    # 登记了却根本没被消费 —— 类型改名或登记过期。
    stale = sorted(set(external) - set(consumed))

    print(f"  形参消费 {len(consumed)} 种 / 库内生产 {len(produced & set(consumed))} 种 / "
          f"登记外部供给 {len(set(external) & set(consumed))} 种")

    if holes:
        # 按引擎生产端数量排序：生产端越少越像「该补封装」，越多越像「调用方自备」。
        by_ret: dict[str, list[str]] = {}
        for ret, name, _p in natives:
            if ret in handles:
                by_ret.setdefault(ret, []).append(name)
        wrapped = wrapped_natives({n for lst in by_ret.values() for n in lst})

        print()
        print(f"  {'不可达类型':<20}{'引擎生产端':>10}{'库已封':>8}  被谁消费")
        print("  " + "-" * 74)
        for t in sorted(holes, key=lambda x: len(by_ret.get(x, []))):
            prods = by_ret.get(t, [])
            mine = [n for n in prods if n in wrapped]
            users = ", ".join(sorted(set(consumed[t]))[:3])
            more = "" if len(set(consumed[t])) <= 3 else " ..."
            print(f"  {t:<20}{len(prods):>10}{len(mine):>8}  {users}{more}")

    print()
    problems: list[str] = []
    if holes:
        problems.append(f"不可达句柄类型 {len(holes)} 种"
                        f"（形参收它，但库不产它、也没登记外部供给）："
                        + ", ".join(holes))
    if blank:
        problems.append(f"登记理由为空 {len(blank)} 种：" + ", ".join(blank))
    if stale:
        problems.append(f"过期登记 {len(stale)} 种"
                        f"（登记了外部供给，但公开 API 根本不收这个类型）："
                        + ", ".join(stale))

    if problems:
        print("-" * 78)
        for p in problems:
            print("FAIL  " + p)
        print("-" * 78)
        print("[types] FAILED —— 要么补生产端封装，"
              "要么加一行 // @type-external <类型> <理由>")
        return 1
    print("[types] PASSED —— 公开 API 收的每种句柄类型都可达")
    return 0


if __name__ == "__main__":
    sys.exit(main())
