# -*- coding: utf-8 -*-
"""
ledger_survey.py — native 族规模测量（round26）

## 为什么先测量再扩族

round25 建立的台账门禁（check_native_ledger.py）目前只管 `aifilter` 一族。
遗留项写着「其它 native 族按 FAMILIES 逐族扩展」，但**不能拍脑袋扩** ——

如果一个族引擎有 300 个符号、CMLib 只封了 40 个，剩下 260 个全要写
`// @ledger-reject` 行，那这份"人写清单"就退化成 260 行噪音：
没人会认真读，写的时候就是复制粘贴，和 round25 要治的"人肉名单"是同一个病，
只是换了个文件放。**门禁的价值在于人写的那部分足够小、小到每一行都必须动脑子。**

所以本脚本先把每个族的三个数摆出来：

    engine   引擎声明的族全集
    called   CMLib 实现里真的调用了的
    gap      = engine - called，也就是「本轮必须逐个交代」的工作量

然后按 gap 从小到大排序 —— **优先吃能吃干净的族**。gap 太大的族本轮不纳管，
诚实地留在遗留项里，而不是塞一堆敷衍的 reject 行假装闭环。

## 用法
    python ledger_survey.py [--max-gap N] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CMLIB = HERE / "scripts" / "cmlib"
GAMEDATA = (REPO / "reference" / "sc2mapster" / "SC2GameData" / "mods"
            / "core.sc2mod" / "base.sc2data")
TRIG = GAMEDATA / "TriggerLibs"

NATIVE_RE = re.compile(r"^\s*native\s+[\w\[\]<>]+\s+(\w+)\s*\(")

# 候选族：前缀正则 -> 族名。
# 划分依据是「CMLib 已经有成员入库」——一个族一旦被库碰过，
# 它的其余成员就该逐个有交代。完全没碰过的族不在本门禁职责内
# （那属于 gap_scan 的覆盖率话题，不是台账的完整性话题）。
CANDIDATES = {
    "aifilter":   r"^AI(?:Set)?Filter\w*$",
    "aiwave":     r"^AIAttackWave\w*$",
    "aistock":    r"^AI(?:Enable|Clear|Set|Get)Stock\w*$",
    "board":      r"^Board\w+$",
    "vpanel":     r"^VictoryPanel\w+$",
    "statevent":  r"^StatEvent\w+$",
    "datatable":  r"^DataTable\w+$",
    "bank":       r"^Bank\w+$",
    "catalog":    r"^Catalog\w+$",
    "unitgroup":  r"^UnitGroup\w+$",
    "unit":       r"^Unit\w+$",
    "dialog":     r"^Dialog\w+$",
    "player":     r"^Player\w+$",
    "region":     r"^Region\w+$",
    "point":      r"^Point\w+$",
    "text":       r"^Text\w+$",
    "string":     r"^String\w+$",
    "timer":      r"^Timer\w+$",
    "trigger":    r"^Trigger\w+$",
    "sound":      r"^Sound\w+$",
    "camera":     r"^Camera\w+$",
    "actor":      r"^Actor\w+$",
    "order":      r"^Order\w+$",
    "upgrade":    r"^(?:Tech|Libs?)?Upgrade\w*$",
    "visual":     r"^Visibility\w+$",
    "ping":       r"^Ping\w+$",
    "conv":       r"^Conversation\w+$",
    "cinematic":  r"^Cinematic\w+$",
    "transmiss":  r"^Transmission\w+$",
    "objective":  r"^Objective\w+$",
    "reward":     r"^Reward\w+$",
    "melee":      r"^Melee\w+$",
    "game":       r"^Game\w+$",
}


def engine_natives() -> dict[str, Path]:
    """全部引擎 native 声明 -> 声明所在文件（用于台账的 decl_file 配置）。"""
    out: dict[str, Path] = {}
    srcs: list[Path] = [TRIG / "natives.galaxy", TRIG / "natives_missing.galaxy"]
    srcs += sorted((TRIG / "GameData").glob("*.galaxy"))
    srcs += sorted(TRIG.glob("*.galaxy"))
    srcs += sorted((TRIG / "Tactical").glob("*.galaxy"))
    for p in srcs:
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = NATIVE_RE.match(line)
            if m and m.group(1) not in out:
                out[m.group(1)] = p
    return out


def cmlib_called(symbols: set[str]) -> set[str]:
    """CMLib 实现里真的调用了的符号（剥行注释，注释不算证据）。"""
    out: set[str] = set()
    for f in sorted(CMLIB.glob("*.galaxy")):
        if f.name.endswith("_h.galaxy"):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        body = "\n".join(ln.split("//", 1)[0] for ln in text.splitlines())
        for s in symbols:
            if s in out:
                continue
            if re.search(r"\b" + re.escape(s) + r"\s*\(", body):
                out.add(s)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-gap", type=int, default=12,
                    help="建议纳管的 gap 上限（默认 12）")
    ap.add_argument("--json", type=str, default="")
    args = ap.parse_args()

    natives = engine_natives()
    print("=" * 78)
    print(f"[survey] 引擎 native 声明总数 = {len(natives)}")
    print("=" * 78)

    all_syms = set(natives)
    called_all = cmlib_called(all_syms)
    print(f"[survey] CMLib 实现里调用到的引擎 native = {len(called_all)}\n")

    rows = []
    for fam, pat in CANDIDATES.items():
        rx = re.compile(pat)
        fam_syms = {s for s in all_syms if rx.match(s)}
        if not fam_syms:
            continue
        fam_called = fam_syms & called_all
        gap = fam_syms - fam_called
        if not fam_called:
            continue  # 库完全没碰过的族，不在台账职责内
        # 声明文件分布（台账需要知道从哪个文件读族全集）
        files = sorted({natives[s].name for s in fam_syms})
        rows.append({
            "family": fam,
            "pattern": pat,
            "engine": len(fam_syms),
            "called": len(fam_called),
            "gap": len(gap),
            "coverage": round(100.0 * len(fam_called) / len(fam_syms), 1),
            "decl_files": files,
            "gap_symbols": sorted(gap),
        })

    rows.sort(key=lambda r: (r["gap"], -r["coverage"]))

    print(f"{'族':<12}{'引擎':>6}{'已封':>6}{'缺口':>6}{'覆盖率':>8}   声明文件")
    print("-" * 78)
    budget = []
    for r in rows:
        mark = "  <= 本轮可纳管" if r["gap"] <= args.max_gap else ""
        if r["gap"] <= args.max_gap:
            budget.append(r)
        print(f"{r['family']:<12}{r['engine']:>6}{r['called']:>6}{r['gap']:>6}"
              f"{r['coverage']:>7.1f}%   {','.join(r['decl_files'][:2])}{mark}")

    total_gap = sum(r["gap"] for r in budget)
    print("-" * 78)
    print(f"[survey] 建议本轮纳管 {len(budget)} 族，"
          f"需逐个交代的符号合计 {total_gap} 个（gap <= {args.max_gap}）")
    print(f"[survey] 暂不纳管 {len(rows) - len(budget)} 族"
          f"（gap 过大，塞 reject 行会让台账退化成噪音清单）")

    print("\n可纳管族的缺口明细：")
    for r in budget:
        print(f"\n  [{r['family']}] gap={r['gap']}  ({', '.join(r['decl_files'])})")
        for s in r["gap_symbols"]:
            print(f"      {s}")

    if args.json:
        Path(args.json).write_text(
            json.dumps({"rows": rows, "budget": [r["family"] for r in budget]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"\n[survey] 明细写入 {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
