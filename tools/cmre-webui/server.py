#!/usr/bin/env python3
"""CMRE 亡者之夜 WebUI 后端服务

提供因子（Mode/Difficulty/Enemy/Mutators）选择界面和启动游戏的 HTTP API。
仅使用 Python 标准库，无第三方依赖。

用法:
    python server.py [--port 8767] [--host 127.0.0.1]
"""

import asyncio
import atexit
import csv
import json
import os
import queue
import shutil
import subprocess
import sys
import time
import threading
import webbrowser
import xml.etree.ElementTree as ET
from collections import deque
from http.server import HTTPServer, ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WEBUI_DIR = SCRIPT_DIR / "webui"
DATA_DIR = SCRIPT_DIR / "data"
MUTATORS_JSON = DATA_DIR / "mutators.json"
# DDS → PNG 转换缓存目录。首次请求某 DDS 时转 PNG 存这里，后续直接返回。
ASSETS_CACHE_DIR = WEBUI_DIR / "assets_cache"
# 预导出的真实图标缓存（从起义狂潮 web-launcher 复制过来）
ASSETS_CACHE_COMMANDERS = WEBUI_DIR / "assets-cache" / "commanders"
ASSETS_CACHE_MUTATORS = WEBUI_DIR / "assets-cache" / "mutators"
# 配置目录：sc2-porting-workspace/src/config/alenger-mods.json
CONFIG_DIR = SCRIPT_DIR.parents[1] / "src" / "config"
ALENGER_MODS_JSON = CONFIG_DIR / "alenger-mods.json"
REBORN_COMMANDERS_JSON = CONFIG_DIR / "reborn-commanders.json"
LAUNCH_SCRIPT = Path(__file__).resolve().parents[1] / "launchers" / "launch-cmre-alenger.ps1"
REPO_ROOT = SCRIPT_DIR.parents[1]
REVOLUTION_PACKAGE_ROOT = REPO_ROOT / "src" / "projects" / "revolution-overdrive-porting" / "packages"
REVOLUTION_COMMANDER_JSON = REVOLUTION_PACKAGE_ROOT / "Commander" / "revolution-overdrive-commander.json"
REVOLUTION_MAPS_JSON = REVOLUTION_PACKAGE_ROOT / "maps.json"
REVOLUTION_LAUNCH_SCRIPT = Path(__file__).resolve().parents[1] / "launchers" / "launch-revolution-overdrive.ps1"
GALAXY_VIBE_ROOT = REPO_ROOT / "tools" / "galaxy-vibe"
VIBE_FUNCTION_REGISTRY = GALAXY_VIBE_ROOT / "kernel" / "function-registry.json"
VIBE_FUNCTION_CATALOG = (
    REPO_ROOT
    / "artifacts"
    / "projects"
    / "cmre-porting"
    / "stage25-ai-ally-capability-completion"
    / "discovery"
    / "function-catalog.json"
)

# CMRE 框架运行时根目录（Maps/Mods/Shared/scripts）
# SCRIPT_DIR.parents[2] = sc2-porting-workspace/tools/cmre-webui → tools → sc2-porting-workspace → SC2VibeTools
SC2VIBE_ROOT = SCRIPT_DIR.parents[2]
CMRE_RUNTIME_ROOT = SC2VIBE_ROOT / "cmre-runtime"
MAPS_CMRE_DIR = CMRE_RUNTIME_ROOT / "Maps" / "CMRE"
COMMANDER_METADATA_JSON = CMRE_RUNTIME_ROOT / "Shared" / "CommanderPower" / "commander-power-metadata.json"
COMMANDERS_REGISTRY_JSON = CMRE_RUNTIME_ROOT / "Shared" / "Commanders" / "_registry.json"
MODS_7VS1_PACKAGES_DIR = SC2VIBE_ROOT / "sc2-porting-workspace" / "src" / "projects" / "cmre-porting" / "packages" / "Mods" / "7vs1"
CMRE_MODS_DIR = CMRE_RUNTIME_ROOT / "Mods" / "CMRE"
MUTATORS_USERDATA_XML = CMRE_MODS_DIR / "CMRE_Core_Triggers.SC2Mod" / "Base.SC2Data" / "GameData" / "UserData.xml"
# SC2 GameData 的 ConfigData.xml 是 VoicePack catalog 的可选项清单；
# RewardData.xml 只包含底层的三种族 reward 定义，不能用于写入 CMRE 启动档案。
OFFICIAL_VOICEPACK_CONFIG_XML = (
    SCRIPT_DIR.parents[1]
    / "reference"
    / "sc2mapster"
    / "SC2GameData"
    / "mods"
    / "liberty.sc2mod"
    / "base.sc2data"
    / "GameData"
    / "ConfigData.xml"
)

# CMRE 因子上限：CMUIX_LAUNCH_PROFILE_MUTATOR_MAX = 20
MUTATOR_MAX = 20

# 指挥官种族前缀（launch-cmre-alenger.ps1 的 -Commander 正则只接受这三种前缀）
COMMANDER_RACES = ["Terran", "Zerg", "Protoss"]

# CMRE Legacy Root：CMRE 框架运行时根目录（Maps/Mods/Shared/scripts）。
# 已从 SC2/合作指挥官-起义狂潮（已归档）迁入 SC2VibeTools/cmre-runtime。
# launch-cmre-alenger.ps1 默认从 $PSScriptRoot 推导也会指向 cmre-runtime，
# 但显式传入可避免环境差异。可通过环境变量 CMRE_LEGACY_ROOT 覆盖默认值。
DEFAULT_LEGACY_ROOT = str(CMRE_RUNTIME_ROOT)
LEGACY_ROOT = os.environ.get("CMRE_LEGACY_ROOT", DEFAULT_LEGACY_ROOT)


def _resolve_powershell_executable() -> str:
    """Use the PowerShell host required by the launcher on Windows."""
    for candidate in ("pwsh", "powershell"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return "pwsh"

# 因子元数据
FACTORS_DATA = {
    "modes": [
        {"id": 1, "name": "标准模式", "description": "正常合作模式，无突变因子"},
        {"id": 2, "name": "突变挑战", "description": "突变挑战模式，可启用突变因子"},
        {"id": 3, "name": "自定义模式", "description": "自定义模式，支持混沌循环"},
    ],
    "difficultyBase": {"min": 0, "max": 5, "default": 0, "name": "基础难度"},
    "difficultyPlus": {"min": 0, "max": 12, "default": 0, "name": "残酷+等级"},
    "enemies": [
        {"id": "", "name": "默认", "description": "使用地图默认敌方阵营"},
        {"id": "ZergAmonSwarm", "name": "虫族（埃蒙虫群）", "description": "亡者之夜默认敌方"},
        {"id": "ProtossCorruptedTemplar", "name": "星灵（堕落圣堂）", "description": "堕落星灵阵营"},
    ],
    "commanders": [
        "TerranAlenger3", "ZergAlenger3", "ProtossAlenger3",
    ],
}


def _find_map_preview(map_dir: Path) -> str:
    """在地图目录中查找预览图。

    优先级：Assets/Textures/ui_loading_*.dds → bnet_*.png → CustomMapPreviewImage.tga
    返回形如 "Maps/CMRE/<map>/..." 的相对路径，供 /api/assets/dds 使用。
    找不到返回空字符串。
    """
    # 1. 优先 ui_loading_*.dds（只有死亡摇篮等少数地图有）
    textures_dir = map_dir / "Assets" / "Textures"
    if textures_dir.is_dir():
        for dds in sorted(textures_dir.glob("ui_loading_*.dds")):
            if "gameplay" not in dds.name.lower():
                return dds.relative_to(MAPS_CMRE_DIR.parent).as_posix()
        for dds in sorted(textures_dir.glob("ui_loading_*.dds")):
            return dds.relative_to(MAPS_CMRE_DIR.parent).as_posix()
    # 2. 回退到 bnet_*.png（大部分地图都有，Battle.net 地图预览图）
    for png in sorted(map_dir.glob("bnet_*.png")):
        return png.relative_to(MAPS_CMRE_DIR.parent).as_posix()
    return ""


def load_maps():
    """扫描 cmre-runtime/Maps/CMRE/ 目录，返回 [{id, name, preview}]。

    id = 文件名（含 .SC2Map），name = 去掉 .SC2Map 扩展名的显示名。
    preview = 地图预览图相对路径（Maps/CMRE/<map>/Assets/Textures/ui_loading_xxx.dds），
              找不到为空字符串。按 name 排序。
    """
    if not MAPS_CMRE_DIR.exists():
        print(f"[warn] CMRE 地图目录不存在: {MAPS_CMRE_DIR}")
        return []
    maps = []
    for entry in sorted(MAPS_CMRE_DIR.iterdir()):
        if entry.is_dir() and entry.name.endswith(".SC2Map"):
            preview = _find_map_preview(entry)
            maps.append({
                "id": entry.name,
                "name": entry.name[:-len(".SC2Map")],
                "preview": preview,
            })
    return maps


def load_revolution_maps():
    """Load the owned Revolution Overdrive maps without changing the CMRE map API."""
    if not REVOLUTION_MAPS_JSON.exists():
        return []
    try:
        entries = json.loads(REVOLUTION_MAPS_JSON.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[warn] unable to load Revolution Overdrive map registry: {exc}")
        return []
    return [
        {
            "id": entry["id"],
            "name": entry.get("name", entry["id"].removesuffix(".SC2Map")),
            "preview": "",
            "packageId": "revolution-overdrive",
        }
        for entry in entries
        if isinstance(entry, dict) and entry.get("id")
    ]


def load_revolution_commanders():
    """Expose native faction presets as selectable Revolution Overdrive commanders."""
    if not REVOLUTION_COMMANDER_JSON.exists():
        return []
    try:
        metadata = json.loads(REVOLUTION_COMMANDER_JSON.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[warn] unable to load Revolution Overdrive commander registry: {exc}")
        return []
    commanders = []
    for faction in metadata.get("factions", []):
        faction_id = faction.get("id", "")
        if not faction_id:
            continue
        commanders.append({
            "id": f"RevolutionOverdrive{faction_id}",
            "label": f"起义狂潮：{faction.get('label', faction_id)}",
            "bank": faction_id,
            "portrait": "",
            "cachedImage": "",
            "race": "Terran",
            "group": "revolution-overdrive",
            "packageId": "revolution-overdrive",
            "faction": faction_id,
        })
    return commanders


def load_extra_mods(bank_commander=""):
    """扫描 packages/Mods/7vs1/ 目录，返回 [{id, name}]。

    若提供 bank_commander（如 "Alenger6"），从 alenger-mods.json 的
    commanderToAlenger[bank_commander] 查出该指挥官会自动加载的 mod 包，
    从结果中排除它们。id = name = 目录名去掉 .SC2Mod 后缀。按 name 排序。
    """
    if not MODS_7VS1_PACKAGES_DIR.exists():
        print(f"[warn] 7vs1 mod 包目录不存在: {MODS_7VS1_PACKAGES_DIR}")
        return []

    excluded = set()
    if bank_commander:
        try:
            if ALENGER_MODS_JSON.exists():
                data = json.loads(ALENGER_MODS_JSON.read_text(encoding="utf-8"))
                mapping = data.get("commanderToAlenger", {})
                excluded = set(mapping.get(bank_commander, []))
        except Exception as exc:
            print(f"[warn] 读取 alenger-mods.json 失败（extra-mods 过滤跳过）: {exc}")

    mods = []
    for entry in sorted(MODS_7VS1_PACKAGES_DIR.iterdir()):
        if entry.is_dir() and entry.name.endswith(".SC2Mod"):
            mod_id = entry.name[:-len(".SC2Mod")]
            if mod_id in excluded:
                continue
            mods.append({"id": mod_id, "name": mod_id})
    return mods


def _resolve_cached_commander_image(runtime_id: str) -> str:
    """检查 assets-cache/commanders/{runtime_id}.png 是否存在，返回 URL 路径，否则返回空字符串。"""
    filename = f"{runtime_id}.png"
    filepath = ASSETS_CACHE_COMMANDERS / filename
    if filepath.is_file():
        try:
            mtime = filepath.stat().st_mtime
            return f"/assets-cache/commanders/{filename}?v={int(mtime * 1000)}"
        except OSError:
            return f"/assets-cache/commanders/{filename}"
    return ""


def _resolve_cached_mutator_image(mutator_id: str) -> str:
    """检查 assets-cache/mutators/{mutator_id}.png 是否存在，返回 URL 路径，否则返回空字符串。"""
    filename = f"{mutator_id}.png"
    filepath = ASSETS_CACHE_MUTATORS / filename
    if filepath.is_file():
        try:
            mtime = filepath.stat().st_mtime
            return f"/assets-cache/mutators/{filename}?v={int(mtime * 1000)}"
        except OSError:
            return f"/assets-cache/mutators/{filename}"
    return ""


def _classify_commander(bank_commander: str, runtime_commander: str) -> str:
    """将指挥官分类为 'official'（官方18个）或 'alenger'（起义狂潮自定义）或 'reborn'（重生虫心）。"""
    if bank_commander.startswith("Alenger"):
        return "alenger"
    return "official"


def load_reborn_commanders():
    """从 reborn-commanders.json 读取重生虫心指挥官列表。

    返回 [{id, runtimeId, label, bank, portrait, cachedImage, race, group, rebornName, expectedUnits, expectedBuildings}]。

    关键：id 加 "Reborn" 前缀（如 "RebornZergAbathur"）避免与原版 8 个重名指挥官冲突。
    原版 Abathur/Kerrigan/Dehaka/Mengsk/Raynor/Stukov/Zagara/Zeratul 在 commander-power-metadata.json
    和 reborn-commanders.json 中均存在，若 id 相同则前端 state.commanders.find() 永远返回 official 版本，
    导致 cmdrMeta.group === "official" 不触发 enableReborn 透传，启动的是原版而非 Reborn mod。

    runtimeId 字段保存实际传给 launcher 的形式（如 "ZergAbathur"，与原版一致），launch 时由
    app.js 据此覆盖 body.commander。portrait/cachedImage 仍用 runtimeId 查找（与原版共用缓存图）。

    rebornName 用于 -RebornCommander 参数，expectedUnits/expectedBuildings 来自 galaxy 静态分析。
    跳过 id 为 "Random" 的条目（不直接可选）。
    """
    if not REBORN_COMMANDERS_JSON.exists():
        print(f"[warn] reborn-commanders.json 不存在: {REBORN_COMMANDERS_JSON}")
        return []
    try:
        data = json.loads(REBORN_COMMANDERS_JSON.read_text(encoding="utf-8"))
        commanders = []
        for cmd in data.get("commanders", []):
            cmd_id = cmd.get("id", "")
            if not cmd_id or cmd_id == "Random":
                continue
            race = cmd.get("race", "") or "Zerg"
            runtime_id = f"{race}{cmd_id}"
            unique_id = f"Reborn{runtime_id}"  # 前端唯一 id，避免与原版重名
            display = cmd.get("display_name", "") or cmd_id
            commanders.append({
                "id": unique_id,
                "runtimeId": runtime_id,  # 实际传给 launcher 的 -Commander 值
                "label": display,
                "bank": cmd_id,
                "portrait": get_commander_portrait(runtime_id),
                "cachedImage": _resolve_cached_commander_image(runtime_id),
                "race": race,
                "group": "reborn",
                "rebornName": cmd_id,
                "expectedUnits": cmd.get("expected_units", []),
                "expectedBuildings": cmd.get("expected_buildings", []),
            })
        commanders.sort(key=lambda c: ({"Terran": 0, "Zerg": 1, "Protoss": 2}.get(c["race"], 9), c["label"]))
        return commanders
    except Exception as exc:
        print(f"[warn] 读取 reborn-commanders.json 失败: {exc}")
        return []


def load_commanders():
    """从 commander-power-metadata.json + _registry.json 读取可玩指挥官列表。

    使用 _registry.json 确定哪些指挥官是 playable 的，返回所有可玩指挥官（含官方18个+Alenger全系列）。
    每条记录含：id(runtime), label(display_name), bank(bank_commander), portrait(DDS文件名),
    cachedImage(预导出PNG URL或空), race, group(official/alenger)。
    metadata 不存在时回退到默认。
    """
    default_cmd = "TerranRaynor"

    playable_set = set()
    bank_to_runtime = {}
    bank_to_race = {}
    try:
        if COMMANDERS_REGISTRY_JSON.exists():
            registry = json.loads(COMMANDERS_REGISTRY_JSON.read_text(encoding="utf-8"))
            for name, entry in registry.items():
                if entry.get("playable") is True:
                    bank_to_runtime[name] = name
                    bank_to_race[name] = entry.get("race", "")
                    for alias in entry.get("aliases", []):
                        bank_to_runtime[alias] = name
                        bank_to_race[alias] = entry.get("race", "")
                    if name.startswith(("Terran", "Zerg", "Protoss")):
                        playable_set.add(name)
                        bank_to_runtime[name] = name
            playable_set = {name for name, entry in registry.items() if entry.get("playable") is True}
    except Exception as exc:
        print(f"[warn] 读取 _registry.json 失败: {exc}")

    try:
        if COMMANDER_METADATA_JSON.exists():
            data = json.loads(COMMANDER_METADATA_JSON.read_text(encoding="utf-8"))
            commanders = []
            seen_runtimes = set()
            for cmd in data.get("commanders", []):
                runtime = cmd.get("runtime_commander", "")
                bank = cmd.get("bank_commander", "")
                display = cmd.get("display_name", "") or runtime
                if not runtime:
                    continue
                bank_key = bank if bank else runtime
                is_playable = (
                    bank in playable_set
                    or runtime in playable_set
                    or any(alias in playable_set for alias in [runtime.replace("Terran","").replace("Zerg","").replace("Protoss","")])
                    or (bank.startswith("Alenger") and bank in playable_set)
                    or (runtime.startswith("Alenger") and runtime in playable_set)
                )
                if not is_playable:
                    if bank.startswith("Alenger") or runtime.startswith("Alenger"):
                        is_playable = True
                    elif bank and bank in bank_to_runtime:
                        is_playable = True
                if not is_playable:
                    continue
                if runtime in seen_runtimes:
                    continue
                seen_runtimes.add(runtime)
                race = ""
                if runtime.startswith("Terran"):
                    race = "Terran"
                elif runtime.startswith("Zerg"):
                    race = "Zerg"
                elif runtime.startswith("Protoss"):
                    race = "Protoss"
                if not race and bank:
                    race = bank_to_race.get(bank, "")
                commanders.append({
                    "id": runtime,
                    "label": display,
                    "bank": bank,
                    "portrait": get_commander_portrait(runtime),
                    "cachedImage": _resolve_cached_commander_image(runtime),
                    "race": race,
                    "group": _classify_commander(bank, runtime),
                })
            if commanders:
                # 追加 Reborn 指挥官（重生虫心），从 reborn-commanders.json 加载
                reborn_cmdrs = load_reborn_commanders()
                commanders.extend(reborn_cmdrs)
                def sort_key(c):
                    group_order = {"official": 0, "alenger": 1, "reborn": 2}
                    race_order = {"Terran": 0, "Zerg": 1, "Protoss": 2, "": 3}
                    return (group_order.get(c["group"], 9), race_order.get(c["race"], 9), c["label"])
                commanders.sort(key=sort_key)
                return commanders
            print(f"[warn] metadata 中无可用指挥官，回退默认: {COMMANDER_METADATA_JSON}")
    except Exception as exc:
        print(f"[warn] 读取 commander-power-metadata.json 失败，使用默认: {exc}")
    return [{
        "id": default_cmd,
        "label": "雷诺",
        "bank": "Raynor",
        "portrait": get_commander_portrait(default_cmd),
        "cachedImage": _resolve_cached_commander_image(default_cmd),
        "race": "Terran",
        "group": "official",
    }]


def build_factors_data():
    """构造 /api/factors 返回数据，指挥官每次实时从配置派生。"""
    data = dict(FACTORS_DATA)
    data["commanders"] = load_commanders()
    data["revolutionCommanders"] = load_revolution_commanders()
    return data


# 原版 18 位指挥官的 runtime_commander 列表（含 3 威望 + 6 精通）。
# 仅这些指挥官支持 Buff 补丁（起义指挥官无原版威望/精通系统）。
OFFICIAL_BUFF_COMMANDERS = [
    "TerranRaynor", "ZergKerrigan", "ProtossArtanis", "TerranSwann",
    "ZergZagara", "ProtossVorazun", "ProtossKarax", "ZergAbathur",
    "ProtossAlarak", "TerranNova", "ZergStukov", "ProtossFenix",
    "ZergDehaka", "TerranHorner", "TerranTychus", "ProtossZeratul",
    "ZergStetmann", "TerranMengsk",
]

# 威望子选项（extra_options）：来源于起义狂潮 Shared/Talents 配置。
# 结构: {(runtime_commander, prestige_slot_1based): [{id, name, description, upgrade_id, needs_review}]}
# prestige_slot 为 1-based（1=P1, 2=P2, 3=P3）。
PRESTIGE_EXTRA_OPTIONS = {
    ("TerranRaynor", 1): [
        {
            "id": "BioSuperStim",
            "name": "强化兴奋剂",
            "description": "枪兵和劫掠者使用强化版兴奋剂（不扣血且加快生命恢复）。",
            "upgrade_id": "CommanderPrestigeRaynorBioSuperStim",
            "needs_manual_review": False,
        },
    ],
    ("ZergStukov", 2): [
        {
            "id": "P2SpawnInfestedMarineInBanshee",
            "name": "女妖孵化感染枪兵",
            "description": "女妖每10秒消耗20点能量，在货舱中生成1个被感染的枪兵（需要女妖有货舱/能量）。",
            "upgrade_id": "CommanderPrestigeStukovP2SpawnInfestedMarineInBanshee",
            "needs_manual_review": True,
        },
    ],
}


def load_buff_metadata():
    """读取原版 18 指挥官的威望 + 精通 + 威望子选项元数据，用于 WebUI Buff 补丁面板。

    数据源：
      - cmre-runtime/Shared/CommanderPower/commander-power-metadata.json（威望/精通基础数据）
      - PRESTIGE_EXTRA_OPTIONS（威望子选项 extra_options，来源：起义狂潮 Talents）
    返回结构：
        {
          "commanders": [
            {
              "runtime_commander": "TerranRaynor",
              "display_name": "雷诺",
              "prestiges": [
                {
                  "slot": 1,
                  "name": "死水元帅",
                  "advantage_text": "...",
                  "disadvantage_text": "...",
                  "bonus_upgrade_id": "CommanderPrestigeRaynorBioBonus",
                  "needs_manual_review": false,
                  "extras": [
                    {
                      "index": 0,
                      "id": "BioSuperStim",
                      "name": "强化兴奋剂",
                      "description": "...",
                      "upgrade_id": "CommanderPrestigeRaynorBioSuperStim",
                      "needs_manual_review": false
                    }
                  ]
                }, ...
              ],
              "masteries": [...]
            }, ...
          ]
        }
    """
    if not COMMANDER_METADATA_JSON.exists():
        return {"commanders": []}

    try:
        metadata = json.loads(COMMANDER_METADATA_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"commanders": []}

    # bonus_upgrade_id 反查表：从 prestige-bonus-index.json 读取
    bonus_index_path = (
        SC2VIBE_ROOT
        / "sc2-porting-workspace"
        / "artifacts"
        / "buff-patch"
        / "prestige-bonus-index.json"
    )
    bonus_index = {}
    if bonus_index_path.exists():
        try:
            for entry in json.loads(bonus_index_path.read_text(encoding="utf-8")):
                key = (entry.get("runtime_commander", ""), entry.get("slot", -1))
                bonus_index[key] = {
                    "bonus_upgrade_id": entry.get("bonus_upgrade_id", ""),
                    "needs_manual_review": entry.get("needs_manual_review", False),
                    "review_notes": entry.get("review_notes", ""),
                }
        except (OSError, json.JSONDecodeError):
            pass

    import re

    def parse_tooltip_parts(tooltip):
        """从原版 tooltip 中解析优点/缺点文本。

        tooltip 格式：<s val="Coop_Prestige_Advantage">优点</s><n/>text<n/><n/><s val="Coop_Prestige_Disadvantage">缺点</s><n/>text
        """
        advantage = ""
        disadvantage = ""
        if not tooltip:
            return advantage, disadvantage
        # 移除所有 <s ...>label</s> 标签，但记录位置
        adv_match = re.search(
            r'<s val="Coop_Prestige_Advantage">[^<]*</s><n/>(.*?)(?:<n/><n/><s val="Coop_Prestige_Disadvantage">|$)',
            tooltip, re.DOTALL,
        )
        if adv_match:
            advantage = adv_match.group(1).strip()
        dis_match = re.search(
            r'<s val="Coop_Prestige_Disadvantage">[^<]*</s><n/>(.*?)$',
            tooltip, re.DOTALL,
        )
        if dis_match:
            disadvantage = dis_match.group(1).strip()
        # 清理剩余标签
        advantage = re.sub(r"<[^>]+>", "", advantage).strip()
        disadvantage = re.sub(r"<[^>]+>", "", disadvantage).strip()
        return advantage, disadvantage

    commanders = []
    for record in metadata.get("commanders", []):
        runtime = record.get("runtime_commander", "")
        if runtime not in OFFICIAL_BUFF_COMMANDERS:
            continue
        prestiges_out = []
        for prest in record.get("prestiges", []):
            slot = prest.get("slot", 0)
            # metadata slot 是 0/1/2 对应 P1/P2/P3，前端用 1/2/3
            slot_1based = slot + 1
            advantage, disadvantage = parse_tooltip_parts(prest.get("tooltip", ""))
            bonus_info = bonus_index.get((runtime, slot), {})
            raw_extras = PRESTIGE_EXTRA_OPTIONS.get((runtime, slot_1based), [])
            extras_out = []
            for idx, ex in enumerate(raw_extras):
                extras_out.append({
                    "index": idx,
                    "id": ex["id"],
                    "name": ex["name"],
                    "description": ex["description"],
                    "upgrade_id": ex["upgrade_id"],
                    "needs_manual_review": ex.get("needs_manual_review", False),
                })
            prestiges_out.append({
                "slot": slot_1based,
                "name": prest.get("name", ""),
                "name_en": prest.get("name_en", ""),
                "advantage_text": advantage,
                "disadvantage_text": disadvantage,
                "bonus_upgrade_id": bonus_info.get("bonus_upgrade_id", ""),
                "needs_manual_review": bonus_info.get("needs_manual_review", False),
                "review_notes": bonus_info.get("review_notes", ""),
                "extras": extras_out,
            })

        masteries_out = []
        for mas in record.get("masteries", []):
            slot = mas.get("slot", 0)
            slot_1based = slot + 1
            masteries_out.append({
                "slot": slot_1based,
                "id": mas.get("id", ""),
                "name": mas.get("name", ""),
                "category": mas.get("category", 0),
                "value_format": mas.get("value_format", ""),
                "point_increments": mas.get("point_increments", []),
                "default_value": 30,
            })

        commanders.append({
            "runtime_commander": runtime,
            "display_name": record.get("display_name", ""),
            "prestiges": prestiges_out,
            "masteries": masteries_out,
        })

    # 保持 OFFICIAL_BUFF_COMMANDERS 顺序
    order = {c: i for i, c in enumerate(OFFICIAL_BUFF_COMMANDERS)}
    commanders.sort(key=lambda c: order.get(c["runtime_commander"], 999))
    return {"commanders": commanders}


def load_localized_strings():
    """读取当前 CMRE 运行时的中文本地化表。"""
    strings = {}
    if not CMRE_MODS_DIR.exists():
        return strings
    for path in CMRE_MODS_DIR.rglob("GameStrings.txt"):
        if "zhCN.SC2Data" not in str(path):
            continue
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line or line.startswith("//") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                strings[key.strip()] = value
        except OSError as exc:
            print(f"[warn] 读取 CMRE 本地化文件失败: {path}: {exc}")
    return strings


def load_mutators():
    """从当前 CMRE 的 UserData.xml 构造可用于自定义模式的因子目录。

    每条记录含 id/name/description/icon，icon 为 UserData.xml 中 <Field Id="MA - Icon">
    引用的 DDS 路径（如 "Assets\\Textures\\walkingdead_coop.dds"），供前端通过
    /api/assets/dds 路由加载。
    """
    try:
        root = ET.parse(MUTATORS_USERDATA_XML).getroot()
        strings = load_localized_strings()
        mutators = []
        for instance in root.findall("./CUser[@id='Mutators']/Instances"):
            mutator_id = instance.get("Id", "")
            allowed = any(
                value.get("Int") == "1"
                and value.find("Field") is not None
                and value.find("Field").get("Id") in {"CustomAllowed", "MA - Custom Allowed"}
                for value in instance.findall("./Int")
            )
            if not mutator_id or not allowed:
                continue
            # 提取 MA - Icon 字段引用的 DDS 路径
            icon_path = ""
            for img_el in instance.findall("./Image"):
                field_el = img_el.find("Field")
                if field_el is not None and field_el.get("Id") == "MA - Icon":
                    icon_path = img_el.get("Image", "")
                    break
            mutators.append(
                {
                    "id": mutator_id,
                    "name": strings.get(f"UserData/Mutators/{mutator_id}_Name", mutator_id),
                    "description": strings.get(f"UserData/Mutators/{mutator_id}_Description", ""),
                    "icon": icon_path,
                    "cachedImage": _resolve_cached_mutator_image(mutator_id),
                }
            )
        if mutators:
            return sorted(mutators, key=lambda item: item["name"])
        print(f"[warn] CMRE 因子目录为空，回退到缓存: {MUTATORS_USERDATA_XML}")
    except (ET.ParseError, OSError) as exc:
        print(f"[warn] 读取 CMRE 因子目录失败，回退到缓存: {exc}")

    try:
        return json.loads(MUTATORS_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[warn] 读取因子缓存失败: {exc}")
        return []


# 资源根目录：在 CMRE_Core_Triggers 和 CMRE_Core_Base 两个 mod 中查找 DDS 文件。
# 指挥官头像、CM_Mutator* 等在 mod 根的 Assets/Textures 下；
# 3P_*.dds 在 CMRE_Core_Base.SC2Mod 根目录；Base.SC2Data 下的 Assets 兜底。
DDS_SEARCH_ROOTS = [
    CMRE_MODS_DIR / "CMRE_Core_Triggers.SC2Mod",
    CMRE_MODS_DIR / "CMRE_Core_Triggers.SC2Mod" / "Base.SC2Data",
    CMRE_MODS_DIR / "CMRE_Core_Base.SC2Mod",
    CMRE_MODS_DIR / "CMRE_Core_Base.SC2Mod" / "Base.SC2Data",
]

# 指挥官头像文件名规则：ui_commanderportrait_<name>.dds。
# Alenger 系列没有专属头像，按种族 fallback 到代表头像。
COMMANDER_PORTRAIT_BY_RACE = {
    "Terran": "ui_commanderportrait_raynor.dds",
    "Zerg": "ui_commanderportrait_zagara.dds",
    "Protoss": "ui_commanderportrait_artanis.dds",
}
COMMANDER_PORTRAIT_FALLBACK = "ui_commanderportrait_random.dds"


def find_asset_file(rel_path: str) -> Path | None:
    """在 CMRE mod 的 Assets 目录中查找图片文件（DDS 或 PNG）。

    rel_path 形如 "Assets\\Textures\\xxx.dds" 或 "Assets/Textures/xxx.dds"，
    也支持 "Maps/CMRE/<map>/..." 的地图预览图路径（含 .png 回退）。
    返回找到的第一个文件 Path，否则 None。
    """
    if not rel_path:
        return None
    # 归一化路径分隔符
    normalized = rel_path.replace("\\", "/").lstrip("/")
    # 先搜 CMRE mod 目录
    for root in DDS_SEARCH_ROOTS:
        candidate = root / normalized
        if candidate.is_file():
            return candidate
    # 地图预览图路径（如 CMRE/xxx/...，相对于 cmre-runtime/Maps/）
    maps_root = MAPS_CMRE_DIR.parent  # cmre-runtime/Maps
    candidate = maps_root / normalized
    if candidate.is_file():
        return candidate
    return None


def convert_dds_to_png(dds_path: Path, png_path: Path) -> bool:
    """将 DDS 转 PNG 缓存。成功返回 True，失败返回 False。"""
    try:
        from PIL import Image  # 延迟导入，仅在需要时加载 Pillow
        with Image.open(dds_path) as img:
            # 部分 DDS 是 BGRA/RGBA 混合，统一转 RGBA
            if img.mode not in ("RGBA", "RGB"):
                img = img.convert("RGBA")
            png_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(png_path, "PNG")
        return True
    except Exception as exc:
        print(f"[warn] DDS 转 PNG 失败: {dds_path} -> {png_path}: {exc}")
        return False


def get_commander_portrait(commander_id: str) -> str:
    """根据 runtime_commander 名称前缀返回 DDS 文件名。"""
    for race, portrait in COMMANDER_PORTRAIT_BY_RACE.items():
        if commander_id.startswith(race):
            return portrait
    return COMMANDER_PORTRAIT_FALLBACK


def load_voice_packs():
    """返回 CMRE 启动档案实际使用的 VoicePack catalog ID。

    官方 ConfigData.xml 的 ``VoicePack,<id>`` 条目与 CMRE 的
    ``c_gameCatalogVoicePack`` 枚举一致。RewardData.xml 中的
    ``VoicePackTerranRaynor`` 一类是底层 reward，而非 ``VoicePack`` 字段
    应写入的 ID，不能直接提供给 WebUI。
    """
    strings = load_localized_strings()
    voice_packs = {}

    try:
        root = ET.parse(OFFICIAL_VOICEPACK_CONFIG_XML).getroot()
        for entry in root.findall(".//GameContentArray"):
            value = entry.get("value", "")
            category, separator, voice_id = value.partition(",")
            if category != "VoicePack" or not separator or not voice_id or voice_id == "eSports":
                continue
            voice_packs[voice_id] = {
                "id": voice_id,
                "name": strings.get(f"VoicePack/Name/{voice_id}", voice_id),
            }
    except (ET.ParseError, OSError) as exc:
        print(f"[warn] 读取官方 VoicePack 目录失败: {exc}")

    # CMRE 可能带有官方清单之外的自定义语音包。扫描所有随 runtime 安装的
    # RewardData.xml，并取其 voicepack 属性（而不是 reward 的 id）。
    if CMRE_MODS_DIR.exists():
        for path in CMRE_MODS_DIR.rglob("RewardData.xml"):
            try:
                root = ET.parse(path).getroot()
            except (ET.ParseError, OSError) as exc:
                print(f"[warn] 读取 CMRE 语音包扩展失败: {path}: {exc}")
                continue
            for reward in root.findall("./CRewardVoicePack"):
                voice_id = reward.get("voicepack", "")
                if not voice_id or voice_id == "eSports":
                    continue
                voice_packs.setdefault(
                    voice_id,
                    {
                        "id": voice_id,
                        "name": strings.get(f"VoicePack/Name/{voice_id}", voice_id),
                    },
                )

    if voice_packs:
        return sorted(voice_packs.values(), key=lambda item: item["name"])

    # 仅在官方目录缺失时退回原有的 runtime Reward 扫描；这能保住最小可用性，
    # 但其 ID 不一定是完整 VoicePack catalog，因此不会成为正常路径。
    try:
        for path in CMRE_MODS_DIR.rglob("RewardData.xml"):
            root = ET.parse(path).getroot()
            for reward in root.findall("./CRewardVoicePack"):
                voice_id = reward.get("id", "")
                if voice_id and voice_id != "eSports":
                    voice_packs[voice_id] = {"id": voice_id, "name": voice_id}
    except (ET.ParseError, OSError) as exc:
        print(f"[warn] 读取降级语音包目录失败: {exc}")
    return sorted(voice_packs.values(), key=lambda item: item["name"])


def normalize_mutators(raw_mutators):
    """校验、去重并限制客户端提交的因子。"""
    if not isinstance(raw_mutators, list):
        raise ValueError("mutators 必须是数组")
    valid_ids = {mutator["id"] for mutator in load_mutators()}
    normalized = []
    seen = set()
    for item in raw_mutators:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("每个因子必须包含字符串 id")
        mutator_id = item["id"]
        if mutator_id not in valid_ids:
            raise ValueError(f"不支持的 CMRE 因子: {mutator_id}")
        if mutator_id in seen:
            continue
        seen.add(mutator_id)
        normalized.append({"id": mutator_id, "enhanced": bool(item.get("enhanced", False))})
    return normalized[:MUTATOR_MAX], len(normalized) > MUTATOR_MAX


# === 异步启动 / SSE 日志流 全局状态 ===
_launcher_process = None  # 当前异步启动的 launcher 子进程
_launcher_lock = threading.Lock()


class RuntimeConsole:
    """Own one long-lived VibeREPL on a worker event loop for the browser console."""

    def __init__(self):
        self._lock = threading.RLock()
        self._loop = None
        self._thread = None
        self._ready = threading.Event()
        self._repl = None
        self._status = "disconnected"
        self._error = ""
        self._port = None
        self._session_id = ""
        self._trace = []
        self._running = ""

    def _ensure_loop(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._ready.clear()
            self._thread = threading.Thread(
                target=self._run_loop, name="vibe-console-loop", daemon=True
            )
            self._thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("runtime console event loop did not start")

    def _run_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
            self._ready.set()
        loop.run_forever()
        loop.close()

    def _submit(self, coroutine, timeout=30):
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        return future.result(timeout=timeout)

    @staticmethod
    def _imports():
        if str(GALAXY_VIBE_ROOT) not in sys.path:
            sys.path.insert(0, str(GALAXY_VIBE_ROOT))
        from galaxy_repl import VibeREPL, _unit_id_resolver, _unit_name_lookup
        from vibe.debug_vm import DebugVm, load_function_catalog, load_function_metadata

        return (
            VibeREPL,
            _unit_id_resolver,
            _unit_name_lookup,
            DebugVm,
            load_function_catalog,
            load_function_metadata,
        )

    @staticmethod
    def catalog():
        data = json.loads(VIBE_FUNCTION_REGISTRY.read_text(encoding="utf-8"))
        entries = []
        for function_id, definition in data.get("functions", {}).items():
            entries.append({"function_id": function_id, **definition})
        entries.sort(key=lambda item: item["function_id"])
        return {"version": data.get("version", 1), "functions": entries}

    def sessions(self):
        self._imports()
        from galaxy_repl import DEFAULT_RPC_BANK, parse_bank

        sessions = {}
        for raw in parse_bank(DEFAULT_RPC_BANK).get("response", {}).values():
            if not isinstance(raw, str):
                continue
            try:
                response = json.loads(raw)
            except json.JSONDecodeError:
                continue
            session_id = response.get("session_id")
            if not session_id:
                continue
            current = sessions.setdefault(
                session_id,
                {"session_id": session_id, "sequence": 0, "operation": ""},
            )
            current["sequence"] = max(
                current["sequence"], int(response.get("sequence", 0) or 0)
            )
            current["operation"] = response.get("operation", current["operation"])
        return sorted(sessions.values(), key=lambda item: item["sequence"], reverse=True)[:20]

    async def _connect(self, payload):
        VibeREPL, resolve, name_lookup, _, _, _ = self._imports()
        port = int(payload.get("port", 5000))
        map_path = str(payload.get("map_path", "") or "")
        join_wait = float(payload.get("join_wait", 0) or 0)
        rpc_session_id = str(payload.get("rpc_session_id", "") or "")
        if self._repl is not None:
            await self._repl.close()
        repl = VibeREPL(
            port,
            resolve(),
            name_lookup(),
            map_path=map_path,
            join_wait=join_wait,
            rpc_session_id=rpc_session_id,
        )
        with self._lock:
            self._status = "connecting"
            self._error = ""
        try:
            await repl.connect()
        except Exception as exc:
            with self._lock:
                self._status = "error"
                self._error = str(exc)
            await repl.close()
            raise
        with self._lock:
            self._repl = repl
            self._port = port
            self._session_id = repl.rpc_session_id
            self._status = "connected"
            self._error = ""
            self._trace = []
        return self.status()

    async def _disconnect(self):
        if self._repl is not None:
            await self._repl.close()
        with self._lock:
            self._repl = None
            self._status = "disconnected"
            self._running = ""
        return self.status()

    def connect(self, payload):
        return self._submit(self._connect(payload), timeout=90)

    def disconnect(self):
        return self._submit(self._disconnect(), timeout=15)

    async def _invoke(self, function_id, args):
        if self._repl is None:
            raise RuntimeError("未连接 SC2 Vibe session")
        with self._lock:
            previous_running = self._running
            if not previous_running:
                self._running = "invoke"
        started = time.perf_counter()
        try:
            result = await self._repl.invoke_function_request(function_id, args)
            record = {
                "ts": time.time(),
                "op": "call",
                "function_id": function_id,
                "args": args,
                "result": result,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "status": "passed" if result.get("error_code") == "OK" else "failed",
            }
            self._append_trace(record)
            return record
        finally:
            with self._lock:
                if not previous_running:
                    self._running = ""

    def invoke(self, function_id, args):
        return self._submit(self._invoke(function_id, args), timeout=30)

    async def _step(self, loops):
        if self._repl is None:
            raise RuntimeError("未连接 SC2 Vibe session")
        from galaxy_repl import send_request

        response = await send_request(
            self._repl.ws,
            self._step_request(loops),
            timeout=10.0,
        )
        result = (
            {"kind": "error", "error_code": "STEP_FAILED", "payload": {"errors": list(response.error)}}
            if response.error
            else {"kind": "result", "error_code": "OK", "payload": {"requested_loops": loops}}
        )
        self._append_trace({"ts": time.time(), "op": "step", "loops": loops, "result": result})
        return result

    def step(self, loops):
        return self._submit(self._step(loops), timeout=15)

    async def _run_vm(self, program):
        if self._repl is None:
            raise RuntimeError("未连接 SC2 Vibe session")
        _, _, _, DebugVm, load_function_catalog, load_function_metadata = self._imports()
        with self._lock:
            self._running = "vm"
        manager = self
        try:
            catalog = load_function_catalog(VIBE_FUNCTION_CATALOG) if VIBE_FUNCTION_CATALOG.exists() else []

            class ReplBridge:
                async def call(inner_self, function_id, call_args):
                    record = await manager._invoke(function_id, call_args)
                    return record["result"]

                async def step(inner_self, loops):
                    return await manager._step(loops)

            result = await DebugVm(
                ReplBridge(),
                function_metadata=load_function_metadata(),
                catalog=catalog,
            ).run(program)
            for item in result.get("trace", []):
                if item.get("op") != "call":
                    self._append_trace({"ts": time.time(), **item})
            return result
        finally:
            with self._lock:
                self._running = ""

    @staticmethod
    def _step_request(loops):
        from s2clientprotocol import sc2api_pb2 as sc_pb

        return sc_pb.Request(step=sc_pb.RequestStep(count=loops))

    def run_vm(self, program):
        return self._submit(self._run_vm(program), timeout=180)

    def _append_trace(self, record):
        with self._lock:
            self._trace.append(record)
            self._trace = self._trace[-300:]

    def status(self):
        with self._lock:
            return {
                "status": self._status,
                "error": self._error,
                "port": self._port,
                "session_id": self._session_id,
                "running": self._running,
                "trace": list(self._trace),
            }

    def shutdown(self):
        try:
            if self._repl is not None:
                self.disconnect()
        except Exception:
            pass
        with self._lock:
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._loop.stop)


_runtime_console = RuntimeConsole()
atexit.register(_runtime_console.shutdown)
_log_lines = []  # 环形缓冲，最多 2000 行
_log_subscribers = []  # SSE 订阅者 queue 列表
_log_lock = threading.Lock()

_GAME_PROCESS_NAMES = {
    "sc2.exe",
    "sc2_x64.exe",
    "sc2switcher.exe",
    "sc2switcher_x64.exe",
}


def _append_log(line):
    """添加日志行并推送给所有 SSE 订阅者。"""
    with _log_lock:
        _log_lines.append(line)
        if len(_log_lines) > 2000:
            _log_lines.pop(0)
        for q in _log_subscribers:
            try:
                q.put_nowait(line)
            except queue.Full:
                pass


def _read_pipe(pipe, prefix="", output_tail=None, tail_lock=None, stream_name=""):
    """逐行读取 launcher 输出，并保留有限尾部供失败摘要使用。"""
    try:
        for line in iter(pipe.readline, ''):
            clean = line.rstrip('\r\n')
            if output_tail is not None and stream_name:
                if tail_lock is None:
                    output_tail[stream_name].append(clean)
                else:
                    with tail_lock:
                        output_tail[stream_name].append(clean)
            _append_log(prefix + clean)
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def _format_launcher_exit_code(code):
    """把 Windows 无符号进程码补充为可读的有符号值。"""
    try:
        numeric = int(code)
    except (TypeError, ValueError):
        return str(code)
    if numeric > 0x7FFFFFFF and numeric <= 0xFFFFFFFF:
        return f"{numeric} (signed={numeric - 0x100000000})"
    if numeric < 0:
        return f"{numeric} (unsigned={numeric & 0xFFFFFFFF})"
    return str(numeric)


def _wait_for_process(proc, reader_threads=None, output_tail=None, tail_lock=None):
    """等待 launcher 和 reader 完成，再按顺序记录错误摘要与退出码。"""
    global _launcher_process
    reader_threads = reader_threads or []
    try:
        code = proc.wait()
    except Exception as exc:
        _append_log(f"[webui] 等待进程结束异常: {exc}")
        code = -1
    for reader in reader_threads:
        reader.join()
    if code != 0 and output_tail is not None:
        if tail_lock is None:
            stderr_tail = list(output_tail.get("stderr", []))[-40:]
            stdout_tail = list(output_tail.get("stdout", []))[-60:]
        else:
            with tail_lock:
                stderr_tail = list(output_tail.get("stderr", []))[-40:]
                stdout_tail = list(output_tail.get("stdout", []))[-60:]
        # 标记错误行：stdout 中可能包含我们通过全局 trap 写入的 LAUNCHER ERROR
        # 或其他明显的警告/失败行，优先抽取并展示。
        error_markers = ("LAUNCHER ERROR", "[trap]", "启动器执行失败", "位置:", " 代码:",
                         "failed", "Exception", "throw", "无法", "失败")
        def _pick_error_lines(lines):
            hits = [ln for ln in lines if any(m.lower() in ln.lower() for m in error_markers)]
            return hits
        stdout_errors = _pick_error_lines(stdout_tail)
        stderr_errors = _pick_error_lines(stderr_tail)

        if stderr_tail:
            _append_log("[webui] launcher stderr summary: " + " | ".join(stderr_tail))
        if stdout_tail:
            # 如果有显式错误行，单独列出来，避免用户在 summary 长串中遗漏。
            if stdout_errors and not stderr_errors:
                _append_log("[webui] launcher stdout 中的错误行: " + " | ".join(stdout_errors[-20:]))
            _append_log("[webui] launcher stdout summary: " + " | ".join(stdout_tail))
        # stderr 为空时给出提示，避免被误认为"没有错误"。
        if not stderr_tail and not stdout_errors:
            _append_log("[webui] 未从 launcher stderr 捕获到可读错误信息（可能是 PowerShell 编码异常），请检查 stdout summary 末尾与 GameLogs。")
    _append_log(f"[webui] launcher 进程结束, exit={_format_launcher_exit_code(code)}")
    with _launcher_lock:
        if _launcher_process is proc:
            _launcher_process = None


def _list_game_processes():
    """返回当前 SC2/SC2Switcher 进程，供 WebUI 的强制重启使用。"""
    if os.name != "nt":
        return []
    try:
        completed = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _append_log(f"[webui] 枚举 SC2 进程失败: {exc}")
        return []

    processes = []
    for row in csv.reader(completed.stdout.splitlines()):
        if len(row) < 2:
            continue
        name = row[0].strip().lower()
        if name not in _GAME_PROCESS_NAMES:
            continue
        try:
            pid = int(row[1].strip())
        except ValueError:
            continue
        if pid != os.getpid():
            processes.append((pid, row[0].strip()))
    return processes


def _force_kill_process_tree(pid):
    """强制终止 pid 及其子树；非 Windows 测试环境回退到无操作。"""
    if os.name != "nt":
        return False
    try:
        completed = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        return completed.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        _append_log(f"[webui] 强制结束 PID {pid} 失败: {exc}")
        return False


def _force_stop_current_game():
    """终止当前 WebUI 跟踪的 launcher，而不影响外部 SC2 会话。"""
    global _launcher_process

    with _launcher_lock:
        tracked_launcher = _launcher_process
        _launcher_process = None

    killed = []
    if tracked_launcher is not None and tracked_launcher.poll() is None:
        if _force_kill_process_tree(tracked_launcher.pid):
            killed.append(f"launcher:{tracked_launcher.pid}")
        else:
            try:
                tracked_launcher.kill()
                killed.append(f"launcher:{tracked_launcher.pid}")
            except OSError:
                pass
        try:
            tracked_launcher.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass

    if killed:
        _append_log(f"[webui] 强制重启: 已结束旧进程 {', '.join(killed)}")
    else:
        _append_log("[webui] 强制重启: 未发现由 WebUI 跟踪的 launcher")
    return killed


class CmreWebUIHandler(SimpleHTTPRequestHandler):
    """处理 WebUI 的 HTTP 请求。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEBUI_DIR), **kwargs)

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_HEAD(self):
        """HEAD 请求委托给 do_GET（不发送 body）。"""
        # 临时替换 wfile 以丢弃 body 输出
        import io
        orig_wfile = self.wfile
        self.wfile = io.BytesIO() if hasattr(io, "BytesIO") else open(os.devnull, "wb")
        try:
            self.do_GET()
        finally:
            self.wfile = orig_wfile

    def do_GET(self):
        if self.path == "/api/mutators":
            self._handle_get_mutators()
            return
        if self.path == "/api/voice-packs":
            self._send_json({"voicePacks": load_voice_packs()})
            return
        if self.path == "/api/factors":
            self._send_json(build_factors_data())
            return
        if self.path == "/api/vibe/catalog":
            try:
                self._send_json(_runtime_console.catalog())
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
            return
        if self.path == "/api/vibe/sessions":
            try:
                self._send_json({"sessions": _runtime_console.sessions()})
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
            return
        if self.path == "/api/vibe/status":
            self._send_json(_runtime_console.status())
            return
        if self.path == "/api/buff-metadata":
            self._send_json(load_buff_metadata())
            return
        if self.path == "/api/maps":
            self._send_json({
                "maps": load_maps(),
                "revolutionMaps": load_revolution_maps(),
            })
            return
        if self.path == "/api/logs/stream":
            self._handle_logs_stream()
            return
        if self.path == "/api/status":
            self._send_json({
                "launcherRunning": _launcher_process is not None and _launcher_process.poll() is None,
                "pid": _launcher_process.pid if _launcher_process else None,
            })
            return
        if self.path.startswith("/api/extra-mods"):
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            bank = qs.get("commander", [""])[0]
            self._send_json({"extraMods": load_extra_mods(bank)})
            return
        if self.path.startswith("/api/assets/dds"):
            self._handle_dds_asset()
            return
        if self.path == "/" or self.path == "":
            self.path = "/index.html"
        return super().do_GET()

    def _handle_dds_asset(self):
        """提供 DDS→PNG 转换或直接 PNG 的图片资源。

        GET /api/assets/dds?path=Assets/Textures/walkingdead_coop.dds
        GET /api/assets/dds?path=Maps/CMRE/亡者之夜.SC2Map/bnet_don.png

        首次请求 DDS 时从 CMRE mod 中查找并转 PNG 缓存到 webui/assets_cache/，
        后续直接返回缓存的 PNG。PNG 文件直接返回，无需转换。
        找不到或转换失败时返回 404，前端 fallback 到默认图标。
        """
        from urllib.parse import urlparse, parse_qs, unquote
        import hashlib
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        rel_path = qs.get("path", [""])[0]
        rel_path = unquote(rel_path)
        if not rel_path:
            self.send_error(400, "missing path parameter")
            return

        asset_path = find_asset_file(rel_path)
        if asset_path is None:
            self.send_error(404, f"Asset not found: {rel_path}")
            return

        # PNG 文件直接返回，无需转换
        if asset_path.suffix.lower() == ".png":
            try:
                data = asset_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(data)
            except OSError as exc:
                self.send_error(500, f"read png failed: {exc}")
            return

        # DDS 文件：转 PNG 缓存
        cache_key = hashlib.md5(rel_path.encode("utf-8")).hexdigest()[:16]
        png_path = ASSETS_CACHE_DIR / f"{cache_key}.png"

        if not png_path.is_file():
            if not convert_dds_to_png(asset_path, png_path):
                self.send_error(500, f"DDS conversion failed: {rel_path}")
                return

        # 返回 PNG 文件
        try:
            data = png_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(data)
        except OSError as exc:
            self.send_error(500, f"read png failed: {exc}")

    def _handle_get_mutators(self):
        self._send_json(load_mutators())

    def do_POST(self):
        if self.path == "/api/launch":
            self._handle_launch()
            return
        if self.path == "/api/launch-async":
            self._handle_launch_async()
            return
        if self.path == "/api/stop":
            self._handle_stop()
            return
        if self.path == "/api/vibe/connect":
            self._handle_vibe_connect()
            return
        if self.path == "/api/vibe/disconnect":
            self._handle_vibe_disconnect()
            return
        if self.path == "/api/vibe/invoke":
            self._handle_vibe_invoke()
            return
        if self.path == "/api/vibe/run-vm":
            self._handle_vibe_run_vm()
            return
        if self.path == "/api/vibe/step":
            self._handle_vibe_step()
            return
        self._send_json({"success": False, "error": "未知端点"}, 404)

    def _handle_vibe_connect(self):
        body = self._read_body()
        try:
            result = _runtime_console.connect({
                "port": body.get("port", 5000),
                "map_path": body.get("mapPath", ""),
                "join_wait": body.get("joinWait", 0),
                "rpc_session_id": body.get("rpcSessionId", ""),
            })
            self._send_json({"success": True, **result})
        except Exception as exc:
            self._send_json({"success": False, "error": str(exc), **_runtime_console.status()}, 502)

    def _handle_vibe_disconnect(self):
        try:
            self._send_json({"success": True, **_runtime_console.disconnect()})
        except Exception as exc:
            self._send_json({"success": False, "error": str(exc)}, 500)

    def _handle_vibe_invoke(self):
        body = self._read_body()
        function_id = body.get("functionId", "")
        args = body.get("args", {})
        if not isinstance(function_id, str) or not function_id:
            self._send_json({"success": False, "error": "functionId 必须是非空字符串"}, 400)
            return
        if not isinstance(args, dict):
            self._send_json({"success": False, "error": "args 必须是 JSON 对象"}, 400)
            return
        try:
            record = _runtime_console.invoke(function_id, args)
            self._send_json({"success": True, "record": record, "status": _runtime_console.status()})
        except Exception as exc:
            self._send_json({"success": False, "error": str(exc), "status": _runtime_console.status()}, 502)

    def _handle_vibe_run_vm(self):
        body = self._read_body()
        program = body.get("program", body)
        if not isinstance(program, dict):
            self._send_json({"success": False, "error": "program 必须是 JSON 对象"}, 400)
            return
        try:
            result = _runtime_console.run_vm(program)
            self._send_json({"success": result.get("status") == "passed", "result": result, "status": _runtime_console.status()})
        except Exception as exc:
            self._send_json({"success": False, "error": str(exc), "status": _runtime_console.status()}, 502)

    def _handle_vibe_step(self):
        body = self._read_body()
        try:
            loops = int(body.get("loops", 1))
            if loops < 1 or loops > 10000:
                raise ValueError("loops 必须在 1..10000")
            result = _runtime_console.step(loops)
            self._send_json({"success": result.get("error_code") == "OK", "result": result, "status": _runtime_console.status()})
        except Exception as exc:
            self._send_json({"success": False, "error": str(exc), "status": _runtime_console.status()}, 400)

    def _build_revolution_launch_args(self, body):
        """Build an explicit map-plus-faction request for the owned package."""
        map_name = body.get("mapName", "")
        faction = body.get("faction", "")
        commander = body.get("commander", "")
        if not faction and commander.startswith("RevolutionOverdrive"):
            faction = commander.removeprefix("RevolutionOverdrive")
        valid_maps = {entry["id"] for entry in load_revolution_maps()}
        valid_factions = {
            entry["faction"] for entry in load_revolution_commanders()
        }
        if map_name not in valid_maps:
            self._send_json({"success": False, "error": f"未知起义狂潮地图: {map_name}"}, 400)
            return None
        if faction not in valid_factions:
            self._send_json({"success": False, "error": f"未知起义狂潮阵营: {faction}"}, 400)
            return None
        if not REVOLUTION_LAUNCH_SCRIPT.exists():
            self._send_json({"success": False, "error": f"启动脚本不存在: {REVOLUTION_LAUNCH_SCRIPT}"}, 500)
            return None

        listen_port = int(body.get("listenPort", 0) or 0)
        # launcher 脚本内部已设置 [Console]::OutputEncoding = UTF8，
        # 直接用 -File 方式调用（-Command + & 方式在 PS 5.x 下不正确处理 UTF-8 BOM）。
        args = [
            _resolve_powershell_executable(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REVOLUTION_LAUNCH_SCRIPT),
            "-MapName",
            map_name,
            "-Faction",
            faction,
        ]
        if listen_port > 0:
            args.extend(["-ListenPort", str(listen_port)])
        if os.environ.get("CMRE_WEBUI_DRY_RUN"):
            args.append("-NoLaunch")
        return {
            "kind": "revolution-overdrive",
            "args": args,
            "commander": commander or f"RevolutionOverdrive{faction}",
            "faction": faction,
            "map_name": map_name,
            "listen_port": listen_port,
        }

    def _build_launch_args(self, body):
        """从请求 body 解析参数、校验并构建 launcher 命令行参数。

        成功返回 dict: {args, mode, capped, api_minimal, enable_buff_patch,
                        buffs, masteries, listen_port, commander}；
        失败时发送错误 JSON 响应并返回 None。
        """
        if body.get("packageId") == "revolution-overdrive":
            return self._build_revolution_launch_args(body)

        commander = body.get("commander", "TerranAlenger3")
        map_name = body.get("mapName", "亡者之夜.SC2Map")
        mode = int(body.get("mode", 1))
        difficulty_base = int(body.get("difficultyBase", 0))
        difficulty_plus = int(body.get("difficultyPlus", 0))
        enemy = body.get("enemy", "")
        raw_mutators = body.get("mutators", []) or []
        extra_mods = body.get("extraMods", []) or []
        voice_pack = body.get("voicePack", "")
        # API 模式（SC2API 校准）：listenPort > 0 时 launcher 用 -ListenPort 启动 SC2，
        # SC2 加载地图 + 开 API 端口，galaxy 触发器（CMUIX_ReadyBeginCountdown）自动执行
        # 让 SC2 进入 in_game。客户端用 --skip-create 连接已加载的游戏。
        listen_port = int(body.get("listenPort", 0) or 0)
        # ApiMinimal: 跳过 commander UI/setup 但调用 libCOOC_gf_CC_CustomStartupLaunch()
        # 推进 SC2 从 Launched → in_game。用于 CMRE Coop 地图在 API 模式下避免 UI 阻塞。
        api_minimal = bool(body.get("apiMinimal", False))
        # 重生虫心指挥官：WebUI 透传 enableReborn + rebornCommander，
        # launcher 据此追加 -EnableReborn -RebornCommander <Name> 加载 5 个 Reborn mod 并应用
        # K5Kerrigan 替换逻辑。commander 形如 "ZergAbathur"，rebornCommander 为 "Abathur"。
        enable_reborn = bool(body.get("enableReborn", False))
        reborn_commander = body.get("rebornCommander", "") or ""
        # Buff 补丁：仅对原版 18 指挥官生效。
        enable_buff_patch = bool(body.get("enableBuffPatch", False))
        raw_buffs = body.get("buffs", []) or []
        raw_masteries = body.get("masteries", []) or []
        raw_extras = body.get("buffExtras", {}) or {}
        # 仅原版指挥官允许启用 Buff 补丁
        if enable_buff_patch and commander not in OFFICIAL_BUFF_COMMANDERS:
            self._send_json(
                {"success": False, "error": f"Buff 补丁仅支持原版 18 指挥官，当前: {commander}"},
                400,
            )
            return None
        # 校验 buffs
        valid_buff_tokens = {"P1", "P2", "P3"}
        buffs = [b for b in raw_buffs if b in valid_buff_tokens] if raw_buffs else []
        if enable_buff_patch and not buffs:
            self._send_json(
                {"success": False, "error": "启用 Buff 补丁时至少需要选择一个威望优点 (P1/P2/P3)"},
                400,
            )
            return None
        # 校验 masteries（0..30 整数，最多 6 个）
        masteries = []
        for v in raw_masteries[:6]:
            try:
                iv = int(v)
                if iv < 0 or iv > 30:
                    raise ValueError
                masteries.append(iv)
            except (TypeError, ValueError):
                self._send_json(
                    {"success": False, "error": f"精通点数必须为 0..30 整数: {v}"},
                    400,
                )
                return None
        # 校验/编码 extras：每个 P 槽位的 extra index 列表 → 3 个 bitmask 整数
        extra_masks = {"P1": 0, "P2": 0, "P3": 0}
        for key in ("P1", "P2", "P3"):
            idxs = raw_extras.get(key, []) if isinstance(raw_extras, dict) else []
            if not isinstance(idxs, list):
                idxs = []
            mask = 0
            for idx in idxs:
                try:
                    i = int(idx)
                    if 0 <= i <= 30:
                        mask |= (1 << i)
                except (TypeError, ValueError):
                    pass
            extra_masks[key] = mask

        try:
            mutators, capped = normalize_mutators(raw_mutators)
        except ValueError as exc:
            self._send_json({"success": False, "error": str(exc)}, 400)
            return None

        if not isinstance(voice_pack, str):
            self._send_json({"success": False, "error": "voicePack 必须是字符串"}, 400)
            return None
        valid_voice_pack_ids = {voice["id"] for voice in load_voice_packs()}
        if voice_pack and voice_pack not in valid_voice_pack_ids:
            self._send_json({"success": False, "error": f"不支持的 CMRE 语音包: {voice_pack}"}, 400)
            return None

        # 因子生效关键修复（"选择的因子无效"根因）：
        # CMRE 仅在 Mode=2 (MutatorChallenges) 或 Mode=1 (Standard) 且 Brutal+ > 0 时
        # 才会读取银行中的 Mutator|N|Id 并启用对应因子。若用户勾选了因子但当前处于
        # 标准模式且残酷+=0（UI 默认状态）会忽略普通因子数组。
        # 自定义模式会读取 Chaos|N|Id，因此必须保留 Mode=3。
        if mutators:
            if mode == 1 and difficulty_plus == 0:
                mode = 2

        if not LAUNCH_SCRIPT.exists():
            self._send_json(
                {"success": False, "error": f"启动脚本不存在: {LAUNCH_SCRIPT}"}, 500
            )
            return None

        # 模式 3 使用 CMRE 的 Chaos 队列，不支持 Enhanced；其他模式使用普通因子数组。
        mutator_str = ",".join(
            f"{m['id']}:enhanced" if m["enhanced"] else m["id"] for m in mutators
        )
        chaos_mutator_str = ",".join(m["id"] for m in mutators) if mode == 3 else ""

        ps_exe = _resolve_powershell_executable()
        # launcher 脚本内部已设置 [Console]::OutputEncoding = UTF8，
        # 因此直接用 -File 方式调用（-Command + & 方式在 PS 5.x 下不正确处理 UTF-8 BOM）。
        args = [
            ps_exe,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(LAUNCH_SCRIPT),
            "-MapName",
            map_name,
            "-Commander",
            commander,
            "-LegacyRootOverride",
            LEGACY_ROOT,
            "-Mode",
            str(mode),
            "-DifficultyBase",
            str(difficulty_base),
            "-DifficultyPlus",
            str(difficulty_plus),
        ]
        if enemy:
            args.extend(["-Enemy", enemy])
        if mutator_str and mode != 3:
            args.extend(["-Mutators", mutator_str])
        if chaos_mutator_str:
            args.extend(["-ChaosMutators", chaos_mutator_str])
        if voice_pack:
            args.extend(["-VoicePack", voice_pack])
        if extra_mods:
            extra_str = ",".join(m for m in extra_mods if m)
            if extra_str:
                args.extend(["-ExtraMods", extra_str])
        if listen_port > 0:
            args.extend(["-ListenPort", str(listen_port)])
        if api_minimal:
            args.append("-ApiMinimal")
        # 重生虫心参数透传：launcher 据此加载 5 个 Reborn mod 包并应用 K5Kerrigan 替换逻辑。
        # reborn_commander 必须是 reborn-commanders.json 中的 id（如 "Abathur"）。
        if enable_reborn and reborn_commander:
            args.append("-EnableReborn")
            args.extend(["-RebornCommander", reborn_commander])
        # Buff 补丁参数透传：launcher 据此写 bank 字段，galaxy 端读取后应用。
        if enable_buff_patch:
            args.append("-EnableBuffPatch")
            args.extend(["-Buffs", ",".join(buffs)])
            if masteries:
                args.extend(["-Masteries", ",".join(str(v) for v in masteries)])
            # Extra 子选项：三个 P 槽位各一个 bitmask（逗号分隔：P1mask,P2mask,P3mask）
            extras_str = f"{extra_masks['P1']},{extra_masks['P2']},{extra_masks['P3']}"
            args.extend(["-BuffExtras", extras_str])

        # WebUI 启动 = 玩家模式：launcher 不会清理已有 SC2 进程，
        # 若 SC2 已在运行则报错退出，避免误杀玩家正在进行的游戏。
        # AI 调试脚本（run-cmre-sc2api.ps1）应使用 -DebugMode 而非 WebUI。
        args.append("-PlayerMode")

        # 测试/CI 用：设置 CMRE_WEBUI_DRY_RUN 时追加 -NoLaunch，
        # 只暂存地图 + 写银行、不启动 SC2。正常启动不受影响。
        if os.environ.get("CMRE_WEBUI_DRY_RUN"):
            args.append("-NoLaunch")

        return {
            "kind": "cmre",
            "args": args,
            "mode": mode,
            "capped": capped,
            "api_minimal": api_minimal,
            "enable_buff_patch": enable_buff_patch,
            "buffs": buffs,
            "masteries": masteries,
            "listen_port": listen_port,
            "commander": commander,
        }

    def _handle_revolution_launch(self, ctx):
        """Synchronously run the owned-package launcher for compatibility with /api/launch."""
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.Popen(
                ctx["args"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", creationflags=creationflags,
            )
            stdout, stderr = proc.communicate(timeout=720)
        except subprocess.TimeoutExpired:
            proc.kill()
            self._send_json({"success": False, "error": "起义狂潮启动脚本超时（720s）"}, 504)
            return
        except Exception as exc:
            self._send_json({"success": False, "error": str(exc)}, 500)
            return
        if proc.returncode != 0:
            self._send_json({
                "success": False,
                "error": f"起义狂潮启动脚本退出码 {proc.returncode}",
                "output": stdout[-800:] if stdout else "",
                "stderr": stderr[-800:] if stderr else "",
            }, 500)
            return
        self._send_json({
            "success": True,
            "message": "起义狂潮已启动" if not os.environ.get("CMRE_WEBUI_DRY_RUN") else "起义狂潮已完成 staging",
            "packageId": "revolution-overdrive",
            "faction": ctx["faction"],
            "mapName": ctx["map_name"],
            "listenPort": ctx["listen_port"] or None,
            "output": stdout[-800:] if stdout else "",
            "debug_args": ctx["args"],
        })

    def _handle_launch(self):
        """同步启动 launcher（阻塞等待完成）。保留兼容旧前端。"""
        body = self._read_body()
        ctx = self._build_launch_args(body)
        if ctx is None:
            return
        _force_stop_current_game()
        if ctx.get("kind") == "revolution-overdrive":
            self._handle_revolution_launch(ctx)
            return
        args = ctx["args"]
        mode = ctx["mode"]
        capped = ctx["capped"]
        api_minimal = ctx["api_minimal"]
        enable_buff_patch = ctx["enable_buff_patch"]
        buffs = ctx["buffs"]
        masteries = ctx["masteries"]
        listen_port = ctx["listen_port"]

        # CREATE_NO_WINDOW: 避免 PowerShell 控制台窗口弹出干扰玩家。
        # 仅 Windows 平台有此标志。
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                # PowerShell 7 emits UTF-8. Decoding it as GBK masked launcher
                # diagnostics and made the real-launch test fail while printing them.
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
            # 等待上限须大于 wait-for-game-ready.ps1 的 MaxWaitSeconds(600)，
            # 否则 SC2 正常加载（~340s+20s grace）时会被误判超时。
            stdout, stderr = proc.communicate(timeout=720)

            if proc.returncode == 0:
                result = {
                    "success": True,
                    "message": "SC2 已启动",
                    "effectiveMode": mode,
                    "mutatorsCapped": capped,
                    "output": stdout[-800:] if stdout else "",
                    "debug_args": args,
                    "debug_api_minimal": api_minimal,
                    "debug_buff_patch": {
                        "enabled": enable_buff_patch,
                        "buffs": buffs if enable_buff_patch else [],
                        "masteries": masteries if enable_buff_patch and masteries else [],
                    },
                    "debug_stdout_full": stdout if stdout else "",
                }
                if listen_port > 0:
                    result["listenPort"] = listen_port
                    result["apiReady"] = True
                    result["message"] = f"SC2 API 已就绪 (127.0.0.1:{listen_port})，可用 --skip-create 连接"
                self._send_json(result)
            else:
                self._send_json(
                    {
                        "success": False,
                        "error": f"启动脚本退出码 {proc.returncode}",
                        "output": stdout[-800:] if stdout else "",
                        "stderr": stderr[-800:] if stderr else "",
                    },
                    500,
                )
        except subprocess.TimeoutExpired:
            proc.kill()
            self._send_json({"success": False, "error": "启动脚本超时（720s）"}, 504)
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, 500)

    def _handle_launch_async(self):
        """异步启动 launcher（不阻塞），日志通过 SSE 实时推送。"""
        global _launcher_process
        body = self._read_body()

        ctx = self._build_launch_args(body)
        if ctx is None:
            return
        _force_stop_current_game()
        args = ctx["args"]
        commander = ctx["commander"]

        # CREATE_NO_WINDOW: 避免 PowerShell 控制台窗口弹出干扰玩家。
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
                bufsize=1,
            )
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, 500)
            return

        with _launcher_lock:
            _launcher_process = proc

        _append_log(f"[webui] 异步启动 launcher, pid={proc.pid}, commander={commander}")
        _append_log(f"[webui] args: {' '.join(args)}")

        # 启动 daemon 线程读取 stdout / stderr；等待线程会先 join reader，
        # 确保失败原因已经进入 SSE 队列后才发送 launcher exit 行。
        output_tail = {
            "stdout": deque(maxlen=80),
            "stderr": deque(maxlen=80),
        }
        tail_lock = threading.Lock()
        stdout_reader = threading.Thread(
            target=_read_pipe,
            args=(proc.stdout, ""),
            kwargs={"output_tail": output_tail, "tail_lock": tail_lock, "stream_name": "stdout"},
            daemon=True,
        )
        stderr_reader = threading.Thread(
            target=_read_pipe,
            args=(proc.stderr, "[stderr] "),
            kwargs={"output_tail": output_tail, "tail_lock": tail_lock, "stream_name": "stderr"},
            daemon=True,
        )
        stdout_reader.start()
        stderr_reader.start()
        # 启动 daemon 线程等待进程结束并记录退出码
        threading.Thread(
            target=_wait_for_process,
            args=(proc, [stdout_reader, stderr_reader], output_tail, tail_lock),
            daemon=True,
        ).start()

        self._send_json({
            "success": True,
            "message": "SC2 启动中...",
            "pid": proc.pid,
        })

    def _handle_logs_stream(self):
        """SSE 日志流：先发送历史日志，再实时推送新日志行。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        q = queue.Queue(maxsize=1000)
        with _log_lock:
            # 先发送最近 200 行历史日志
            for line in _log_lines[-200:]:
                try:
                    self.wfile.write(f"data: {line}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
            _log_subscribers.append(q)

        try:
            while True:
                try:
                    line = q.get(timeout=15)
                    self.wfile.write(f"data: {line}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    # 发送心跳保持连接
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _log_lock:
                if q in _log_subscribers:
                    _log_subscribers.remove(q)

    def _handle_stop(self):
        """停止正在运行的 launcher 进程。"""
        killed = _force_stop_current_game()
        self._send_json({"success": True, "message": "已停止", "killed": killed})

    def log_message(self, format, *args):
        sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")


def open_browser_delayed(url, delay=1.0):
    import time
    time.sleep(delay)
    webbrowser.open(url)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="CMRE 亡者之夜 WebUI 后端服务")
    parser.add_argument("--port", type=int, default=8767, help="监听端口")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), CmreWebUIHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"CMRE 亡者之夜 WebUI 服务已启动: {url}")
    print(f"WebUI 目录: {WEBUI_DIR}")
    print(f"Mutator 数据: {MUTATORS_JSON}")
    print(f"启动脚本: {LAUNCH_SCRIPT}")
    print("按 Ctrl+C 停止服务")

    if not args.no_browser:
        threading.Thread(target=open_browser_delayed, args=(url,), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.server_close()


if __name__ == "__main__":
    main()
