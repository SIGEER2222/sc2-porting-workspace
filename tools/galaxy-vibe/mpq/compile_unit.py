#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Galaxy 编译单元解析器 —— 跨「地图 MPQ + 依赖 mod 目录 + 暴雪基础库」。

【为什么必须跨 mod】
2026-08-08 踩坑：只扫地图 MPQ 得出 "CMPE_PlayerEventFunc 未声明" 的错误结论。
实际上该 typedef 在 `CMRE_Core_Triggers.SC2Mod/Base.SC2Data/scripts/cm_pointer_events_h.galaxy`，
被 `LibCOOC/LibCOMI/LibCOUI` include，而地图 MapScript 第 11-13 行正好 include 了这三个库
⇒ 类型在编译单元里是**可用**的。判断符号是否可用，必须解析完整 include 闭包。

【SC2 include 解析规则】
`include "X/Y"` → 在每个 data root 下找 `X/Y.galaxy`。root 顺序：
  1. 地图 MPQ 根 + `Base.SC2Data/`
  2. DocumentHeader 里每个 `file:Mods/...` 依赖的 `Base.SC2Data/`（按声明顺序）
  3. 暴雪基础库（core / liberty / swarm / void）的 `base.sc2data/`

用法:
  python compile_unit.py <map.SC2Map> [--list] [--sym NAME ...]
"""
from __future__ import annotations

import ctypes
import re
import sys
from collections import defaultdict
from pathlib import Path

def _workspace_root() -> Path:
    """从**任意一份副本**都算出同一个 sc2-porting-workspace 根。

    【2026-08-08 事故，勿改回 `parents[1]`】本文件有 out/ 与 tools/galaxy-vibe/mpq/
    两份**字节完全一致**的副本，字节镜像门禁因此长期 PASS —— 但 `parents[1]` 是相对
    `__file__` 推导的，两份副本算出的 BLIZZ 根本不是同一个目录：
      out/            -> <ws>/reference/sc2mapster/...        存在
      tools/galaxy-vibe/mpq/ -> <ws>/tools/galaxy-vibe/reference/... 不存在
    于是同一张图，closure_doctor（先插 out/，取 out 副本）看到 285 文件/0 未解析，
    verify_funcref（取 mpq 副本）只看到 120 文件/33 未解析 —— 暴雪标准库整块缺席，
    判定依据被悄悄削弱却不报错。哪份生效纯看 import 顺序，是典型「同字节异行为」。
    改为向上找同时含 out/ 与 tools/galaxy-vibe/mpq/ 的祖先目录，两份副本结果恒等。
    """
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "out").is_dir() and (p / "tools" / "galaxy-vibe" / "mpq").is_dir():
            return p
    return here.parents[1]


_WS_ROOT = _workspace_root()
sys.path.insert(0, str(_WS_ROOT / "tools/galaxy-vibe/mpq"))
from mpq_patch_kernel import CRLF, LF, STREAM_FLAG_READ_ONLY, load_storm, mpq_read  # noqa: E402

SC2_ROOT = Path(r"E:/SC2/SC2new/StarCraft II")
BLIZZ = _WS_ROOT / "reference/sc2mapster/SC2GameData/mods"
BLIZZ_MODS = ["core.sc2mod", "liberty.sc2mod", "swarm.sc2mod", "void.sc2mod",
              "libertymulti.sc2mod", "swarmmulti.sc2mod", "voidmulti.sc2mod",
              "alliedcommanders.sc2mod"]

RE_INC = re.compile(r'^\s*include\s+"([^"]+)"', re.M)
RE_DEPBIN = re.compile(rb"file:[\x20-\x7e]{2,200}\.SC2Mod")

# 定义（函数原型/实现、全局、常量）。类型名放宽为任意标识符（支持自定义 typedef）。
# 【2026-08-08 真机取证，勿去掉 group(1) 的关键字过滤】原正则不捕获类型位，于是
# `    return libVibeInvoke_gf_Error(...);` 里的 `return` 被当成返回类型、
# `libVibeInvoke_gf_Error` 被当成**定义**记进 symbols（owner 还指向调用点所在文件）。
# 后果：凡是在 `return X(...)` / `else X(...)` 位置出现过的符号一律被认为"已定义"，
# 未定义调用检测对它们系统性失明 —— 而 generated adapter 里 `return libX_gf_Y(...)`
# 遍地都是。表现为「closure_doctor 全绿、真机 Kernel 永不注册」。
RE_DEF = re.compile(
    r"^[ \t]*(?:native[ \t]+|static[ \t]+|const[ \t]+)*"
    r"([A-Za-z_]\w*)(?:<[^>\n]*>)?(?:[ \t]*\[[ \t]*\d*[ \t]*\])?[ \t]+"
    r"([A-Za-z_]\w*)[ \t]*[\(\[=;]", re.M)
# 出现在「类型位」上就说明这不是声明/定义，而是控制流语句。
NOT_A_TYPE = {"return", "else", "if", "while", "for", "do", "switch", "case",
              "break", "continue", "new", "delete"}
RE_STRUCT = re.compile(r"^[ \t]*struct[ \t]+(\w+)", re.M)
RE_TYPEDEF = re.compile(r"^[ \t]*typedef[ \t]+.*?\b(\w+)[ \t]*;", re.M)

KEYWORDS = {
    "if", "else", "while", "for", "do", "return", "break", "continue", "switch",
    "case", "default", "include", "struct", "typedef", "native", "const", "static",
    "true", "false", "null", "void", "int", "bool", "fixed", "string", "text",
    "byte", "char", "funcref", "structref", "arrayref", "new", "delete",
}

# Galaxy 内建复合类型（引擎内建，任何编译单元都可用）。漏掉它们会把
# `unit lv_p1;` 这种声明里的类型名当成缺失符号，产生成百上千条误报。
BUILTIN_TYPES = {
    "abilcmd", "actor", "actorscope", "aifilter", "animtarget", "bank", "bitmask",
    "camerainfo", "color", "control", "conversationtarget", "datetime", "doodad",
    "generichandle", "marker", "objective", "order", "physicsmover", "ping",
    "planet", "player", "playergroup", "point", "portrait", "region", "revealer",
    "reply", "room", "sound", "soundlink", "soundtag", "story", "timer",
    "transmissionsource", "trigger", "unit", "unitfilter", "unitgroup", "unitref",
    "wave", "waveinfo", "wavetarget", "camerapath", "cameraobject", "actormsg",
}
KEYWORDS |= BUILTIN_TYPES


class Unit:
    def __init__(self) -> None:
        self.files: list[str] = []
        self.symbols: set[str] = set()
        self.sym_owner: dict[str, str] = {}
        self.unresolved: list[str] = []
        self.roots: list[str] = []


def _disk_roots(deps: list[str]) -> list[Path]:
    roots: list[Path] = []
    for d in deps:
        rel = d.split("file:", 1)[-1].replace("\\", "/")
        p = SC2_ROOT / rel / "Base.SC2Data"
        if p.is_dir():
            roots.append(p)
    # 【fail-closed，勿降级为 warning】暴雪基础库缺席时，闭包会安静地少掉上百个文件，
    # include 变 unresolved、符号表残缺，而所有体检器照样输出 CLEAN/PASS。
    # 本项目已被这种「静默降级」坑过多次：宁可炸，也不要给出一个不可信的绿灯。
    if not BLIZZ.is_dir():
        raise SystemExit(
            f"[FAIL] 暴雪基础库目录不存在: {BLIZZ}\n"
            "       编译单元会缺失 core/liberty/swarm/void 全部标准库，任何"
            "「未定义符号 / funcref 合法性」判定都不可信。")
    found = 0
    for m in BLIZZ_MODS:
        p = BLIZZ / m / "base.sc2data"
        if p.is_dir():
            roots.append(p)
            found += 1
    if found == 0:
        raise SystemExit(f"[FAIL] {BLIZZ} 下一个 BLIZZ_MODS 都没找到，闭包不可信。")
    return roots


def resolve(map_path: Path, verbose: bool = False) -> Unit:
    u = Unit()
    dll = load_storm()
    h = ctypes.c_void_p()
    # 签名 SFileOpenArchive(szMpqName, dwPriority, dwFlags, phMpq)。
    # 【勿改回】曾把 STREAM_FLAG_READ_ONLY 填进 dwPriority、dwFlags 传 0 —— 那等于
    # **读写打开**一个本该只读取证的档案：既可能回写污染证据，也会在 SC2 正持有
    # 该图句柄（真机探针进行中）或另一取证进程并发打开时直接 open 失败。
    if not dll.SFileOpenArchive(str(map_path), 0, STREAM_FLAG_READ_ONLY, ctypes.byref(h)):
        raise SystemExit(f"[FAIL] open {map_path}")
    try:
        # --- MPQ 虚拟根 ---
        names = [l.strip() for l in mpq_read(dll, h, "(listfile)")
                 .decode("utf-8", "replace").replace("\r\n", "\n").split("\n") if l.strip()]
        mpq_gal: dict[str, str] = {}
        for n in names:
            if not n.lower().endswith(".galaxy"):
                continue
            norm = n.replace("\\", "/")
            mpq_gal[norm.lower()] = n
            low = norm.lower()
            if low.startswith("base.sc2data/"):
                mpq_gal[low[len("base.sc2data/"):]] = n

        deps = []
        try:
            raw = mpq_read(dll, h, "DocumentHeader")
            for m in RE_DEPBIN.finditer(raw):
                s = m.group(0).decode("ascii", "replace")
                if s not in deps:
                    deps.append(s)
        except Exception:
            pass
        roots = _disk_roots(deps)
        u.roots = [str(r) for r in roots]
        if verbose:
            print(f"[deps ] {len(deps)}: {[d.split('/')[-1] for d in deps]}")
            print(f"[roots] {len(roots)} 磁盘搜索根")

        def read(key: str) -> str | None:
            """key = MPQ 内名 或 'disk:<abspath>'"""
            if key.startswith("disk:"):
                try:
                    return Path(key[5:]).read_text(
                        encoding="utf-8-sig", errors="replace").replace(CRLF, LF)
                except Exception:
                    return None
            try:
                return mpq_read(dll, h, key).decode("utf-8-sig", "replace").replace(CRLF, LF)
            except Exception:
                return None

        def find(inc: str) -> str | None:
            rel = inc.replace("\\", "/").lower()
            if not rel.endswith(".galaxy"):
                rel += ".galaxy"
            if rel in mpq_gal:
                return mpq_gal[rel]
            for r in roots:
                p = r / rel
                if p.is_file():
                    return "disk:" + str(p)
                # 大小写不敏感兜底
                try:
                    parent = (r / rel).parent
                    tgt = (r / rel).name.lower()
                    if parent.is_dir():
                        for f in parent.iterdir():
                            if f.name.lower() == tgt:
                                return "disk:" + str(f)
                except Exception:
                    pass
            return None

        seen: set[str] = set()
        stack = ["MapScript.galaxy"]
        # 引擎隐式提供的 native 声明：dump 里拆成 natives / natives_missing 两份，
        # 后者无人 include。不 seed 会把 TextToString 等真 native 误判为缺失。
        for extra in ("TriggerLibs/natives", "TriggerLibs/natives_missing"):
            k = find(extra)
            if k:
                stack.append(k)
        while stack:
            cur = stack.pop(0)
            if cur.lower() in seen:
                continue
            seen.add(cur.lower())
            t = read(cur)
            if t is None:
                continue
            u.files.append(cur)
            for m in RE_DEF.finditer(t):
                if m.group(1) in NOT_A_TYPE:
                    continue        # `return Foo(...)` 不是定义，见 RE_DEF 注释
                n = m.group(2)
                if n in KEYWORDS:
                    continue
                u.symbols.add(n)
                u.sym_owner.setdefault(n, cur)
            for rx in (RE_STRUCT, RE_TYPEDEF):
                for n in rx.findall(t):
                    u.symbols.add(n)
                    u.sym_owner.setdefault(n, cur)
            for inc in RE_INC.findall(t):
                nxt = find(inc)
                if nxt is None:
                    u.unresolved.append(f"{inc} (from {cur})")
                else:
                    stack.append(nxt)
        return u
    finally:
        dll.SFileCloseArchive(h)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    mp = Path(sys.argv[1])
    u = resolve(mp, verbose=True)
    print(f"[unit ] 闭包 {len(u.files)} 文件, 符号 {len(u.symbols)}")
    mpq_n = sum(1 for f in u.files if not f.startswith("disk:"))
    print(f"        其中 MPQ 内 {mpq_n}, 磁盘 mod {len(u.files) - mpq_n}")
    if u.unresolved:
        agg: dict[str, int] = defaultdict(int)
        for x in u.unresolved:
            agg[x.split(" (from")[0]] += 1
        print(f"[warn ] 未解析 include {len(agg)} 种: {sorted(agg)[:15]}")
    if "--list" in sys.argv:
        for f in u.files:
            print("   ", f)
    for i, a in enumerate(sys.argv):
        if a == "--sym" and i + 1 < len(sys.argv):
            n = sys.argv[i + 1]
            print(f"[sym  ] {n}: {'YES @ ' + u.sym_owner.get(n, '?') if n in u.symbols else 'MISSING'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
