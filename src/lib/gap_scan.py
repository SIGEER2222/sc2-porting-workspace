#!/usr/bin/env python3
"""CMLib 覆盖缺口扫描器.

扫描工作区所有 mod 的 .galaxy 源码，统计引擎 native / 库函数调用频次，
按领域分桶，并与 CMLib 现有 API 覆盖面比对，输出未覆盖的高频领域。

用法:
    python gap_scan.py [--top N] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

WS = Path(__file__).resolve().parents[3]  # SC2VibeTools
CMLIB = Path(__file__).resolve().parent / "scripts" / "cmlib"

# 扫描范围：真实 mod / 地图源码目录（排除 CMLib 自身、工具链与构建产物）
SCAN_ROOTS = [
    WS / "cmre-runtime" / "Mods",
    WS / "cmre-runtime" / "Maps",
    WS / "sc2-porting-workspace" / "src" / "projects",
    WS / "sc2-porting-workspace" / "reference" / "sc2mapster",
    WS / "sc2-porting-workspace" / "reference" / "Night-of-the-Dead",
    WS / "sc2-porting-workspace" / "reference" / "SC2plusSCBW",
    WS / "sc2-porting-workspace" / "reference" / "SC2BW",
    WS / "sc2-porting-workspace" / "reference" / "Cerebrates",
]

EXCLUDE_PARTS = {
    "cmlib", "_depmap_build", "_negmap_build", "_probe_build",
    "_testmap_build", "_testmap_src", "node_modules", ".git",
    "stubs", "sc2-galaxy-toolkit", "galaxy-vibe", ".cache",
}

# 引擎权威 native 判据（round23 修正）
# ------------------------------------------------------------------
# 旧判据：只把「扫到的 .galaxy 里出现 `native X(...)` 声明」当作真 native。
# round22 已证伪这条：SC2 的 native 符号表是**引擎内建**的，.galaxy 里的
# `native` 声明只是编辑器 / lint 的元数据。典型反例 StatEvent* 六件套——
# core 的 natives.galaxy 里没有、只在 natives_missing.galaxy 有声明，
# 却在 NativeLib.TriggerLib 里全部带 <FlagNative/>，真机三档探针全 PASS。
# 新判据 = natives.galaxy ∪ natives_missing.galaxy ∪ <FlagNative/> 条目。
CORE = (WS / "sc2-porting-workspace" / "reference" / "sc2mapster" /
        "SC2GameData" / "mods" / "core.sc2mod" / "base.sc2data")
CORE_TRIGGERLIBS = CORE / "TriggerLibs"
# 权威 native 声明文件（.galaxy 形态）
NATIVE_DECL_FILES = ("natives.galaxy", "natives_missing.galaxy")
# 权威 native 元数据（XML 形态，编辑器函数库）
NATIVE_XML = "NativeLib.TriggerLib"

_FLAGNATIVE_ELEM_RE = re.compile(
    r"<Element\b[^>]*Type=\"FunctionDef\"[^>]*>(.*?)</Element>", re.S)
_IDENT_RE = re.compile(r"<Identifier>([\w]+)</Identifier>")

# 领域分桶规则：前缀 -> 领域名。按顺序首次匹配。
DOMAIN_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("unit",      re.compile(r"^Unit(?!Group)")),
    ("unitgroup", re.compile(r"^UnitGroup")),
    ("player",    re.compile(r"^Player")),
    ("playergroup", re.compile(r"^PlayerGroup")),
    ("trigger",   re.compile(r"^(Trigger|Event)")),
    ("timer",     re.compile(r"^(Timer|Wait)")),
    ("ui",        re.compile(r"^(UI|Dialog|Text.*Message|Message)")),
    ("catalog",   re.compile(r"^Catalog")),
    ("bank",      re.compile(r"^Bank")),
    ("board",     re.compile(r"^(Board|VictoryPanel)")),
    ("ai",        re.compile(r"^(AI|Melee|Wave|Tech)")),
    ("actor",     re.compile(r"^Actor")),
    ("sound",     re.compile(r"^(Sound|Music)")),
    ("camera",    re.compile(r"^Camera")),
    ("cinematic", re.compile(r"^(Cinematic|Transmission|Portrait|Movie)")),
    ("point",     re.compile(r"^Point")),
    ("region",    re.compile(r"^Region")),
    ("string",    re.compile(r"^(String|Text|Fixed|Int)To|^(String|Text)")),
    ("order",     re.compile(r"^Order")),
    ("ability",   re.compile(r"^Abil")),
    ("behavior",  re.compile(r"^Behavior")),
    ("upgrade",   re.compile(r"^(Tech|Lib.*Upgrade|Upgrade)")),
    ("visibility", re.compile(r"^(Visibility|Fog|Reveal)")),
    ("objective", re.compile(r"^(Objective|Mission|Bounty)")),
    ("ping",      re.compile(r"^Ping")),
    ("effect",    re.compile(r"^Effect")),
    ("game",      re.compile(r"^Game")),
    ("data",      re.compile(r"^(DataTable|Store|Load)")),
    ("math",      re.compile(r"^(Rand|Abs|Min|Max|Sqrt|Pow|Mod|Sin|Cos|Tan|A(Sin|Cos|Tan))")),
    ("conversion", re.compile(r"To(Text|String|Int|Fixed)$")),
    ("cargo",     re.compile(r"^(Cargo|Transport)")),
    ("dialogitem", re.compile(r"^DialogControl")),
    ("weather",   re.compile(r"^(Weather|Light|Terrain|Doodad|Water)")),
    ("path",      re.compile(r"^(Path|Placement)")),
    ("conversation", re.compile(r"^Conversation")),
    ("achievement", re.compile(r"^Achievement")),
    ("leaderboard", re.compile(r"^(Leaderboard|Score|Stat)")),
    ("resource",  re.compile(r"^(Resource|Minerals|Vespene|Supply)")),
    ("difficulty", re.compile(r"^Difficulty")),
    ("campaign",  re.compile(r"^Campaign")),
]

# 非函数关键字 / 控制流，需过滤
KEYWORDS = {
    "if", "while", "for", "return", "break", "continue", "else",
    "include", "struct", "typedef", "const", "static", "native",
    "void", "int", "bool", "fixed", "string", "text", "byte",
    "switch", "case", "default", "do", "new", "delete", "sizeof",
}

CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
# 库前缀函数 lib<Hash>_gf_Xxx / gf_Xxx / gv_ 等
LIB_FN_RE = re.compile(r"^(lib[0-9A-Za-z]+_)?(gf|gv|gt)_")
_TYPE = (r"(?:void|int|bool|fixed|string|text|byte|point|unit|unitgroup|player|"
         r"playergroup|region|trigger|timer|order|actor|sound|wave|revealer|"
         r"[A-Za-z_][A-Za-z0-9_]*)")
# native 声明（引擎 API），不算 mod 自定义实现
NATIVE_DECL_RE = re.compile(
    rf"^\s*native\s+{_TYPE}\s*(?:\[[^\]]*\])?\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
# mod 自身实现的函数（有函数体）
DECL_RE = re.compile(
    rf"^\s*(?:static\s+)?{_TYPE}\s*(?:\[[^\]]*\])?\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"//[^\n]*", " ", src)
    return src


def bucket(name: str) -> str:
    for dom, pat in DOMAIN_RULES:
        if pat.search(name):
            return dom
    return "misc"


def iter_galaxy_files() -> list[Path]:
    out: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.galaxy"):
            parts = {x.lower() for x in p.parts}
            if parts & EXCLUDE_PARTS:
                continue
            out.append(p)
    return out


def load_engine_natives() -> tuple[set[str], set[str], set[str]]:
    """返回 (全集, 来自 .galaxy 声明的, 仅由 <FlagNative/> 背书的)。

    第三项是 round23 新增判据带来的增量——这些符号在 core 的 natives.galaxy
    里查不到，但引擎内建、真机可调用（StatEvent* 即属此类）。
    """
    from_galaxy: set[str] = set()
    for fn in NATIVE_DECL_FILES:
        p = CORE_TRIGGERLIBS / fn
        if not p.exists():
            continue
        src = strip_comments(p.read_text(encoding="utf-8", errors="replace"))
        for line in src.splitlines():
            m = NATIVE_DECL_RE.match(line)
            if m:
                from_galaxy.add(m.group(1))

    from_xml: set[str] = set()
    px = CORE_TRIGGERLIBS / NATIVE_XML
    if px.exists():
        txt = px.read_text(encoding="utf-8", errors="replace")
        for m in _FLAGNATIVE_ELEM_RE.finditer(txt):
            body = m.group(1)
            if "<FlagNative/>" not in body:
                continue
            mi = _IDENT_RE.search(body)
            if mi:
                from_xml.add(mi.group(1))

    return from_galaxy | from_xml, from_galaxy, from_xml - from_galaxy


def cmlib_covered() -> tuple[set[str], set[str]]:
    """返回 (CMLib 导出的函数名, CMLib 内部引用的引擎 native 名)."""
    exported: set[str] = set()
    referenced: set[str] = set()
    if not CMLIB.exists():
        return exported, referenced
    for p in CMLIB.glob("*.galaxy"):
        src = strip_comments(p.read_text(encoding="utf-8", errors="replace"))
        for line in src.splitlines():
            m = DECL_RE.match(line)
            if m and m.group(1).startswith("CMLib_"):
                exported.add(m.group(1))
        for m in CALL_RE.finditer(src):
            n = m.group(1)
            if n in KEYWORDS or n.startswith("CMLib_"):
                continue
            referenced.add(n)
    return exported, referenced


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--json", type=str, default="")
    args = ap.parse_args()

    files = iter_galaxy_files()
    print(f"[scan] {len(files)} 个 .galaxy 文件", file=sys.stderr)

    calls: Counter[str] = Counter()
    file_hits: defaultdict[str, set[str]] = defaultdict(set)
    declared: set[str] = set()       # mod 自定义实现
    # round23：引擎 native 集合先以 core.sc2mod 的权威判据打底，
    # 再叠加扫描到的 mod 内 `native` 声明（第三方补声明）。
    eng_all, eng_galaxy, eng_xml_only = load_engine_natives()
    natives: set[str] = set(eng_all)
    print(f"[engine] 权威 native {len(eng_all)} 个 "
          f"(.galaxy 声明 {len(eng_galaxy)} / 仅 <FlagNative/> 背书 "
          f"{len(eng_xml_only)})", file=sys.stderr)

    for p in files:
        try:
            src = strip_comments(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for line in src.splitlines():
            mn = NATIVE_DECL_RE.match(line)
            if mn:
                natives.add(mn.group(1))
                continue
            m = DECL_RE.match(line)
            if m:
                declared.add(m.group(1))
        for m in CALL_RE.finditer(src):
            n = m.group(1)
            if n in KEYWORDS:
                continue
            calls[n] += 1
            file_hits[n].add(str(p))

    # native 声明优先：即使某 mod 也同名实现，它仍是引擎 API
    declared -= natives
    print(f"[scan] native 声明 {len(natives)} 个, mod 自定义 {len(declared)} 个",
          file=sys.stderr)

    # 引擎 native / 平台 API = 被调用但不是 mod 自定义的 lib 函数
    engine_calls = Counter()
    for name, cnt in calls.items():
        if LIB_FN_RE.match(name):
            continue
        if name in declared:
            continue  # mod 内部自定义函数
        if name not in natives and not name[0].isupper():
            continue  # 既非 native 又非 PascalCase，多半是解析噪声
        engine_calls[name] = cnt

    exported, referenced = cmlib_covered()
    print(f"[cmlib] 导出 {len(exported)} 个函数, 引用 {len(referenced)} 个外部符号",
          file=sys.stderr)

    # 领域分桶
    dom_total: Counter[str] = Counter()
    dom_covered: Counter[str] = Counter()
    dom_uncovered: defaultdict[str, Counter[str]] = defaultdict(Counter)

    for name, cnt in engine_calls.items():
        d = bucket(name)
        dom_total[d] += cnt
        if name in referenced:
            dom_covered[d] += cnt
        else:
            dom_uncovered[d][name] += cnt

    rows = []
    for d, total in dom_total.most_common():
        cov = dom_covered[d]
        rate = cov / total if total else 0.0
        rows.append({
            "domain": d,
            "total_calls": total,
            "covered_calls": cov,
            "coverage": round(rate, 4),
            "top_uncovered": dom_uncovered[d].most_common(12),
            "uncovered_distinct": len(dom_uncovered[d]),
        })

    print("\n=== 领域覆盖率（按调用量降序）===")
    print(f"{'领域':<14}{'总调用':>9}{'已覆盖':>9}{'覆盖率':>9}  {'未覆盖高频 top6'}")
    for r in rows[: args.top]:
        top6 = ", ".join(f"{n}({c})" for n, c in r["top_uncovered"][:6])
        print(f"{r['domain']:<14}{r['total_calls']:>9}{r['covered_calls']:>9}"
              f"{r['coverage'] * 100:>8.1f}%  {top6}")

    # 全局最高频未覆盖符号
    all_unc: Counter[str] = Counter()
    for d, c in dom_uncovered.items():
        all_unc.update(c)
    print("\n=== 全局最高频【未覆盖】引擎符号 top40 ===")
    for i, (n, c) in enumerate(all_unc.most_common(40), 1):
        print(f"{i:>3}. {n:<42}{c:>7}  [{bucket(n)}]  files={len(file_hits[n])}")

    if args.json:
        outp = Path(args.json)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps({
            "files_scanned": len(files),
            "cmlib_exported": sorted(exported),
            "cmlib_referenced_count": len(referenced),
            "domains": rows,
            "top_uncovered": all_unc.most_common(120),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[json] 写入 {outp}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
