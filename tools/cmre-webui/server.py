#!/usr/bin/env python3
"""CMRE 亡者之夜 WebUI 后端服务

提供因子（Mode/Difficulty/Enemy/Mutators）选择界面和启动游戏的 HTTP API。
仅使用 Python 标准库，无第三方依赖。

用法:
    python server.py [--port 8767] [--host 127.0.0.1]
"""

import json
import os
import subprocess
import sys
import threading
import webbrowser
import xml.etree.ElementTree as ET
from http.server import HTTPServer, SimpleHTTPRequestHandler
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
LAUNCH_SCRIPT = Path(__file__).resolve().parents[1] / "launchers" / "launch-cmre-alenger.ps1"

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
    """将指挥官分类为 'official'（官方18个）或 'alenger'（起义狂潮自定义）。"""
    if bank_commander.startswith("Alenger"):
        return "alenger"
    return "official"


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
                def sort_key(c):
                    group_order = {"official": 0, "alenger": 1}
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
    return data


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
        if self.path == "/api/maps":
            self._send_json({"maps": load_maps()})
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
        self._send_json({"success": False, "error": "未知端点"}, 404)

    def _handle_launch(self):
        body = self._read_body()
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

        try:
            mutators, capped = normalize_mutators(raw_mutators)
        except ValueError as exc:
            self._send_json({"success": False, "error": str(exc)}, 400)
            return

        if not isinstance(voice_pack, str):
            self._send_json({"success": False, "error": "voicePack 必须是字符串"}, 400)
            return
        valid_voice_pack_ids = {voice["id"] for voice in load_voice_packs()}
        if voice_pack and voice_pack not in valid_voice_pack_ids:
            self._send_json({"success": False, "error": f"不支持的 CMRE 语音包: {voice_pack}"}, 400)
            return

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
            return

        # 模式 3 使用 CMRE 的 Chaos 队列，不支持 Enhanced；其他模式使用普通因子数组。
        mutator_str = ",".join(
            f"{m['id']}:enhanced" if m["enhanced"] else m["id"] for m in mutators
        )
        chaos_mutator_str = ",".join(m["id"] for m in mutators) if mode == 3 else ""

        args = [
            "powershell",
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

        # 测试/CI 用：设置 CMRE_WEBUI_DRY_RUN 时追加 -NoLaunch，
        # 只暂存地图 + 写银行、不启动 SC2。正常启动不受影响。
        if os.environ.get("CMRE_WEBUI_DRY_RUN"):
            args.append("-NoLaunch")

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

    server = HTTPServer((args.host, args.port), CmreWebUIHandler)
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
