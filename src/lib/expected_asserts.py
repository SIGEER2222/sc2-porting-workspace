# -*- coding: utf-8 -*-
"""断言会计（branch-aware assertion accounting）—— round22。

**要解决的问题**

真机 runner 长期报「断言通过 509/511」，差值 2 一直被 README / 自动化记忆
解释成「事件处理器内断言未触发（OnReaverTargetDied 类）」。

round22 逐点核查推翻了这个归因：selftest 的 **511 个 Mark 点全部位于
`CMLibTest_Deferred`(499) 与 `CMLibTest_AIDeferred`(12) 两个函数内**，
任何事件处理器里一个断言都没有。真实成因是两组 **if/else 互斥对**：

    if (lv_r19s != "")            -> "unit.abilcmd.ability.roundtrip"
    else                          -> "unit.abilcmd.skipped.nocatalog"

    if (CMLib_PlayerIsComputer(2))-> "ai.state.read"
    else                          -> "ai.state.skipped.nocomputer"

每组静态 2 个点、运行时必然只走 1 个 —— 静态 511、运行时 509，分毫不差。

**为什么值得单独一个模块**

含糊的「下限哨兵」会吞掉真实退化：只要执行数比静态少，判定一律说"多半是
未触发事件断言"，那么**真丢了 2 条断言**和**结构性互斥少 2 条**长得一模一样。
把互斥对精确算出来之后，期望值变成可判等的确定数，任何一条真丢失都会立刻
表现为 `执行数 != 期望数`，证据链不再有解释不清的残差。

**输出的三个量**

- ``sites``      : 静态 Mark 调用点总数（老口径，511）
- ``exclusive``  : 互斥分支扣减数（确定可扣的，2）
- ``expected``   : 分支感知期望执行数 = sites - exclusive（509）

另外报告 ``loop_sites``：位于 for/while 体内的 Mark 点。这类点运行时会**多**
执行（历史上 round13 的「158 vs 152」正是此类），一旦出现就不能再判等，
必须退化成区间判定 —— 所以要显式检出而不是默默算错。
"""

from __future__ import annotations

import os
import re
import sys
from typing import Dict, List, Tuple

# 控制台编码自卫（round24）：本文件会打印 '⚠'(U+26A0)，GBK 编不出来 ->
# UnicodeEncodeError -> 调用方把「打印崩了」误读成「断言会计算错了」。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

MARK_RE = re.compile(r"\bCMLibTest_Mark(?:Tag)?\s*\(")
MARK_DEF_RE = re.compile(r"\bvoid\s+CMLibTest_Mark(?:Tag)?\s*\(")
TAG_RE = re.compile(r"CMLibTest_MarkTag\s*\([^;]*?\"([^\"]+)\"")


def _strip_comments(text: str) -> str:
    """去注释但**保持行号与字符偏移不变**。

    直接 re.sub 掉注释会让后续的行号定位全部错位，诊断信息就没法用了；
    这里把注释内容替换成等长空格，偏移与行结构原样保留。
    """
    out = []
    i, n = 0, len(text)
    in_line = in_block = in_str = False
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line:
            if c == "\n":
                in_line = False
                out.append(c)
            else:
                out.append(" ")
        elif in_block:
            if c == "*" and nxt == "/":
                in_block = False
                out.append("  ")
                i += 2
                continue
            out.append("\n" if c == "\n" else " ")
        elif in_str:
            out.append(c)
            if c == "\\" and nxt:
                out.append(nxt)
                i += 2
                continue
            if c == '"':
                in_str = False
        else:
            if c == "/" and nxt == "/":
                in_line = True
                out.append("  ")
                i += 2
                continue
            if c == "/" and nxt == "*":
                in_block = True
                out.append("  ")
                i += 2
                continue
            if c == '"':
                in_str = True
            out.append(c)
        i += 1
    return "".join(out)


def _match_block(text: str, open_idx: int) -> int:
    """返回与 text[open_idx]=='{' 配对的 '}' 的下标；找不到返回 -1。

    字符串字面量里的花括号必须跳过，否则一个 `"{"` 就能把整棵块结构算歪。
    """
    depth = 0
    i, n = open_idx, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _count_marks(seg: str) -> int:
    return len(MARK_RE.findall(seg)) - len(MARK_DEF_RE.findall(seg))


def _tags_in(seg: str) -> List[str]:
    return TAG_RE.findall(seg)


def analyze(src_path: str) -> Dict:
    """分析 selftest 源码，返回断言会计结果。"""
    try:
        raw = open(src_path, encoding="utf-8", errors="replace").read()
    except OSError as exc:
        return {
            "ok": False, "error": str(exc), "sites": 0,
            "exclusive": 0, "expected": 0, "pairs": [], "loop_sites": [],
        }

    text = _strip_comments(raw)
    sites = _count_marks(text)

    line_of = [0] * (len(text) + 1)
    ln = 1
    for i, ch in enumerate(text):
        line_of[i] = ln
        if ch == "\n":
            ln += 1
    line_of[len(text)] = ln

    # ---- 1) 互斥 if/else 对 ----
    # 只认「if 体与 else 体都含 Mark」的对：那才会造成静态多计。
    # `else if` 链按最内层展开处理（else 体本身又是一个 if 语句，递归匹配）。
    pairs: List[Dict] = []
    for m in re.finditer(r"\belse\b", text):
        j = m.end()
        while j < len(text) and text[j] in " \t\r\n":
            j += 1
        if j >= len(text) or text[j] != "{":
            continue  # `else if (...)` 形态：其内部的 if 会被本循环单独遍历到
        else_close = _match_block(text, j)
        if else_close < 0:
            continue

        # 反向找到与本 else 配对的 if 体（else 之前紧邻的 '}'）
        k = m.start() - 1
        while k >= 0 and text[k] in " \t\r\n":
            k -= 1
        if k < 0 or text[k] != "}":
            continue
        depth = 0
        p = k
        if_open = -1
        while p >= 0:
            if text[p] == "}":
                depth += 1
            elif text[p] == "{":
                depth -= 1
                if depth == 0:
                    if_open = p
                    break
            p -= 1
        if if_open < 0:
            continue
        # 该 '{' 之前必须真是一个 if(...) 头，排除裸块 / 函数体误配
        head = text[max(0, if_open - 400):if_open]
        if not re.search(r"\bif\s*\([^;{}]*\)\s*$", head, re.S):
            continue

        if_body = text[if_open + 1:k]
        else_body = text[j + 1:else_close]
        a, b = _count_marks(if_body), _count_marks(else_body)
        if a == 0 or b == 0:
            continue  # 只有一侧有断言 -> 静态计数本就等于最坏情况，无需扣减

        pairs.append({
            "line_if": line_of[if_open],
            "line_else": line_of[j],
            "if_marks": a,
            "else_marks": b,
            "if_tags": _tags_in(if_body),
            "else_tags": _tags_in(else_body),
            # 确定可扣：无论走哪条分支，至少 min(a,b) 个点必不执行
            "deduct_certain": min(a, b),
            "deterministic": a == b,
        })

    exclusive = sum(p["deduct_certain"] for p in pairs)
    deterministic = all(p["deterministic"] for p in pairs)

    # ---- 2) 循环体内的 Mark（会让运行时**多**跑）----
    loop_sites: List[Tuple[int, int]] = []
    for m in re.finditer(r"\b(for|while)\s*\(", text):
        p = text.find("{", m.end())
        if p < 0:
            continue
        close = _match_block(text, p)
        if close < 0:
            continue
        c = _count_marks(text[p + 1:close])
        if c:
            loop_sites.append((line_of[m.start()], c))

    return {
        "ok": True,
        "sites": sites,
        "exclusive": exclusive,
        "expected": sites - exclusive,
        "deterministic": deterministic and not loop_sites,
        "pairs": pairs,
        "loop_sites": loop_sites,
    }


def describe(res: Dict) -> str:
    if not res.get("ok"):
        return f"断言会计不可用：{res.get('error')}"
    out = [f"静态调用点 {res['sites']} - 互斥分支 {res['exclusive']} "
           f"= 期望执行 {res['expected']}"
           f"{'（确定值）' if res['deterministic'] else '（非确定，见下）'}"]
    for p in res["pairs"]:
        out.append(
            f"  互斥对 L{p['line_if']}/else L{p['line_else']}: "
            f"if={p['if_marks']}({','.join(p['if_tags']) or '-'}) "
            f"else={p['else_marks']}({','.join(p['else_tags']) or '-'}) "
            f"-> 扣 {p['deduct_certain']}")
    for ln, c in res["loop_sites"]:
        out.append(f"  ⚠ 循环体内断言 L{ln} x{c} —— 运行时会多执行，期望值退化为下限")
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        here, "selftest", "cmlib_selftest.galaxy")
    print(describe(analyze(path)))
