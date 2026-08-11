"""把 CMLib 引用到的、natives.galaxy 里没有的引擎符号，映射回定义它们的 TriggerLibs 库文件。

背景：core.sc2mod 的 TriggerLibs 下除 natives.galaxy 外还有 AI.galaxy / Bank.galaxy 等库，
它们不会被自动挂载，必须显式 include。缺 include 会让真实 SC2 编译器整段丢弃 MapScript
（静默失败，无崩溃、无日志），正是本次 InitMap 不执行的根因。
"""
import re
import sys
from pathlib import Path
from collections import defaultdict

REPO = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace")
TRIGGERLIBS = REPO / "reference" / "sc2mapster" / "SC2GameData" / "mods" / "core.sc2mod" / "base.sc2data" / "TriggerLibs"
CMLIB = REPO / "src" / "lib" / "scripts" / "cmlib"

DEF_RE = re.compile(r"^\s*(?:native\s+)?(?:const\s+)?[A-Za-z_][A-Za-z0-9_<>]*\s+([A-Za-z_][A-Za-z0-9_]*)\s*[(=]", re.M)
CALL_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\s*\(")


def defs_in(path):
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return set()
    return set(DEF_RE.findall(txt))


def main():
    # 1) natives.galaxy + GameData/Game.galaxy = lint 已挂载的基线
    base = set()
    base |= defs_in(TRIGGERLIBS / "natives.galaxy")
    base |= defs_in(TRIGGERLIBS / "GameData" / "Game.galaxy")
    # 常量也算
    for p in [TRIGGERLIBS / "natives.galaxy", TRIGGERLIBS / "GameData" / "Game.galaxy"]:
        if p.exists():
            base |= set(re.findall(r"const\s+\w+\s+(\w+)", p.read_text(encoding="utf-8", errors="replace")))

    # 2) 其它 TriggerLibs 库提供的符号
    lib_defs = {}
    for p in sorted(TRIGGERLIBS.glob("*.galaxy")):
        if p.name == "natives.galaxy":
            continue
        lib_defs[p.stem] = defs_in(p)
    for p in sorted((TRIGGERLIBS / "GameData").glob("*.galaxy")):
        if p.name == "Game.galaxy":
            continue
        s = defs_in(p)
        s |= set(re.findall(r"const\s+\w+\s+(\w+)", p.read_text(encoding="utf-8", errors="replace")))
        lib_defs["GameData/" + p.stem] = s

    # 3) CMLib 自身符号（排除）
    own = set()
    for p in CMLIB.glob("*.galaxy"):
        own |= defs_in(p)
        own |= set(re.findall(r"const\s+\w+\s+(\w+)", p.read_text(encoding="utf-8", errors="replace")))

    # 4) 扫 CMLib 的调用
    need = defaultdict(set)      # lib -> {symbols}
    unknown = defaultdict(set)   # file -> {symbols}
    for p in sorted(CMLIB.glob("*.galaxy")):
        txt = re.sub(r"//.*", "", p.read_text(encoding="utf-8", errors="replace"))
        for sym in set(CALL_RE.findall(txt)):
            if sym in own or sym in base:
                continue
            if sym in ("if", "while", "for", "return", "Point", "Color"):
                continue
            hit = [lib for lib, syms in lib_defs.items() if sym in syms]
            if hit:
                need[hit[0]].add((sym, p.name))
            else:
                unknown[p.name].add(sym)

    print("=== 需要补的 TriggerLibs include ===")
    for lib in sorted(need):
        files = sorted({f for _, f in need[lib]})
        syms = sorted({s for s, _ in need[lib]})
        print(f'\ninclude "TriggerLibs/{lib}"')
        print(f"  引用它的 CMLib 文件: {', '.join(files)}")
        print(f"  符号({len(syms)}): {', '.join(syms[:14])}{' ...' if len(syms) > 14 else ''}")

    if unknown:
        print("\n=== 未能在任何 TriggerLibs 中定位的符号（需人工确认）===")
        for f in sorted(unknown):
            print(f"  {f}: {', '.join(sorted(unknown[f]))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
