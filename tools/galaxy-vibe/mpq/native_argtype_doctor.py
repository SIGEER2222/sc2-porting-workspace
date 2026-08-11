"""形态 J：native 调用**实参类型**核对（closure/arity 体检的盲区）。

【VIBE_GEN_003 — 2026-08-09 真机二分坐实】
生成器的 ctor 模板会把 wire 值拆出来喂给引擎 native，例如
    Order(AbilityCommand(<slot0>, <slot1>))
其中 `native abilcmd AbilityCommand (string inAbil, int inCmdIndex)` 的槽 0 是
**string**。旧生成器兜底成 `StringToInt(...)` → 类型不匹配 → 编译错误 →
SC2 **静默丢弃整个 MapScript**（无 ScriptError、无日志、无崩溃）。

为什么已有的三层体检全部漏报：
  - closure_doctor(A~I)：只问「符号存不存在」，不看实参类型。
  - arity_doctor(G)    ：只数**实参个数**，个数正好时完全静默。
  - check_types        ：只核对 adapter 直接调用的**目标函数**，
                          看不进 ctor 模板内层嵌套的 native 调用。
真机代价：一次完整二分（阶梯地图 ×6 轮 + 每轮真机 ~2 分钟）才收敛到 Call#66。

本检查器补上这块：解析 native 签名表 → 对受检文件里每个 native 调用逐参推断
实参类型 → 比对。**推断不出来就跳过**（宁可漏报也不误报：误报会污染二分信号，
比漏报更贵——2026-08-09 的形态 H 首版就因白名单误报 27 处浪费了一轮）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

WS = Path(__file__).resolve().parents[3]
NATIVE_DIRS = [
    WS / "reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs",
]

RE_BLOCK = re.compile(r"/\*.*?\*/", re.S)
RE_LINE = re.compile(r"//[^\n]*")
RE_STR = re.compile(r'"(?:\\.|[^"\\])*"')

RE_NATIVE = re.compile(
    r"^native[ \t]+([A-Za-z_]\w*)[ \t]+([A-Za-z_]\w*)[ \t]*\(([^)]*)\)[ \t]*;",
    re.M | re.S)
# natives.galaxy 里有大量**多行**声明（如 UnitCreate 参数逐行排布），按逗号切开后
# 每个分片带前导换行。`^[ \t]*` 匹配不到换行 -> 整条签名被判解析失败而丢弃 ->
# 对该 native 完全失明。必须用 `\s*`（覆盖 \n）。踩过一次，别再收窄。
RE_PARAM = re.compile(r"^\s*(?:const\s+)?([A-Za-z_]\w*(?:<[^>]*>)?)\s+([A-Za-z_]\w*)")
RE_FUNC_OPEN = re.compile(
    r"^[ \t]*(?:static[ \t]+|const[ \t]+)*"
    r"([A-Za-z_]\w*)[ \t]+([A-Za-z_]\w*)[ \t]*\(([^;{]*)\)[ \t]*\{[ \t]*$")
RE_LOCAL = re.compile(
    r"^[ \t]*(?:const[ \t]+)?([A-Za-z_]\w*)(?:[ \t]*\[[^\]]*\])?[ \t]+"
    r"([A-Za-z_]\w*)[ \t]*(?:=[^;]*)?;[ \t]*$")

# int 可隐式提升为 fixed；反向不行。其余一律要求精确匹配。
WIDENS = {("int", "fixed")}
# 这些形参类型不做核对：泛型/引用/回调，推断代价高且易误报。
SKIP_PARAM_TYPES = {"funcref", "structref", "arrayref", "void"}
# `structref<T>` / `arrayref<T>` / `funcref<T>` 形参：Galaxy 里**只能**直接传同名
# 结构体/数组变量（结构体不能按值传参），`Foo(lv_myStruct)` 就是唯一合法写法。
# 按裸类型比对会把它一律判成错配 —— 实测在 shard25 的 Histogram 系列上产生 2 处误报。
SKIP_PARAM_PREFIXES = ("funcref<", "structref<", "arrayref<")


def _skip_param(want: str) -> bool:
    return want in SKIP_PARAM_TYPES or want.startswith(SKIP_PARAM_PREFIXES)


def strip_noise(text: str) -> str:
    """去注释；字符串字面量替换成占位符 `__STR__`（保留可推断的类型信息）。"""
    text = RE_BLOCK.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    text = RE_LINE.sub("", text)
    return RE_STR.sub("__STR__", text)


def load_natives() -> dict[str, tuple[str, list[str]]]:
    """返回 {name: (return_type, [param_types])}。"""
    sigs: dict[str, tuple[str, list[str]]] = {}
    for d in NATIVE_DIRS:
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.galaxy")):
            for m in RE_NATIVE.finditer(strip_noise(
                    f.read_text(encoding="utf-8", errors="replace"))):
                ret, name, params = m.group(1), m.group(2), m.group(3).strip()
                ptypes: list[str] = []
                ok = True
                if params and params != "void":
                    for p in params.split(","):
                        pm = RE_PARAM.match(p)
                        if not pm:
                            ok = False
                            break
                        ptypes.append(pm.group(1))
                if ok:
                    sigs[name] = (ret, ptypes)
    return sigs


def split_args(s: str) -> list[str]:
    """按顶层逗号切分实参（尊重括号嵌套）。"""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


RE_CALL_HEAD = re.compile(r"(?<![\w.])([A-Za-z_]\w*)[ \t]*\(")
# 纯赋值语句（排除 `==`/`!=`/`+=` 等复合，只看单纯的 `x = expr;`）
RE_ASSIGN = re.compile(r"^[ \t]*([A-Za-z_]\w*)[ \t]*=[ \t]*([^=].*);[ \t]*$")
_INT_LIT = re.compile(r"^-?\d+$")
_FIXED_LIT = re.compile(r"^-?\d+\.\d*$")


def infer(expr: str, locals_: dict[str, str],
          sigs: dict[str, tuple[str, list[str]]]) -> str | None:
    """推断表达式类型；推断不出返回 None（跳过，不报错）。"""
    e = expr.strip()
    while e.startswith("(") and e.endswith(")") and _balanced(e[1:-1]):
        e = e[1:-1].strip()
    if not e:
        return None
    if e == "__STR__":
        return "string"
    if e in ("true", "false"):
        return "bool"
    if e == "null":
        return None                      # null 可赋给任意 handle
    if _INT_LIT.match(e):
        return "int"
    if _FIXED_LIT.match(e):
        return "fixed"
    if e in locals_:
        return locals_[e]
    m = RE_CALL_HEAD.match(e)
    if m and e.endswith(")"):
        fn = m.group(1)
        if fn in sigs:
            return sigs[fn][0]
        return None
    return None                          # 运算表达式/字段访问/未知：不猜


def _balanced(s: str) -> bool:
    d = 0
    for ch in s:
        if ch in "([":
            d += 1
        elif ch in ")]":
            d -= 1
            if d < 0:
                return False
    return d == 0


def scan_text(text: str, short: str,
              sigs: dict[str, tuple[str, list[str]]]) -> list[str]:
    bad: list[str] = []
    lines = strip_noise(text).split("\n")
    locals_: dict[str, str] = {}
    for i, ln in enumerate(lines):
        fo = RE_FUNC_OPEN.match(ln)
        if fo:
            locals_ = {}
            for p in split_args(fo.group(3)):
                pm = RE_PARAM.match(p)
                if pm:
                    locals_[pm.group(2)] = pm.group(1)
            continue
        lo = RE_LOCAL.match(ln)
        if lo and lo.group(1) not in ("return", "else", "break", "continue"):
            locals_[lo.group(2)] = lo.group(1)
            # 声明行也可能含调用（`int x = Foo(...)`），继续往下扫

        # 赋值类型核对：`lv_x = <expr>;`。native 实参核对看不到这一类
        # （例：`int lv_ret = <某个返回 fixed 的 native>();` 元数正确、符号存在、
        #  实参类型正确，却仍是编译错误 -> 静默丢弃）。
        am = RE_ASSIGN.match(ln)
        if am and am.group(1) in locals_:
            want = locals_[am.group(1)]
            got = infer(am.group(2), locals_, sigs)
            if (got is not None and not _skip_param(want)
                    and got != want and (got, want) not in WIDENS):
                bad.append(f"{short}:L{i + 1} 赋值 {am.group(1)} 需 {want} 得 {got}"
                           f"  ->  `{am.group(2)[:60]}`")

        for m in RE_CALL_HEAD.finditer(ln):
            fn = m.group(1)
            if fn not in sigs:
                continue
            # 取出这次调用的实参串（到配对的右括号为止）
            start = m.end()
            depth, j = 1, start
            while j < len(ln) and depth > 0:
                if ln[j] in "([":
                    depth += 1
                elif ln[j] in ")]":
                    depth -= 1
                j += 1
            if depth != 0:
                continue                 # 跨行调用：跳过（宁漏勿误）
            args = split_args(ln[start:j - 1])
            ptypes = sigs[fn][1]
            if len(args) != len(ptypes):
                continue                 # 元数问题交给 arity_doctor
            for k, (a, want) in enumerate(zip(args, ptypes)):
                if _skip_param(want):
                    continue
                got = infer(a, locals_, sigs)
                if got is None or got == want:
                    continue
                if (got, want) in WIDENS:
                    continue
                bad.append(
                    f"{short}:L{i + 1} {fn}() 第{k + 1}参 需 {want} 得 {got}"
                    f"  ->  `{a[:60]}`")
    return bad


RE_PROTO = re.compile(
    r"^[ \t]*(?:static[ \t]+|const[ \t]+)*"
    r"([A-Za-z_]\w*)[ \t]+([A-Za-z_]\w*)[ \t]*\(([^;{)]*)\)[ \t]*;[ \t]*$", re.M)


def collect_closure_sigs(texts: dict[str, str]) -> dict[str, tuple[str, list[str]]]:
    """从**编译闭包自身**抽函数签名（定义体 + 前置原型）。

    【为什么必须有 —— VIBE_GEN_004 血泪】只装 native 签名等于只覆盖了冰山一角：
    6709 个导出函数里绝大多数是 map-local 的 `libX_gf_Y` / `gf_Y`，adapter 包装它们时
    同样会踩类型错配（VIBE_GEN_003 的 `AbilityCommand(string,int)` 只是碰巧是 native）。
    map-local 目标的签名 native 表里根本没有 -> `fn not in sigs` -> 直接 continue ->
    **系统性失明**。闭包内的定义/原型就是权威签名源，必须一并装表。

    native 优先：闭包里若同名（如某 mod 重声明），以 native 表为准，避免被脏声明带偏。
    """
    sigs: dict[str, tuple[str, list[str]]] = {}

    def _params(raw: str) -> list[str] | None:
        raw = raw.strip()
        if not raw or raw == "void":
            return []
        out: list[str] = []
        for p in split_args(raw):
            pm = RE_PARAM.match(p)
            if not pm:
                return None
            out.append(pm.group(1))
        return out

    for text in texts.values():
        clean = strip_noise(text)
        for ln in clean.split("\n"):
            fo = RE_FUNC_OPEN.match(ln)
            if fo:
                ps = _params(fo.group(3))
                if ps is not None:
                    sigs[fo.group(2)] = (fo.group(1), ps)
        for m in RE_PROTO.finditer(clean):
            if m.group(2) in sigs:
                continue
            ps = _params(m.group(3))
            if ps is not None:
                sigs[m.group(2)] = (m.group(1), ps)
    return sigs


def check(texts: dict[str, str], own: list[str]) -> list[str]:
    sigs = load_natives()
    if not sigs:
        return []                        # 无签名源时不误伤（镜像未初始化）
    # 闭包内签名先铺底，native 表后盖（native 权威）。
    merged = collect_closure_sigs(texts)
    merged.update(sigs)
    bad: list[str] = []
    for f in own:
        bad += scan_text(texts[f], f.rsplit("\\", 1)[-1], merged)
    return bad


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    sigs = load_natives()
    print(f"[info] native 签名表 {len(sigs)} 条")
    files: list[Path] = []
    for a in args:
        p = Path(a)
        files += sorted(p.rglob("*.galaxy")) if p.is_dir() else [p]
    print(f"[info] 受检 {len(files)} 文件")

    total = 0
    seen: set[str] = set()
    for f in files:
        for s in scan_text(f.read_text(encoding="utf-8", errors="replace"),
                           f.name, sigs):
            total += 1
            key = s.split("  ->")[0].split(":L")[0] + s.split("] ")[-1][:40]
            if key not in seen and len(seen) < 40:
                seen.add(key)
                print(f"[FAIL] {s}")
    print(f"\n=== 形态 J native 实参类型错配 {total} 处 ===")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
