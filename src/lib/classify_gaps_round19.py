# -*- coding: utf-8 -*-
"""Round19 缺口分类器：把 gap_scan 的「未覆盖高频符号」按**可封装性**分三类。

历史教训：前面若干轮反复把同一批符号拿出来讨论，是因为没有把
「为什么不包」的判据固化成可复跑的脚本 —— 每轮都靠记忆复述，容易漂移。
本脚本把判据写死，输出可直接决策的三张表。

判据（按顺序命中即定类）：
  NOISE   : GUI 触发器编译期自动生成的访问器（*FromId/*FromName/*LastCreated/*Loop*/
            *GetTriggerControl 等），地图源码里满天飞但不是「库该封装的能力」。
  UNSAFE  : 声明文件不在 core.sc2mod 的**默认 include 链**内（例如 Tactical/TacticalAI.galaxy、
            natives_missing.galaxy）。包了会在真机静默编译失败 → 整个 MapScript 被丢弃。
  DUP     : CMLib 已有等价封装（人工维护的等价映射表）。
  REAL    : 其余 —— 真实可封装缺口。
"""
import json
import re
import sys
from pathlib import Path

WS = Path(__file__).resolve().parents[3]
CORE = (WS / "sc2-porting-workspace" / "reference" / "sc2mapster" / "SC2GameData"
        / "mods" / "core.sc2mod" / "base.sc2data")
CMLIB = Path(__file__).resolve().parent / "scripts" / "cmlib"

# core.sc2mod 里「一定被默认 include」的声明文件（真机可安全调用）
SAFE_DECL_FILES = {
    "TriggerLibs/natives.galaxy",
    "TriggerLibs/GameData/Game.galaxy",
    "TriggerLibs/GameData/GameData.galaxy",
}
# 明确不安全（曾踩坑或已论证）
UNSAFE_DECL_HINTS = ("natives_missing", "Tactical/", "TacticalAI", "/AI/", "BaseAI")

NOISE_PAT = re.compile(
    r"(FromId|FromName|LastCreated|LoopBegin|LoopStep|LoopDone|LoopEnd|LoopCurrent"
    r"|GetTriggerControl)$"
)

# CMLib 已有等价封装：native -> CMLib 对应物（多轮论证结论，固化下来）
DUP_MAP = {
    "StringWord": "CMLib_SplitAt / CMLib_SplitCount（任意分隔符，覆盖空白切分）",
    "SoundPlayForPlayer": "CMLib_SfxPlayForPlayer",
    "CatalogFieldValueSet": "CMLib_CatSetFixed 等 CatSet* 族",
    "CatalogFieldValueSetFixed": "CMLib_CatSetFixed",
    "MinI": "CMLib_ClampI / 直接调 native 更省（纯数学，封装零收益）",
    "MaxI": "同 MinI",
    "MinF": "同 MinI",
    "MaxF": "同 MinI",
    "AbsF": "同 MinI",
    "ModF": "CMLib_ModSafe（含除零兜底）",
}


def load_decl_index():
    """扫 core.sc2mod 全部 .galaxy，建立 符号 -> **全部**声明文件集合。

    坑：一个符号可能同时声明在 natives.galaxy 和 AI.galaxy/NativeLib.galaxy。
    只记第一个命中的文件（setdefault）会让「其实安全」的符号被误判 UNSAFE，
    反之亦然。必须记全集，再按「只要出现在安全文件里就算安全」判定。
    """
    idx = {}
    if not CORE.is_dir():
        print("!! 找不到 core.sc2mod：%s" % CORE, file=sys.stderr)
        return idx
    decl = re.compile(r"^\s*(?:native\s+)?[A-Za-z_][\w<>]*\s+([A-Za-z_]\w*)\s*\(")
    for p in CORE.rglob("*.galaxy"):
        rel = p.relative_to(CORE).as_posix()
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for line in txt.splitlines():
            m = decl.match(line)
            if m:
                idx.setdefault(m.group(1), set()).add(rel)
    return idx


def cmlib_referenced():
    """CMLib 内部已引用（=已被封装或已被内部使用）的引擎符号集合。"""
    s = set()
    tok = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
    for p in CMLIB.glob("*.galaxy"):
        txt = re.sub(r"//.*", "", p.read_text(encoding="utf-8", errors="replace"))
        s.update(tok.findall(txt))
    return s


def main():
    src = Path(__file__).resolve().parent / (sys.argv[1] if len(sys.argv) > 1
                                             else "gap_scan_round19.json")
    data = json.loads(src.read_text(encoding="utf-8"))
    # gap_scan 的 json：全局 top_uncovered = [[name,count],...]；
    # 另有 domains[].top_uncovered —— 全局榜会被 point/region 的海量噪声挤爆，
    # 必须把每个领域的榜单也并进来，否则真缺口永远排不进视野。
    items = []
    for name, cnt in data.get("top_uncovered", []):
        items.append({"name": name, "count": cnt, "domain": ""})
    seen = {i["name"] for i in items}
    for dom in data.get("domains", []):
        for name, cnt in dom.get("top_uncovered", []):
            if name not in seen:
                seen.add(name)
                items.append({"name": name, "count": cnt,
                              "domain": dom.get("domain", "")})
            else:
                for i in items:
                    if i["name"] == name and not i["domain"]:
                        i["domain"] = dom.get("domain", "")
    if not items:
        print("!! 无法从 %s 解析未覆盖列表，keys=%s" % (src.name, list(data)[:10]))
        return 1

    decl = load_decl_index()
    used = cmlib_referenced()
    buckets = {"REAL": [], "NOISE": [], "UNSAFE": [], "DUP": [], "UNKNOWN": []}

    for it in items:
        name = it.get("name") or it.get("symbol") or ""
        cnt = it.get("count") or it.get("calls") or 0
        dom = it.get("domain") or ""
        if not name:
            continue
        where = decl.get(name) or set()
        safe_hits = where & SAFE_DECL_FILES
        if NOISE_PAT.search(name):
            buckets["NOISE"].append((name, cnt, dom, "GUI 自动访问器"))
        elif name in DUP_MAP or name in used:
            buckets["DUP"].append((name, cnt, dom, DUP_MAP.get(name, "CMLib 内部已引用")))
        elif not where:
            buckets["UNKNOWN"].append((name, cnt, dom, "core.sc2mod 中找不到声明"))
        elif safe_hits:
            buckets["REAL"].append((name, cnt, dom, sorted(safe_hits)[0]))
        else:
            buckets["UNSAFE"].append((name, cnt, dom,
                                      "仅见于 " + ",".join(sorted(where)[:2])))

    for k in ("REAL", "UNSAFE", "DUP", "NOISE", "UNKNOWN"):
        rows = sorted(buckets[k], key=lambda r: -r[1])
        print("\n=== %s (%d) ===" % (k, len(rows)))
        for name, cnt, dom, why in rows[:40]:
            print("  %-38s %7d  [%-12s] %s" % (name, cnt, dom, why))
    return 0


if __name__ == "__main__":
    sys.exit(main())
