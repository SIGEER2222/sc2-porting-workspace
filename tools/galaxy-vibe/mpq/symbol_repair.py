"""编译单元符号闭包修复器 —— 让 generated adapter 包能在目标地图里真正编译通过。

【真机根因，2026-08-08 取证】Galaxy 单遍编译器遇到**未定义标识符**即编译错误，
而 SC2 编译失败时会 **静默丢弃整个 MapScript**（不报错、不写 ScriptError、
InitMap 从不执行、Bank 里没有 kernel_initialized）。所以"静态 lint 全绿"毫无意义，
必须在打包前把编译单元的符号闭包算清楚。

具体事故：generated 包是从**完整的**亡者之夜地图导出的，它引用了
`libA3ADAPTER_gf_*` / `libPortingObserver_gf_*` / `libEFA54406_gf_*` /
`libDeadOfNightObserver_gf_*`。这些库的 .galaxy **文件在 MPQ 里存在**，但
MapScript 的 include 链**不包含它们** ⇒ 不在编译单元 ⇒ 未定义标识符 ⇒ 全图静默失效。
（`nofuncref` 变体真机 PASS、`incl` 变体真机 reg={} 已 100% 坐实。）

修复分两级：
  Stage A 自动补 include —— 缺失符号的 `lib<X>_` 前缀若能对应到 MPQ 内某个
          未进链的 `Lib<X>.galaxy`，就把该库补进 active 的 include 头部。
  Stage B 中和残余 —— 仍无法满足的符号，按引用形态就地改写 generated 源：
          B1 `lv_x = <missing>(...);` 整行删除（配套的 Has_ 守卫恒 false，死代码）
          B2 ResolveFuncref 的 `if (name == "..") { return <missing>; }` 分支删除
          B3 其余：把整个 `libVibeInvoke_gf_CallNNNN` 函数体换成结构化错误返回
最后硬门禁：修复后重扫必须 0 缺失，否则直接 FAIL，绝不交付一张会静默丢弃的图。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

WS = Path(r"E:/Code/MyMod/SC2VibeTools/sc2-porting-workspace")

# 目标地图 DocumentHeader 声明的依赖 mod —— 它们的 Base.SC2Data 也是 include 搜索根
# （MapScript 里的 `include "scripts/cm_pointer_events"` 就由此解析）。
MOD_ROOTS = [
    WS / "src/projects/cmre-porting/packages/Mods/CMRE/CMRE_Core_Base.SC2Mod/Base.SC2Data",
    WS / "src/projects/cmre-porting/packages/Mods/CMRE/CMRE_Core_Triggers.SC2Mod/Base.SC2Data",
    WS / "src/projects/cmre-porting/packages/Mods/CMRE/CMRE_Core_Mengsk.SC2Mod/Base.SC2Data",
    WS / "src/projects/cmre-porting/packages/Mods/CMRE/CMRE_Core_Stetmann.SC2Mod/Base.SC2Data",
    WS / "src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/Base.SC2Data",
]

# 暴雪 TriggerLibs 在 CASC 内、磁盘不可读 —— 按库前缀白名单放行，不当作缺失。
BLIZZ_PREFIX = re.compile(
    r"^lib(Ntve|Lbty|Hots|Swar|Void|Camp|Comm|SwaC|VoiC|LbtyC|StEx|UIUI|Core)_")

# trigger-lib 风格标识符（编辑器生成的命名是确定性的，可精确扫描）
#
# 【2026-08-08 真机根因修正，勿收窄回 _g[fv]_】
# 原正则 `lib[A-Za-z0-9]+_g[fv]_\w+` 只认 **函数/全局变量** 两种中缀，于是这些
# 引用全部逃过符号闭包扫描、symrep 报「0 缺失」而地图编译期即死：
#   - `libEFA54406_InitLib()` / `libCOMI_InitTriggers()`  —— 无 _g?_ 中缀
#   - `libEFA54406_gt_CleanUp_Func()`                     —— _gt_（trigger）中缀
#   - `auto_libEFA54406_gf_create_context_TriggerFunc()`  —— auto_ 前缀使 \b 失配
# 实测代价：gen 图 44 处未定义调用 + 24 处孤儿原型全部漏检，真机 Kernel 永不注册。
# 放宽为「任意 lib<Name>_ 后缀 / auto_ / gf_ / gv_ / gt_」；暴雪引擎库仍由
# BLIZZ_PREFIX 白名单放行，故不会产生误报。
REF_RE = re.compile(
    r"\b(lib[A-Za-z0-9]+_\w+|auto_\w+|gf_\w+|gv_\w+|gt_\w+)\b")

_KW = {"return", "if", "while", "for", "else", "break", "continue", "include",
       "do", "switch", "case", "typedef", "struct", "const", "static", "native"}

_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_STRING_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"')


def strip_noncode(text: str) -> str:
    """去掉注释与字符串字面量，只留真正会被编译器解析的代码。

    【必须】否则两类假阳性会毒化符号闭包判定：
      1. Stage B 把删掉的行改写成注释时，注释里原样带着缺失符号名 → 修复后重扫
         永远消不掉（本函数缺席时表现为"删了 2 行、中和了 2 个函数，还是 1 缺失"）。
      2. ResolveFuncref 的 `if (name == "libX_gf_Y")` 里字符串字面量与函数同名，
         被当成代码引用会把"只在字符串里出现"的名字误判为缺失。
    换行用等长空白替换，保证行号不漂移（Stage B 的按行改写依赖行号稳定）。
    """
    def _blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))
    text = _COMMENT_RE.sub(_blank, text)
    return _STRING_RE.sub(_blank, text)


def scan_defined(text: str) -> set[str]:
    """扫描一个 galaxy 文件定义/声明的顶层符号（宁可多收，不可漏收）。"""
    out: set[str] = set()
    text = strip_noncode(text)   # 注释掉的定义不算定义，否则会漏判缺失
    # 函数定义与原型（返回类型可以是自定义 typedef/struct，故不枚举类型白名单）
    for ret, name in re.findall(r"^\s*(?:native\s+)?(\w+)\s+(\w+)\s*\(", text, re.M):
        if ret not in _KW:
            out.add(name)
    # 全局变量 / 常量 / 数组
    out |= set(re.findall(
        r"^\s*(?:const\s+|static\s+)?\w+(?:\s*\[[^\]]*\])?\s+(\w+)\s*(?:=|;|\[)",
        text, re.M))
    out |= set(re.findall(r"^\s*struct\s+(\w+)", text, re.M))
    out |= set(re.findall(r"^\s*typedef\s+.*?\s+(\w+)\s*;", text, re.M))
    return out


def scan_refs(text: str) -> set[str]:
    return {m.group(1) for m in REF_RE.finditer(strip_noncode(text))}


# funcref 目标必须是「编译单元内有实现体的脚本函数」。以 `{` 而非 `;` 收尾是关键判据：
# native 声明与孤儿原型都以 `;` 结束，天然被排除在外。
_IMPL_RE = re.compile(r"^[ \t]*(\w+)[ \t]+(\w+)[ \t]*\(([^)]*)\)[ \t]*\{", re.M)


def scan_funcref_targets(text: str) -> set[str]:
    """扫描可安全用作 `funcref<void(int)>` 目标的函数名。

    【2026-08-08 真机根因 #2，勿退回用 scan_defined 当白名单】Stage C 原先拿
    `scan_defined()` 的符号集做裁剪白名单，但那个正则写的是
    `^\\s*(?:native\\s+)?(\\w+)\\s+(\\w+)\\s*\\(` —— **native 是被显式收进去的**。
    于是 CMRE `TriggerLibs/AI.galaxy` 里的 29 个 `native void AIClearStock(int);`
    统统"符号存在"、统统通过裁剪，而 Galaxy **禁止对 native 取 funcref**
    （引擎绑定，没有脚本地址）⇒ 编译错误 ⇒ SC2 静默丢弃整个 MapScript。
    同理，只有原型、没有实现体的名字也不能当 funcref 目标。

    实证（VibeDeadOfNight-Gen，281 文件 / 35586 符号）：406 个候选里
    29 个 native + 31 个未定义 = 60 个非法，Stage C 却一条都没删
    （MPQ 内实测 `branches 406 / dropped 0`），真机 `kernel_registered=False`。
    模块头注释里"natives 磁盘不可读、天然不在符号集里"的旧假设是错的。

    判据收紧为三条，缺一不可：
      1. 有函数体（`) {` 而不是 `);`）—— 排除 native 与孤儿原型；
      2. 返回类型是 `void`；
      3. 形参恰好一个 `int` —— 与 `libVibeInvoke_gp_VoidIntProto` 签名一致。
    """
    out: set[str] = set()
    for ret, name, args in _IMPL_RE.findall(strip_noncode(text)):
        if ret != "void" or ret in _KW or name in _KW:
            continue
        parts = [a.strip() for a in args.split(",") if a.strip()]
        if len(parts) != 1 or parts[0].split()[0] != "int":
            continue
        out.add(name)
    return out


# --------------------------------------------------------------------------
# Stage B 改写原语
# --------------------------------------------------------------------------

def drop_assign_lines(src: str, missing: set[str]) -> tuple[str, int]:
    """B1：删掉 `lv_x = <missing>(...);` 这类纯赋值行。

    典型场景：structref 句柄。LibVibeHandles 为 struct 类型只生成了
    `Has_`(恒 false) / `Drop_` / `Clear_`，没有 `Get_`（Galaxy 函数不能返回 struct）。
    生成器却照常发了 `lv_p1 = libVibeHandles_gf_Get_<struct>(id);`。
    该行运行时不可达（前一行 Has_ 守卫恒 false 已 return），但编译期照样致命。
    """
    n = 0
    lines = src.split("\n")
    out = []
    for ln in lines:
        m = re.match(r"^\s*\w+\s*=\s*(\w+)\s*\(.*\);\s*$", ln)
        if m and m.group(1) in missing:
            n += 1
            out.append(f"    // [symbol-repair] dropped: {ln.strip()}")
            continue
        out.append(ln)
    return "\n".join(out), n


def drop_funcref_branches(src: str, missing: set[str]) -> tuple[str, int]:
    """B2：删掉 ResolveFuncref 里指向缺失函数的 `if (name == "..") { return X; }`。"""
    n = 0
    out_lines = []
    pat = re.compile(r'^\s*if \(name == "[^"]+"\) \{ return (\w+); \}\s*$')
    for ln in src.split("\n"):
        m = pat.match(ln)
        if m and m.group(1) in missing:
            n += 1
            continue
        out_lines.append(ln)
    return "\n".join(out_lines), n


_FUNCREF_BRANCH = re.compile(
    r'^([ \t]*)if \(name == "([^"]+)"\) \{ return (\w+); \}[ \t]*$', re.M)


def reduce_funcref_table(src: str, allowed: set[str]) -> tuple[str, int, int]:
    """Stage C：把 `ResolveFuncref` 静态表里目标**不在编译单元符号集**的分支删掉。

    【真机根因，2026-08-08 二分坐实】变体实验 `incl`（只 include Common）真机 reg={}，
    `nofuncref`（整体剥离 ResolveFuncref）真机 PASS ⇒ 这张 406 分支的 funcref 表就是
    编译杀手。构成：226 个 `lib*_gf_*` 脚本函数 + **180 个裸 native**
    （AIAddAirDangerUnits 之类）。Galaxy 的 `funcref` 只能指向脚本函数，
    **对 native 取函数引用是编译错误**；而 native 名不带 `lib`/`gf_` 前缀，
    压根不匹配 REF_RE，所以此前的符号闭包检查一次都没看见它们。

    【订正，2026-08-08 第二轮】本 docstring 原先写"natives 来自 CASC、磁盘不可读，
    天然不在符号集里 → 自动清零"——**这个假设是错的**，也正是第二层根因。CMRE 的
    `TriggerLibs/AI.galaxy` 就在 MPQ 里、磁盘完全可读，而 `scan_defined()` 的正则
    `^\\s*(?:native\\s+)?(\\w+)\\s+(\\w+)\\s*\\(` 明确把 native 收进符号集，于是 29 个
    `native void AI*(int)` 全部通过裁剪，真机 `kernel_registered=False`。

    现行规则：`allowed` 必须由 `scan_funcref_targets()` 产出（要求编译单元内存在
    `void <name>(int) {` 实现体），而不是 `scan_defined()` 的符号集。
    删掉分支后 `name` 落到函数末尾的兜底 return（no-op proto），语义安全降级。
    """
    kept = dropped = 0

    def _sub(m: re.Match) -> str:
        nonlocal kept, dropped
        indent, key, target = m.group(1), m.group(2), m.group(3)
        if target in allowed:
            kept += 1
            return m.group(0)
        dropped += 1
        return f"{indent}// [symbol-repair] funcref dropped: {key}"

    return _FUNCREF_BRANCH.sub(_sub, src), kept, dropped


def neutralize_functions(src: str, missing: set[str]) -> tuple[str, list[str]]:
    """B3：把仍引用缺失符号的 `string libVibeInvoke_gf_CallNNNN(...)` 换成错误返回。

    generated 代码是机器排版的：函数签名在行首、闭合 `}` 也在行首，可安全按列 0 切块。
    """
    lines = src.split("\n")
    starts: list[tuple[int, str]] = []
    sig_re = re.compile(r"^string\s+(libVibeInvoke_gf_Call\d+)\s*\(")
    for i, ln in enumerate(lines):
        m = sig_re.match(ln)
        if m:
            starts.append((i, m.group(1)))
    if not starts:
        return src, []

    killed: list[str] = []
    # 从后往前替换，避免行号漂移
    for i, fname in reversed(starts):
        j = i + 1
        while j < len(lines) and not lines[j].startswith("}"):
            j += 1
        if j >= len(lines):
            continue
        body = "\n".join(lines[i:j + 1])
        hit = sorted(missing & scan_refs(body))
        if not hit:
            continue
        sig = lines[i]
        lines[i:j + 1] = [
            f"// [symbol-repair] {fname} 中和：引用了编译单元外的符号 {','.join(hit)}",
            sig,
            f'    return libVibeInvoke_gf_Error("SYMBOL_NOT_IN_MAP", "{hit[0]}");',
            "}",
        ]
        killed.append(fname)
    return "\n".join(lines), killed


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

@dataclass
class RepairResult:
    extra_includes: list[str] = field(default_factory=list)
    patched: dict[str, str] = field(default_factory=dict)   # gen 文件名 -> 修复后文本
    still_missing: set[str] = field(default_factory=set)
    dropped_assign: int = 0
    dropped_funcref: int = 0
    neutralized: list[str] = field(default_factory=list)
    chain_files: int = 0
    initial_missing: list[str] = field(default_factory=list)
    banned: list[str] = field(default_factory=list)   # 因自身符号不闭合被回滚的库
    added_chain: list[str] = field(default_factory=list)  # Stage A 实际带进链的 MPQ 内名
    funcref_kept: int = 0
    funcref_dropped: int = 0
    # 因「声明晚于接线块」被排除的 map-local funcref 目标数（见 Stage C 注释）
    funcref_maplocal_dropped: int = 0


class BaseIndex:
    """目标地图的 include 搜索索引：MPQ 内文件 + 依赖 mod 的 Base.SC2Data。"""

    def __init__(self, mpq_texts: dict[str, str]):
        # mpq_texts: MPQ 内名（如 "Base.SC2Data\\LibCOOC.galaxy" / "MapScript.galaxy"）-> 文本
        self.mpq = mpq_texts
        self._cache: dict[str, str | None] = {}

    def resolve(self, inc: str) -> tuple[str, str] | None:
        """include 名 -> (来源标识, 文本)；解析不到返回 None（暴雪 TriggerLibs）。"""
        if inc in self._cache:
            v = self._cache[inc]
            return (inc, v) if v is not None else None
        if inc.startswith("TriggerLibs/"):
            self._cache[inc] = None
            return None
        for key in (f"Base.SC2Data\\{inc}.galaxy", f"{inc}.galaxy"):
            key = key.replace("/", "\\")
            if key in self.mpq:
                self._cache[inc] = self.mpq[key]
                return (key, self.mpq[key])
        for root in MOD_ROOTS:
            p = root / f"{inc}.galaxy"
            if p.is_file():
                t = p.read_bytes().decode("utf-8-sig", "replace").replace("\r\n", "\n")
                self._cache[inc] = t
                return (str(p), t)
        self._cache[inc] = None
        return None

    def walk(self, entry_text: str, seed_inc: list[str] | None = None) -> dict[str, str]:
        """从入口文本递归展开 include 链，返回 {来源标识: 文本}。"""
        seen: dict[str, str] = {}
        stack = list(re.findall(r'^\s*include\s+"([^"]+)"', entry_text, re.M))
        stack += list(seed_inc or [])
        while stack:
            inc = stack.pop()
            got = self.resolve(inc)
            if got is None:
                continue
            key, text = got
            if key in seen:
                continue
            seen[key] = text
            stack += re.findall(r'^\s*include\s+"([^"]+)"', text, re.M)
        return seen


def repair(mpq_texts: dict[str, str], mapscript: str, gen_texts: dict[str, str],
           seed_includes: list[str], log=print,
           funcref_mode: str = "closure", stage_a: bool = True) -> RepairResult:
    """算符号闭包并修复。

    mpq_texts  : MPQ 内全部可读 galaxy（内名 -> 文本）
    mapscript  : MapScript.galaxy 文本（编译入口）
    gen_texts  : 将要注入的 generated 文件（短名 -> 文本），含 Common 与各 shard
    seed_includes: active 里已经写死的 include（Common + 各 shard body）
    funcref_mode : "closure" 只保留目标在编译单元里的 funcref 分支（默认）；
                   "none" 清空整张表（等价于真机已 PASS 的 nofuncref 变体，兜底用）
    """
    res = RepairResult()
    idx = BaseIndex(mpq_texts)

    # 基线闭包 = MapScript 的 include 链。这部分**已知能编译**（对照组真机 PASS），
    # 故只需要保证"新加进来的东西"自身闭合。
    base_chain = idx.walk(mapscript)
    base_syms = scan_defined(mapscript)
    for t in base_chain.values():
        base_syms |= scan_defined(t)
    base_syms.add("libVibeInvoke_gf_Dispatch")   # active 自己定义

    # 候选 = MPQ 内 Base.SC2Data\Lib*.galaxy 但不在基线链里的库（排除 _h 头）
    cands: dict[str, str] = {}          # include 名 -> MPQ 内名
    for key in mpq_texts:
        if key in base_chain or "\\generated\\" in key:
            continue
        m = re.fullmatch(r"Base\.SC2Data\\(Lib\w+)\.galaxy", key)
        if m and not m.group(1).endswith("_h"):
            cands[m.group(1)] = key

    def _added_only(chain_map: dict[str, str]) -> dict[str, str]:
        return {k: v for k, v in chain_map.items() if k not in base_chain}

    def _closure(added: dict[str, str]) -> tuple[set[str], set[str]]:
        """返回 (当前编译单元符号集, 缺失符号集)。

        【关键】缺失要同时扫 generated 包 **和 Stage A 新拉进来的库**。
        只扫 generated 是致命疏漏：补进来的库自己引用了链外符号照样编译失败，
        表现为"symrep 报 0 缺失、真机 Kernel 依然不注册"。
        """
        syms = set(base_syms)
        for t in added.values():
            syms |= scan_defined(t)
        for t in gen_texts.values():
            syms |= scan_defined(t)
        miss: set[str] = set()
        for t in list(gen_texts.values()) + list(added.values()):
            for name in scan_refs(t):
                if name not in syms and not BLIZZ_PREFIX.match(name):
                    miss.add(name)
        return syms, miss

    _, missing0 = _closure({})
    res.initial_missing = sorted(missing0)
    log(f"[symrep] 基线闭包 {len(base_chain) + 1} 文件 / {len(base_syms)} 符号；"
        f"初始缺失 {len(missing0)} 个")

    # ---- Stage A：补 include，带"引入新缺失就回滚"的自校验 ----
    banned: set[str] = set()
    chosen: list[str] = []
    added: dict[str, str] = {}
    missing: set[str] = set(missing0)

    def _take(inc: str) -> None:
        """把某个库拉进编译单元（同时进 active 的 include 列表与符号闭包）。"""
        chosen.append(inc)
        added.update(_added_only(
            idx.walk(mpq_texts[f"Base.SC2Data\\{inc}.galaxy"], [inc])))

    def _fill() -> None:
        """按缺失符号补 include，补到不动点。"""
        nonlocal missing
        for _ in range(16):
            if not missing:
                return
            pick = None
            for inc, key in sorted(cands.items()):
                if inc in chosen or inc in banned:
                    continue
                if scan_defined(mpq_texts[key]) & missing:
                    pick = inc
                    break
            if pick is None:
                return
            _take(pick)
            before = len(missing)
            _, missing = _closure(added)
            log(f"[symrep] Stage A 补 include \"{pick}\"：缺失 {before} -> {len(missing)}")

    def _orphan_impls() -> list[str]:
        """链上有 `LibXxx_h` 头却没有 `LibXxx` 实现体的库名。

        【2026-08-08 真机根因，勿删】Stage A 沿 include 链拉库时，会把**别的**库的
        `LibXxx_h.galaxy` 顺带带进闭包（被拉进来的库自己 include 了它），但
        `LibXxx.galaxy` 实现体并不在链上。Galaxy 要求「有原型声明必有实现体」，
        否则编译期错误 ⇒ SC2 **静默丢弃整个 MapScript**。
        而 scan_defined 把原型也算作"已定义"，所以符号闭包会报 0 缺失、
        构建门禁全绿，真机却 Kernel 永不注册 —— 排查代价极高。
        实测：gen 图因此产生 24 处孤儿原型（LibEFA54406_h / LibPortingObserver_h 等），
        补上实现体后 closure_doctor 的孤儿数 24 -> 0。
        """
        have = set(base_chain) | set(added)
        out: set[str] = set()
        for key in list(added):
            m = re.fullmatch(r"Base\.SC2Data\\(\w+)_h\.galaxy", key)
            if not m:
                continue
            name = m.group(1)
            impl = f"Base.SC2Data\\{name}.galaxy"
            if impl in have or impl not in mpq_texts or name in banned:
                continue
            out.add(name)
        return sorted(out)

    for _round in range(1 if not stage_a else 12):
        chosen, added = [], {}
        _, missing = _closure(added)
        if not stage_a:
            log("[symrep] Stage A 已禁用（VIBE_STAGEA=0，诊断模式）")
            break
        _fill()
        # ---- Stage A2：给链上孤儿 _h 补实现体，再重新补符号到不动点 ----
        for _ in range(8):
            need = [n for n in _orphan_impls() if n not in chosen]
            if not need:
                break
            for inc in need:
                _take(inc)
                log(f"[symrep] Stage A2 补实现体 \"{inc}\""
                    f"（其 _h 已入链但 body 不在链上 => 孤儿原型 => 整图静默丢弃）")
            before = len(missing)
            _, missing = _closure(added)
            log(f"[symrep] Stage A2 本轮补 {len(need)} 个：缺失 {before} -> {len(missing)}")
            _fill()
        if not missing:
            break
        # 残余是否由某个补进来的库自己引入？是则回滚该库（gen 侧改走 Stage B）
        culprit = None
        for inc in reversed(chosen):
            sub = _added_only(idx.walk(mpq_texts[f"Base.SC2Data\\{inc}.galaxy"], [inc]))
            hit = set()
            for t in sub.values():
                hit |= scan_refs(t) & missing
            if hit:
                culprit = inc
                log(f"[symrep] Stage A 回滚 \"{inc}\"：它自身引用了链外符号 "
                    f"{sorted(hit)[:6]}（补它反而会让全图静默丢弃）")
                break
        if culprit is None:
            break                        # 残余全来自 generated → 交给 Stage B
        banned.add(culprit)

    res.extra_includes = chosen
    res.banned = sorted(banned)
    res.added_chain = sorted(added.keys())
    res.chain_files = len(base_chain) + len(added) + 1

    # ---- Stage C：funcref 静态表按「有 void(int) 实现体」裁剪 ----
    # 【勿改回 _closure 的 syms_final】那个集合由 scan_defined 产出，正则显式收
    # `native` 与孤儿原型，于是 29 个 `native void AI*(int)` 全部漏网、真机静默死。
    # 详见 scan_funcref_targets 的 docstring。
    impl_targets: set[str] = set()
    for t in list(base_chain.values()) + list(added.values()) + list(gen_texts.values()):
        impl_targets |= scan_funcref_targets(t)

    # 【2026-08-08 真机根因 #3，勿把 mapscript 加回 impl_targets】
    # Galaxy 要求**先声明后使用**，而 include 是 DFS 就地展开。接线块位于
    # `MapScript.galaxy` 顶部（`include "LibVibeInvokeDispatch_active"` ≈ 第 20 行），
    # 地图本体自己的触发器函数原型却排在其后（实测 `gf_AIPrepareAttackDirection`
    # 声明在第 239 行）。于是 Common 第 284 行 `return gf_AIPrepareAttackDirection;`
    # 引用了一个此刻**尚未声明**的符号 ⇒ 编译错误 ⇒ 整个 MapScript 被静默丢弃。
    # 该形态骗过了 closure_doctor 的 A~D 形态：它们都是顺序无关的集合判定，
    # 「符号在闭包里存在」即判 CLEAN。真机二分坐实：T-none/T-extras PASS、
    # 加上 Common 的 T-all FAIL，差集只有这一个 map-local funcref 目标。
    maplocal_only = scan_funcref_targets(mapscript) - impl_targets
    if maplocal_only:
        log(f"[symrep] Stage C 排除 map-local funcref 目标 {len(maplocal_only)} 个"
            f"（声明晚于接线块，取址即编译错误）: {sorted(maplocal_only)[:8]}")
    res.funcref_maplocal_dropped = len(maplocal_only)

    allowed: set[str] = set() if funcref_mode == "none" else impl_targets
    for name, text in list(gen_texts.items()):
        if "libVibeInvoke_gf_ResolveFuncref" not in text:
            continue
        t, kept, dropped = reduce_funcref_table(text, allowed)
        if dropped:
            gen_texts[name] = t
            res.patched[name] = t
            res.funcref_kept += kept
            res.funcref_dropped += dropped
            log(f"[symrep] Stage C {name}: funcref 表保留 {kept} / 删除 {dropped}"
                f"（mode={funcref_mode}）")
    _, missing = _closure(added)

    # ---- Stage B：中和残余（只能改 generated，绝不改地图自带库）----
    if missing:
        log(f"[symrep] Stage B 中和残余 {len(missing)} 个: {sorted(missing)[:12]}")
        for name, text in list(gen_texts.items()):
            t = text
            t, n1 = drop_assign_lines(t, missing)
            t, n2 = drop_funcref_branches(t, missing)
            t, killed = neutralize_functions(t, missing)
            if n1 or n2 or killed:
                gen_texts[name] = t
                res.patched[name] = t
                res.dropped_assign += n1
                res.dropped_funcref += n2
                res.neutralized += killed
                log(f"[symrep]   {name}: 删赋值 {n1} / 删 funcref 分支 {n2} / "
                    f"中和函数 {len(killed)}")
        _, missing = _closure(added)

    res.still_missing = missing
    if missing:
        log(f"[symrep] !! 仍有 {len(missing)} 个缺失符号: {sorted(missing)[:20]}")
    else:
        log(f"[symrep] OK 符号闭包完整（0 缺失）；补 include {chosen}，"
            f"回滚 {res.banned}")
    return res
