# -*- coding: utf-8 -*-
"""Round20 权威签名抽取器 —— 从引擎 natives.galaxy 抽取待封装符号的真实声明。

铁律（round19 用一整轮三档全灭换来的）：
  库里每一个封装的形参类型/个数/常量名都必须来自这里，绝不凭记忆写。
  真机上 arity 错、类型错、常量不存在 = SC2 **静默丢弃整个 MapScript**，
  静态 lint 因 `R3-undeclared` 抑制规则照样报 0 错误。

本轮范围（对齐任务书「单位 / 建筑 / 面板效果」+ 覆盖率最低的真实域）：
  · unit      建筑放置、生产队列、挂点、武器、行为时长、属性
  · ui/board  胜利面板成就、Dialog 控件查询、指令面板与目标模式
  · data      DataTable 强类型存取（真实域最低覆盖 66.1%）
  · conv      round19 剩下的 6 个 ConversationData*
  · misc      世界高度 / UserData / 过场书签

用法：
    python sigs_round20.py            # 打印命中的签名 + 缺失清单
    python sigs_round20.py --json     # 机器可读，供 extend_round20.py 生成代码时核对
"""
import json
import re
import sys
from pathlib import Path

WS = Path(__file__).resolve().parents[3]
CORE = (WS / "sc2-porting-workspace" / "reference" / "sc2mapster" / "SC2GameData"
        / "mods" / "core.sc2mod" / "base.sc2data")
NATIVES = CORE / "TriggerLibs" / "natives.galaxy"

WANT = [
    # ---------- 单位 / 建筑 ----------
    "UnitFlashSelection", "UnitCargoGroup", "UnitBehaviorSetDuration",
    "UnitBehaviorEffectUnit", "UnitGetPropertyInt", "UnitAbilityShow",
    "UnitTypePlacementFromPoint", "UnitGetAttachmentPoint",
    "UnitQueueItemTypeCheck", "UnitQueueItemCount", "UnitQueueItemProgress",
    "UnitAbilityExists", "UnitGetName", "UnitWeaponCount", "UnitWeaponPeriod",
    "UnitWeaponDamage", "UnitTypeGetProperty", "UnitIsHarvesting",
    # ---------- 单位组 ----------
    "UnitGroupSelect", "UnitGroupIdle",
    # ---------- 面板 / UI ----------
    "VictoryPanelAddAchievement", "VictoryPanelSetCustomText",
    "DialogControlIsVisible", "DialogControlGetDialog",
    "DialogControlHookupUnitStatus", "UISetTargetingOrder",
    "UIAlertClear", "UISetCommandAllowed", "UISetWorldVisible",
    "UISetMode", "UISetResourceTradeEnabled",
    # ---------- DataTable 强类型存取（真实域最低覆盖） ----------
    "DataTableSetBool", "DataTableGetBool",
    "DataTableSetUnitGroup", "DataTableGetUnitGroup",
    "DataTableSetTimer", "DataTableGetTimer",
    "DataTableSetObjective", "DataTableGetObjective",
    "DataTableSetRegion", "DataTableGetRegion",
    "DataTableValueRemove", "DataTableValueCount", "DataTableValueName",
    "DataTableValueExists", "DataTableClear",
    # ---------- ConversationData 剩余 6 ----------
    "ConversationDataPreloadLines", "ConversationDataStateFixedValue",
    "ConversationDataActiveSound", "ConversationDataLoadNodeState",
    "ConversationDataSaveNodeState", "ConversationDataResetStateValues",
    # ---------- misc ----------
    "WorldHeight", "UserDataResetType", "UserDataGetUpgrade",
    "CutsceneGoToBookmark", "CutscenePlay", "RoundI",
    # ---------- timer / order / sound ----------
    "TimerGetDuration", "TimerIsPaused",
    "OrderGetFlag", "OrderGetTargetPosition", "OrderGetTargetType",
    "SoundWait",
]

# 判定「常量是否真的存在于引擎」用；round19 的 c_maxInt 就是死在这里
WANT_CONSTS = [
    "c_unitPropLife", "c_unitPropEnergy", "c_unitCountAll", "c_noMaxCount",
    "c_conversationSkipFull", "c_animFlagPlayForever",
    "c_orderQueueReplace", "c_unitCreateIgnorePlacement",
    "c_gameOverVictory", "c_playerPropMinerals",
]


def decl_index():
    """符号 -> 声明它的文件集合（判断是否在 core 默认 include 链内）。"""
    idx = {}
    pat = re.compile(r"^\s*(?:native\s+)?[A-Za-z_][\w<>]*\s+([A-Za-z_]\w*)\s*\(")
    for p in CORE.rglob("*.galaxy"):
        rel = p.relative_to(CORE).as_posix()
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for line in txt.splitlines():
            m = pat.match(line)
            if m:
                idx.setdefault(m.group(1), set()).add(rel)
    return idx


def main():
    txt = NATIVES.read_text(encoding="utf-8", errors="replace")
    found = {}
    for m in re.finditer(r"native\s+([\w<>]+)\s+(\w+)\s*\(([^;]*?)\)\s*;", txt, re.S):
        ret, name, args = m.group(1), m.group(2), m.group(3)
        found[name] = {"ret": ret, "name": name,
                       "args": re.sub(r"\s+", " ", args).strip()}
    idx = decl_index()

    ok, miss, unsafe = [], [], []
    for w in WANT:
        if w not in found:
            miss.append((w, sorted(idx.get(w, [])) or ["<无任何声明>"]))
            continue
        where = idx.get(w, set())
        if not (where & {"TriggerLibs/natives.galaxy"}):
            unsafe.append(w)
        ok.append(found[w])

    consts = {}
    const_txt = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in CORE.rglob("*.galaxy")
        if p.name in ("natives.galaxy", "NativeLib.galaxy") or "GameData" in p.as_posix()
    )
    for c in WANT_CONSTS:
        consts[c] = bool(re.search(r"\bconst\s+\w+\s+%s\b" % re.escape(c), const_txt))

    if "--json" in sys.argv:
        print(json.dumps({"ok": ok, "missing": [m[0] for m in miss],
                          "consts": consts}, ensure_ascii=False, indent=2))
        return 0

    print("=== 命中 natives.galaxy 的权威签名 (%d) ===" % len(ok))
    for f in ok:
        print("native %s %s(%s);" % (f["ret"], f["name"], f["args"]))
    print("\n=== 常量存在性 ===")
    for c, v in consts.items():
        print("  %-32s %s" % (c, "OK" if v else "!! 不存在，禁止使用"))
    if unsafe:
        print("\n=== 声明不在 natives.galaxy（不可封装） ===")
        for w in unsafe:
            print("  -", w)
    if miss:
        print("\n=== natives.galaxy 里根本没有（名字错 / 不可封装）(%d) ===" % len(miss))
        for w, where in miss:
            print("  - %-38s 其它声明处: %s" % (w, ",".join(where[:2])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
