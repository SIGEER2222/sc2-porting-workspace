#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""generated adapter 包「按目标地图编译单元」净化器 —— fail-closed 降级。

【为什么必须有】
Stage 26 的 adapter 包是针对 **完整 CMRE 依赖集** 的 `亡者之夜.SC2Map` 生成的；
把它整包塞进只带 5 个依赖的 standalone 测试图时，一部分 adapter 会引用编译单元里
根本不存在的符号（别的 mod 的 `libA3ADAPTER_*`、原图自带的 `libEFA54406_*`、
以及生成器发错名的伪 native `DateTime(...)` / `RevealerCreate(...)`）。

Galaxy 铁律：**任何一处未定义符号 ⇒ 整个 MapScript 编译失败 ⇒ SC2 静默丢弃**
（不报错、不写日志、InitMap 不执行、Kernel 永不注册）。所以哪怕只有 1 个坏
adapter，整张图就是死的 —— 这正是 gen 图 P0 长期全灭的真因。

净化策略（保签名、保 include 链闭合）：
  * 函数体引用了不可用符号 → 整个函数体替换成
    `return libVibeInvoke_gf_Error("FUNCTION_NOT_IN_MAP", "gen.<id>");`
    签名与原型完全不变，`_h` 与 DispatchShard 路由无需改动。
  * 只降级，不删除；调用方拿到明确错误码而不是静默超时。

引用提取要点（三条血泪，勿收窄）：
  1. `strip_noise` **必须保长**：analyze() 在 clean 上算 start/end，sanitize_text()
     却用这些偏移去切原始 text。注释/字符串换成等长空白才不会错位切坏文件。
  2. 取**全部裸标识符**（不止 `foo(` 调用）—— `libVibeInvoke_gf_ResolveFuncref`
     的 funcref 表全是 `return SomeFunc;`，只匹配 `foo(` 会整段漏掉。
  3. 不能把「`ident;` / `ident=` 形式」一律当局部变量豁免，否则第 2 点里的
     `return SomeFunc;` 又被放行 —— 只认真正的 `type name;` 声明式。
"""
from __future__ import annotations

import re

RE_LINE_COMMENT = re.compile(r"//[^\n]*")
RE_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
RE_STRLIT = re.compile(r'"(?:[^"\\\n]|\\.)*"')
RE_IDENT = re.compile(r"(?<![\w.])([A-Za-z_]\w*)")
RE_NUMSUF = re.compile(r"^\d")
# 函数定义起始行：<type> <name>(<params>) {
RE_FUNC = re.compile(
    r"^([A-Za-z_]\w*)[ \t]+([A-Za-z_]\w*)[ \t]*\(([^)]*)\)[ \t]*\{", re.M)
# 任意函数定义/原型（用于收集本文件自带符号）
RE_ANYFUNC = re.compile(
    r"^[ \t]*(?:static[ \t]+)?[A-Za-z_]\w*(?:\[\])?[ \t]+([A-Za-z_]\w*)[ \t]*\([^;{]*\)[ \t]*[;{]",
    re.M)
# 变量声明 `type name;` / `type name = ...` / `type[N] name;`
# 【勿删负向断言】没有它，`return SomeMissingFunc;` 会被当成「类型 变量;」声明，
# 于是 funcref 静态表里所有 `return XXX;` 引用的缺失函数全部漏检 —— 而那恰恰是
# 我们最需要抓的一类（gen 图静默丢弃 MapScript 的真凶就藏在这里）。
RE_DECL = re.compile(
    r"^[ \t]*(?:const[ \t]+|static[ \t]+)*"
    r"(?!(?:return|case|new|delete|else|do|goto|break|continue)[ \t])"
    r"[A-Za-z_]\w*(?:\[[^\]]*\])?[ \t]+"
    r"([A-Za-z_]\w*)(?:\[[^\]]*\])?[ \t]*[;=]", re.M)
RE_TYPEDEF = re.compile(r"^[ \t]*typedef[^;]*?([A-Za-z_]\w*)[ \t]*;", re.M)
RE_STRUCT = re.compile(r"^[ \t]*struct[ \t]+([A-Za-z_]\w*)", re.M)

LOCAL_PREFIXES = ("lv_", "lp_", "auto_", "auto")

# 只有这些开头的 `X Y(...) {` 不是函数定义（`else if (c) {` 会被 RE_FUNC 误命中）
CONTROL = {"if", "else", "while", "for", "do", "switch", "case", "return",
           "typedef", "break", "continue", "include", "native"}

# Galaxy 内建类型 + 控制关键字 + 字面量：永远「可用」，绝不该出现在 missing 里。
KEYWORDS: set[str] = {
    # 控制/修饰
    "if", "else", "while", "for", "do", "break", "continue", "return",
    "switch", "case", "default", "struct", "typedef", "const", "static",
    "include", "native", "new", "delete", "true", "false", "null",
    "funcref", "structref", "arrayref", "autodeclare", "goto", "sizeof",
    # 内建类型
    "void", "bool", "byte", "char", "int", "fixed", "string", "text",
    "color", "abilcmd", "actor", "actorscope", "aifilter", "bank", "bitmask",
    "camerainfo", "cooldown", "datetime", "doodad", "generichandle", "handle",
    "marker", "order", "playergroup", "point", "region", "revealer",
    "soundlink", "soundlinkid", "timer", "transmissionsource", "trigger",
    "unit", "unitfilter", "unitgroup", "unitref", "wave", "waveinfo",
    "wavetarget", "objective", "preset", "file", "actormsg", "charge",
    "soundtrack", "camerapath", "layout", "reply", "planet", "trigger",
}


def strip_noise(t: str) -> str:
    """剥注释与字符串字面量，**等长替换**（换行保留），保证偏移与原文一致。"""
    def blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))
    t = RE_BLOCK_COMMENT.sub(blank, t)
    t = RE_LINE_COMMENT.sub(blank, t)
    t = RE_STRLIT.sub(blank, t)
    return t


def file_symbols(clean: str) -> set[str]:
    """本文件自身提供的符号：函数名/原型名/全局变量/typedef/struct。"""
    syms: set[str] = set()
    syms |= set(RE_ANYFUNC.findall(clean))
    syms |= set(RE_DECL.findall(clean))
    syms |= set(RE_TYPEDEF.findall(clean))
    syms |= set(RE_STRUCT.findall(clean))
    return syms


def _span(t: str, start: int) -> int:
    """从函数定义起始位置找到匹配的右花括号（返回其后一位）。"""
    i = t.index("{", start)
    depth = 0
    while i < len(t):
        c = t[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(t)


def analyze(text: str, available: set[str]) -> list[dict]:
    """返回每个函数的 {name, rettype, start, end, missing} 列表。

    `available` = 目标图编译单元里已定义的符号集合（compile_unit.resolve 给出）。
    本文件自身定义的符号会自动并入，无需调用方预先塞。
    """
    clean = strip_noise(text)
    own = file_symbols(clean)
    ok = available | own | KEYWORDS
    out: list[dict] = []
    for m in RE_FUNC.finditer(clean):
        rt, name, params = m.group(1), m.group(2), m.group(3)
        if rt in CONTROL:
            continue  # `else if (x) {` 之类，不是函数定义
        end = _span(clean, m.start())
        body = clean[m.start():end]
        declared = set(RE_DECL.findall(body))
        param_names = set(re.findall(r"[A-Za-z_]\w*(?:\[\])?[ \t]+([A-Za-z_]\w*)", params))
        missing: set[str] = set()
        for ident in set(RE_IDENT.findall(body)):
            if (ident in ok or ident == name or ident in declared
                    or ident in param_names
                    or ident.startswith(LOCAL_PREFIXES)
                    or RE_NUMSUF.match(ident)):
                continue
            missing.add(ident)
        out.append({"name": name, "rettype": rt, "start": m.start(),
                    "end": end, "missing": sorted(missing)})
    return out


def _fail_closed(rt: str, name: str, params: str, missing: list[str]) -> str:
    gid = re.sub(r"^libVibeInvoke_gf_Call", "", name)
    why = ",".join(missing[:4]) + ("..." if len(missing) > 4 else "")
    head = f"{rt} {name} ({params}) {{"
    note = (f"    // [sanitizer] 目标图编译单元缺少: {why}\n"
            f"    // 保留签名以维持 _h 原型与 DispatchShard 路由闭合，仅降级为明确错误。")
    if rt == "string":
        ret = f'    return libVibeInvoke_gf_Error("FUNCTION_NOT_IN_MAP", "gen.{gid}");'
    elif rt == "void":
        ret = "    return;"
    elif rt == "int":
        ret = "    return 0;"
    elif rt == "bool":
        ret = "    return false;"
    elif rt == "fixed":
        ret = "    return 0.0;"
    else:
        ret = "    return null;"
    return f"{head}\n{note}\n{ret}\n}}"


# funcref 静态表的一行：`if (name == "X") { return X; }`
RE_TABLE_LINE = re.compile(
    r'^[ \t]*if[ \t]*\([ \t]*\w+[ \t]*==[ \t]*"[^"]*"[ \t]*\)[ \t]*\{'
    r'[ \t]*return[ \t]+([A-Za-z_]\w*)[ \t]*;[ \t]*\}[ \t]*$')


def prune_table_lines(text: str, available: set[str]) -> tuple[str, list[str]]:
    """行级剔除 funcref 静态表里指向缺失符号的候选行。

    `libVibeInvoke_gf_ResolveFuncref` 有 400+ 个 `if (name=="X") { return X; }`。
    若走整函数降级，只要坏 1 个候选就会把整张表变成 `return null;` —— 所有
    funcref 解析集体失效。这里只摘掉坏行，其余候选原样保留。
    """
    ok = available | file_symbols(strip_noise(text)) | KEYWORDS
    dropped: list[str] = []
    lines = text.split("\n")
    for idx, ln in enumerate(lines):
        m = RE_TABLE_LINE.match(ln)
        if not m:
            continue
        target = m.group(1)
        if target in ok or target.startswith(LOCAL_PREFIXES):
            continue
        dropped.append(target)
        lines[idx] = f"    // [sanitizer] 目标图缺少 {target}，已从 funcref 表摘除"
    return "\n".join(lines), dropped


def sanitize_text(text: str, available: set[str]) -> tuple[str, list[dict]]:
    """返回 (净化后文本, 被降级的函数记录)。"""
    text, dropped = prune_table_lines(text, available)
    infos = analyze(text, available)
    bad = [i for i in infos if i["missing"]]
    if dropped:
        bad = bad + [{"name": "<funcref-table>", "rettype": "-", "start": -1,
                      "end": -1, "missing": sorted(set(dropped)),
                      "kind": "table-prune"}]
    if not bad:
        return text, []
    bad_funcs = [b for b in bad if b["start"] >= 0]
    if not bad_funcs:
        return text, bad
    # 从后往前替换，保持前面的偏移有效
    out = text
    for i in sorted(bad_funcs, key=lambda x: -x["start"]):
        orig = text[i["start"]:i["end"]]
        m = RE_FUNC.match(strip_noise(orig))
        params = m.group(3) if m else "string argsJson"
        out = out[:i["start"]] + _fail_closed(
            i["rettype"], i["name"], params, i["missing"]) + out[i["end"]:]
    return out, bad
