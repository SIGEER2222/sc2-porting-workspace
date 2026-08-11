"""编译闭包体检器 —— 离线复现 Galaxy 编译期错误，交付前最后一道 fail-closed 门禁。

【为什么必须有它】
Galaxy 铁律：编译单元里出现**任何**编译错误，SC2 会**静默丢弃整个 MapScript**——
不报错、不写 ScriptError.txt、不留日志，`InitMap()` 根本不被调用，表现为
「所有门禁全绿、真机 Kernel 永不注册」，排查代价极高。

历史上被逐个踩出来的致命形态（本模块一次性全覆盖）：
  A. 孤儿原型：有 `void Foo(int);` 声明却无实现体。
     事故：Stage A 补 include 时把 `LibEFA54406_h` / `LibPortingObserver_h` 头文件
     带进链，却没带实现体 `LibEFA54406.galaxy` ⇒ 24 处孤儿原型。
  B. 跨文件重复实现：同名函数在两个文件各定义一份。
  C. 未定义调用：调了编译单元里根本不存在的符号。
     事故 C1（假 native）：生成器凭空造 `DateTime(y,m,d,...)`、`RevealerCreate(p,r)`，
       Galaxy 真名是 `IntToDateTime(int)` / `VisRevealerCreate(int, region)`。
     事故 C2（漏扫前缀）：`libEFA54406_InitLib()` / `libX_gt_Y_Func()` /
       `auto_libX_gf_Y_TriggerFunc()` 逃过 symbol_repair 的 REF_RE。
  D. 未定义标识符（**非调用位置**的变量 / trigger 引用）。
     形态 C 的正则 `RE_CALL` 只匹配 `名字(`，对 `x = libX_gv_Foo;` 这类纯变量引用
     完全失明。事故：注入工作区内核时带进了 watchdog 代码，它引用
     `libVibeKernel_gv_watchdogLastSeen` / `_gv_watchdogRestarts` / `_gt_Watchdog`，
     而注入的头文件声明块只补了 tagCache 系列 ⇒ 3 个未定义标识符 ⇒ 整图静默丢弃。
     真机对照：N0min(无此注入)=PASS、N0a(仅多此注入)=FAIL，差集恰为这 3 个符号。

【为什么可信 —— 有对照组】
基准 = `compile_unit.resolve()` 解析出的**真实 include 闭包**（地图 MPQ + 依赖 mod +
暴雪基础库），而非某个手写白名单。对已知能跑的 standalone 基线图
`VibeDeadOfNight.SC2Map` 实测输出 **0 / 0 / 0**（217 文件 / 28736 符号），
对同期编译期即死的 gen 图输出 **24 / 0 / 44** —— 零误报、精确命中。

用法:
    python closure_doctor.py <map.SC2Map>            # CLI 体检
    from closure_doctor import diagnose              # 构建脚本内做硬门禁
    d = diagnose(Path(...)); assert d.clean
"""
from __future__ import annotations

import ctypes
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WS = _HERE.parents[2]
for _p in (str(_WS / "out"), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 形态 J（native 实参/赋值类型错配，VIBE_GEN_003）单独成模块，此处复用其 check()。
# 必须在 sys.path 插入之后 import，故不在文件顶部。
import native_argtype_doctor  # noqa: E402


def _assert_compile_unit_mirrored() -> None:
    """`compile_unit.py` 存在 out/ 与 mpq/ 两份副本，必须字节一致。

    【2026-08-08 真机事故，勿删】sys.path 插入顺序让 `mpq/` 那份胜出（_HERE 后插
    ⇒ 排在最前），于是修在 `out/compile_unit.py` 的 RE_DEF 类型位补丁**根本没生效**，
    体检器一直跑旧正则：`return libX_gf_Y(...)` 里的 `libX_gf_Y` 被误记为「定义」，
    未定义调用检测对 generated adapter 系统性失明 ⇒ 报 CLEAN，真机静默丢弃。
    与 LibVibeKernel 的「3 副本字节一致」门禁同理，这里也 fail-closed。
    """
    import hashlib
    a = _WS / "out" / "compile_unit.py"
    b = _HERE / "compile_unit.py"
    if not (a.is_file() and b.is_file()):
        return
    ha = hashlib.sha256(a.read_bytes()).hexdigest()
    hb = hashlib.sha256(b.read_bytes()).hexdigest()
    if ha != hb:
        raise SystemExit(
            "[FAIL] compile_unit.py 双副本漂移，体检结果不可信：\n"
            f"       {a} {ha[:16]}\n"
            f"       {b} {hb[:16]}\n"
            "       修复: cp out/compile_unit.py tools/galaxy-vibe/mpq/compile_unit.py")


_assert_compile_unit_mirrored()

import compile_unit  # noqa: E402
from mpq_patch_kernel import (  # noqa: E402
    CRLF, LF, STREAM_FLAG_READ_ONLY, load_storm, mpq_read,
)

RE_BLOCK = re.compile(r"/\*.*?\*/", re.S)
RE_LINE = re.compile(r"//[^\n]*")
RE_STR = re.compile(r'"(?:[^"\\\n]|\\.)*"')
RE_CALL = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\s*\(")
RE_PROTO = re.compile(
    r"^[ \t]*(?:native[ \t]+|static[ \t]+|const[ \t]+)*"
    r"([A-Za-z_]\w*)[ \t]+([A-Za-z_]\w*)[ \t]*\([^;{]*\)[ \t]*;", re.M)
RE_IMPL = re.compile(
    r"^[ \t]*(?:static[ \t]+|const[ \t]+)*"
    r"([A-Za-z_]\w*)[ \t]+([A-Za-z_]\w*)[ \t]*\([^;{]*\)[ \t]*\{", re.M)
# 变量声明。Galaxy 的数组维度写在**类型**后面，且可多维、下标可为任意常量表达式：
#   `fixed[N + 1] libX_gv_Y;`
#   `unit[libCOMI_gv_cMC_Fenix_ChampionCount + 1][libCOOC_gv_cCC_MAXPLAYERS + 1] libX_gv_Z;`
RE_VARDECL = re.compile(
    r"^[ \t]*(?:const[ \t]+|static[ \t]+)*"
    r"([A-Za-z_]\w*)(?:[ \t]*\[[^\]]*\])*[ \t]+"
    r"([A-Za-z_]\w*)[ \t]*(?:=[^;]*)?;", re.M)
# 只对工程符号做未定义标识符检查：暴雪库/局部变量命名千奇百怪，纳入即噪声。
RE_PROJECT_SYM = re.compile(r"^(?:auto_)?lib\w*_(?:gv|gt|gf|gs)_")
RE_IDENT = re.compile(r"(?<![\w.])([A-Za-z_]\w*)")

# 出现在「类型位」上就说明这不是函数声明/定义，而是控制流语句
_NOT_A_TYPE = {"return", "else", "if", "while", "for", "do", "switch", "case"}
KW = compile_unit.KEYWORDS | {"sizeof"}


def strip_noise(text: str) -> str:
    """去注释与字符串字面量；只留编译器真正解析的代码。"""
    return RE_STR.sub('""', RE_LINE.sub("", RE_BLOCK.sub(" ", text)))


@dataclass
class Diagnosis:
    files: int = 0
    symbols: int = 0
    unresolved_includes: list[str] = field(default_factory=list)
    orphan_protos: list[str] = field(default_factory=list)
    orphan_by_file: dict[str, int] = field(default_factory=dict)
    dup_impls: list[str] = field(default_factory=list)
    undefined_calls: dict[str, list[str]] = field(default_factory=dict)
    undefined_idents: dict[str, list[str]] = field(default_factory=dict)
    # 形态 E：引用点早于声明点（use-before-declare）。value = (引用文件, 声明文件)
    late_decls: dict[str, tuple[str, str]] = field(default_factory=dict)
    # 形态 H：函数体内局部变量未置顶（`语句; ... <type> lv_x;`）
    local_late_decls: list[str] = field(default_factory=list)
    # 形态 I：else-if 链过长 ⇒ 语法树嵌套深度超限（硬上限 65）
    overlong_elseif: list[str] = field(default_factory=list)
    # 形态 J：native 实参/赋值类型错配（arity 只数个数，看不到类型）
    native_argtypes: list[str] = field(default_factory=list)
    # 形态 K：调用了只有原型没有实现体的函数（funcref 签名模板）
    protoonly_calls: list[str] = field(default_factory=list)
    # 形态 L：跨文件调用 `static`（文件局部）函数 ⇒ 未定义符号
    cross_file_static: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.orphan_protos or self.dup_impls or self.undefined_calls
                    or self.undefined_idents or self.unresolved_includes
                    or self.late_decls or self.local_late_decls
                    or self.overlong_elseif or self.native_argtypes
                    or self.protoonly_calls or self.cross_file_static)

    def summary(self) -> str:
        return (f"闭包 {self.files} 文件/{self.symbols} 符号；"
                f"孤儿原型 {len(self.orphan_protos)}、重复实现 {len(self.dup_impls)}、"
                f"未定义调用 {len(self.undefined_calls)}、"
                f"未定义标识符 {len(self.undefined_idents)}、"
                f"迟声明 {len(self.late_decls)}、"
                f"局部迟声明 {len(self.local_late_decls)}、"
                f"超长 else-if 链 {len(self.overlong_elseif)}、"
                f"类型错配 {len(self.native_argtypes)}、"
                f"调用空原型 {len(self.protoonly_calls)}、"
                f"跨文件调用 static {len(self.cross_file_static)}、"
                f"未解析 include {len(self.unresolved_includes)}")


def _read_closure(map_path: Path, unit) -> dict[str, str]:
    out: dict[str, str] = {}
    dll = load_storm()
    h = ctypes.c_void_p()
    # 参数顺序 (szMpqName, dwPriority, dwFlags, phMpq)；只读取证必须把
    # STREAM_FLAG_READ_ONLY 放在第 3 个 dwFlags 槽位，放错会变成读写打开。
    if not dll.SFileOpenArchive(str(map_path), 0, STREAM_FLAG_READ_ONLY, ctypes.byref(h)):
        raise SystemExit(f"[FAIL] 打不开 {map_path}")
    try:
        for f in unit.files:
            if f.startswith("disk:"):
                try:
                    out[f] = Path(f[5:]).read_text(
                        encoding="utf-8-sig", errors="replace").replace(CRLF, LF)
                except Exception:
                    pass
                continue
            try:
                out[f] = mpq_read(dll, h, f).decode(
                    "utf-8-sig", "replace").replace(CRLF, LF)
            except Exception:
                pass
    finally:
        dll.SFileCloseArchive(h)
    return out


def _dfs_segments(map_path: Path, unit) -> list[tuple[str, str]]:
    """复刻 SC2 的 include 展开顺序：DFS 前序 + 去重，切成 (文件, 代码段) 序列。

    形态 A~D 都是**顺序无关的集合判定**，只回答「符号在闭包里存不存在」。
    但 Galaxy 与 C 一样要求**先声明后使用**，而 `include` 是就地展开。
    于是「符号确实存在、但声明排在引用点之后」会全绿过检、真机静默丢弃。
    切段的目的就是给每个符号一个可比较的「首次声明位置」。
    """
    texts = _read_closure(map_path, unit)
    # 建立 include 名 -> 闭包 key 的索引（与 compile_unit.find 同规则的近似）
    idx: dict[str, str] = {}
    for f in unit.files:
        if f.startswith("disk:"):
            rel = Path(f[5:]).name.lower()
        else:
            rel = f.replace("\\", "/").split("/")[-1].lower()
        idx.setdefault(rel, f)

    order: list[tuple[str, str]] = []
    seen: set[str] = set()

    def walk(key: str) -> None:
        if key in seen or key not in texts:
            return
        seen.add(key)
        # 【勿用 strip_noise 找 include】它会把字符串字面量替换成 ""，
        # `include "LibX"` 会被抹成 `include ""` ⇒ DFS 一步都走不动、形态 E 全漏报。
        # 这里先只去注释保留字符串定位 include，切段后再抹字符串。
        body = RE_LINE.sub("", RE_BLOCK.sub(" ", texts[key]))
        pos = 0
        for m in compile_unit.RE_INC.finditer(body):
            seg = RE_STR.sub('""', body[pos:m.start()])
            if seg.strip():
                order.append((key, seg))
            nxt = idx.get(m.group(1).replace("\\", "/").split("/")[-1].lower() + ".galaxy")
            if nxt:
                walk(nxt)
            pos = m.end()
        tail = RE_STR.sub('""', body[pos:])
        if tail.strip():
            order.append((key, tail))

    for f in unit.files:                    # 引擎 native 声明恒最先可见
        if f.replace("\\", "/").lower().endswith(("triggerlibs/natives.galaxy",
                                                  "triggerlibs/natives_missing.galaxy")):
            walk(f)
    walk("MapScript.galaxy")
    return order


def _check_late_decls(order: list[tuple[str, str]]) -> dict[str, tuple[str, str]]:
    """形态 E：在 DFS 展开序上找 use-before-declare。

    实证事故（2026-08-08 真机二分坐实）：`symbol_repair` 把 **MapScript 本体**的
    触发器函数也收进了 funcref 静态表，生成
    `LibVibeInvokeCommon.galaxy:284  return gf_AIPrepareAttackDirection;`。
    而接线块 `include "LibVibeInvokeDispatch_active"` 在 `MapScript.galaxy:20`，
    该函数的原型却在 `MapScript.galaxy:239` —— 展开时它还不存在 ⇒ 编译错误
    ⇒ 整个 MapScript 被静默丢弃。closure_doctor A~D 全绿，真机 Kernel 永不注册。

    保守判定（宁可漏报不可误报）：
      * 只比较**段序号**，同段内的前后引用不算（生成代码惯例是原型置顶）；
      * 只查工程符号（`libX_gv_/gf_/gt_/gs_` 或 `gf_/gv_/gt_` 地图本体前缀），
        暴雪库与局部变量不纳入；
      * 原型也算声明（与 Galaxy 语义一致）。

    == 形态 E+（VIBE_GEN_006，2026-08-08 追加）==
    上面「只查工程符号」的白名单会漏掉**没有 gf_/gv_ 前缀**的 MapScript 本体函数。
    真机二分坐实：shard07 `2474-2513 PASS / 2474-2514 FAIL`，Call#2514 = `InitGlobals();`
    —— `InitGlobals` 定义在 MapScript.galaxy:470，挂载点在 line 20，且注入管线的
    前置原型块**刻意跳过**了 InitMap/InitLibs/InitGlobals/InitTriggers 这 4 个名字，
    于是调用早于声明 ⇒ 编译错误 ⇒ 整图静默丢弃，而形态 E 因前缀不匹配全程沉默。

    修法：对 own（我们注入的）段**额外**扫一遍**函数调用点**（不是全部标识符），
    不套前缀白名单。只查调用点是刻意的 —— 标识符全查会把暴雪库的局部/宏名扫进来
    变成噪声，而「调用一个后面才声明的函数」是无歧义的致命错。
    """
    proj = re.compile(r"^(?:auto_)?(?:lib\w*_)?(?:gv|gt|gf|gs)_\w+$")
    decl_at: dict[str, int] = {}
    for i, (_key, seg) in enumerate(order):
        for m in compile_unit.RE_DEF.finditer(seg):
            if m.group(1) in compile_unit.NOT_A_TYPE:
                continue
            n = m.group(2)
            if n not in KW:
                decl_at.setdefault(n, i)
        for rx in (compile_unit.RE_STRUCT, compile_unit.RE_TYPEDEF):
            for n in rx.findall(seg):
                decl_at.setdefault(n, i)

    late: dict[str, tuple[str, str]] = {}
    for i, (key, seg) in enumerate(order):
        if key.startswith("disk:"):
            continue                         # 暴雪/依赖 mod 自身顺序不由我们控制
        for n in set(RE_IDENT.findall(seg)):
            if n in KW or not proj.match(n):
                continue
            d = decl_at.get(n)
            if d is not None and d > i and n not in late:
                late[n] = (key.rsplit("\\", 1)[-1], order[d][0].rsplit("\\", 1)[-1])

    # ---- 形态 E+：own 段内的**函数调用点**，不套前缀白名单（VIBE_GEN_006）----
    for i, (key, seg) in enumerate(order):
        if key.startswith("disk:"):
            continue
        for n in set(RE_CALL.findall(seg)):
            if n in KW or n in late:
                continue
            d = decl_at.get(n)
            if d is not None and d > i:
                late[n] = (key.rsplit("\\", 1)[-1], order[d][0].rsplit("\\", 1)[-1])
    return late


_STMT_KW = {"return", "break", "continue", "else", "do", "case", "default",
            "goto", "include", "if", "while", "for", "switch", "struct"}
_RE_FUNC_OPEN = re.compile(
    r"^[ \t]*(?:static[ \t]+|const[ \t]+|native[ \t]+)*"
    r"([A-Za-z_]\w*)[ \t]+([A-Za-z_]\w*)[ \t]*\([^;{]*\)[ \t]*\{[ \t]*$")
_RE_LOCAL_DECL = re.compile(
    r"^[ \t]*(?:const[ \t]+|static[ \t]+)*"
    r"([A-Za-z_]\w*)(?:[ \t]*\[[^\]]*\])*[ \t]+"
    r"([A-Za-z_]\w*)[ \t]*(?:=[^;]*)?;[ \t]*$")


def _check_local_decls(texts: dict[str, str], own: list[str]) -> list[str]:
    """形态 H：函数体内局部变量未置顶 ⇒ 编译错误 ⇒ 静默丢弃。

    Galaxy 硬性规则：一个函数体内所有局部变量声明必须位于**任何可执行语句之前**。
    形态 E 只比较跨文件的段序号，对函数体内部完全失明；arity/type 体检同样看不到。

    判据刻意**不依赖类型白名单**：Galaxy 里「两个相邻标识符 + 分号」只可能是变量
    声明（可执行语句必含 `=` / `(` / `.` / 运算符，或以关键字开头）。用白名单会把
    `datetime`、用户 `struct`（如 `libCOTF_gs_HistogramData`）判成语句，制造成片假阳性
    ——2026-08-09 首版就是这么误报 27 处的。
    """
    bad: list[str] = []
    for f in own:
        raw = texts[f]
        # 保行号去噪：块注释按换行数还原
        clean = RE_STR.sub('""', RE_LINE.sub(
            "", RE_BLOCK.sub(lambda m: "\n" * m.group(0).count("\n"), raw)))
        lines = clean.split("\n")
        short = f.rsplit("\\", 1)[-1]
        i, n = 0, len(lines)
        while i < n:
            m = _RE_FUNC_OPEN.match(lines[i])
            if not m or m.group(1) in _NOT_A_TYPE:
                i += 1
                continue
            fname = m.group(2)
            depth, j, first_stmt = 1, i + 1, None
            while j < n and depth > 0:
                ln = lines[j]
                depth += ln.count("{") - ln.count("}")
                if depth <= 0:
                    break
                body = ln.strip()
                if body:
                    dm = _RE_LOCAL_DECL.match(ln)
                    if dm and dm.group(1) not in _STMT_KW:
                        if first_stmt is not None:
                            bad.append(f"{short}:L{j + 1} {fname}() `{body}` "
                                       f"(首条语句 L{first_stmt})")
                    elif body not in ("{", "}") and first_stmt is None:
                        first_stmt = j + 1
                j += 1
            i = j + 1
    return bad


_RE_NATIVE_DECL = re.compile(
    r"^[ \t]*native[ \t]+([A-Za-z_]\w*)[ \t]+([A-Za-z_]\w*)[ \t]*\(", re.M)
_RE_DECL_HEAD_TMPL = (r"^[ \t]*(?:native[ \t]+|static[ \t]+|const[ \t]+)*"
                      r"[A-Za-z_]\w*[ \t]+{name}[ \t]*\(")


def _check_protoonly_calls(texts: dict[str, str], own: list[str]) -> list[str]:
    """形态 K：调用了**只有原型、没有实现体**的函数 ⇒ 编译失败 ⇒ 静默丢弃。

    【VIBE_GEN_004 — 2026-08-09 真机二分坐实】
    Galaxy 的 funcref 用法要求先声明一个「签名模板原型」：

        void CMPE_PlayerEvent_Proto(int lp_player);          // 故意无实现体
        typedef funcref<CMPE_PlayerEvent_Proto> CMPE_PlayerEventFunc;

    这**完全合法** —— 前提是永不调用它。Stage 26 的导出清单把它当普通函数
    生成了 adapter（`CMPE_PlayerEvent_Proto(lv_p0);`），于是调用一个无实现符号，
    整图静默丢弃。

    为什么形态 A（孤儿原型）漏报：A 只在 `own`（地图自身文件）内配对原型/实现，
    而该原型住在**依赖 mod** `cm_pointer_events_h.galaxy` 里 —— 压根不在扫描范围。
    依赖 mod 里存在无实现原型本身没问题（原版地图从不调用它），
    真正致命的是**我们生成的代码去调用了它**。所以判据必须是：
        全闭包收集 impl/native  ->  求出 proto-only 集合  ->  只在 own 里查调用。

    真机二分：shard03 `801-1015 PASS / 801-1016 FAIL`，Call#1016 恰是它的 adapter。
    """
    impls: set[str] = set()
    natives: set[str] = set()
    protos: set[str] = set()
    for t0 in texts.values():
        t = strip_noise(t0)
        for _typ, nm in RE_IMPL.findall(t):
            impls.add(nm)
        for _typ, nm in _RE_NATIVE_DECL.findall(t):
            natives.add(nm)
        for typ, nm in RE_PROTO.findall(t):
            if typ in _NOT_A_TYPE or nm in KW:
                continue
            protos.add(nm)
    dead = protos - impls - natives
    if not dead:
        return []
    bad: list[str] = []
    for f in own:
        short = f.rsplit("\\", 1)[-1]
        for i, ln in enumerate(strip_noise(texts[f]).split("\n"), 1):
            for m in RE_CALL.finditer(ln):
                nm = m.group(1)
                if nm not in dead:
                    continue
                # 声明行自身不算调用
                if re.match(_RE_DECL_HEAD_TMPL.format(name=re.escape(nm)), ln):
                    continue
                bad.append(f"{short}:L{i} 调用无实现体原型 `{nm}`"
                           f"（多半是 funcref 签名模板，见 VIBE_GEN_004）")
    return bad


# 与 RE_IMPL 同形，但把修饰符（static/const）单独捕获出来
_RE_IMPL_FLAGGED = re.compile(
    r"^[ \t]*((?:static[ \t]+|const[ \t]+)*)"
    r"([A-Za-z_]\w*)[ \t]+([A-Za-z_]\w*)[ \t]*\([^;{]*\)[ \t]*\{", re.M)


def _check_cross_file_static_calls(texts: dict[str, str],
                                   own: list[str]) -> list[str]:
    """形态 L：跨文件调用 `static`（文件局部）函数 ⇒ 未定义符号 ⇒ 静默丢弃。

    【VIBE_GEN_005 — 2026-08-09 真机二分坐实】
    Galaxy 的 `include` **不是** C 式文本内联：每个 `.galaxy` 是独立编译单元，
    `static` 把符号**限死在定义它的那个文件里**。因此

        // tactterrai.galaxy
        static bool CallDownMule (int player, unit aiUnit) { ... }

    从别的文件写 `CallDownMule(p, u);` = 调用未定义符号 = 编译失败 = 整图静默丢弃。

    为什么形态 C（未定义调用）漏报：C 只看「全闭包里有没有这个名字的实现」，
    `CallDownMule` 确确实实有实现体，所以 C 判它已定义。可见性（file-local）
    是 C 看不到的维度 —— 必须单独建一项。

    判据：某函数名的**所有**实现体都带 `static` ⇒ 该名字是文件局部符号集合；
    只要调用点所在文件 ∉ 定义它的文件集合，就是致命错。
    （若同名还存在一个非 static 实现或 native 声明，则全局可见，不报。）

    真机二分：shard07 `2401-2472 PASS / 2401-2473 FAIL`，Call#2473 恰是
    `CallDownMule(lv_p0, lv_p1);`。亡者之夜 bundle 共 4 个此类导出
    （CallDownMule/CastAutoTurret/ForceField/GuardianShield），最小 id = 2473，
    与二分结果逐位吻合。
    """
    static_owners: dict[str, set[str]] = {}
    global_vis: set[str] = set()
    for f, t0 in texts.items():
        t = strip_noise(t0)
        for mods, typ, nm in _RE_IMPL_FLAGGED.findall(t):
            if typ in _NOT_A_TYPE or nm in KW:
                continue
            if "static" in mods:
                static_owners.setdefault(nm, set()).add(f)
            else:
                global_vis.add(nm)
        for _typ, nm in _RE_NATIVE_DECL.findall(t):
            global_vis.add(nm)
    file_local = {nm: owners for nm, owners in static_owners.items()
                  if nm not in global_vis}
    if not file_local:
        return []
    bad: list[str] = []
    for f in own:
        short = f.rsplit("\\", 1)[-1]
        for i, ln in enumerate(strip_noise(texts[f]).split("\n"), 1):
            for m in RE_CALL.finditer(ln):
                nm = m.group(1)
                owners = file_local.get(nm)
                if owners is None or f in owners:
                    continue
                if re.match(_RE_DECL_HEAD_TMPL.format(name=re.escape(nm)), ln):
                    continue
                src = sorted(o.rsplit("\\", 1)[-1] for o in owners)[:2]
                bad.append(f"{short}:L{i} 跨文件调用 static 函数 `{nm}`"
                           f"（仅在 {src} 内可见，见 VIBE_GEN_005）")
    return bad


_RE_ELSEIF = re.compile(r"\belse[ \t\r\n]+if\b")
_RE_IF_OPEN = re.compile(r"(?<![\w.])if[ \t]*\(")
ELSEIF_LIMIT = 60          # 安全阈值；真机实测硬上限 65


def _check_overlong_elseif(texts: dict[str, str], own: list[str]) -> list[str]:
    """形态 I：`else if` 链过长 ⇒ 语法树嵌套超限 ⇒ 静默丢弃整个 MapScript。

    【VIBE_GEN_002 — 2026-08-09 真机二分坐实】
    Galaxy 里 `} else if (c) {` 在语法树上等价于 `else { if (c) { ... } }`，
    N 个分支 = N 层嵌套。真机阶梯地图二分实测：
        1-65 分支 -> P0 PASS（bank_keys=22）
        1-66 分支 -> P0 FAIL（bank_keys=0，MapScript 整体被静默丢弃）
    超限时**没有任何** ScriptError / 日志，closure(A~F)/arity(G)/type 体检全绿，
    是本项目排查成本最高的一次静默失败（耗掉一次完整真机二分才定位）。

    修法：改**扁平 early-return**（`if (c) { return ...; }` 逐条并列），
    嵌套深度恒为 1，与分支数无关。
    """
    bad: list[str] = []
    for f in own:
        clean = RE_STR.sub('""', RE_LINE.sub(
            "", RE_BLOCK.sub(lambda m: "\n" * m.group(0).count("\n"), texts[f])))
        lines = clean.split("\n")
        short = f.rsplit("\\", 1)[-1]
        chain, start = 0, 0
        for i, ln in enumerate(lines):
            if _RE_ELSEIF.search(ln):
                if chain == 0:
                    chain, start = 2, i + 1     # 补上被 else 接续的首个 if
                else:
                    chain += 1
                continue
            if _RE_IF_OPEN.search(ln):
                if chain > ELSEIF_LIMIT:
                    bad.append(f"{short}:L{start} else-if 链 {chain} 分支"
                               f"（嵌套 {chain} 层 > 硬上限 65）")
                chain, start = 1, i + 1
                continue
            if ln.strip() in ("", "{", "}"):
                continue                        # 链中间的空白/括号行不打断
            if chain > ELSEIF_LIMIT:
                bad.append(f"{short}:L{start} else-if 链 {chain} 分支"
                           f"（嵌套 {chain} 层 > 硬上限 65）")
            chain = 0
        if chain > ELSEIF_LIMIT:
            bad.append(f"{short}:L{start} else-if 链 {chain} 分支"
                       f"（嵌套 {chain} 层 > 硬上限 65）")
    return bad


def diagnose(map_path: Path) -> Diagnosis:
    """对打包后的 .SC2Map 做全闭包编译期体检。"""
    unit = compile_unit.resolve(map_path)
    texts = _read_closure(map_path, unit)
    d = Diagnosis(files=len(unit.files), symbols=len(unit.symbols),
                  unresolved_includes=sorted({x.split(" (from")[0]
                                              for x in unit.unresolved}))

    # 只对 MPQ 内文件（地图 + 注入包）做严格体检：暴雪基础库(disk:)含大量
    # native 声明与工程约定，不属于本次改动可控范围，纳入会产生噪声。
    own = [f for f in texts if not f.startswith("disk:")]

    protos: dict[str, str] = {}
    impls: dict[str, list[str]] = {}
    for f in own:
        t = strip_noise(texts[f])
        for typ, nm in RE_PROTO.findall(t):
            if typ in _NOT_A_TYPE or nm in KW:
                continue
            protos.setdefault(nm, f)
        for typ, nm in RE_IMPL.findall(t):
            if typ in _NOT_A_TYPE or nm in KW:
                continue
            impls.setdefault(nm, []).append(f)

    d.orphan_protos = sorted(n for n in protos if n not in impls)
    for n in d.orphan_protos:
        k = protos[n].rsplit("\\", 1)[-1]
        d.orphan_by_file[k] = d.orphan_by_file.get(k, 0) + 1
    d.dup_impls = sorted(n for n, fs in impls.items() if len(set(fs)) > 1)

    known = unit.symbols | KW
    for f in own:
        for nm in sorted(set(RE_CALL.findall(strip_noise(texts[f])))):
            if nm in known:
                continue
            d.undefined_calls.setdefault(nm, []).append(f.rsplit("\\", 1)[-1])

    # ---- 形态 D：未定义标识符（变量 / trigger，非调用位置）----
    # 变量声明扫**整个闭包**（含 disk: 暴雪库），引用侧只查 MPQ 内自有文件。
    declared: set[str] = set()
    for t in texts.values():
        for typ, nm in RE_VARDECL.findall(strip_noise(t)):
            if typ not in _NOT_A_TYPE:
                declared.add(nm)
    known_ident = known | declared
    for f in own:
        for nm in sorted(set(RE_IDENT.findall(strip_noise(texts[f])))):
            if nm in known_ident or not RE_PROJECT_SYM.match(nm):
                continue
            d.undefined_idents.setdefault(nm, []).append(f.rsplit("\\", 1)[-1])

    # ---- 形态 E：use-before-declare（顺序敏感，A~D 一律漏报）----
    d.late_decls = _check_late_decls(_dfs_segments(map_path, unit))

    # ---- 形态 H：函数体内局部变量未置顶（A~E 与 arity/type 体检一律漏报）----
    d.local_late_decls = _check_local_decls(texts, own)

    # ---- 形态 I：else-if 链过长（VIBE_GEN_002，A~H 与 arity/type 一律漏报）----
    d.overlong_elseif = _check_overlong_elseif(texts, own)

    # ---- 形态 J：native 实参/赋值类型错配（VIBE_GEN_003，A~I 与 arity 全漏报）----
    d.native_argtypes = native_argtype_doctor.check(texts, own)

    # ---- 形态 K：调用无实现体原型（VIBE_GEN_004，A~J 全漏报）----
    d.protoonly_calls = _check_protoonly_calls(texts, own)

    # ---- 形态 L：跨文件调用 static 函数（VIBE_GEN_005，A~K 全漏报）----
    d.cross_file_static = _check_cross_file_static_calls(texts, own)
    return d


def report(d: Diagnosis, label: str) -> int:
    """打印体检报告，返回退出码（0=CLEAN，1=BROKEN）。

    从 main() 抽出来供前置门禁（staged_map_doctor.py）复用：否则调用方要自己
    重写 12 种形态的输出，新增形态时必然漂移成"门禁看不见的错误"。
    """
    print(f"[unit ] {d.summary()}")
    if d.unresolved_includes:
        print(f"[FAIL] 未解析 include: {d.unresolved_includes[:10]}")
    if d.orphan_protos:
        print(f"[FAIL] 孤儿原型 {len(d.orphan_protos)}（有声明无实现 ⇒ 编译错误）")
        for k, v in sorted(d.orphan_by_file.items(), key=lambda x: -x[1]):
            print(f"        {v:5d}  {k}")
        print(f"        样本: {d.orphan_protos[:8]}")
    if d.dup_impls:
        print(f"[FAIL] 跨文件重复实现 {len(d.dup_impls)}: {d.dup_impls[:8]}")
    if d.undefined_calls:
        print(f"[FAIL] 未定义调用 {len(d.undefined_calls)}")
        agg: dict[str, int] = {}
        for fs in d.undefined_calls.values():
            for f in set(fs):
                agg[f] = agg.get(f, 0) + 1
        for k, v in sorted(agg.items(), key=lambda x: -x[1])[:15]:
            print(f"        {v:5d}  {k}")
        print(f"        样本: {sorted(d.undefined_calls)[:10]}")
    if d.undefined_idents:
        print(f"[FAIL] 未定义标识符 {len(d.undefined_idents)}（变量/trigger 无声明 ⇒ 编译错误）")
        for nm in sorted(d.undefined_idents)[:15]:
            print(f"        {nm}  <- {d.undefined_idents[nm][:3]}")
    if d.late_decls:
        print(f"[FAIL] 迟声明 {len(d.late_decls)}（引用早于声明 ⇒ 编译错误 ⇒ 静默丢弃）")
        for nm in sorted(d.late_decls)[:15]:
            ref, dec = d.late_decls[nm]
            print(f"        {nm}  引用@{ref}  声明@{dec}")
    if d.local_late_decls:
        print(f"[FAIL] 局部迟声明 {len(d.local_late_decls)}"
              f"（函数体内变量未置顶 ⇒ 编译错误 ⇒ 静默丢弃）")
        for s in d.local_late_decls[:15]:
            print(f"        {s}")
    if d.overlong_elseif:
        print(f"[FAIL] 超长 else-if 链 {len(d.overlong_elseif)}"
              f"（嵌套深度 > 65 ⇒ 编译错误 ⇒ 静默丢弃，见 VIBE_GEN_002）")
        for s in d.overlong_elseif[:15]:
            print(f"        {s}")
    if d.native_argtypes:
        print(f"[FAIL] native 类型错配 {len(d.native_argtypes)}"
              f"（实参/赋值类型不符 ⇒ 编译错误 ⇒ 静默丢弃，见 VIBE_GEN_003）")
        for s in d.native_argtypes[:15]:
            print(f"        {s}")
    if d.protoonly_calls:
        print(f"[FAIL] 调用无实现体原型 {len(d.protoonly_calls)}"
              f"（funcref 签名模板被当普通函数调用 ⇒ 静默丢弃，见 VIBE_GEN_004）")
        for s in d.protoonly_calls[:15]:
            print(f"        {s}")
    if d.cross_file_static:
        print(f"[FAIL] 跨文件调用 static {len(d.cross_file_static)}"
              f"（file-local 符号被外部调用 ⇒ 未定义 ⇒ 静默丢弃，见 VIBE_GEN_005）")
        for s in d.cross_file_static[:15]:
            print(f"        {s}")
    print(f"[{'CLEAN' if d.clean else 'BROKEN'}] {label}")
    return 0 if d.clean else 1


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    map_path = Path(sys.argv[1])
    return report(diagnose(map_path), map_path.name)


if __name__ == "__main__":
    raise SystemExit(main())
