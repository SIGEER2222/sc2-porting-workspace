#!/usr/bin/env python3
"""CMLib 静态自检：重定义 / 声明一致性 / 符号存在性 / 实参个数 / 聚合完整性.

这几项是"静态 lint 报 0 错误但真机静默失败"的历史根因，必须单独把关：
  1. 重定义   —— 同名函数在两个模块各定义一份 => SC2 静默丢弃整个 MapScript
  2. 声明漂移 —— header 声明与实现签名不一致
  3. 未知符号 —— 调用了引擎里不存在的 native（拼写/记忆错误）
  4. 实参个数 —— 调 native 少传/多传一个参数，同样是静默不编译
  5. 聚合遗漏 —— 新模块忘了注册进 cmlib.galaxy
  6. 数组形参 —— Galaxy 不支持数组做形参，真机静默丢弃整个 MapScript

用法:  python check_cmlib.py
退出码 0 = 全通过。
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
CMLIB = HERE / "scripts" / "cmlib"
# selftest 不是库的一部分，但它是**唯一的真机证据来源**：里面调错一个参数
# 会让整条 Deferred 触发器在真机上中断，表现为"断言计数少一截"，
# 而这类错误 galaxy-lint 抓不到、check 前 6 项也扫不到（不在 CMLIB 目录）。
# 实测 2026-08-08 第 7 轮就是这样漏掉两个签名错（BuffStripAll / PStateGet）。
# 因此把它一并纳入调用点校验，但不计入模块统计、不参与聚合完整性检查。
SELFTEST = HERE / "selftest"
SPW = HERE.parents[1]           # sc2-porting-workspace
GAMEDATA = (SPW / "reference" / "sc2mapster" / "SC2GameData" / "mods" /
            "core.sc2mod" / "base.sc2data")

TYPE = (r"(?:void|int|bool|fixed|string|text|byte|point|unit|unitgroup|player|"
        r"playergroup|region|trigger|timer|order|actor|sound|soundlink|wave|"
        r"revealer|marker|transmissionsource|camerainfo|abilcmd|doodad|color|"
        r"aifilter|objective|bank|dialogcontrol|actorscope|waveinfo|wavetarget|"
        r"unitfilter|unitref|generichandle|datetime|texttag|ping|portrait|"
        r"effecthistory|"
        r"trigger)")

# 实现：签名后跟 {   声明：签名后跟 ;
# 用 MULTILINE + DOTALL 友好的写法，支持跨行签名（本库大量存在）。
IMPL_RE = re.compile(
    rf"(?m)^[ \t]*(?:static[ \t]+)?({TYPE})[ \t]*(\[[^\]]*\])?[ \t]+(CMLib_\w+)[ \t]*\(([^;{{)]*(?:\)[^;{{(]*)*?)\)\s*\{{")
DECL_RE = re.compile(
    rf"(?m)^[ \t]*(?:static[ \t]+)?({TYPE})[ \t]*(\[[^\]]*\])?[ \t]+(CMLib_\w+)[ \t]*\(([^;{{)]*(?:\)[^;{{(]*)*?)\)\s*;")
# static 函数是刻意的文件内私有实现，不要求出现在 header 里
STATIC_FN_RE = re.compile(
    rf"(?m)^[ \t]*static[ \t]+{TYPE}[ \t]*(?:\[[^\]]*\])?[ \t]+(CMLib_\w+)[ \t]*\(")
# 附加文件（selftest）里的本地函数定义 —— 名字不带 CMLib_ 前缀，例如 CMLibTest_Mark
LOCAL_FN_RE = re.compile(
    rf"(?m)^[ \t]*(?:static[ \t]+)?({TYPE})[ \t]*(?:\[[^\]]*\])?[ \t]+(\w+)[ \t]*\(([^;{{)]*(?:\)[^;{{(]*)*?)\)\s*\{{")
CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
CONST_RE = re.compile(r"\bconst\s+\w+\s+(\w+)\s*=")
# funcref 类型别名：typedef funcref<Proto> Alias;
FUNCREF_TD_RE = re.compile(r"\btypedef\s+funcref\s*<\s*(\w+)\s*>\s*(\w+)\s*;")

KEYWORDS = {
    "if", "while", "for", "return", "break", "continue", "else", "switch",
    "include", "struct", "typedef", "const", "static", "native", "new",
    "void", "int", "bool", "fixed", "string", "text", "byte",
}


def strip_comments(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    return re.sub(r"//[^\n]*", " ", s)


def blank_strings(s: str) -> str:
    """把字符串字面量内容替换成等长空格，保留引号与整体偏移。

    不这么做的话，形如 "Foo(" 的字面量会被当成函数调用，
    实参计数也会被字面量里的逗号带偏。
    """
    out = list(s)
    i, n = 0, len(s)
    while i < n:
        if s[i] == '"':
            j = i + 1
            while j < n and s[j] != '"':
                if s[j] == "\\":
                    j += 1
                j += 1
            for k in range(i + 1, min(j, n)):
                out[k] = " "
            i = j + 1
        else:
            i += 1
    return "".join(out)


def count_args(txt: str, open_idx: int) -> int | None:
    """从 '(' 的下标开始，数这一层调用的实参个数。括号不闭合返回 None。"""
    depth = 0
    args = 0
    seen = False
    i, n = open_idx, len(txt)
    while i < n:
        c = txt[i]
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
            if depth == 0:
                return args + 1 if seen else 0
        elif depth == 1 and c == ",":
            args += 1
        elif depth >= 1 and not c.isspace():
            seen = True
        i += 1
    return None


def sig_arity(params: str) -> int:
    p = " ".join(params.split()).strip()
    if not p or p == "void":
        return 0
    return p.count(",") + 1


def norm_params(p: str) -> str:
    """规范化参数列表用于比对：去掉参数名，只留类型序列。"""
    p = " ".join(p.split())
    if not p.strip():
        return ""
    out = []
    for part in p.split(","):
        toks = part.strip().split()
        if not toks:
            continue
        # 类型可能带 [N] 数组维度，参数名是最后一个 token
        ty = " ".join(toks[:-1]) if len(toks) > 1 else toks[0]
        out.append(" ".join(ty.split()))
    return ",".join(out)


ENGINE_SIG_RE = re.compile(
    r"(?m)^[ \t]*(?:native[ \t]+)?[\w]+(?:\[[^\]]*\])?[ \t]+(\w+)[ \t]*\(([^)]*)\)[ \t]*[;{]")

# 同上，但**只匹配 native 声明**。用于那些不在默认 include 链里的库文件
# （Tactical/*.galaxy）：里面的 native 是引擎内建、裸调即可用；里面的普通
# Galaxy 函数则必须 include 才存在，绝不能混进引擎符号表。
ENGINE_NATIVE_RE = re.compile(
    r"(?m)^[ \t]*native[ \t]+[\w]+(?:\[[^\]]*\])?[ \t]+(\w+)[ \t]*\(([^)]*)\)[ \t]*;")


# NativeLib.TriggerLib 里带 <FlagNative/> 的 FunctionDef 条目。
# round22 血泪：SC2 的 native 符号表是**引擎内建**的，.galaxy 里的 `native`
# 声明只是编辑器 / lint 的元数据。因此"不在 natives.galaxy 里"推不出
# "不可调用"——StatEvent* 六件套只在 natives_missing.galaxy 有声明，
# 但 NativeLib.TriggerLib 给它们全部打了 <FlagNative/>，真机三档探针也
# 全部 PASS。判"是否可调用"必须以 <FlagNative/> + natives_missing 为准。
FLAGNATIVE_RE = re.compile(
    r"<Element\b[^>]*Type=\"FunctionDef\"[^>]*>(.*?)</Element>", re.S)
IDENT_RE = re.compile(r"<Identifier>([\w]+)</Identifier>")


def load_flag_natives() -> set[str]:
    """从 NativeLib.TriggerLib 解析所有带 <FlagNative/> 的函数标识符。"""
    p = GAMEDATA / "TriggerLibs" / "NativeLib.TriggerLib"
    if not p.exists():
        return set()
    txt = p.read_text(encoding="utf-8", errors="replace")
    out: set[str] = set()
    for m in FLAGNATIVE_RE.finditer(txt):
        body = m.group(1)
        if "<FlagNative/>" not in body:
            continue
        mi = IDENT_RE.search(body)
        if mi:
            out.add(mi.group(1))
    return out


def load_engine_symbols() -> tuple[set[str], dict[str, int]]:
    """加载引擎提供的全部 native / 库函数 / 常量名，以及函数形参个数表。"""
    syms: set[str] = set()
    arity: dict[str, int] = {}
    srcs = [GAMEDATA / "TriggerLibs" / "natives.galaxy",
            # natives_missing.galaxy：社区补齐的引擎 native 声明。它不被任何
            # 引擎库 include，但里面的符号全部是引擎内建、真机可调用的。
            GAMEDATA / "TriggerLibs" / "natives_missing.galaxy"]
    srcs += sorted((GAMEDATA / "TriggerLibs" / "GameData").glob("*.galaxy"))
    srcs += [GAMEDATA / "TriggerLibs" / "NativeLib.galaxy",
             GAMEDATA / "TriggerLibs" / "AI.galaxy",
             GAMEDATA / "TriggerLibs" / "AIThink.galaxy",
             GAMEDATA / "TriggerLibs" / "AIAdvanced.galaxy"]
    for s in srcs:
        if not s.exists():
            continue
        txt = blank_strings(strip_comments(
            s.read_text(encoding="utf-8", errors="replace")))
        for m in ENGINE_SIG_RE.finditer(txt):
            name = m.group(1)
            if name in KEYWORDS:
                continue
            syms.add(name)
            arity.setdefault(name, sig_arity(m.group(2)))
        for m in CONST_RE.finditer(txt):
            syms.add(m.group(1))

    # Tactical/*.galaxy（TacticalAI / TactTerrAI / TactProtAI / TactZergAI …）：
    # 这些文件**不在默认 include 链**里，所以只取其中的 `native` 声明，
    # 绝不能连里面的普通 Galaxy 函数（AICampSkirDiffTest / AIFilterAlliance …）
    # 一起收进来 —— 那些是真需要 include 才存在的库函数，把它们当"引擎符号"
    # 放行，等于亲手拆掉"裸调库函数 -> 真机静默编译失败"这条防线。
    #
    # 取 native 的依据是 round24 探针实证：aifilter 族在只 include natives 的
    # MapScript 里**裸调即可用**（六档全 PASS，句柄非 null、过滤产出非空组），
    # 印证了 round22/23 那条"native 符号表是引擎内建"的判据。
    # 常量同理不收 —— c_planeGround 之流在 GameData/Game.galaxy 才有定义。
    for s in sorted((GAMEDATA / "TriggerLibs" / "Tactical").glob("*.galaxy")):
        txt = blank_strings(strip_comments(
            s.read_text(encoding="utf-8", errors="replace")))
        for m in ENGINE_NATIVE_RE.finditer(txt):
            name = m.group(1)
            if name in KEYWORDS:
                continue
            syms.add(name)
            arity.setdefault(name, sig_arity(m.group(2)))

    # <FlagNative/> 条目只补名字、不补 arity（XML 里参数是 ParamDef 引用，
    # 解析成本高且无必要——真有签名的都能从上面的 .galaxy 拿到）。
    syms |= load_flag_natives()
    return syms, arity


def main() -> int:
    if not CMLIB.exists():
        print(f"!! 找不到库目录 {CMLIB}")
        return 2

    lib_files = sorted(CMLIB.glob("*.galaxy"))
    extra_files = sorted(SELFTEST.glob("*.galaxy")) if SELFTEST.exists() else []
    files = lib_files + extra_files
    extra_names = {f.name for f in extra_files}
    impls: dict[str, list[tuple[str, str]]] = defaultdict(list)  # name -> [(file, params)]
    decls: dict[str, list[tuple[str, str]]] = defaultdict(list)
    consts: dict[str, list[str]] = defaultdict(list)
    calls: dict[str, set[str]] = defaultdict(set)   # name -> {files}
    # 调用点：(函数名, 文件, 行号, 实参个数)
    callsites: list[tuple[str, str, int, int]] = []
    # 每个函数签名的形参串，用于第 6 项「数组形参」检查
    sigparams: list[tuple[str, str, int, str]] = []
    funcref_types: set[str] = set()                 # funcref 类型别名
    funcref_params: set[str] = set()                # 被声明为 funcref 的参数名
    static_fns: set[str] = set()                    # 文件内私有函数
    # selftest 等附加文件里定义的、不带 CMLib_ 前缀的本地函数（如 CMLibTest_Mark）。
    # 收进来才能既不误报"未知符号"，又能校验它们的实参个数。
    local_arity: dict[str, int] = {}

    # 先扫一遍拿到所有 funcref 类型别名，才能识别哪些参数是可调用的回调
    for f in files:
        txt = strip_comments(f.read_text(encoding="utf-8", errors="replace"))
        for m in FUNCREF_TD_RE.finditer(txt):
            funcref_types.add(m.group(2))
    if funcref_types:
        alt = "|".join(sorted(re.escape(t) for t in funcref_types))
        fp_re = re.compile(rf"\b(?:{alt})\s+(\w+)")
        for f in files:
            txt = strip_comments(f.read_text(encoding="utf-8", errors="replace"))
            for m in fp_re.finditer(txt):
                funcref_params.add(m.group(1))

    # 函数定义/声明本身的 '(' 位置，避免把定义头当成调用来数实参
    for f in files:
        txt = blank_strings(strip_comments(
            f.read_text(encoding="utf-8", errors="replace")))
        defparen: set[int] = set()
        for ms in STATIC_FN_RE.finditer(txt):
            static_fns.add(ms.group(1))
        for mi in IMPL_RE.finditer(txt):
            impls[mi.group(3)].append((f.name, norm_params(mi.group(4))))
            defparen.add(txt.index("(", mi.start(3)))
            sigparams.append((mi.group(3), f.name,
                              txt.count("\n", 0, mi.start()) + 1, mi.group(4)))
        for md in DECL_RE.finditer(txt):
            decls[md.group(3)].append((f.name, norm_params(md.group(4))))
            defparen.add(txt.index("(", md.start(3)))
            sigparams.append((md.group(3), f.name,
                              txt.count("\n", 0, md.start()) + 1, md.group(4)))
        if f.name in extra_names:
            for ml in LOCAL_FN_RE.finditer(txt):
                local_arity[ml.group(2)] = sig_arity(norm_params(ml.group(3)))
                defparen.add(txt.index("(", ml.start(2)))
        for m in CONST_RE.finditer(txt):
            consts[m.group(1)].append(f.name)
        for m in CALL_RE.finditer(txt):
            n = m.group(1)
            if n in KEYWORDS:
                continue
            calls[n].add(f.name)
            op = m.end() - 1
            if op in defparen:
                continue
            na = count_args(txt, op)
            if na is not None:
                callsites.append((n, f.name, txt.count("\n", 0, m.start()) + 1, na))

    errors: list[str] = []
    warns: list[str] = []

    # --- 1. 函数重定义（致命）---
    for name, sites in impls.items():
        if len(sites) > 1:
            where = ", ".join(f"{f}" for f, _ in sites)
            errors.append(f"[重定义] {name} 在 {len(sites)} 个文件各定义一份: {where}")

    # --- 1b. 常量重定义 ---
    for name, sites in consts.items():
        if len(set(sites)) > 1:
            errors.append(f"[常量重定义] {name}: {', '.join(sorted(set(sites)))}")

    # --- 1c. 与引擎 native / 引擎常量撞名（致命，且比库内重定义更难查）---
    #
    # 库内两处同名会被第 1 项抓到；但「库里定义了一个和引擎 native 同名的函数」
    # 只有真机才会炸：SC2 视为函数重定义 → 静默丢弃整个 MapScript，
    # 而 galaxy-lint 与前 5 项检查全部通过。并发多人/多进程编辑同一个库时，
    # 有人图省事直接写 `void UnitSetState(...)` 这类名字就会踩中。
    # 放在第 3 项之前先把 engine 表加载好，因此这里延后到符号表加载后执行（见下）。

    # --- 2. 声明 / 实现一致性 ---
    for name, dsites in decls.items():
        if name not in impls:
            errors.append(f"[有声明无实现] {name} (声明于 {dsites[0][0]})")
            continue
        dparams = dsites[0][1]
        iparams = impls[name][0][1]
        if dparams != iparams:
            errors.append(
                f"[签名不一致] {name}\n"
                f"    header: ({dparams})\n"
                f"    impl  : ({iparams})")
    for name, isites in impls.items():
        if name not in decls and name not in static_fns:
            if isites[0][0] in extra_names:
                continue      # selftest 里的入口函数由 MapScript 直接调，无 header
            warns.append(f"[无 header 声明] {name} (实现于 {isites[0][0]}) — "
                         f"若是内部私有函数请显式加 static")

    # --- 3. 外部符号存在性 ---
    engine, engine_arity = load_engine_symbols()
    if not engine:
        warns.append("[跳过] 未能加载引擎符号表，外部符号检查未执行")
    else:
        # 1c 的实际执行点：库内实现 / 常量与引擎符号撞名
        for name, isites in impls.items():
            if name in engine:
                errors.append(
                    f"[撞名引擎 native] {name} (实现于 {isites[0][0]}) — "
                    f"与引擎同名函数冲突，真机会静默丢弃整个 MapScript。"
                    f"请加 CMLib_ 前缀")
        for name, csites in consts.items():
            if name in engine:
                errors.append(
                    f"[撞名引擎常量] {name} ({csites[0]}) — 请加 CMLIB_ 前缀")

        unknown: dict[str, set[str]] = {}
        for name, where in calls.items():
            if name.startswith("CMLib_") or name.startswith("CMLIB_"):
                continue
            if name in engine or name in impls or name in decls:
                continue
            if name in funcref_params or name in funcref_types:
                continue   # funcref 回调调用，不是缺失符号
            if name in local_arity:
                continue   # selftest 自己定义的辅助函数
            unknown[name] = where
        for name in sorted(unknown):
            errors.append(f"[未知符号] {name} — 引擎符号表里找不到 "
                          f"(用于 {', '.join(sorted(unknown[name]))})")

    # --- 4. 实参个数（少传/多传一个参数 = 真机静默不编译）---
    #     库内函数用实现签名做期望值，引擎函数用 native 声明做期望值。
    lib_arity = {n: sig_arity(v[0][1]) for n, v in impls.items()}
    n_checked = 0
    for name, fname, line, got in callsites:
        if name in funcref_params or name in funcref_types:
            continue          # 回调调用，签名由 typedef 决定，此处不校验
        want = lib_arity.get(name, local_arity.get(name, engine_arity.get(name)))
        if want is None:
            continue          # 未知符号已在第 3 项报告
        n_checked += 1
        if got != want:
            errors.append(f"[实参个数] {fname}:{line} {name}(...) "
                          f"传了 {got} 个，期望 {want} 个")

    # --- 5. 聚合入口完整性 ---
    agg = CMLIB / "cmlib.galaxy"
    agg_txt = agg.read_text(encoding="utf-8", errors="replace") if agg.exists() else ""
    included = set(re.findall(r'include\s+"scripts/cmlib/(\w+)"', agg_txt))
    for f in lib_files:
        stem = f.stem
        if stem in ("cmlib",):
            continue
        if stem not in included:
            errors.append(f"[未注册] {f.name} 没有被 cmlib.galaxy include")
    # 反向：include 了不存在的文件
    for inc in sorted(included):
        if not (CMLIB / f"{inc}.galaxy").exists():
            errors.append(f"[悬空 include] cmlib.galaxy 引用了不存在的 {inc}.galaxy")

    # --- 6. 数组形参（真机静默不编译，lint 与类型检查都抓不到）---
    #
    # Galaxy 不支持把数组作为函数形参。核实过 core.sc2mod 全部引擎库：
    # natives.galaxy / NativeLib / AI* 中 0 例数组形参，本版本也没有 arrayref。
    # 写成 `void f(int[8] arr)` 时：
    #   - galaxy-lint（含 --type-check）报 0 错误
    #   - check_cmlib 前 5 项也全过
    #   - 真机 SC2 直接静默丢弃整个 MapScript，InitMap 永不被调用
    # 这是 2026-08-08 真机二分（k=13 cmlib_game）实测抓出的根因，故固化为门禁。
    # 替代写法：玩家集合用 playergroup；同类批量入参用 CSV 串 + CMLib_SplitAt。
    arr_param_re = re.compile(r"\[[^\]]*\]\s*[A-Za-z_]\w*\s*(?:,|$)")
    seen_arr: set[tuple[str, str, int]] = set()
    for name, fname, line, params in sigparams:
        if not params or "[" not in params:
            continue
        if not arr_param_re.search(params):
            continue
        key = (name, fname, line)
        if key in seen_arr:
            continue
        seen_arr.add(key)
        errors.append(
            f"[数组形参] {fname}:{line} {name}(...) 用了数组做形参 —— "
            f"Galaxy 不支持，真机会静默丢弃整个 MapScript。"
            f"改用 playergroup / unitgroup 或 CSV 串入参")

    # --- 第 6.5 项：门禁自检（返回类型白名单覆盖）---
    # TYPE 是白名单正则：返回类型不在其中的函数，IMPL_RE/DECL_RE 根本抓不到，
    # 于是它的实参个数、声明/实现配对全都不被校验 —— 静默盲区，比报错危险得多。
    # round17 真实踩过：effecthistory 缺席，CMLib_EffHist 被漏检了整整两轮。
    type_ok = re.compile(rf"^{TYPE}$")
    loose_def = re.compile(r"(?m)^[ \t]*(?:static[ \t]+)?([A-Za-z_]\w*)[ \t]+(CMLib_\w+)[ \t]*\(")
    blind: dict[str, str] = {}
    for f in lib_files:
        txt = strip_comments(f.read_text(encoding="utf-8", errors="replace"))
        for m in loose_def.finditer(txt):
            rt = m.group(1)
            if type_ok.match(rt) or rt in ("return", "if", "while", "for",
                                           "else", "typedef", "const",
                                           "include", "native"):
                continue
            blind.setdefault(rt, f"{f.name}:{m.group(2)}")
    for rt, where in sorted(blind.items()):
        errors.append(
            f"[门禁盲区] 返回类型 `{rt}` 不在 TYPE 白名单里（{where}）—— "
            f"该函数的声明/实现/实参个数全都不被校验。把 `{rt}` 加进 check_cmlib.py 的 TYPE")

    # --- 第 7 项：文档漂移（API_INDEX.md 与 _h 声明必须 1:1）---
    # 漂移不会让真机崩，但「漏记的 API 等于不存在」，所以走 WARN 而非 ERROR。
    # 修复方式：python src/lib/gen_api_index.py
    idx_path = CMLIB / "API_INDEX.md"
    if idx_path.exists():
        idx_txt = idx_path.read_text(encoding="utf-8")
        # 表格单元格形如：| `void` | **`CMLib_Xxx`** | `int, string` |
        idx_names = set(re.findall(
            r"\|\s*\**\s*`?(CMLib_[A-Za-z0-9_]+)`?\s*\**\s*\|", idx_txt))
        decl_names = set(decls.keys())
        missing = sorted(decl_names - idx_names)
        stale = sorted(idx_names - decl_names)
        if missing:
            warns.append(
                f"[文档漂移] API_INDEX.md 少了 {len(missing)} 个已声明函数"
                f"（如 {', '.join(missing[:5])}）—— 跑 gen_api_index.py 重生成")
        if stale:
            warns.append(
                f"[文档漂移] API_INDEX.md 多了 {len(stale)} 个已不存在的函数"
                f"（如 {', '.join(stale[:5])}）—— 跑 gen_api_index.py 重生成")
    else:
        warns.append("[文档漂移] 缺 scripts/cmlib/API_INDEX.md —— 跑 gen_api_index.py 生成")

    # --- 第 9 项：G1001 局部变量置顶（round18 新增） ---
    # Galaxy 要求函数体内所有局部声明位于任何可执行语句之前。违反时 SC2
    # **静默丢弃整个 MapScript**（不报错、InitMap 不被调用），而本门禁前 8 项
    # 与 galaxy-lint 一律报 0 错误。第 8 轮真机就栽在这上面（Ghost=0）。
    # 它是"静态全绿 != 能跑"最主要的单点成因，必须由门禁而不是真机来兜。
    try:
        from check_g1001 import (BUILTIN_TYPES, collect_struct_types,
                                 scan_file as g1001_scan)
        g_files = sorted(lib_files) + sorted(extra_files)
        g_text = "\n".join(f.read_text(encoding="utf-8", errors="replace")
                           for f in g_files)
        g_types = set(BUILTIN_TYPES) | collect_struct_types(g_text)
        for f in g_files:
            for ln, fn, code in g1001_scan(f, g_types):
                errors.append(
                    f"[G1001 局部变量未置顶] {f.name}:{ln} 函数 {fn}() -> {code}"
                    f" —— 真机会静默丢整个 MapScript")
    except Exception as ex:                        # noqa: BLE001
        warns.append(f"[跳过] G1001 检查未执行: {ex}")

    # --- 第 10 项：注释里的引擎常量必须真实存在（round18 新增） ---
    # 动机：第 17 轮踩过 `c_unitFlagStructure` 这种「听起来很像但引擎根本没有」
    # 的常量；本轮 header 里又写了 `c_chargeInfo*` / `c_ASState*` 两个不存在的
    # 常量族。写在注释里编译不会炸，但**下一个照着注释写代码的人必炸**，
    # 而且炸法是"编译失败 → 整图静默丢弃"，最难查。
    # 注释是给人看的 API 契约，契约撒谎和代码写错等价，所以也要过门禁。
    # 走 WARN 而非 ERROR：常量族用 `c_xxx*` 通配写法时无法逐个坐实。
    const_re = re.compile(r"\bc_[A-Za-z][A-Za-z0-9_]{3,}\b")
    # 「这个常量根本不存在」是**有价值的**注释（正是本项想推广的写法），
    # 不能因为写了它就被自己的门禁骂。同一行出现否定词即视为反面举例。
    neg_re = re.compile(r"没有|不存在|查无|并无|别用|勿用|不要用|误以为")
    bad_consts: dict[str, list[str]] = {}
    for f in sorted(lib_files) + sorted(extra_files):
        for i, line in enumerate(
                f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            s = line.lstrip()
            if not s.startswith("//"):
                continue                    # 只查注释行，代码行由第 6 项管
            if neg_re.search(s):
                continue                    # 反面举例，跳过
            for name in const_re.findall(s):
                if name in engine or name in consts or name in decls:
                    continue
                # `c_xxx*` 通配前缀：只要引擎里有同前缀常量就算数
                star = f"{name}*" in s or f"{name}\\*" in s
                if star and any(k.startswith(name) for k in engine):
                    continue
                bad_consts.setdefault(name, []).append(f"{f.name}:{i}")
    if bad_consts:
        head = ", ".join(f"{k}({v[0]})" for k, v in
                         sorted(bad_consts.items())[:4])
        warns.append(
            f"[注释常量不存在] 注释里引用了 {len(bad_consts)} 个引擎符号表中"
            f"查无此名的常量：{head} —— 注释是 API 契约，照着它写代码会编译失败"
            f"（真机表现为整图静默丢弃）")

    # --- 报告 ---
    n_mod = len({f.stem.replace("_h", "") for f in lib_files if f.stem != "cmlib"})
    print(f"CMLib 静态自检 — {len(lib_files)} 文件 / {n_mod} 模块 / "
          f"{len(impls)} 个函数实现 / {len(decls)} 个声明"
          + (f" (+{len(extra_files)} 个 selftest 文件一并校验实参)"
             if extra_files else ""))
    print(f"引擎符号表: {len(engine)} 个（其中 {len(engine_arity)} 个带签名）")
    print(f"调用点: {len(callsites)} 处，已校验实参个数 {n_checked} 处")
    print("-" * 72)

    for w in warns:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")

    print("-" * 72)
    if errors:
        print(f"FAILED — {len(errors)} 个错误, {len(warns)} 个警告")
        return 1
    print(f"PASSED — 0 错误, {len(warns)} 个警告")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
