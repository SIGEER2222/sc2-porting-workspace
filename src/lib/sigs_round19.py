# -*- coding: utf-8 -*-
"""从引擎 natives.galaxy 抽取指定符号的**权威签名**。

铁律：库里每一个封装的形参类型/个数都必须来自这里，绝不凭记忆写。
真机上 arity 或类型错 = 整个 MapScript 被静默丢弃，静态 lint 照样 0 错误。
"""
import re
import sys
from pathlib import Path

WS = Path(__file__).resolve().parents[3]
NATIVES = (WS / "sc2-porting-workspace" / "reference" / "sc2mapster" / "SC2GameData"
           / "mods" / "core.sc2mod" / "base.sc2data" / "TriggerLibs" / "natives.galaxy")

WANT = [
    # --- conversation data（数据驱动战役对白，本轮最大真缺口） ---
    "ConversationDataRun", "ConversationDataStop", "ConversationDataIsRunning",
    "ConversationDataGetSound", "ConversationDataLineSetPlayers",
    "ConversationDataLineResetPlayers", "ConversationDataRegisterCamera",
    "ConversationDataStateSetValue", "ConversationDataStateGetValue",
    "ConversationDataStateText", "ConversationDataStateIndexCount",
    "ConversationDataSkip", "ConversationDataPause",
    # --- trigger 事件补齐 ---
    "TriggerAddEventKeyPressed", "TriggerAddEventButtonPressed",
    "TriggerAddEventUpgradeLevelChanged",
    "TriggerAddEventUnitBehaviorChangeFromCategory",
    "EventUnitDamageEffect", "EventUnitOrder", "EventUnitTarget",
    "EventUnitTargetPoint", "EventTimer", "EventPlayerWave",
    "EventKeyPressed", "EventKeyShift", "EventKeyControl", "EventKeyAlt",
    "EventButtonPressed", "EventUpgradeLevel",
    "TriggerSkippableBegin", "TriggerSkippableEnd", "TriggerSkippableWaitFor",
    "TriggerSkippableIsSkipping",
    # --- camera ---
    "CameraInfoGetValue", "CameraInfoGetTarget", "CameraSetBounds",
    "CameraFollowUnitGroup", "CameraSetData",
    # --- ping ---
    "PingSetVisible", "PingSetPosition", "PingSetColor", "PingSetRotation",
    "PingSetModel", "PingSetDuration", "PingSetScale", "PingDestroy",
    # --- text / string ---
    "TextTimeFormat", "TextReplaceWord", "TextTagShow", "TextTagCreate",
    "TextTagDestroy",
    # --- preload ---
    "PreloadModel", "PreloadMovie", "PreloadAsset", "PreloadImage",
    "PreloadSound",
    # --- unit / game ---
    "UnitTypeGetCost", "UnitCargoLastCreatedGroup", "GameSetBackground",
    "GameCheatAllow", "GameIsOnline", "GameIsTestMap",
    "RegionPlayableMapSet", "SoundtrackPause", "SoundtrackDefault",
    "PortraitSetVisible", "MovieStartRecording", "MovieStopRecording",
    "AITimePause", "TechTreeUnitHelp", "AbilityCommandGetAbility",
    "UserDataGetImagePath",
]


def main():
    txt = NATIVES.read_text(encoding="utf-8", errors="replace")
    # 支持跨行声明
    found = {}
    for m in re.finditer(r"native\s+([\w<>]+)\s+(\w+)\s*\(([^;]*?)\)\s*;", txt, re.S):
        ret, name, args = m.group(1), m.group(2), m.group(3)
        found[name] = "%s %s(%s);" % (ret, name, re.sub(r"\s+", " ", args).strip())
    miss = []
    for w in WANT:
        if w in found:
            print(found[w])
        else:
            miss.append(w)
    if miss:
        print("\n### 不存在于 natives.galaxy（不可封装 / 名字错） ###")
        for w in miss:
            print("  -", w)


if __name__ == "__main__":
    sys.exit(main())
