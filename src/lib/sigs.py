#!/usr/bin/env python3
"""从权威 natives.galaxy / GameData 提取 native 签名与常量，供写库时逐字核对。

用法:
    python sigs.py <正则1> [正则2 ...]          # 打印匹配的 native 签名
    python sigs.py --const <正则>               # 打印匹配的 const 常量
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

WS = Path(__file__).resolve().parents[3]
GAMEDATA_ROOT = (WS / "sc2-porting-workspace" / "reference" / "sc2mapster" /
                 "SC2GameData" / "mods" / "core.sc2mod" / "base.sc2data")

SOURCES = [GAMEDATA_ROOT / "TriggerLibs" / "natives.galaxy"]
SOURCES += sorted((GAMEDATA_ROOT / "TriggerLibs" / "GameData").glob("*.galaxy"))
SOURCES += [GAMEDATA_ROOT / "TriggerLibs" / "NativeLib.galaxy",
            GAMEDATA_ROOT / "TriggerLibs" / "AI.galaxy",
            GAMEDATA_ROOT / "TriggerLibs" / "AIThink.galaxy"]

NATIVE_RE = re.compile(r"^\s*native\s+.*?\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
CONST_RE = re.compile(r"^\s*(?:static\s+)?const\s+\w+\s+([A-Za-z_][A-Za-z0-9_]*)\s*=")
# NativeLib / AI 里的普通函数（非 native）也要能查到
FUNC_RE = re.compile(
    r"^\s*(?:void|int|bool|fixed|string|text|point|unit|unitgroup|player|"
    r"playergroup|region|trigger|timer|order|actor|sound|wave|revealer|marker|"
    r"transmissionsource|camerainfo|aifilter|abilcmd|doodad)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    want_const = args[0] == "--const"
    if want_const:
        args = args[1:]
    pats = [re.compile(a) for a in args]

    seen: set[str] = set()
    hits = 0
    for src in SOURCES:
        if not src.exists():
            continue
        for raw in src.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.rstrip()
            if want_const:
                m = CONST_RE.match(line)
            else:
                m = NATIVE_RE.match(line) or FUNC_RE.match(line)
            if not m:
                continue
            name = m.group(1)
            if not any(p.search(name) for p in pats):
                continue
            key = f"{name}|{line.strip()}"
            if key in seen:
                continue
            seen.add(key)
            hits += 1
            print(f"[{src.name}] {line.strip()}")
    print(f"\n-- {hits} 条匹配 --", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
