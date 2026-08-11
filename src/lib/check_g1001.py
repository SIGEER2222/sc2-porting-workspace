# -*- coding: utf-8 -*-
"""
check_g1001.py — Galaxy「局部变量必须置顶」静态门禁（G1001）

背景（真机血泪）：
  Galaxy 要求函数体内**所有局部变量声明必须位于任何可执行语句之前**。
  违反时 SC2 **静默丢弃整个 MapScript**：不报错、不写日志、InitMap() 根本不被调用，
  而 galaxy-lint / check_cmlib.py 照样报 0 错误。表现为真机 Ghost=0 / 地图起不来。

本脚本以「函数体 = 从 `{` 到配对 `}`」为单位扫描，识别第一条可执行语句之后出现的
局部声明。用一个保守的声明识别器（类型白名单 + `ident ident [= ...];` 形态），
避免把 `a = b;`、`if (...)`、函数调用误判为声明。

用法:
    python check_g1001.py            # 扫 src/lib 全树（含 selftest）
    python check_g1001.py <file...>  # 只扫指定文件
退出码: 0 = 通过, 1 = 发现违规
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Galaxy 内置类型 + 引擎 handle 类型（声明左侧可能出现的类型名）
BUILTIN_TYPES = {
    "int", "fixed", "bool", "string", "text", "void", "byte", "char",
    "abilcmd", "actor", "actorscope", "aifilter", "animtarget", "bank",
    "bitmask", "camerainfo", "color", "doodad", "marker", "order",
    "playergroup", "point", "region", "revealer", "sound", "soundlink",
    "timer", "transmissionsource", "trigger", "unit", "unitfilter",
    "unitgroup", "unitref", "wave", "waveinfo", "wavetarget",
    "objective", "generichandle", "effecthistory", "datetime",
    "handle", "unittype",
}

# 语句起手关键字（说明这是可执行语句而非声明）
STMT_KEYWORDS = {
    "if", "else", "while", "for", "do", "return", "break", "continue",
    "switch", "case", "default", "include",
}

DECL_RE = re.compile(
    r"""^\s*(?:const\s+)?
        (?P<type>[A-Za-z_][A-Za-z0-9_]*)
        (?:\s*\[\s*\d*\s*\])?          # 数组类型后缀（少见）
        \s+
        (?P<name>[A-Za-z_][A-Za-z0-9_]*)
        (?:\s*\[[^\]]*\])?             # 数组维度
        \s*(?:=[^;]*)?;\s*$
    """,
    re.X,
)

FUNC_HEAD_RE = re.compile(
    r"^\s*(?:static\s+)?(?:const\s+)?[A-Za-z_][A-Za-z0-9_]*(?:\s*\[\s*\])?\s+"
    r"(?P<fname>[A-Za-z_][A-Za-z0-9_]*)\s*\([^;{]*\)\s*\{\s*$"
)


def strip_comments(text: str) -> list[str]:
    """去掉 // 行注释与 /* */ 块注释（保留行结构，便于报行号）。"""
    out = []
    in_block = False
    for line in text.split("\n"):
        buf = []
        i = 0
        in_str = False
        while i < len(line):
            two = line[i:i + 2]
            if in_block:
                if two == "*/":
                    in_block = False
                    i += 2
                    continue
                i += 1
                continue
            if in_str:
                if line[i] == "\\":
                    buf.append("  ")
                    i += 2
                    continue
                if line[i] == '"':
                    in_str = False
                buf.append(line[i])
                i += 1
                continue
            if two == "//":
                break
            if two == "/*":
                in_block = True
                i += 2
                continue
            if line[i] == '"':
                in_str = True
                buf.append(line[i])
                i += 1
                continue
            buf.append(line[i])
            i += 1
        out.append("".join(buf))
    return out


def is_decl(stripped: str, known_types: set[str]) -> bool:
    m = DECL_RE.match(stripped)
    if not m:
        return False
    t = m.group("type")
    if t in STMT_KEYWORDS:
        return False
    return t in known_types


def collect_struct_types(all_text: str) -> set[str]:
    return set(re.findall(r"^\s*struct\s+([A-Za-z_][A-Za-z0-9_]*)", all_text, re.M))


def scan_file(path: Path, known_types: set[str]) -> list[tuple[int, str, str]]:
    """返回 [(行号, 函数名, 违规行内容)]"""
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = strip_comments(raw)
    violations: list[tuple[int, str, str]] = []

    depth = 0
    fn_name = None
    fn_depth = 0
    seen_stmt = False

    for idx, line in enumerate(lines, start=1):
        s = line.strip()
        if not s:
            continue

        opens = line.count("{")
        closes = line.count("}")

        if fn_name is None:
            m = FUNC_HEAD_RE.match(line)
            if m and depth == 0:
                fn_name = m.group("fname")
                fn_depth = depth + opens - closes
                seen_stmt = False
                depth += opens - closes
                continue
            depth += opens - closes
            if depth < 0:
                depth = 0
            continue

        # 函数体内
        body_line = s
        # 先判断是否函数结束
        new_depth = depth + opens - closes

        if body_line not in ("{", "}"):
            if is_decl(body_line, known_types):
                if seen_stmt:
                    violations.append((idx, fn_name, body_line))
            else:
                # 忽略纯括号/标签行
                if not re.fullmatch(r"[{}]+;?", body_line):
                    seen_stmt = True

        depth = new_depth
        if fn_name is not None and depth <= fn_depth - 1:
            fn_name = None
            seen_stmt = False
            if depth < 0:
                depth = 0

    return violations


def main() -> int:
    if len(sys.argv) > 1:
        files = [Path(a) for a in sys.argv[1:]]
    else:
        files = sorted(HERE.rglob("*.galaxy"))
        files = [f for f in files if "_build" not in str(f)]

    all_text = "\n".join(
        f.read_text(encoding="utf-8", errors="replace") for f in files
    )
    known = set(BUILTIN_TYPES) | collect_struct_types(all_text)

    total = 0
    for f in files:
        vs = scan_file(f, known)
        if vs:
            print(f"\n[G1001] {f.relative_to(HERE) if HERE in f.parents else f}")
            for ln, fn, code in vs:
                print(f"   L{ln:<6} 函数 {fn}()  ->  {code}")
            total += len(vs)

    print("\n" + "-" * 72)
    print(f"扫描 {len(files)} 个 .galaxy 文件，已知类型 {len(known)} 个")
    if total:
        print(f"FAILED — {total} 处「局部变量未置顶」违规（真机会静默丢整个 MapScript）")
        return 1
    print("PASSED — 0 处 G1001 违规")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
