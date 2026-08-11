#!/usr/bin/env python
"""CMLib 门禁 :: 调用范围三层可见性检查（round27）

## 这一关在守什么

Galaxy 调用一个**编译单元里没有声明**的函数 = 编译错误，而 SC2 对编译错误的
反应是**静默丢弃整个 MapScript**：不报错、不写日志、`InitMap()` 根本不被调用。
静态 lint 照样报 0 错误。这是本项目最贵的一类事故（README §5.3）。

所以「这个符号能不能调」必须有权威判据。历轮反复在这上面翻车，原因是把
**三个不同层级**混成了一个「存在/不存在」的布尔：

    A 层 · 编译单元内有声明（安全）
        声明在 `TriggerLibs/NativeLib` 的**传递 include 闭包**里。
        闭包 = NativeLib → NativeLib_h + natives → GameData/GameDataAllNatives
        （→110 个 GameData/*.galaxy）+ TriggerLibs/AI → TriggerLibs/BaseAI。
        依据：`core.sc2mod/.../TriggerLibs/LibraryList.xml` 只声明了一个共享
        外部库 `TriggerLibs/NativeLib`，所以 core 带进编译单元的就是这个闭包。

        **根必须是 NativeLib 而不是 natives**：写这一关时先拿 natives 当根，
        当场把 `SoundPlay`/`SoundPlayAtPoint`/`SoundPlayOnUnit` 判成禁止调用
        —— 实测 `NativeLib.galaxy:4260` 是 `void SoundPlay(...) {` **有函数体的
        普通库函数**（`NativeLib_h.galaxy:541` 是它的原型），而 NativeLib
        include natives（方向是反的）。CMLib 测试图的 MapScript 只写了
        `include "TriggerLibs/natives"` 却照样真机 556/556，是因为
        core.sc2mod 自身的脚本先编译、整条依赖链共享一个编译单元。
        判「能不能调」要看**最终编译单元**，不是看自己那行 include 写了什么。

    B 层 · 闭包外，但官方 `.galaxy` 里白纸黑字 `native`（可调用，记台账不阻断）
        典型：整个 AI filter 一族（`AIFilter` / `AISetFilterAlliance` /
        `AIFilterCasters` …）实测全部是 `TriggerLibs/Tactical/TacticalAI.galaxy`
        里的 `native` 声明。TacticalAI 只被 `TriggerLibs/Computer.galaxy` include，
        而 Computer 只被**每张地图编辑器自动生成的 `aiXXXXXXXX.galaxy`** 引入，
        core 的 LibraryList 里没有它 —— 所以它们确实在闭包外。

        但它们照样能调：round22 的翻案证据是官方合作 mod `LibCOOC.galaxy`
        零自声明直调 `StatEventCreate`。**native 符号表是引擎内建的**，
        `.galaxy` 里的 `native` 行只是编辑器/lint 元数据。既然官方文件里
        白纸黑字写着 `native`，引擎符号表里就一定有这个符号。

        这一层**只打台账不阻断**。强制给 24 个官方 native 逐条写登记，
        换来的只会是 24 行橡皮图章 —— 一个人人都会闭眼签的登记表等于恒绿判据，
        还会把下面真正需要人判断的那几条淹掉。登记要留给真的有判断的地方。

    R 层 · 闭包外 + 无官方 native 声明（必须逐条登记）
        只出现在 `natives_missing.galaxy`（**社区补录**，看头部那种
        `/// * Unit :: unit` 注释风格就知道不是暴雪原文件，而且全树没人 include 它）
        或只有 `NativeLib.TriggerLib` 的 `<FlagNative/>` 背书。
        round23 的教训正出在这一层：`StatEventCreate` **可调用但恒返回 0**
        （非暴雪签名内容里被引擎拒绝）—— 「可调用 ≠ 可用」。
        所以这一层必须**逐个显式登记**，写清为什么接受风险。

    C 层 · 既不在闭包内、也没有任何 native 背书（禁止调用）
        典型形态是「某个 mod 里有函数体、但不在我们编译单元里」的库函数。
        调了就是未声明函数 → 编译错误 → SC2 静默丢弃整个 MapScript。硬失败。

## 为什么值得单独立一关

round27 的生成器 `extend_round27b.py` 一开始把判据写成「只认 natives.galaxy」，
直接把 `AISetStockTechNextUnCap` / `AISetStockAlias` / `AISetStockFree` 这三个
**在链内**的符号误判成范围外要拒绝；更早一版用 `<FlagNative/>` 当判据，又把
`PointFromId` / `OrderSetPlayer`（natives.galaxy 白纸黑字声明、但不在 FlagNative
集合里）误判成不能调；这一关自己第一版把闭包根写成 natives 而漏掉整个
NativeLib；第二版又把**分层的轴选错了** —— 以为是「在不在闭包」的一维问题，
实际是「引擎内建 native」和「有函数体的库函数」两种完全不同的东西，
前者不需要声明也能调，后者不在编译单元里就是死。

**同一个口径连错四次、四个不同方向。** 靠人脑记不住 —— 这正是把它变成可执行
门禁而不是文档一行字的理由。

判据本身会写窄或写宽，所以这关自带五向反向对照（见 `selftest()`）。
恒绿和恒红一样是坏死。

## 登记语法（机器可读）

在任意 `scripts/cmlib/*_h.galaxy` 里写：

    // @scope-flagonly <符号> <为什么可以接受>

判定是集合等式：`被调用的R层符号集合 == 登记集合`，多一个（幽灵）少一个（过期）
都失败。人写的那一半只能多不能少，跟 `check_native_ledger.py` 同款纪律。
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
SELFTEST = HERE / "selftest"
GAMEDATA = (REPO / "reference" / "sc2mapster" / "SC2GameData" / "mods"
            / "core.sc2mod" / "base.sc2data")
TRIG = GAMEDATA / "TriggerLibs"

# 根必须是 NativeLib：它 include natives（方向是反的），拿 natives 当根会漏掉
# 整个 NativeLib.galaxy（SoundPlay 等普通库函数就住在那里）。详见模块 docstring。
ROOT_INCLUDE = "TriggerLibs/NativeLib"

# fail-closed 下限。参考树没铺开时闭包会缩水成一个「看起来全绿」的子集，
# 那比没有门禁更危险 —— 它给人已经检查过的错觉。
MIN_CLOSURE_FILES = 100
MIN_CLOSURE_SYMBOLS = 2000
MIN_FLAG_SYMBOLS = 2000
MIN_OFFICIAL_NATIVES = 2000

INCLUDE_RE = re.compile(r'^\s*include\s+"([^"]+)"', re.M)
# 匹配 `native void Foo(`、`void Foo(`、`static void Foo(`、`const int Foo(`。
# 修饰符必须单独成组吃掉：第一版写成 `(?:native )?<类型> <名>(`，于是
# `static void CMLib_LogEmit(` 被解析成「类型=static 名=void」而漏掉真名，
# CMLib 自己的 static 函数全部没进 own 集合，反过来被这一关当成外部调用告警。
DECL_RE = re.compile(
    r"^[ \t]*(?:(?:native|static|const)[ \t]+)*"     # 修饰符（可叠加、可为空）
    r"([\w\[\]<>]+)[ \t]+"                            # 返回类型
    r"(\w+)[ \t]*\(",                                 # 函数名
    re.M,
)
CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
SCOPE_RE = re.compile(r"//\s*@scope-flagonly\s+(\w+)\s+(.+?)\s*$")

KEYWORDS = {
    "if", "while", "for", "return", "include", "native", "const", "struct",
    "typedef", "break", "continue", "else", "do", "switch", "case", "static",
    "void", "true", "false", "null", "and", "or", "not", "new", "delete",
}

# 只有这些能出现在「返回类型」位上才算假声明。**`void` 绝不能进这个集合** ——
# 第一版直接复用了 KEYWORDS，于是 `void Foo(` 全被判成假声明：闭包符号从
# 3000+ 缩到 1553（fail-closed 下限当场救了场），CMLib 自己的 void 函数也没进
# own 集合，1100+ 条自指误报。判据的解析器本身就是 bug 的高发地。
NON_TYPE_KEYWORDS = {
    "if", "while", "for", "return", "include", "else", "do", "switch", "case",
    "break", "continue", "new", "delete", "and", "or", "not", "true", "false",
    "null", "typedef", "struct",
}

# funcref 变量的调用点 `lp_visitor()` / `lv_f()` 长得和函数调用一模一样，
# 但它们是**变量**，符号解析发生在赋值处而不是调用处。CMLib 的命名规范里
# lp_=形参 / lv_=局部 / gv_=全局 / av_=数组元素，全部不是函数名。
# 这不是"放宽判据"：真有人把函数命名成 lp_ 开头，check_cmlib.py 的命名关会先红。
LOCALREF_RE = re.compile(r"^(?:lp|lv|gv|av)_")


def _strip_comments(text: str) -> str:
    return "\n".join(ln.split("//", 1)[0] for ln in text.splitlines())


def _resolve(inc: str) -> Path | None:
    for cand in (GAMEDATA / inc, GAMEDATA / (inc + ".galaxy")):
        if cand.is_file():
            return cand
    return None


def include_closure() -> list[Path]:
    """从 TriggerLibs/natives 出发求传递 include 闭包。

    include 串有的带 `.galaxy` 后缀有的不带（natives.galaxy 里两种都有），
    解析时必须两种都试 —— 只试一种会让闭包提前截断，然后整关变成
    「口径更窄的假门禁」。
    """
    seen: set[str] = set()
    queue: list[str] = [ROOT_INCLUDE]
    files: list[Path] = []
    while queue:
        cur = queue.pop(0)
        key = cur[:-7] if cur.endswith(".galaxy") else cur
        if key in seen:
            continue
        seen.add(key)
        p = _resolve(cur)
        if p is None:
            continue
        files.append(p)
        for m in INCLUDE_RE.finditer(p.read_text(encoding="utf-8", errors="replace")):
            queue.append(m.group(1))
    return files


def _decl_names(body: str) -> list[str]:
    """从源码正文抽函数名。返回类型落在 KEYWORDS 里的直接丢 ——
    否则 `return Foo(` 会被当成「类型 return / 名 Foo」的声明。"""
    out: list[str] = []
    for m in DECL_RE.finditer(body):
        rettype, name = m.group(1), m.group(2)
        if rettype in NON_TYPE_KEYWORDS or name in KEYWORDS:
            continue
        out.append(name)
    return out


def closure_symbols(files: list[Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in files:
        body = _strip_comments(p.read_text(encoding="utf-8", errors="replace"))
        for name in _decl_names(body):
            out.setdefault(name, p.name)
    return out


NATIVE_DECL_RE = re.compile(r"^[ \t]*native[ \t]+[\w\[\]<>]+[ \t]+(\w+)[ \t]*\(", re.M)

# natives_missing.galaxy 是社区补录，不是暴雪原文件（全树零 include，
# 参数注释是 galaxy-lint 的 `/// * Unit :: unit` 风格）。它的 native 声明
# 不能当官方背书用 —— StatEventCreate 就是从这里来的，而它恒返回 0。
COMMUNITY_DECL = {"natives_missing.galaxy"}


def _official_native_files() -> list[Path]:
    return [p for p in sorted(TRIG.rglob("*.galaxy")) if p.name not in COMMUNITY_DECL]


def official_natives() -> dict[str, str]:
    """core.sc2mod 官方 `.galaxy` 里所有 `native` 声明 → 引擎符号表确凿有。"""
    out: dict[str, str] = {}
    for p in _official_native_files():
        body = _strip_comments(p.read_text(encoding="utf-8", errors="replace"))
        for m in NATIVE_DECL_RE.finditer(body):
            out.setdefault(m.group(1), p.name)
    return out


def community_natives() -> set[str]:
    out: set[str] = set()
    for name in COMMUNITY_DECL:
        p = TRIG / name
        if not p.exists():
            continue
        body = _strip_comments(p.read_text(encoding="utf-8", errors="replace"))
        out.update(m.group(1) for m in NATIVE_DECL_RE.finditer(body))
    return out


def flag_natives() -> set[str]:
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


def cmlib_sources() -> list[Path]:
    return sorted(CMLIB.glob("*.galaxy")) + sorted(SELFTEST.glob("*.galaxy"))


def scan_cmlib(extra: dict[str, str] | None = None
               ) -> tuple[set[str], dict[str, str]]:
    """返回 (库自身定义的函数名, {外部被调符号: 第一个出现的文件名})。

    `extra` 用于 selftest 注入合成源码，不落盘、不污染仓库。
    """
    texts: list[tuple[str, str]] = []
    for p in cmlib_sources():
        texts.append((p.name, p.read_text(encoding="utf-8", errors="replace")))
    for name, body in (extra or {}).items():
        texts.append((name, body))

    own: set[str] = set()
    for _, raw in texts:
        own.update(_decl_names(_strip_comments(raw)))

    called: dict[str, str] = {}
    for name, raw in texts:
        for m in CALL_RE.finditer(_strip_comments(raw)):
            sym = m.group(1)
            if sym in own or sym in KEYWORDS or LOCALREF_RE.match(sym):
                continue
            called.setdefault(sym, name)
    return own, called


def registered_flagonly(extra: dict[str, str] | None = None) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    srcs = [(f.name, f.read_text(encoding="utf-8", errors="replace"))
            for f in sorted(CMLIB.glob("*_h.galaxy"))]
    srcs += list((extra or {}).items())
    for fname, raw in srcs:
        for line in raw.splitlines():
            m = SCOPE_RE.search(line)
            if m:
                out[m.group(1)] = (m.group(2).strip(), fname)
    return out


class Scan:
    """一次分析的全部中间量。用类而不是 7 元组 —— 上一版返回 7 个位置参数，
    加一层分类就得改所有调用点，改漏一个就是静默错位。"""

    def __init__(self, files, scope, official, community, flag, called, reg):
        self.files, self.scope = files, scope
        self.official, self.community, self.flag = official, community, flag
        self.called, self.reg = called, reg
        self.tier_a: dict[str, str] = {}
        self.tier_b: dict[str, str] = {}   # 闭包外 + 官方 native 声明
        self.tier_r: dict[str, str] = {}   # 闭包外 + 只有社区补录/FlagNative
        self.tier_c: dict[str, str] = {}   # 什么背书都没有
        for sym, where in called.items():
            if sym in scope:
                self.tier_a[sym] = where
            elif sym in official:
                self.tier_b[sym] = where
            elif sym in community or sym in flag:
                self.tier_r[sym] = where
            else:
                self.tier_c[sym] = where


def analyse(extra_src: dict[str, str] | None = None,
            extra_reg: dict[str, str] | None = None) -> Scan:
    files = include_closure()
    return Scan(files, closure_symbols(files), official_natives(),
                community_natives(), flag_natives(),
                scan_cmlib(extra_src)[1], registered_flagonly(extra_reg))


def _verdict(s: Scan, verbose: bool = True) -> int:
    errs: list[str] = []

    # ---- fail-closed：输入残缺时绝不放行 ----
    if len(s.files) < MIN_CLOSURE_FILES:
        errs.append(f"include 闭包只有 {len(s.files)} 个文件（下限 {MIN_CLOSURE_FILES}）"
                    f"—— 参考树没铺开，判据会缩水成假门禁")
    if len(s.scope) < MIN_CLOSURE_SYMBOLS:
        errs.append(f"闭包内可见符号只有 {len(s.scope)} 个（下限 {MIN_CLOSURE_SYMBOLS}）")
    if len(s.flag) < MIN_FLAG_SYMBOLS:
        errs.append(f"FlagNative 只解析到 {len(s.flag)} 个（下限 {MIN_FLAG_SYMBOLS}）")
    if len(s.official) < MIN_OFFICIAL_NATIVES:
        errs.append(f"官方 native 声明只解析到 {len(s.official)} 个"
                    f"（下限 {MIN_OFFICIAL_NATIVES}）")

    # ---- C 层：硬失败 ----
    for sym, where in sorted(s.tier_c.items()):
        errs.append(f"[C层·禁止调用] {sym}（出现在 {where}）"
                    f" —— 既不在 include 闭包内，也没有任何 native 声明背书；"
                    f"调用它 = 未声明函数 = SC2 静默丢弃整个 MapScript")

    # ---- R 层：必须登记，且登记不能过期 ----
    for sym, where in sorted(s.tier_r.items()):
        if sym not in s.reg:
            src = "社区补录 natives_missing" if sym in s.community else "仅 <FlagNative/>"
            errs.append(f"[R层·未登记] {sym}（出现在 {where}，背书来源：{src}）"
                        f" —— 无官方 native 声明，「可调用 ≠ 可用」（见 StatEventCreate 恒返回 0），"
                        f"必须写 `// @scope-flagonly {sym} <理由>` 明示接受风险")
    for sym, (reason, fname) in sorted(s.reg.items()):
        if sym not in s.tier_r:
            if sym in s.scope:
                errs.append(f"[登记过期] {sym}（登记在 {fname}）"
                            f" —— 它其实在闭包内（{s.scope[sym]}），属 A 层，登记是多余的")
            elif sym in s.official:
                errs.append(f"[登记过期] {sym}（登记在 {fname}）"
                            f" —— 它有官方 native 声明（{s.official[sym]}），属 B 层，不需要登记")
            else:
                errs.append(f"[登记过期] {sym}（登记在 {fname}）—— 库里已经不调用它了")
        elif not reason:
            errs.append(f"[登记无理由] {sym}（登记在 {fname}）")

    if verbose:
        print("=" * 78)
        print("[scope] 调用范围四层：A=编译单元内 / B=官方native(台账) / "
              "R=无官方背书(须登记) / C=禁止")
        print("=" * 78)
        print(f"  include 闭包：{len(s.files)} 个文件 / {len(s.scope)} 个可见符号"
              f"（根：{ROOT_INCLUDE}）")
        print(f"  官方 native 声明 {len(s.official)} · 社区补录 {len(s.community)} · "
              f"<FlagNative/> {len(s.flag)}")
        print(f"  CMLib 外部调用面：{len(s.called)} 个符号")
        print(f"  A 层 {len(s.tier_a)} · B 层 {len(s.tier_b)} · "
              f"R 层 {len(s.tier_r)} · C 层 {len(s.tier_c)}")
        if s.tier_b:
            print()
            print("  B 层台账（闭包外，但官方 .galaxy 有 native 声明 —— 可调，不阻断）：")
            byfile: dict[str, list[str]] = {}
            for sym in sorted(s.tier_b):
                byfile.setdefault(s.official[sym], []).append(sym)
            for fname, syms in sorted(byfile.items()):
                print(f"    {fname}  ({len(syms)}): {', '.join(syms[:6])}"
                      f"{' …' if len(syms) > 6 else ''}")
        if s.tier_r:
            print()
            print("  R 层（无官方 native 声明，必须登记）：")
            for sym in sorted(s.tier_r):
                mark = "已登记" if sym in s.reg else "!! 未登记"
                reason = s.reg.get(sym, ("", ""))[0]
                print(f"    {sym:<34} {mark}  {reason[:44]}")
        print()

    if errs:
        print(f"[scope] FAILED —— {len(errs)} 项")
        for e in errs:
            print("  - " + e)
        return 1
    if verbose:
        print("[scope] PASSED —— 无 C 层调用，R 层全部有显式登记且无过期项")
    return 0


# --------------------------------------------------------------------------
# 门禁的门禁：五向反向对照
# --------------------------------------------------------------------------
# 判据坏死有两种形态，恒绿（同义反复）和恒红（与被测系统正常态冲突）。
# 只验「现状 PASS」抓不到恒绿，只验「注入必红」抓不到恒红，所以两个方向都要。
# 这一关有四个分层，每多一层就多一条会误伤的边 —— B 层就是第二版真的踩到的
# 那条边（把 24 个官方 native 判成禁止调用），所以它必须有自己的对照档。
#
# 探针符号一律**运行时从参考树里挑**，且要求 CMLib 零接触：
# 硬编码一个符号名，参考树一换版它就可能失效，判据会静默退化成永远不注入。
SYNTH_C = "CMLibNoSuchEngineFunctionZZZ"   # 保证任何来源都查不到


def _pick(cands: list[str], label: str) -> str | None:
    if not cands:
        print(f"  [E] 找不到可用的 {label} 探针符号 —— 无法证伪，fail-closed")
        return None
    return cands[0]


def selftest() -> int:
    print("=" * 78)
    print("[scope-selftest] 门禁的门禁：五向反向对照")
    print("=" * 78)
    base = analyse()
    scope, called = base.scope, base.called

    # R 档探针：闭包外 + 无官方 native 声明 + CMLib 零接触
    probe_r = _pick(sorted(s for s in (base.community | base.flag)
                           if s not in scope and s not in base.official
                           and s not in called), "R层")
    # B 档探针：闭包外 + 有官方 native 声明 + CMLib 零接触
    probe_b = _pick(sorted(s for s in base.official
                           if s not in scope and s not in called), "B层")
    if probe_r is None or probe_b is None:
        return 1

    def inject(sym: str, tag: str) -> dict[str, str]:
        return {f"fake_scope_{tag}.galaxy": f"void CMLibFake_{tag}() {{ {sym}(); }}"}

    rows: list[tuple[str, str, bool]] = []

    # A 档：现状必须 PASS。可证伪 —— 谁再引入 C 层调用或漏登记就立刻红。
    rows.append(("A 现状", "仓库当前调用面",
                 _verdict(base, verbose=False) == 0))

    # R 档：注入未登记的「无官方背书」调用 -> 必须 FAIL。证明不是恒绿。
    rows.append(("R 未登记无背书", f"注入 {probe_r}",
                 _verdict(analyse(extra_src=inject(probe_r, "r")), verbose=False) != 0))

    # C 档：注入一个任何来源都查不到的符号 -> 必须 FAIL（静默丢图形态）。
    rows.append(("C 未声明符号", f"注入 {SYNTH_C}",
                 _verdict(analyse(extra_src=inject(SYNTH_C, "c")), verbose=False) != 0))

    # D 档：R 档注入 + 补上登记 -> 必须回到 PASS。证明登记出口真的通。
    rows.append(("D 登记后放行", f"{probe_r} + 登记",
                 _verdict(analyse(
                     extra_src=inject(probe_r, "r"),
                     extra_reg={"fake_h.galaxy":
                                f"// @scope-flagonly {probe_r} 合成对照，仅存在于内存"}),
                     verbose=False) == 0))

    # E 档：注入官方 native（闭包外）-> 必须 PASS 且**不要求登记**。
    # 这一档专治恒红：第二版就是在这里把整个 AI filter 一族判成了禁止调用。
    rows.append(("E 官方native不误伤", f"注入 {probe_b}",
                 _verdict(analyse(extra_src=inject(probe_b, "b")), verbose=False) == 0))

    ok = True
    for name, detail, good in rows:
        print(f"  [{'OK' if good else 'BAD'}] {name:<22} {detail}")
        ok = ok and good
    print()
    if not ok:
        print("[scope-selftest] FAILED —— 门禁自身行为不正确，本关结论不可信")
        return 1
    print("[scope-selftest] PASSED —— 门禁在 A~E 五个方向上都行为正确")
    return 0


def main() -> int:
    if "--selftest-only" in sys.argv:
        return selftest()
    rc = selftest()
    if rc:
        return rc
    print()
    return _verdict(analyse())


if __name__ == "__main__":
    raise SystemExit(main())
