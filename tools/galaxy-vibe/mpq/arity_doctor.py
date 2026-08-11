"""调用签名体检 —— closure_doctor 覆盖不到的第 7 种静默丢弃形态。

== 为什么需要它 ==
closure_doctor 回答的是「这个符号在编译单元里存不存在 / 声明得够不够早」，
它是**集合 + 顺序**判定，完全不看签名。但 Galaxy 是强类型单遍编译器：

    实参个数 != 形参个数        ⇒ 编译错误
    void 函数的返回值被赋给变量  ⇒ 编译错误
    非 void 函数被当语句丢弃      ⇒ 合法（Galaxy 允许），不报

任何一条编译错误的后果都一样：**SC2 静默丢弃整个 MapScript**，
无 ScriptError、无日志，表现为内核从未注册（bank_keys=0）。

== 为什么现在才暴露 ==
Stage 26 的 adapter 是从 `function-catalog.json` 生成的，而 catalog 抽取自
**完整 CMRE 亡者之夜**；gen 图的基座却是精简的 **standalone VibeDeadOfNight**。
两边同名函数一旦签名漂移（catalog 于 2026-08-08 07:50 重生成过），
生成的 `lv_ret = Foo(a, b, c);` 就会与图内真实的 `Foo(a, b)` 元数不匹配。

用法:
    python arity_doctor.py [地图路径] [--shard 01] [--limit 40]
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import closure_doctor  # noqa: E402
import compile_unit  # noqa: E402

DEFAULT_MAP = r"C:/tmp/VibeDeadOfNight-Gen.SC2Map"

# 函数**定义/原型**的签名。参数区允许换行（暴雪库里有多行签名）。
RE_SIG = re.compile(
    r"^[ \t]*(?:native[ \t]+|static[ \t]+|const[ \t]+)*"
    r"([A-Za-z_]\w*)[ \t]+([A-Za-z_]\w*)[ \t]*\(([^;{)]*)\)[ \t]*[;{]",
    re.M)

_NOT_A_TYPE = {"return", "else", "if", "while", "for", "do", "switch", "case", "sizeof"}


def parse_params(raw: str) -> int | None:
    """形参个数。`()` 与 `(void)` 都算 0；解析不了返回 None（不参与判定）。"""
    s = raw.strip()
    if not s or s == "void":
        return 0
    depth = 0
    n = 1
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            n += 1
    return n


def build_sig_table(texts: dict[str, str]) -> dict[str, tuple[str, int]]:
    """符号 -> (返回类型, 形参个数)。同名以**首次**出现为准（原型通常先于实现）。"""
    table: dict[str, tuple[str, int]] = {}
    for _name, txt in texts.items():
        code = closure_doctor.strip_noise(txt)
        for m in RE_SIG.finditer(code):
            ret, fn, params = m.group(1), m.group(2), m.group(3)
            if ret in _NOT_A_TYPE or fn in _NOT_A_TYPE:
                continue
            n = parse_params(params)
            if n is None or fn in table:
                continue
            table[fn] = (ret, n)
    return table


def split_args(raw: str) -> int:
    """实参个数（顶层逗号切分，忽略括号/方括号内的逗号）。"""
    s = raw.strip()
    if not s:
        return 0
    depth = 0
    n = 1
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            n += 1
    return n


def iter_calls(code: str):
    """产出 (函数名, 实参个数, 调用点偏移, 是否被赋值/用作右值)。"""
    for m in re.finditer(r"(?<![\w.])([A-Za-z_]\w*)\s*\(", code):
        fn = m.group(1)
        if fn in _NOT_A_TYPE:
            continue
        i = m.end() - 1
        depth = 0
        while i < len(code):
            if code[i] in "([":
                depth += 1
            elif code[i] in ")]":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        else:
            continue
        args = code[m.end():i]
        # 是否是「声明/原型」而非调用：右侧紧跟 { 或 ;，且左侧是类型位
        head = code[max(0, m.start() - 40):m.start()].rstrip()
        is_decl = bool(re.search(r"(?:^|[;{}\n])\s*[A-Za-z_]\w*\s*$", head))
        tail = code[i + 1:i + 3].lstrip()
        if is_decl and tail[:1] in ("{", ";"):
            continue
        used_as_value = head.endswith(("=", "+", "-", "*", "/", "(", ",", "!", "<", ">", "&", "|"))
        yield fn, split_args(args), m.start(), used_as_value


@dataclass
class Audit:
    n_sigs: int = 0
    n_files: int = 0
    bad_arity: list[str] = field(default_factory=list)
    bad_void: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


def audit(map_path: Path | str, shard: str | None = None) -> Audit:
    """对一张已打包的 .SC2Map 做调用签名体检（供构建门禁直接调用）。"""
    map_path = Path(map_path)
    unit = compile_unit.resolve(map_path)
    texts = closure_doctor._read_closure(map_path, unit)
    sigs = build_sig_table(texts)

    targets = {k: v for k, v in texts.items()
               if "LibVibeInvoke" in k and not k.endswith("_h.galaxy")}
    if shard:
        targets = {k: v for k, v in targets.items() if f"_{shard}." in k}

    res = Audit(n_sigs=len(sigs), n_files=len(targets))
    unknown: set[str] = set()
    for name, txt in sorted(targets.items()):
        code = closure_doctor.strip_noise(txt)
        line_of = [0]
        for ch in code:
            line_of.append(line_of[-1] + (1 if ch == "\n" else 0))
        for fn, nargs, off, as_value in iter_calls(code):
            sig = sigs.get(fn)
            if sig is None:
                if fn.startswith(("libVibeInvoke_", "libVibeKernel_", "libVibeHandles_")):
                    unknown.add(fn)
                continue
            ret, nparams = sig
            ln = line_of[min(off, len(line_of) - 1)] + 1
            if nargs != nparams:
                res.bad_arity.append(f"{name}:{ln} {fn}(...) 实参 {nargs} != 形参 {nparams}")
            if ret == "void" and as_value:
                res.bad_void.append(f"{name}:{ln} void {fn}(...) 的返回值被当右值使用")
    res.unknown = sorted(unknown)
    return res


def main() -> int:
    argv = list(sys.argv[1:])
    shard = None
    if "--shard" in argv:
        i = argv.index("--shard")
        shard = argv[i + 1]
        del argv[i:i + 2]
    limit = 40
    if "--limit" in argv:
        i = argv.index("--limit")
        limit = int(argv[i + 1])
        del argv[i:i + 2]
    map_path = Path(next((a for a in argv if not a.startswith("--")), DEFAULT_MAP))

    unit = compile_unit.resolve(map_path)
    texts = closure_doctor._read_closure(map_path, unit)
    print(f"[unit ] 闭包 {len(unit.files)} 文件 / 实读 {len(texts)}")

    sigs = build_sig_table(texts)
    print(f"[sig  ] 签名表 {len(sigs)} 个函数")

    targets = {k: v for k, v in texts.items()
               if "LibVibeInvoke" in k and not k.endswith("_h.galaxy")}
    if shard:
        targets = {k: v for k, v in targets.items() if f"_{shard}." in k}
    print(f"[scan ] 受检 adapter 文件 {len(targets)}: {sorted(targets)}")

    bad_arity: list[str] = []
    bad_void: list[str] = []
    unknown: set[str] = set()

    for name, txt in sorted(targets.items()):
        code = closure_doctor.strip_noise(txt)
        line_of = [0]
        for ch in code:
            line_of.append(line_of[-1] + (1 if ch == "\n" else 0))
        for fn, nargs, off, as_value in iter_calls(code):
            sig = sigs.get(fn)
            if sig is None:
                if fn.startswith(("libVibeInvoke_", "libVibeKernel_", "libVibeHandles_")):
                    unknown.add(fn)
                continue
            ret, nparams = sig
            ln = line_of[min(off, len(line_of) - 1)] + 1
            if nargs != nparams:
                bad_arity.append(f"{name}:{ln} {fn}(...) 实参 {nargs} != 形参 {nparams}")
            if ret == "void" and as_value:
                bad_void.append(f"{name}:{ln} void {fn}(...) 的返回值被当右值使用")

    print()
    print(f"[R1] 元数不匹配 : {len(bad_arity)}")
    for s in bad_arity[:limit]:
        print("     ", s)
    if len(bad_arity) > limit:
        print(f"      ... 另有 {len(bad_arity) - limit} 条")

    print(f"[R2] void 当右值 : {len(bad_void)}")
    for s in bad_void[:limit]:
        print("     ", s)

    print(f"[R3] 签名表缺失的 vibe 符号 : {len(unknown)}")
    for s in sorted(unknown)[:limit]:
        print("     ", s)

    return 1 if (bad_arity or bad_void) else 0


if __name__ == "__main__":
    raise SystemExit(main())
