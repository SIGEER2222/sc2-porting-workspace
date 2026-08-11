# -*- coding: utf-8 -*-
"""
extend_round27b.py — 收口 round27 台账扩围后暴露的 74 个幽灵项

## 背景

`check_native_ledger.py` 本轮早些时候从「只管 aifilter 一族」扩到 14 族。
扩范围是对的，但扩完没复跑门禁 —— 于是 74 个「既没封装也没登记拒绝」的
引擎符号一次性浮出水面，门禁红着放了半轮。

**扩了范围就得当场承担新暴露的洞**，否则下一个人看到的是一条常红的链，
常红和常绿一样会被无视。

## 这个脚本做什么

对每个幽灵项：

  1. **范围前置校验**（血泪来源：StatEvent / Tactical）
     只封**声明在 `natives.galaxy` 里**的符号。理由是编译期的硬约束：
     Galaxy 调用未声明函数是编译错误，而编译错误在 SC2 上的表现是
     **静默丢弃整个 MapScript** —— 不报错、不写日志、InitMap 不被调用。
     所以判据必须落在"编译器看不看得见这个声明"，而不是"引擎有没有这个符号"。

     两类典型的坑都会被这条挡住：
       - `natives_missing.galaxy`：社区补录的"引擎里有、Blizzard 忘了声明"清单。
         符号可能真的存在，但 core 不 include 它，封了就是未声明调用。
       - `AI.galaxy` / `Tactical/*.galaxy`：那是**库函数**不是 native，
         要额外 include 才有，core 默认链上没有。

     注意这里刻意**没有**用 `NativeLib.TriggerLib` 的 `<FlagNative/>` 当判据：
     实测 `PointFromId` / `OrderSetPlayer` 这些在 natives.galaxy 里白纸黑字
     声明着，却根本不在 FlagNative 集合里 —— 那张表是**GUI 触发器编辑器的
     函数目录**（决定"编辑器里点得到"），不是"脚本调不调得了"。
     拿它当拒绝理由等于往台账里写假话，比不写还糟。

     再叠一条：签名取不到就不封，宁可登记也不生成一个没法验证的转发。
  2. **就近落模块**：不靠人拍脑袋决定放哪个文件，而是统计"这一族的 native
     现在主要被哪个模块调用"，落到票数最高的那个模块。族第一次入库时
     没有票数，才回落到人工映射表。
  3. **生成守门 + 转发**：句柄形参一律 null 早退，返回零值。
     刻意**不**对 string 形参做空串守门 —— 空串对 StringReplace 之类是
     合法输入，一刀切守门会造出"看起来能调、实际永远不生效"的死分支，
     那正是本轮 marker 事件要治的病，不能换个地方再犯一次。

幂等：函数名已在头文件里出现过就跳过。

    python extend_round27b.py
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import check_native_ledger as led  # noqa: E402

CMLIB = HERE / "scripts" / "cmlib"

PRIMS = {"void", "int", "fixed", "bool", "string", "byte", "char"}
# color 是值类型，和 null 比较编译不过（round22 踩过）。
NO_NULL_GUARD = {"color"}

ZERO = {"void": None, "int": "0", "fixed": "0.0", "bool": "false", "string": '""'}

# 族第一次入库、没有历史票数时的回落映射。
FALLBACK_MODULE = {
    "board": "board", "vpanel": "panel", "objective": "panel", "timer": "panel",
    "aifilter": "ai", "aistock": "stock", "order": "unit", "catalog": "catalog",
    "point": "geo", "region": "geo", "string": "text", "cinematic": "fx",
    "transmiss": "text", "statevent": "stat",
}

SIG_RE = re.compile(
    r"^[ \t]*native\s+([\w\[\]<>]+)\s+(\w+)\s*\(([^)]*)\)\s*;", re.M)

# 唯一允许封装的声明文件：core 编译链上真正可见的那一份。
SAFE_DECL = "natives.galaxy"


def _strip_comments(text: str) -> str:
    """剥掉 // 与 /// 行尾注释。

    必须在正则之前做：`natives_missing.galaxy` 的多行声明每个形参后面都挂着
    `/// * Filter :: aifilter` 这样的文档注释，不剥的话形参会被解析成 `/// *`，
    生成出来的封装形参表全是垃圾（干跑时实测过一次）。
    """
    return "\n".join(ln.split("//", 1)[0] for ln in text.splitlines())


def engine_signatures() -> dict[str, tuple[str, str, list[tuple[str, str]]]]:
    """符号名 -> (声明文件名, 返回类型, [(形参类型, 形参名)])。"""
    out: dict[str, tuple[str, str, list[tuple[str, str]]]] = {}
    for f in led._decl_sources():
        if not f.exists():
            continue
        body = _strip_comments(f.read_text(encoding="utf-8", errors="replace"))
        for m in SIG_RE.finditer(body):
            ret, name, raw = m.group(1), m.group(2), m.group(3)
            params: list[tuple[str, str]] = []
            for i, chunk in enumerate(raw.split(",")):
                toks = chunk.split()
                if len(toks) >= 2:
                    params.append((toks[0], toks[1]))
                elif len(toks) == 1 and toks[0] not in ("void", ""):
                    params.append((toks[0], f"lp_a{i}"))
            out.setdefault(name, (f.name, ret, params))
    return out


def module_votes(family_rx: str) -> Counter:
    """这一族的 native 现在主要被哪个模块调用（数据驱动决定落点）。"""
    rx = re.compile(family_rx)
    votes: Counter = Counter()
    for f in sorted(CMLIB.glob("cmlib_*.galaxy")):
        if f.name.endswith("_h.galaxy"):
            continue
        mod = f.stem[len("cmlib_"):]
        if not mod:
            continue
        body = f.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"\b(\w+)\s*\(", body):
            if rx.match(m.group(1)):
                votes[mod] += 1
    return votes


def wrapper_name(sym: str, taken: set[str]) -> str:
    name = "CMLib_" + sym
    if name not in taken:
        return name
    n = 2
    while f"{name}{n}" in taken:
        n += 1
    return f"{name}{n}"


def render(sym: str, ret: str, params: list[tuple[str, str]], fn: str) -> tuple[str, str]:
    """返回 (声明行, 实现块)。"""
    plist = ", ".join(f"{t} {n}" for t, n in params) if params else ""
    decl = f"{ret} {fn}({plist});"

    guards: list[str] = []
    zero = ZERO.get(ret, "null")
    for t, n in params:
        if t in PRIMS or t in NO_NULL_GUARD:
            continue
        guards.append(f"    if ({n} == null) {{ "
                      + ("return;" if ret == "void" else f"return {zero};")
                      + " }")
    call = f"{sym}(" + ", ".join(n for _t, n in params) + ")"
    body = "\n".join(guards)
    if body:
        body += "\n"
    if ret == "void":
        body += f"    {call};"
    else:
        body += f"    return {call};"
    impl = f"{ret} {fn}({plist}) {{\n{body}\n}}"
    return decl, impl


def main() -> int:
    sigs = engine_signatures()
    existing_h = {}
    for f in sorted(CMLIB.glob("*_h.galaxy")):
        existing_h[f.name] = f.read_text(encoding="utf-8", errors="replace")
    taken = set(re.findall(r"\b(CMLib_\w+)\s*\(", "\n".join(existing_h.values())))

    universe, _decl_only, _flag_set = led.engine_symbol_universe()
    called = led.called_symbols(universe)
    rejected = set(led.registered_rejects())

    plan: dict[str, list[tuple[str, str]]] = {}      # module -> [(decl, impl)]
    rejects: dict[str, list[str]] = {}               # module -> [reject 行]
    stats = Counter()

    for fam in sorted(led.FAMILIES):
        rx = re.compile(led.FAMILIES[fam])
        ghosts = sorted(s for s in universe
                        if rx.match(s) and s not in called and s not in rejected)
        if not ghosts:
            continue
        votes = module_votes(led.FAMILIES[fam])
        mod = votes.most_common(1)[0][0] if votes else FALLBACK_MODULE.get(fam, "core")

        for sym in ghosts:
            info = sigs.get(sym)
            if info is None:
                rejects.setdefault(mod, []).append(
                    f"// @ledger-reject {sym} 引擎声明源里取不到完整签名，"
                    f"无法生成可验证的封装（round27b 自动登记）")
                stats["reject_nosig"] += 1
                continue
            declfile, ret, params = info
            # ---- 范围前置校验：core 编译链看不见的声明一律不封 ----------------
            if declfile.lower() != SAFE_DECL:
                rejects.setdefault(mod, []).append(
                    f"// @ledger-reject {sym} 声明只出现在 {declfile}，"
                    f"不在 core 编译链可见的 natives.galaxy 里；"
                    f"调用未声明函数是编译错误，而 SC2 对编译错误的反应是"
                    f"静默丢弃整个 MapScript（round27b 范围前置校验）")
                stats["reject_scope"] += 1
                continue
            fn = wrapper_name(sym, taken)
            taken.add(fn)
            plan.setdefault(mod, []).append(render(sym, ret, params, fn))
            stats["wrap"] += 1

    if not plan and not rejects:
        print("[round27b] 没有待收口项")
        return 0

    banner = ("\n// ===========================================================\n"
              "// round27b：台账扩围后的收口批次\n"
              "// 逐条经过范围前置校验（只封 natives.galaxy 里声明的符号）。\n"
              "// 句柄形参一律 null 早退；string 形参**刻意不做空串守门** ——\n"
              "// 空串对 StringReplace 之类是合法输入，一刀切会造出死分支。\n"
              "// ===========================================================\n")

    dry = "--dry" in sys.argv
    if dry:
        print("\n[dry-run] 只预览，不落盘\n")
        for mod in sorted(set(plan) | set(rejects)):
            print(f"--- cmlib_{mod} : 封装 {len(plan.get(mod, []))} / "
                  f"登记 {len(rejects.get(mod, []))}")
            for d, _i in plan.get(mod, [])[:4]:
                print("      " + d)
            if len(plan.get(mod, [])) > 4:
                print(f"      ... 另 {len(plan[mod]) - 4} 条")
            for r in rejects.get(mod, [])[:3]:
                print("      " + r[:120])
        print(f"\n[dry-run] 合计 封装 {stats['wrap']} / 范围外 {stats['reject_scope']}"
              f" / 无签名 {stats['reject_nosig']}")
        return 0

    touched = []
    for mod in sorted(set(plan) | set(rejects)):
        h = CMLIB / f"cmlib_{mod}_h.galaxy"
        c = CMLIB / f"cmlib_{mod}.galaxy"
        if not h.exists() or not c.exists():
            print(f"  !! 模块文件缺失，跳过: {mod}")
            continue
        decls = [d for d, _i in plan.get(mod, [])]
        impls = [i for _d, i in plan.get(mod, [])]
        rj = rejects.get(mod, [])

        if decls or rj:
            with h.open("a", encoding="utf-8") as fh:
                fh.write(banner)
                for line in rj:
                    fh.write(line + "\n")
                if rj and decls:
                    fh.write("\n")
                for d in decls:
                    fh.write(d + "\n")
            touched.append(h.name)
        if impls:
            with c.open("a", encoding="utf-8") as fh:
                fh.write(banner)
                fh.write("\n\n".join(impls) + "\n")
            touched.append(c.name)
        print(f"  + cmlib_{mod}: 封装 {len(decls)} / 登记拒绝 {len(rj)}")

    print(f"\n[round27b] 封装 {stats['wrap']} 个 / "
          f"范围外登记 {stats['reject_scope']} 个 / "
          f"无签名登记 {stats['reject_nosig']} 个，改动 {len(touched)} 文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
