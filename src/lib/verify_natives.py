"""引擎符号核对器 —— 补 galaxy-lint 的致命盲区。

为什么必须有它（round19 血泪，代价是一轮三档全灭）：
  `tools/analysis/galaxy-lint-suppressions.json` 里有一条 `R3-undeclared`：
      match: messageContains  pattern: "Undeclared symbol:"
  它把**所有**未声明符号一律抑制，理由是"隔离 lint 未 include 引擎库"。
  这条规则对 CMRE/RO 那种跨库工程是对的，但对 CMLib 是**灾难**：
  CMLib 的编译单元只 include `TriggerLibs/natives` + 自己，符号集是**封闭可枚举**的。
  于是「调用一个根本不存在的 native」在门禁里表现为 0 error 全绿，
  到真机才由 SC2 **静默丢弃整个 MapScript** 兑现。round19 就是这么挂的。

本工具做 lint 不做的三件事（且不抑制）：
  1. 未知符号：调用了 core.sc2mod 与 CMLib 都没有的函数 -> ERROR
  2. 实参个数与引擎声明不符                              -> ERROR
  3. 引用了不存在的引擎常量 `c_*`                        -> ERROR
第 3 条是 round19 真正的凶手：`cmlib_text.galaxy` 写了 `c_maxInt`，
而 core.sc2mod 里压根没有这个常量（Galaxy 没有 c_maxInt，只有各领域的
c_xxxMax 之类）。它在 lint 里报 "Undeclared symbol: c_maxInt"，被
R3-undeclared 一把抑制，门禁全绿，真机整图消失。

用法：
    python verify_natives.py                 # 核对全部 CMLib 源码
    python verify_natives.py --mark Round19  # 只核对带某标记的新增段落
"""
import re
import sys
from pathlib import Path

# 控制台编码自卫（round24）：本文件成功时打印 '✓'(U+2713)，GBK 控制台编不出来
# -> UnicodeEncodeError -> rc=1 -> gate.py 判「4/7 verify_natives FAILED」。
# 那是**打印崩了**，不是核对没过。同一份代码 UTF-8 下 PASS、GBK 下 FAIL，
# 这种关卡的结论不可信。只改 errors 策略，不动 encoding（改 utf-8 会让
# GBK 控制台上的中文全变乱码）。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

REPO = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace")
CORE = REPO / "reference" / "sc2mapster" / "SC2GameData" / "mods" / "core.sc2mod" / "base.sc2data"
CMLIB = REPO / "src" / "lib" / "scripts" / "cmlib"
SELFTEST = REPO / "src" / "lib" / "selftest" / "cmlib_selftest.galaxy"

KEYWORDS = {
    "if", "while", "for", "return", "switch", "case", "break", "continue",
    "else", "do", "include", "struct", "typedef", "const", "static", "native",
}

TYPES = (r"void|int|fixed|bool|string|text|point|unit|unitgroup|unitfilter|unitref|"
         r"player|playergroup|region|trigger|timer|order|abilcmd|actor|actorscope|"
         r"color|camerainfo|wave|waveinfo|wavetarget|doodad|sound|soundlink|marker|"
         r"revealer|transmissionsource|bank|catalogfieldvaluetype|aifilter|"
         r"objective|ping|portrait|dialog|dialogcontrol|texttag|conversation|"
         r"soundtrack|generichandle|handle|planet|reply|talker|trigger|"
         r"[a-z][a-z0-9_]*")

DECL_RE = re.compile(
    r"^(?:static\s+)?(?:native\s+)?(?:" + TYPES + r")\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*\(([^;{]*)\)\s*[;{]",
    re.M)
CONST_RE = re.compile(r"^(?:static\s+)?const\s+\w+\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", re.M)
GLOBAL_RE = re.compile(r"^(?:" + TYPES + r")\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[[^\]]*\])?\s*;", re.M)


def strip_comments(txt: str) -> str:
    txt = re.sub(r"/\*.*?\*/", "", txt, flags=re.S)
    txt = re.sub(r"//[^\n]*", "", txt)
    return txt


def param_count(sig: str) -> int:
    """形参个数。`void`/空 视作 0。"""
    s = sig.strip()
    if not s or s == "void":
        return 0
    depth, n = 0, 1
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            n += 1
    return n


def collect_decls(files) -> dict:
    """函数名 -> 形参个数（多个同名取最后一个）。"""
    out = {}
    for f in files:
        try:
            txt = strip_comments(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        for m in DECL_RE.finditer(txt):
            out[m.group(1)] = param_count(m.group(2))
    return out


def collect_names(files) -> set:
    out = set()
    for f in files:
        try:
            txt = strip_comments(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        out |= set(CONST_RE.findall(txt))
        out |= set(GLOBAL_RE.findall(txt))
    return out


def arg_count(txt: str, open_idx: int):
    """从 '(' 位置起做括号平衡扫描，返回 (实参个数, 结束位置)。"""
    depth, n, i, seen = 0, 0, open_idx, False
    while i < len(txt):
        ch = txt[i]
        if ch == '"':
            # 字符串字面量整体算一个实参内容。忘了置 seen 会把 f("") 数成 0 个参数。
            if depth == 1:
                seen = True
            i += 1
            while i < len(txt) and txt[i] != '"':
                i += 2 if txt[i] == "\\" else 1
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
            if depth == 0:
                return (n + 1 if seen else 0), i
        elif ch == "," and depth == 1:
            n += 1
        elif depth == 1 and not ch.isspace():
            seen = True
        i += 1
    return -1, len(txt)


CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
CONST_USE_RE = re.compile(r"\b(c_[A-Za-z][A-Za-z0-9_]*)\b")


def main() -> int:
    mark = None
    if "--mark" in sys.argv:
        mark = sys.argv[sys.argv.index("--mark") + 1]

    core_files = sorted(CORE.rglob("*.galaxy"))
    cmlib_files = sorted(CMLIB.glob("*.galaxy")) + ([SELFTEST] if SELFTEST.exists() else [])

    engine = collect_decls(core_files)
    mine = collect_decls(cmlib_files)
    known_fn = {**engine, **mine}
    known_sym = collect_names(core_files) | collect_names(cmlib_files) | set(known_fn)

    print(f"[verify] 引擎函数 {len(engine)} 个 / CMLib 函数 {len(mine)} 个 / "
          f"已知符号合计 {len(known_sym)}")

    unknown, arity, consts = [], [], []
    scanned = 0
    for f in cmlib_files:
        txt = f.read_text(encoding="utf-8", errors="replace")
        # 先按标记截断再剥注释：标记本身就写在注释里，反过来会截不到。
        if mark:
            i = txt.find(mark)
            if i < 0:
                continue
            txt = txt[i:]
        txt = strip_comments(txt)
        scanned += 1
        base = 0
        for m in CALL_RE.finditer(txt):
            name = m.group(1)
            if name in KEYWORDS:
                continue
            # funcref 通过形参/局部变量调用（lp_visitor(...)），被调目标在运行时决定，
            # 静态不可解析，不属于未知符号。
            if name.startswith(("lp_", "lv_", "gv_")):
                continue
            line = txt.count("\n", 0, m.start()) + 1
            if name not in known_fn:
                unknown.append((f.name, line, name))
                continue
            n, _ = arg_count(txt, m.end() - 1)
            want = known_fn[name]
            if n >= 0 and n != want and name in engine:
                arity.append((f.name, line, name, n, want))

        # 引擎常量引用核对。`c_*` 是引擎常量的强命名约定，凡引用不存在的
        # c_xxx 都是编译期未声明符号 —— round19 的 c_maxInt 就死在这。
        for m in CONST_USE_RE.finditer(txt):
            name = m.group(1)
            if name in known_sym:
                continue
            line = txt.count("\n", 0, m.start()) + 1
            consts.append((f.name, line, name))
        base += 1

    print(f"[verify] 扫描 {scanned} 个文件" + (f"（仅 {mark} 段落）" if mark else ""))

    if unknown:
        print(f"\n[verify] ✗ 未知函数 {len(unknown)} 处 —— 真机会静默丢整个 MapScript：")
        for fn, ln, name in unknown:
            print(f"    {fn}:{ln}  {name}(...)")
    if arity:
        print(f"\n[verify] ✗ 实参个数不符 {len(arity)} 处：")
        for fn, ln, name, got, want in arity:
            print(f"    {fn}:{ln}  {name}(...) 传 {got} 个，引擎声明 {want} 个")

    if consts:
        print(f"\n[verify] ✗ 未知引擎常量 {len(consts)} 处 —— 真机会静默丢整个 MapScript：")
        for fn, ln, name in consts:
            print(f"    {fn}:{ln}  {name}")

    if not unknown and not arity and not consts:
        print("\n[verify] ✓ 符号存在性 / 实参个数 / 引擎常量 三项均与引擎声明一致")
        return 0
    return 1


sys.exit(main())
