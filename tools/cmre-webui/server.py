#!/usr/bin/env python3
"""CMRE / 斗蛐蛐 WebUI 后端服务

提供因子（Mode/Difficulty/Enemy/Mutators）选择界面和启动游戏的 HTTP API。
仅使用 Python 标准库，无第三方依赖。

用法:
    python server.py [--port 8767] [--host 127.0.0.1] [--dou-ququ-map <path>]
"""

import asyncio
import atexit
import base64
import csv
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import time
import threading
import uuid
import webbrowser
import xml.etree.ElementTree as ET
from collections import deque
from http.server import HTTPServer, ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WEBUI_DIR = SCRIPT_DIR / "webui"
DATA_DIR = SCRIPT_DIR / "data"
VIBE_PROJECT_ROOT = SCRIPT_DIR.parents[1] / "src" / "projects" / "cmre-porting" / "vibe"
if str(VIBE_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(VIBE_PROJECT_ROOT))

from map_commander_adapter import load_adapter_config, resolve_adapter  # noqa: E402
from map_event_extractor import MapEventExtractor  # noqa: E402
from galaxy_script_lab import USER_FUNCTION_ID, USER_SCRIPT_NAME, read_source, source_sha256, validate_source  # noqa: E402
MUTATORS_JSON = DATA_DIR / "mutators.json"
# DDS → PNG 转换缓存目录。首次请求某 DDS 时转 PNG 存这里，后续直接返回。
ASSETS_CACHE_DIR = WEBUI_DIR / "assets_cache"
# 官方地图加载画面转换缓存。生成缓存放到阶段 artifacts，不写回外部地图包。
MAP_PREVIEW_CACHE_DIR = (
    SCRIPT_DIR.parents[1]
    / "artifacts"
    / "projects"
    / "cmre-porting"
    / "stage26-full-function-invoke"
    / "runtime"
    / "webui-map-preview-cache"
)
# Official wide mission/loading art extracted from the local SC2 CASC store.
# The extraction manifest and files live in stage artifacts; source maps remain read-only.
MAP_PREVIEW_ASSET_ROOT = (
    SCRIPT_DIR.parents[1]
    / "artifacts"
    / "projects"
    / "cmre-porting"
    / "stage26-full-function-invoke"
    / "runtime"
    / "map-preview-assets"
)
# 预导出的真实图标缓存（从起义狂潮 web-launcher 复制过来）
ASSETS_CACHE_COMMANDERS = WEBUI_DIR / "assets-cache" / "commanders"
ASSETS_CACHE_MUTATORS = WEBUI_DIR / "assets-cache" / "mutators"
# 配置目录：sc2-porting-workspace/src/config/alenger-mods.json
CONFIG_DIR = SCRIPT_DIR.parents[1] / "src" / "config"
ALENGER_MODS_JSON = CONFIG_DIR / "alenger-mods.json"
REBORN_COMMANDERS_JSON = CONFIG_DIR / "reborn-commanders.json"
LOCAL_SOURCES_JSON = CONFIG_DIR / "local.sources.json"
LAUNCH_SCRIPT = Path(__file__).resolve().parents[1] / "launchers" / "launch-cmre-alenger.ps1"
REPO_ROOT = SCRIPT_DIR.parents[1]
SC2_RUNTIME_LEASE_PATH = REPO_ROOT / "artifacts" / "runtime" / "sc2-runtime-lease.json"
# This is written only by /api/launch-async. It lets a later WebUI request
# distinguish its own detached player session from an unrelated launcher run.
WEBUI_SESSION_LEASE_PATH = REPO_ROOT / "artifacts" / "runtime" / "cmre-webui-session.json"
REVOLUTION_PACKAGE_ROOT = REPO_ROOT / "src" / "projects" / "revolution-overdrive-porting" / "packages"
REVOLUTION_COMMANDER_JSON = REVOLUTION_PACKAGE_ROOT / "Commander" / "revolution-overdrive-commander.json"
REVOLUTION_MAPS_JSON = REVOLUTION_PACKAGE_ROOT / "maps.json"
REVOLUTION_MAPS_ROOT = REVOLUTION_PACKAGE_ROOT / "Maps"
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
COMMANDER_PACKAGE_MODS_DIR = REPO_ROOT / "src" / "projects" / "cmre-porting" / "packages" / "Mods" / "Commanders"
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

# Optional user-owned map input.  The archive/directory is read-only; archives
# are extracted into artifacts before the approved launcher stages its live map.
DOU_QUQU_MAP_SOURCE: Path | None = None
DOU_QUQU_EXTRACTED_SOURCE: Path | None = None
DOU_QUQU_ARTIFACT_ROOT = (
    REPO_ROOT
    / "artifacts"
    / "projects"
    / "cmre-porting"
    / "stage27-dou-ququ-behavior-plugin"
    / "runtime"
    / "webui-map-source"
)
DOU_QUQU_EXTRACTOR = REPO_ROOT / "tools" / "mpq" / "scripts" / "extract_mpq.py"
DOU_QUQU_RUNTIME_PACKED_MAP = (
    DOU_QUQU_ARTIFACT_ROOT.parent / "dou-ququ-runtime-vm.packed.SC2Map"
)
DOU_QUQU_RUNTIME_CALL_LOG = DOU_QUQU_ARTIFACT_ROOT.parent / "douququ-runtime-vm-call-log.jsonl"
DOU_QUQU_RUNTIME_EVENT_LOG = DOU_QUQU_ARTIFACT_ROOT.parent / "douququ-runtime-event-log.jsonl"
DOU_QUQU_USER_SCRIPT_TEMPLATE = (
    REPO_ROOT / "tools" / "launchers" / "overlays" / "cmre-alenger" / "startup" / USER_SCRIPT_NAME
)
DOU_QUQU_USER_SCRIPT_ARTIFACT = DOU_QUQU_ARTIFACT_ROOT.parent / "galaxy-user-script" / USER_SCRIPT_NAME
DOU_QUQU_USER_SCRIPT_STAGE_ROOT = DOU_QUQU_ARTIFACT_ROOT.parent / "galaxy-user-script-stage"
DOU_QUQU_PACK_SCRIPT = REPO_ROOT / "tools" / "mpq" / "scripts" / "pack-sc2map.ps1"
MAP_ADAPTER_CONFIG = VIBE_PROJECT_ROOT / "map_commander_adapters.json"
REVOLUTION_MAP_ADAPTER_CONFIG = (
    REPO_ROOT
    / "src"
    / "projects"
    / "revolution-overdrive-porting"
    / "vibe"
    / "map_commander_adapters.json"
)
_MAP_DETAIL_CACHE: dict[tuple[str, str], tuple[tuple[int, int], dict]] = {}


def parse_runtime_event_bank(path: Path) -> dict:
    """Read the append-only GalaxyVibeEvents bank without mutating it."""
    path = Path(path)
    if not path.is_file():
        return {"path": str(path), "event_session": "", "events": []}
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return {"path": str(path), "event_session": "", "events": [], "parse_error": True}
    sections: dict[str, dict[str, object]] = {}
    for section in root.findall("./Section"):
        section_name = section.get("name", "")
        values: dict[str, object] = {}
        for key in section.findall("./Key"):
            key_name = key.get("name", "")
            value = key.find("./Value")
            if not key_name or value is None:
                continue
            if "int" in value.attrib:
                raw_value: object = value.attrib["int"]
                try:
                    raw_value = int(raw_value)
                except ValueError:
                    pass
            elif "string" in value.attrib:
                raw_value = value.attrib["string"]
            elif "text" in value.attrib:
                raw_value = value.attrib["text"]
            elif "flag" in value.attrib:
                raw_value = value.attrib["flag"] == "1"
            else:
                continue
            values[key_name] = raw_value
        sections[section_name] = values
    index = sections.get("index", {})
    event_values = sections.get("events", {})
    events = []
    for event_id, raw_event in event_values.items():
        if not isinstance(raw_event, str):
            continue
        try:
            event = json.loads(raw_event)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        try:
            numeric_id = int(event.get("eventId", event_id))
        except (TypeError, ValueError):
            continue
        event["eventId"] = numeric_id
        events.append(event)
    events.sort(key=lambda item: int(item.get("eventId", 0)))
    return {
        "path": str(path),
        "event_session": str(index.get("event_session", "") or ""),
        "events": events,
        "last_event_id": max((int(item.get("eventId", 0)) for item in events), default=0),
    }


def _dou_ququ_map_root() -> Path | None:
    """Return an unpacked, artifacts-only 斗蛐蛐 source for the launcher."""
    global DOU_QUQU_EXTRACTED_SOURCE
    source = DOU_QUQU_MAP_SOURCE
    if source is None:
        return None
    source = source.resolve()
    if source.is_dir():
        if (source / "MapScript.galaxy").is_file():
            return source
        nested = [
            child for child in source.iterdir()
            if child.is_dir() and child.name.casefold().endswith(".sc2map")
            and (child / "MapScript.galaxy").is_file()
        ]
        if len(nested) == 1:
            return nested[0]
        raise RuntimeError(f"斗蛐蛐地图目录缺少 MapScript.galaxy: {source}")
    if source.suffix.casefold() != ".sc2map" or not source.is_file():
        raise RuntimeError(f"斗蛐蛐地图必须是 .SC2Map 或解包目录: {source}")
    target = DOU_QUQU_ARTIFACT_ROOT / "extracted" / source.stem
    if not (target / "MapScript.galaxy").is_file():
        if not DOU_QUQU_EXTRACTOR.is_file():
            raise RuntimeError(f"地图解包工具不存在: {DOU_QUQU_EXTRACTOR}")
        target.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [sys.executable, str(DOU_QUQU_EXTRACTOR), str(source), str(target), "*"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0 or not (target / "MapScript.galaxy").is_file():
            detail = (completed.stdout + "\n" + completed.stderr).strip()[-2000:]
            raise RuntimeError(f"斗蛐蛐地图解包失败 (exit={completed.returncode}): {detail}")
    DOU_QUQU_EXTRACTED_SOURCE = target
    return target


def _repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path)


def _galaxy_user_script_payload() -> dict:
    source_path = DOU_QUQU_USER_SCRIPT_ARTIFACT if DOU_QUQU_USER_SCRIPT_ARTIFACT.is_file() else DOU_QUQU_USER_SCRIPT_TEMPLATE
    source = read_source(source_path)
    validation = validate_source(source)
    stage_manifest = DOU_QUQU_USER_SCRIPT_STAGE_ROOT / "galaxy-script-stage.json"
    staged = None
    if stage_manifest.is_file():
        try:
            staged = json.loads(stage_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            staged = None
    return {
        "schema_version": "douququ-galaxy-script.v1",
        "function_id": USER_FUNCTION_ID,
        "file_name": USER_SCRIPT_NAME,
        "source": source,
        "source_path": _repo_relative(source_path),
        "source_sha256": source_sha256(source),
        "validation": validation,
        "staged": staged,
        "compile_boundary": "next_sc2_map_load",
    }


def _save_galaxy_user_script(source: str) -> dict:
    validation = validate_source(source)
    if not validation["valid"]:
        return {"saved": False, "validation": validation}
    DOU_QUQU_USER_SCRIPT_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    DOU_QUQU_USER_SCRIPT_ARTIFACT.write_text(source, encoding="utf-8", newline="\n")
    return {
        "saved": True,
        "path": _repo_relative(DOU_QUQU_USER_SCRIPT_ARTIFACT),
        "validation": validation,
    }


def _stage_galaxy_user_script(source: str) -> dict:
    saved = _save_galaxy_user_script(source)
    if not saved["saved"]:
        return saved
    map_root = _dou_ququ_map_root()
    if map_root is None:
        raise RuntimeError("未绑定斗蛐蛐地图；请先用 -DouQuquMap 指定用户地图")
    from stage_map_vm_runtime import DEFAULT_DISPATCH, DEFAULT_DOU_QUQU_ROOT, DEFAULT_KERNEL_ROOT, stage_map

    digest = saved["validation"]["sha256"][:12]
    staged_dir = DOU_QUQU_USER_SCRIPT_STAGE_ROOT / f"staged-{digest}"
    packed_map = DOU_QUQU_USER_SCRIPT_STAGE_ROOT / f"dou-ququ-user-{digest}.packed.SC2Map"
    stage_result = stage_map(
        map_root,
        staged_dir,
        DEFAULT_KERNEL_ROOT,
        DEFAULT_DISPATCH,
        replace=True,
        dou_ququ_root=DEFAULT_DOU_QUQU_ROOT,
        enable_dou_ququ_runtime=True,
        user_galaxy_source=DOU_QUQU_USER_SCRIPT_ARTIFACT,
    )
    ps_exe = _resolve_powershell_executable()
    completed = subprocess.run(
        [
            ps_exe,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(DOU_QUQU_PACK_SCRIPT),
            str(staged_dir),
            str(packed_map),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0 or not packed_map.is_file():
        detail = (completed.stdout + "\n" + completed.stderr).strip()[-2000:]
        raise RuntimeError(f"斗蛐蛐 Galaxy 源码打包失败 (exit={completed.returncode}): {detail}")
    result = {
        "schema_version": "douququ-galaxy-script-stage.v1",
        "status": "staged_pending_reload",
        "function_id": USER_FUNCTION_ID,
        "source": _repo_relative(DOU_QUQU_USER_SCRIPT_ARTIFACT),
        "source_sha256": saved["validation"]["sha256"],
        "staged_directory": _repo_relative(staged_dir),
        "packed_map": _repo_relative(packed_map),
        "manifest": _repo_relative(Path(stage_result["manifest"])),
        "compile_boundary": "next_sc2_map_load",
        "restart_required": True,
        "validation": saved["validation"],
        "pack_output": (completed.stdout or "").strip()[-1200:],
    }
    DOU_QUQU_USER_SCRIPT_STAGE_ROOT.mkdir(parents=True, exist_ok=True)
    (DOU_QUQU_USER_SCRIPT_STAGE_ROOT / "galaxy-script-stage.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def _resolve_map_detail_source(map_name: str, package_id: str) -> tuple[Path, Path]:
    """Resolve a registered map to a read-only source directory and root."""

    if package_id == "cmre":
        source_root = MAPS_CMRE_DIR.parent
        source = MAPS_CMRE_DIR / map_name
    elif package_id == "reborn":
        source_root = _load_local_source_binding("reborn-hots-071")
        if not source_root:
            raise FileNotFoundError("重生虫心地图源未绑定")
        source = source_root / map_name
    elif package_id == "revolution-overdrive":
        source_root = REVOLUTION_MAPS_ROOT.parent
        source = REVOLUTION_MAPS_ROOT / map_name
    elif package_id == "dou-ququ":
        source = _dou_ququ_map_root()
        if source is None:
            raise FileNotFoundError("斗蛐蛐地图未绑定")
        source_root = source.parent
    else:
        raise ValueError(f"未知地图类别: {package_id}")
    source = source.resolve()
    source_root = source_root.resolve()
    try:
        source.relative_to(source_root)
    except ValueError as exc:
        raise ValueError("地图路径不在登记的地图源目录内") from exc
    if not source.is_dir():
        raise FileNotFoundError(f"地图源不存在: {package_id}/{map_name}")
    return source, source_root


def _map_detail_stamp(source: Path) -> tuple[int, int]:
    paths = [source / name for name in ("MapScript.galaxy", "Objects", "Regions")]
    stamp = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            stamp.append((0, 0))
        else:
            stamp.append((stat.st_mtime_ns, stat.st_size))
    return (max(item[0] for item in stamp), sum(item[1] for item in stamp))


def _map_detail_localization_roots(source: Path) -> list[Path]:
    roots = [source, SC2VIBE_ROOT / "cmre-runtime", REPO_ROOT / "reference" / "sc2mapster" / "SC2GameData"]
    if source.name.endswith(".SC2Map") and source.parent.name.lower() == "maps":
        bound = _load_local_source_binding("cmre-dev-package")
        if bound:
            roots.append(bound)
    return roots


def load_map_details(map_name: str, package_id: str = "cmre", commander_id: str = "TerranAlenger3") -> dict:
    """Return traceable static map details for the WebUI detail pane."""

    map_name = _canonical_map_detail_name(map_name, package_id)
    source, source_root = _resolve_map_detail_source(map_name, package_id)
    cache_key = (package_id, source.as_posix())
    stamp = _map_detail_stamp(source)
    cached = _MAP_DETAIL_CACHE.get(cache_key)
    if cached and cached[0] == stamp:
        extracted = cached[1]
    else:
        extracted = MapEventExtractor(
            source,
            source_root=source_root,
            localization_roots=_map_detail_localization_roots(source),
        ).extract()
        _MAP_DETAIL_CACHE[cache_key] = (stamp, extracted)

    adapter_config = (
        REVOLUTION_MAP_ADAPTER_CONFIG
        if package_id == "revolution-overdrive"
        else MAP_ADAPTER_CONFIG
    )
    try:
        adapter = resolve_adapter(
            load_adapter_config(adapter_config),
            map_name=map_name,
            commander_id=commander_id or "TerranAlenger3",
        )
        adapter.setdefault("evidence", {})["config"] = _repo_relative(adapter_config)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        adapter = {"error": f"适配层未加载: {exc}"}

    timeline = [
        {**item, "record_type": "unit_event"}
        for item in extracted.get("events", [])
    ] + [
        {**item, "record_type": "timing"}
        for item in extracted.get("timings", [])
    ]
    timeline.sort(key=lambda item: (item.get("line") is None, item.get("line") or 0))
    map_record = next(
        (
            item
            for item in load_maps() + load_reborn_maps() + load_revolution_maps()
            if item.get("id") == map_name and item.get("packageId") == package_id
        ),
        {"id": map_name, "name": extracted.get("map_metadata", {}).get("name_zh", map_name)},
    )
    return {
        "schema_version": "cmre-map-details.v1",
        "evidence_type": "static",
        "runtime_claim": "none; details are static source analysis",
        "map": {
            "id": map_name,
            "packageId": package_id,
            "name": map_record.get("name", map_name),
            "sourcePath": extracted.get("map_path", source.name),
            "metadata": extracted.get("map_metadata", {}),
        },
        "summary": extracted.get("summary", {}),
        "preplaced": extracted.get("preplaced", []),
        "events": extracted.get("events", []),
        "timings": extracted.get("timings", []),
        "timeline": timeline,
        "regions": extracted.get("regions", []),
        "eventDeclarations": extracted.get("event_declarations", []),
        "unitCatalog": extracted.get("unit_catalog", []),
        "adapter": adapter,
    }


def _resolve_powershell_executable() -> str:
    """Use the PowerShell host required by the launcher on Windows."""
    for candidate in ("pwsh", "powershell"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return "pwsh"


def _startup_contract_candidates() -> list[Path]:
    """Return current-stage and legacy startup-contract artifacts in priority order."""
    artifacts_root = REPO_ROOT / "artifacts" / "projects" / "cmre-porting"
    candidates: list[Path] = []
    project_path = REPO_ROOT / "src" / "projects" / "cmre-porting" / "project.json"
    try:
        project = json.loads(project_path.read_text(encoding="utf-8-sig"))
        current_stage = str(project.get("currentStage", "")).strip()
    except (OSError, json.JSONDecodeError):
        current_stage = ""
    if current_stage:
        stage_names = [current_stage]
        stage_number = re.match(r"^(\d+)-", current_stage)
        if stage_number:
            stage_names.insert(0, f"stage{stage_number.group(1)}-{current_stage[stage_number.end():]}")
        for stage_name in stage_names:
            stage_root = artifacts_root / stage_name
            candidates.append(stage_root / "map-startup-contract.json")
            if stage_root.is_dir():
                contract_files = sorted(
                    stage_root.rglob("*startup-contract*.json"),
                    key=lambda path: (path.name.endswith(".full.json"), str(path)),
                )
                candidates.extend(contract_files)
    # Stage 26 remains the fallback for the original CMRE map set.
    candidates.append(artifacts_root / "stage26-full-function-invoke" / "map-startup-contract.json")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _find_startup_contract(map_name: str) -> Path | None:
    """Find the first readable contract that explicitly contains ``map_name``."""
    for candidate in _startup_contract_candidates():
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        maps = payload.get("maps", []) if isinstance(payload, dict) else []
        if isinstance(maps, list) and any(
            isinstance(record, dict) and record.get("map") == map_name for record in maps
        ):
            return candidate.resolve()
    return None

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

# 地图显示名必须显式登记，内部 id 只用于启动器和预设传输，不能直接展示给用户。
# 虫心和起义狂潮使用系列前缀，避免与 CMRE 或彼此之间的同名任务混淆。
MAP_DISPLAY_NAMES = {
    "cmre": {
        "黑暗杀星.SC2Map": "黑暗杀星",
        "机会渺茫.SC2Map": "机会渺茫",
        "净网行动.SC2Map": "净网行动",
        "聚铁成兵.SC2Map": "聚铁成兵",
        "克哈裂痕.SC2Map": "克哈裂痕",
        "熔火危机.SC2Map": "熔火危机",
        "升格之链.SC2Map": "升格之链",
        "死亡摇篮.SC2Map": "死亡摇篮",
        "天界封锁.SC2Map": "天界封锁",
        "亡者之夜.SC2Map": "亡者之夜",
        "往日神庙.SC2Map": "往日神庙",
        "虚空降临.SC2Map": "虚空降临",
        "虚空撕裂.SC2Map": "虚空撕裂",
        "湮灭快车.SC2Map": "湮灭快车",
        "营救矿工.SC2Map": "营救矿工",
    },
    "reborn": {
        "zchar01.SC2Map": "[虫心] 支配",
        "zchar02.SC2Map": "[虫心] 天火燎原",
        "zchar03.SC2Map": "[虫心] 老兵不死",
        "zexpedition01.SC2Map": "[虫心] 收割悲鸣",
        "zexpedition02.SC2Map": "[虫心] 杀死信使",
        "zexpedition03.SC2Map": "[虫心] 合相",
        "zhybrid01.SC2Map": "[虫心] 感染",
        "zhybrid02.SC2Map": "[虫心] 黑暗之手",
        "zhybrid03.SC2Map": "[虫心] 虚空魅影",
        "zkorhal01.SC2Map": "[虫心] 行星坠落",
        "zkorhal02.SC2Map": "[虫心] 死亡从天而降",
        "zkorhal03.SC2Map": "[虫心] 清算",
        "zlab01.SC2Map": "[虫心] 实验室老鼠",
        "zlab02.SC2Map": "[虫心] 重整旗鼓",
        "zlab03.SC2Map": "[虫心] 会合",
        "zspace01.SC2Map": "[虫心] 有这样的朋友……",
        "zspace02.SC2Map": "[虫心] 信念",
        "zzerus01.SC2Map": "[虫心] 唤醒远古",
        "zzerus02.SC2Map": "[虫心] 熔炉",
        "zzerus03.SC2Map": "[虫心] 至高",
    },
    "revolution-overdrive": {
        "tarcade.SC2Map": "[起义狂潮] 街机大厅",
        "thanson01.SC2Map": "[起义狂潮] 大撤离",
        "thanson02.SC2Map": "[起义狂潮] 大爆发",
        "thanson03a.SC2Map": "[起义狂潮] 拯救海文",
        "thanson03b.SC2Map": "[起义狂潮] 海文的陷落",
        "thorner01.SC2Map": "[起义狂潮] 火车大劫案",
        "thorner02.SC2Map": "[起义狂潮] 博弈",
        "thorner03.SC2Map": "[起义狂潮] 毁灭引擎",
        "thorner04.SC2Map": "[起义狂潮] 媒体轰炸",
        "thorner05s.SC2Map": "[起义狂潮] 揭露黑幕",
        "traynor01.SC2Map": "[起义狂潮] 自由日",
        "traynor02.SC2Map": "[起义狂潮] 不法之徒",
        "traynor03.SC2Map": "[起义狂潮] 零点行动",
        "tstory01.SC2Map": "[起义狂潮] 自由之翼",
        "ttosh01.SC2Map": "[起义狂潮] 恶魔游乐场",
        "ttosh02.SC2Map": "[起义狂潮] 欢迎来到丛林",
        "ttosh03a.SC2Map": "[起义狂潮] 营救",
        "ttosh03b.SC2Map": "[起义狂潮] 幽灵一击",
        "ttychus01.SC2Map": "[起义狂潮] 来之不易",
        "ttychus02.SC2Map": "[起义狂潮] 挖宝行动",
        "ttychus03.SC2Map": "[起义狂潮] 莫比斯代理人",
        "ttychus04.SC2Map": "[起义狂潮] 超新星",
        "ttychus05.SC2Map": "[起义狂潮] 虚空巨口",
        "tvalerian01.SC2Map": "[起义狂潮] 地狱之门",
        "tvalerian02a.SC2Map": "[起义狂潮] 野兽之腹",
        "tvalerian02b.SC2Map": "[起义狂潮] 天崩地坼",
        "tvalerian03.SC2Map": "[起义狂潮] 背水一战",
        "tzeratul01.SC2Map": "[起义狂潮] 末日密语",
        "tzeratul02.SC2Map": "[起义狂潮] 恶兆",
        "tzeratul03.SC2Map": "[起义狂潮] 未来回响",
        "tzeratul04.SC2Map": "[起义狂潮] 究极黑暗",
    },
}


def _map_display_name(map_id: str, package_id: str) -> str:
    """Return the explicit Chinese UI name; never expose a raw map filename."""
    try:
        return MAP_DISPLAY_NAMES[package_id][map_id]
    except KeyError as exc:
        raise RuntimeError(f"地图未登记中文显示名: {package_id}/{map_id}") from exc


def _canonical_map_detail_name(map_name: str, package_id: str) -> str:
    """Accept both the persisted map id and the human-facing UI name."""
    candidate = str(map_name or "").strip()
    if not candidate:
        return candidate
    names = MAP_DISPLAY_NAMES.get(package_id, {})
    candidate_key = candidate.casefold()
    for map_id, display_name in names.items():
        aliases = {
            map_id,
            map_id.removesuffix(".SC2Map"),
            display_name,
            display_name.split("] ", 1)[-1] if "] " in display_name else display_name,
        }
        if any(candidate_key == alias.casefold() for alias in aliases):
            return map_id
    return candidate


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
    # 2. 回退到 bnet_*.png/tga（Battle.net 地图预览图）
    for preview in sorted(map_dir.glob("bnet_*.png")):
        return preview.relative_to(MAPS_CMRE_DIR.parent).as_posix()
    for preview in sorted(map_dir.glob("bnet_*.tga")):
        return preview.relative_to(MAPS_CMRE_DIR.parent).as_posix()
    return ""


REBORN_MAP_LOADING_ASSETS = {
    "zchar01.SC2Map": "ui_hots_loading_missionselect_zchar01.dds",
    "zchar02.SC2Map": "ui_hots_loading_missionselect_zchar03.dds",
    "zchar03.SC2Map": "ui_hots_loading_missionselect_zchar03.dds",
    "zexpedition01.SC2Map": "ui_hots_loading_missionselect_zexpedition01.dds",
    "zexpedition02.SC2Map": "ui_hots_loading_planetviewkaldir.dds",
    "zexpedition03.SC2Map": "ui_hots_loading_missionselect_zkaldir01.dds",
    "zhybrid01.SC2Map": "ui_hots_loading_missionselect_zhybrid01.dds",
    "zhybrid02.SC2Map": "ui_hots_loading_missionselect_zhybrid01.dds",
    "zhybrid03.SC2Map": "ui_hots_loading_missionselect_zhybrid03.dds",
    "zkorhal01.SC2Map": "ui_hots_loading_missionselect_zkorhal01.dds",
    "zkorhal02.SC2Map": "ui_hots_loading_missionselect_zkorhal02.dds",
    "zkorhal03.SC2Map": "ui_hots_loading_missionselect_zkorhal03.dds",
    "zlab01.SC2Map": "ui_hots_loading_introscreen.dds",
    "zlab02.SC2Map": "loading-valhalla.dds",
    "zlab03.SC2Map": "ui_hots_loading_missionselect_zlab03.dds",
    "zspace01.SC2Map": "ui_hots_loading_missionselect_zspace01.dds",
    "zspace02.SC2Map": "ui_hots_loading_missionselect_zspace02.dds",
    "zzerus01.SC2Map": "ui_hots_loading_missionselect_zzerus01.dds",
    "zzerus02.SC2Map": "ui_hots_loading_missionselect_zzerus02.dds",
    "zzerus03.SC2Map": "ui_hots_loading_missionselect_zzerus03.dds",
}

# Revolution Overdrive reuses the original campaign's scene art. These are
# deliberately named by mission family so the UI never falls back to Minimap.tga.
REVOLUTION_MAP_LOADING_ASSETS = {
    "tarcade.SC2Map": "loading-lostviking.dds",
    "thanson01.SC2Map": "loading-haven.dds",
    "thanson02.SC2Map": "loading-haven.dds",
    "thanson03a.SC2Map": "loading-haven.dds",
    "thanson03b.SC2Map": "loading-haven.dds",
    "thorner01.SC2Map": "loading-tyrador.dds",
    "thorner02.SC2Map": "loading-tyrador.dds",
    "thorner03.SC2Map": "loading-tyrador.dds",
    "thorner04.SC2Map": "loading-tyrador.dds",
    "thorner05s.SC2Map": "loading-tyrador.dds",
    "traynor01.SC2Map": "loading-marsarabarexterior.dds",
    "traynor02.SC2Map": "loading-marsarabarexterior.dds",
    "traynor03.SC2Map": "loading-marsarabarexterior.dds",
    "tstory01.SC2Map": "loading-marsarabarexterior.dds",
    "ttosh01.SC2Map": "loading-agria.dds",
    "ttosh02.SC2Map": "loading-agria.dds",
    "ttosh03a.SC2Map": "loading-agria.dds",
    "ttosh03b.SC2Map": "loading-agria.dds",
    "ttychus01.SC2Map": "loading-char.dds",
    "ttychus02.SC2Map": "loading-char.dds",
    "ttychus03.SC2Map": "loading-char.dds",
    "ttychus04.SC2Map": "loading-char.dds",
    "ttychus05.SC2Map": "loading-char.dds",
    "tvalerian01.SC2Map": "loading-char.dds",
    "tvalerian02a.SC2Map": "loading-char.dds",
    "tvalerian02b.SC2Map": "loading-char.dds",
    "tvalerian03.SC2Map": "loading-char.dds",
    "tzeratul01.SC2Map": "loading-aiur.dds",
    "tzeratul02.SC2Map": "loading-aiur.dds",
    "tzeratul03.SC2Map": "loading-aiur.dds",
    "tzeratul04.SC2Map": "loading-aiur.dds",
}


def _find_extracted_loading_preview(map_id: str, package_id: str) -> tuple[str, str]:
    """Return a stage-artifact preview path and its provenance label."""
    filename = (
        REBORN_MAP_LOADING_ASSETS.get(map_id)
        if package_id == "reborn"
        else REVOLUTION_MAP_LOADING_ASSETS.get(map_id)
    )
    if not filename:
        return "", ""
    candidates = [
        MAP_PREVIEW_ASSET_ROOT / "mods" / "liberty.sc2mod" / "base.sc2assets" / "assets" / "textures" / filename,
        MAP_PREVIEW_ASSET_ROOT / "mods" / "core.sc2mod" / "base.sc2assets" / "assets" / "textures" / filename,
        MAP_PREVIEW_ASSET_ROOT / "campaigns" / "liberty.sc2campaign" / "base.sc2assets" / "assets" / "textures" / filename,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return f"MapPreview/{package_id}/{map_id}/{filename}", "official-loading-art"
    return "", ""


def _find_bound_map_preview(map_dir: Path, package_id: str) -> tuple[str, str]:
    """Return the official wide preview and its provenance, never a minimap."""
    return _find_extracted_loading_preview(map_dir.name, package_id)


def _load_local_source_binding(source_id: str) -> Path | None:
    """Resolve a machine-local source binding without leaking it into committed data."""
    try:
        data = json.loads(LOCAL_SOURCES_JSON.read_text(encoding="utf-8-sig"))
        raw = data.get("bindings", {}).get(source_id, "")
        path = Path(raw).expanduser() if raw else None
        return path if path and path.is_dir() else None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _map_record(map_id: str, name: str, package_id: str, preview: str = "") -> dict:
    return {
        "id": map_id,
        "name": name,
        "preview": preview,
        "packageId": package_id,
        "mapCategory": package_id,
    }


def load_maps():
    """扫描 CMRE 与可选 斗蛐蛐输入，返回 [{id, name, preview}]。

    id = 文件名（含 .SC2Map），name = 去掉 .SC2Map 扩展名的显示名。
    preview = 地图预览图相对路径（Maps/CMRE/<map>/Assets/Textures/ui_loading_xxx.dds），
              找不到为空字符串。按 name 排序。
    """
    maps = []
    if not MAPS_CMRE_DIR.exists():
        print(f"[warn] CMRE 地图目录不存在: {MAPS_CMRE_DIR}")
    else:
        for entry in sorted(MAPS_CMRE_DIR.iterdir()):
            if entry.is_dir() and entry.name.endswith(".SC2Map"):
                preview = _find_map_preview(entry)
                maps.append({
                    **_map_record(
                        entry.name,
                        _map_display_name(entry.name, "cmre"),
                        "cmre",
                        preview,
                    ),
                })
    dou_ququ_root = _dou_ququ_map_root()
    if dou_ququ_root is not None:
        source = DOU_QUQU_MAP_SOURCE.resolve()
        map_id = source.name if source.is_file() else dou_ququ_root.name
        if not map_id.casefold().endswith(".sc2map"):
            map_id += ".SC2Map"
        maps.append({
            **_map_record(
                map_id,
                "斗蛐蛐",
                "dou-ququ",
                "",
            ),
            "runtimeSource": str(dou_ququ_root),
            "runtimeMapPath": (
                str(DOU_QUQU_RUNTIME_PACKED_MAP)
                if DOU_QUQU_RUNTIME_PACKED_MAP.is_file()
                else ""
            ),
            "readOnlySource": str(source),
            "runtimeOnly": True,
        })
    return maps


def load_reborn_maps():
    """Scan the locally bound Reborn Heart of the Swarm campaign maps."""
    root = _load_local_source_binding("reborn-hots-071")
    if not root:
        print(f"[warn] Reborn source binding is unavailable: {LOCAL_SOURCES_JSON}")
        return []
    maps = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and entry.name.endswith(".SC2Map"):
            map_id = entry.name
            preview, preview_source = _find_bound_map_preview(entry, "reborn")
            maps.append(_map_record(
                map_id,
                _map_display_name(map_id, "reborn"),
                "reborn",
                preview,
            ))
            maps[-1]["previewSource"] = preview_source
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
    maps = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        map_id = entry["id"]
        preview, preview_source = _find_bound_map_preview(
            REVOLUTION_MAPS_ROOT / map_id, "revolution-overdrive"
        )
        maps.append({
            **_map_record(
                map_id,
                _map_display_name(map_id, "revolution-overdrive"),
                "revolution-overdrive",
                preview,
            ),
            "previewSource": preview_source,
        })
    return maps


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
    """扫描 CMRE commander adapter packages，返回 [{id, name}]。

    若提供 bank_commander（如 "Alenger6"），从 alenger-mods.json 的
    commanderToAlenger[bank_commander] 查出该指挥官会自动加载的 mod 包，
    从结果中排除它们。id = name = 目录名去掉 .SC2Mod 后缀。按 name 排序。
    """
    if not COMMANDER_PACKAGE_MODS_DIR.exists():
        print(f"[warn] commander mod 包目录不存在: {COMMANDER_PACKAGE_MODS_DIR}")
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
    for entry in sorted(COMMANDER_PACKAGE_MODS_DIR.iterdir()):
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
    # Stage-extracted official wide loading art. Do not expose local CASC paths.
    if normalized.startswith("MapPreview/"):
        parts = normalized.split("/")
        if len(parts) != 4 or any(part in {"", ".", ".."} for part in parts):
            return None
        _, package_id, map_name, filename = parts
        if package_id not in {"reborn", "revolution-overdrive"}:
            return None
        expected, _ = _find_extracted_loading_preview(map_name, package_id)
        if expected != normalized:
            return None
        candidates = [
            MAP_PREVIEW_ASSET_ROOT / "mods" / "liberty.sc2mod" / "base.sc2assets" / "assets" / "textures" / filename,
            MAP_PREVIEW_ASSET_ROOT / "mods" / "core.sc2mod" / "base.sc2assets" / "assets" / "textures" / filename,
            MAP_PREVIEW_ASSET_ROOT / "campaigns" / "liberty.sc2campaign" / "base.sc2assets" / "assets" / "textures" / filename,
        ]
        return next((candidate for candidate in candidates if candidate.is_file()), None)

    # CMRE 地图预览图路径（相对于 cmre-runtime/Maps/）
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


def convert_image_to_png(source_path: Path, png_path: Path) -> bool:
    """Convert a browser-incompatible map image (currently TGA) to PNG."""
    try:
        from PIL import Image

        with Image.open(source_path) as img:
            if img.mode not in ("RGBA", "RGB"):
                img = img.convert("RGBA")
            png_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(png_path, "PNG")
        return True
    except Exception as exc:
        print(f"[warn] 地图预览图转换失败: {source_path} -> {png_path}: {exc}")
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

    def __init__(
        self,
        call_log_path: Path | None = None,
        event_log_path: Path | None = None,
        event_bank_root: Path | None = None,
    ):
        self._lock = threading.RLock()
        self._operation_lock = None
        self._loop = None
        self._thread = None
        self._ready = threading.Event()
        self._repl = None
        self._status = "disconnected"
        self._error = ""
        self._port = None
        self._session_id = ""
        self._session_recovery = []
        self._trace = []
        self._running = ""
        self._call_log_path = Path(call_log_path or DOU_QUQU_RUNTIME_CALL_LOG)
        self._event_log_path = Path(event_log_path or DOU_QUQU_RUNTIME_EVENT_LOG)
        self._event_bank_root = Path(
            event_bank_root
            or (Path.home() / "Documents" / "StarCraft II" / "Banks")
        )
        self._event_session = ""
        self._event_cursor = 0
        self._event_pump_task = None
        self._event_bank_path = ""
        self._readiness = {}

    def _ensure_loop(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                thread = self._thread
            else:
                self._ready.clear()
                self._thread = threading.Thread(
                    target=self._run_loop, name="vibe-console-loop", daemon=True
                )
                self._thread.start()
            thread = self._thread
        if not self._ready.wait(timeout=5):
            raise RuntimeError("runtime console event loop did not start")
        with self._lock:
            if self._loop is None or not thread.is_alive():
                raise RuntimeError("runtime console event loop stopped during startup")

    def _run_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
            # VibeREPL shares one WebSocket and one Bank RPC sequence. Every
            # request must pass this queue so an observer cannot consume a VM
            # response or interleave a second request into the active command.
            self._operation_lock = asyncio.Lock()
            self._ready.set()
        loop.run_forever()
        loop.close()

    def _submit(self, coroutine, timeout=30):
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        return future.result(timeout=timeout)

    async def _run_serialized(self, operation, action):
        if self._operation_lock is None:
            raise RuntimeError("runtime console operation queue is unavailable")
        async with self._operation_lock:
            with self._lock:
                self._running = operation
            try:
                return await action()
            finally:
                with self._lock:
                    self._running = ""

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
        # sequence only increases within one session. It is not a timestamp and
        # must not be used to guess which session belongs to the current game.
        return sorted(sessions.values(), key=lambda item: item["session_id"])[:20]

    def _event_bank_paths(self) -> list[Path]:
        root = self._event_bank_root
        paths = [root / "GalaxyVibeEvents.SC2Bank"]
        if root.is_dir():
            paths.extend(
                child / "GalaxyVibeEvents.SC2Bank"
                for child in root.iterdir()
                if child.is_dir() and child.name.isdigit()
            )
        return paths

    def _read_event_snapshot(self) -> dict:
        snapshots = []
        for path in self._event_bank_paths():
            snapshot = parse_runtime_event_bank(path)
            if snapshot.get("event_session"):
                try:
                    snapshot["_mtime_ns"] = path.stat().st_mtime_ns
                except OSError:
                    snapshot["_mtime_ns"] = 0
                snapshots.append(snapshot)
        if not snapshots:
            return {}
        with self._lock:
            current_session = self._event_session
        matching = [
            item for item in snapshots
            if current_session and item.get("event_session") == current_session
        ]
        candidates = matching or snapshots
        return max(
            candidates,
            key=lambda item: (
                int(item.get("last_event_id", 0) or 0),
                int(item.get("_mtime_ns", 0) or 0),
            ),
        )

    @staticmethod
    def _event_dispatch(event: dict, correlation_id: str):
        event_type = str(event.get("eventType", "") or "")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return None
        if event_type == "unit_attacked":
            attacker_type = str(payload.get("attackerType", "") or "")
            if attacker_type not in {"Reaver", "BroodLord"}:
                return None
            return (
                "douququ.auto.attack",
                {
                    "attacker_tag": int(payload.get("attackerTag", 0) or 0),
                    "target_tag": int(payload.get("targetTag", 0) or 0),
                    "correlation_id": correlation_id,
                },
            )
        if event_type == "unit_died":
            killer_type = str(payload.get("killerType", "") or "")
            victim_type = str(payload.get("victimType", "") or "")
            if victim_type != "Vulture" and killer_type not in {
                "Reaver",
                "Hydralisk",
                "K5Kerrigan",
                "K5KerriganBurrowed",
            }:
                return None
            return (
                "douququ.auto.death",
                {
                    "correlation_id": correlation_id,
                    "killer_tag": int(payload.get("killerTag", 0) or 0),
                    "victim_owner": int(payload.get("victimOwner", 0) or 0),
                    "victim_tag": int(payload.get("victimTag", 0) or 0),
                    "victim_type": victim_type,
                    "victim_x": float(payload.get("victimX", 0.0) or 0.0),
                    "victim_y": float(payload.get("victimY", 0.0) or 0.0),
                },
            )
        if event_type == "unit_created":
            unit_type = str(payload.get("unitType", "") or "")
            if unit_type not in {"Vulture", "InfestedBanshee"}:
                return None
            return (
                "douququ.auto.created",
                {
                    "correlation_id": correlation_id,
                    "unit_tag": int(payload.get("unitTag", 0) or 0),
                },
            )
        if event_type == "effect_used":
            return (
                "douququ.auto.effect",
                {
                    "ability": str(payload.get("ability", "") or ""),
                    "correlation_id": correlation_id,
                    "unit_tag": int(payload.get("unitTag", 0) or 0),
                },
            )
        if event_type == "periodic":
            return (
                "douququ.auto.periodic",
                {
                    "correlation_id": correlation_id,
                    "seconds": float(payload.get("seconds", 0.0) or 0.0),
                },
            )
        return None

    @staticmethod
    def _automatic_program(function_id: str, args: dict) -> dict:
        return {
            "vm": "vibe-debug/1",
            "mode": "debug",
            "steps": [
                {
                    "op": "call",
                    "fn": function_id,
                    "args": args,
                    "save": "automatic",
                }
            ],
        }

    async def _poll_events_unlocked(self):
        snapshot = self._read_event_snapshot()
        event_session = str(snapshot.get("event_session", "") or "")
        if not event_session:
            return []
        with self._lock:
            if self._event_session != event_session:
                self._event_session = event_session
                self._event_cursor = 0
            self._event_bank_path = str(snapshot.get("path", ""))
            cursor = self._event_cursor
        dispatched = []
        for event in snapshot.get("events", [])[:128]:
            event_id = int(event.get("eventId", 0) or 0)
            if event_id <= cursor:
                continue
            correlation_id = (
                f"auto-vm:{self._session_id}:{event_session}:{event_id}"
            )
            dispatch = self._event_dispatch(event, correlation_id)
            # Advance before executing the VM. A malformed or failed event is
            # still consumed exactly once and remains visible in the event log.
            with self._lock:
                self._event_cursor = event_id
            function_id = dispatch[0] if dispatch else ""
            args = dispatch[1] if dispatch else {}
            vm_result = None
            error = None
            status = "ignored"
            if dispatch:
                try:
                    vm_result = await self._run_vm_unlocked(
                        self._automatic_program(function_id, args),
                        origin="auto-vm",
                    )
                    status = (
                        "passed"
                        if isinstance(vm_result, dict)
                        and vm_result.get("status") == "passed"
                        else "failed"
                    )
                except Exception as exc:
                    error = {"type": type(exc).__name__, "message": str(exc)}
                    status = "failed"
            record = {
                "schema_version": "douququ-runtime-event.v1",
                "timestamp": self._timestamp(),
                "ts": time.time(),
                "op": "event",
                "event_id": event_id,
                "event_session": event_session,
                "event_type": event.get("eventType", ""),
                "raw_event": event,
                "correlation_id": correlation_id,
                "dispatch_function_id": function_id,
                "dispatch_args": args,
                "vm_result": vm_result,
                "error": error,
                "status": status,
            }
            self._record_runtime_event(record)
            dispatched.append(record)
            cursor = event_id
        return dispatched

    async def _event_pump(self):
        try:
            while True:
                await asyncio.sleep(0.2)
                with self._lock:
                    connected = self._repl is not None and self._status == "connected"
                if not connected:
                    return
                try:
                    await self._run_serialized(
                        "auto-vm",
                        self._poll_events_unlocked,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._append_trace({
                        "schema_version": "douququ-runtime-event.v1",
                        "timestamp": self._timestamp(),
                        "op": "event-pump-error",
                        "status": "failed",
                        "error": {"type": type(exc).__name__, "message": str(exc)},
                    })
        finally:
            with self._lock:
                if self._event_pump_task is asyncio.current_task():
                    self._event_pump_task = None

    def _start_event_pump_unlocked(self):
        if self._event_pump_task is None or self._event_pump_task.done():
            self._event_pump_task = asyncio.create_task(
                self._event_pump(),
                name="douququ-runtime-event-pump",
            )

    async def _stop_event_pump_unlocked(self):
        task = self._event_pump_task
        if task is None:
            return
        self._event_pump_task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _probe_live_readiness(self, repl):
        """Read the SC2 lifecycle and frame before exposing a live session."""
        from galaxy_repl import send_request
        from s2clientprotocol import sc2api_pb2 as sc_pb

        response = await send_request(
            repl.ws,
            sc_pb.Request(observation=sc_pb.RequestObservation()),
            timeout=15.0,
        )
        status = int(getattr(response, "status", 0) or 0)
        status_name = sc_pb.Status.Name(status) if status else "unknown"
        readiness = {
            "status": status,
            "status_name": status_name,
            "game_loop": 0,
        }
        if response.error:
            readiness["errors"] = list(response.error)
            return readiness
        if not response.HasField("observation"):
            readiness["errors"] = ["observation response missing"]
            return readiness
        readiness["game_loop"] = int(response.observation.observation.game_loop)
        return readiness

    async def _connect_unlocked(self, payload):
        VibeREPL, resolve, name_lookup, _, _, _ = self._imports()
        port = int(payload.get("port", 5000))
        map_path = str(payload.get("map_path", "") or "")
        join_wait = float(payload.get("join_wait", 0) or 0)
        rpc_session_id = str(payload.get("rpc_session_id", "") or "")
        available_sessions = self.sessions()
        await self._stop_event_pump_unlocked()
        if self._repl is not None:
            await self._repl.close()
        with self._lock:
            self._repl = None
            self._port = None
            self._session_id = ""
            self._session_recovery = []
        repl = VibeREPL(
            port,
            resolve(),
            name_lookup(),
            map_path=map_path,
            join_wait=join_wait,
            rpc_session_id=rpc_session_id,
            prefer_ai_opponent=bool(payload.get("prefer_ai_opponent", False)),
        )
        with self._lock:
            self._status = "connecting"
            self._error = ""
        try:
            await repl.connect()
            # The bank can contain responses from older SC2 processes. Probe the
            # session through the live kernel before exposing it as connected.
            # Reuse this already joined socket for every candidate so a failed
            # stale-session probe never recreates the map or resets the game.
            candidates = []
            if rpc_session_id:
                candidates.append(rpc_session_id)
            else:
                candidates.append(repl.rpc_session_id)
            for item in available_sessions:
                candidate = str(item.get("session_id", "") or "")
                if candidate and candidate not in candidates:
                    candidates.append(candidate)
            if rpc_session_id:
                fresh_id = f"repl_{uuid.uuid4().hex[:12]}"
                if fresh_id not in candidates:
                    candidates.append(fresh_id)

            accepted_session = ""
            attempted_sessions = []
            probe_error = ""
            for candidate in candidates:
                repl.rpc_session_id = candidate
                # Session switching happens on the same joined game. Starting
                # at sequence 0 is valid because the kernel validates identity,
                # while request_id remains globally unique.
                repl.rpc_sequence = 0
                probe_started = time.perf_counter()
                probe = await repl.invoke_function_request("douququ.runtime.status", {})
                self._record_runtime_call(
                    "douququ.runtime.status",
                    {},
                    probe,
                    origin="connect",
                    session_id=candidate,
                    port=port,
                    duration_ms=round((time.perf_counter() - probe_started) * 1000, 1),
                )
                error_code = str(probe.get("error_code", "") or "")
                attempt = {"session_id": candidate, "error_code": error_code}
                try:
                    readiness = await self._probe_live_readiness(repl)
                except Exception as exc:
                    readiness = {
                        "status": 0,
                        "status_name": "unknown",
                        "game_loop": 0,
                        "errors": [str(exc)],
                    }
                attempt.update(readiness)
                if error_code != "OK":
                    probe_error = f"{candidate}: {error_code or 'missing error_code'}"
                elif readiness.get("status_name") != "in_game":
                    probe_error = (
                        f"{candidate}: SC2 status={readiness.get('status_name', 'unknown')}"
                    )
                elif int(readiness.get("game_loop", 0) or 0) <= 0:
                    probe_error = f"{candidate}: game_loop=0"
                else:
                    attempt["accepted"] = True
                    accepted_session = candidate
                    with self._lock:
                        self._readiness = dict(readiness)
                attempted_sessions.append(attempt)
                if accepted_session:
                    break
            if not accepted_session:
                raise RuntimeError(
                    "没有可用的当前 Vibe session；已探测候选: "
                    + ", ".join(candidates)
                    + (f"；最后错误: {probe_error}" if probe_error else "")
                )
        except Exception as exc:
            with self._lock:
                self._status = "error"
                self._error = str(exc)
            await repl.close()
            raise
        with self._lock:
            self._repl = repl
            self._port = port
            self._session_id = accepted_session
            self._session_recovery = attempted_sessions
            self._status = "connected"
            self._error = ""
            self._trace = []
            self._event_session = ""
            self._event_cursor = 0
            self._event_bank_path = ""
            self._start_event_pump_unlocked()
        return self.status()

    async def _connect(self, payload):
        """Compatibility coroutine for direct tests; HTTP callers use connect()."""
        if self._operation_lock is None:
            return await self._connect_unlocked(payload)
        return await self._run_serialized(
            "connect", lambda: self._connect_unlocked(payload)
        )

    async def _disconnect_unlocked(self):
        await self._stop_event_pump_unlocked()
        if self._repl is not None:
            await self._repl.close()
        with self._lock:
            self._repl = None
            self._status = "disconnected"
            self._running = ""
            self._event_session = ""
            self._event_cursor = 0
            self._event_bank_path = ""
            self._readiness = {}
        return self.status()

    def connect(self, payload):
        return self._submit(
            self._run_serialized("connect", lambda: self._connect_unlocked(payload)),
            timeout=90,
        )

    def disconnect(self):
        return self._submit(
            self._run_serialized("disconnect", self._disconnect_unlocked),
            timeout=15,
        )

    async def _invoke_unlocked(self, function_id, args, origin="api"):
        if self._repl is None:
            raise RuntimeError("未连接 SC2 Vibe session")
        started = time.perf_counter()
        try:
            result = await self._repl.invoke_function_request(function_id, args)
            record = self._record_runtime_call(
                function_id,
                args,
                result,
                origin=origin,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            return record
        except Exception as exc:
            record = self._record_runtime_call(
                function_id,
                args,
                None,
                origin=origin,
                error={"type": type(exc).__name__, "message": str(exc)},
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            raise
    def invoke(self, function_id, args):
        return self._submit(
            self._run_serialized(
                "invoke",
                lambda: self._invoke_unlocked(function_id, args),
            ),
            timeout=30,
        )

    async def _step_unlocked(self, loops):
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
        return self._submit(
            self._run_serialized("step", lambda: self._step_unlocked(loops)),
            timeout=15,
        )

    async def _observe_unlocked(self):
        if self._repl is None:
            raise RuntimeError("未连接 SC2 Vibe session")
        from galaxy_repl import send_request
        from s2clientprotocol import sc2api_pb2 as sc_pb

        response = await send_request(
            self._repl.ws,
            sc_pb.Request(observation=sc_pb.RequestObservation()),
            timeout=15.0,
        )
        if response.error:
            return {
                "kind": "error",
                "error_code": "OBSERVE_FAILED",
                "payload": {"errors": list(response.error)},
            }
        observation = response.observation.observation
        raw = observation.raw_data
        units = []
        if raw is not None:
            for unit in raw.units:
                units.append({
                    "tag": int(unit.tag),
                    "unit_type_id": int(unit.unit_type),
                    "unit_type": self._repl.name_lookup(int(unit.unit_type)),
                    "owner": int(unit.owner),
                    "x": round(float(unit.pos.x), 3),
                    "y": round(float(unit.pos.y), 3),
                    "life": round(float(unit.health), 3),
                    "max_life": round(float(unit.health_max), 3),
                    "shields": round(float(unit.shield), 3),
                    "energy": round(float(unit.energy), 3),
                    "orders": [int(order.ability_id) for order in unit.orders],
                })
        player = observation.player_common
        return {
            "kind": "result",
            "error_code": "OK",
            "payload": {
                "game_loop": int(observation.game_loop),
                "player": {
                    "id": int(player.player_id),
                    "minerals": int(player.minerals),
                    "vespene": int(player.vespene),
                    "food_used": int(player.food_used),
                    "food_cap": int(player.food_cap),
                },
                "units": units[:500],
                "unit_count": len(units),
            },
        }

    def observe(self):
        return self._submit(
            self._run_serialized("observe", self._observe_unlocked),
            timeout=20,
        )

    async def _run_vm_unlocked(self, program, *, origin="vm"):
        if self._repl is None:
            raise RuntimeError("未连接 SC2 Vibe session")
        _, _, _, DebugVm, load_function_catalog, load_function_metadata = self._imports()
        manager = self
        try:
            catalog = load_function_catalog(VIBE_FUNCTION_CATALOG) if VIBE_FUNCTION_CATALOG.exists() else []

            class ReplBridge:
                async def call(inner_self, function_id, call_args):
                    record = await manager._invoke_unlocked(
                        function_id, call_args, origin=origin
                    )
                    return record["result"]

                async def step(inner_self, loops):
                    return await manager._step_unlocked(loops)

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
            # _run_serialized owns the visible running state for the whole VM.
            pass

    @staticmethod
    def _step_request(loops):
        from s2clientprotocol import sc2api_pb2 as sc_pb

        return sc_pb.Request(step=sc_pb.RequestStep(count=loops))

    def run_vm(self, program):
        return self._submit(
            self._run_serialized("vm", lambda: self._run_vm_unlocked(program)),
            timeout=180,
        )

    def _append_trace(self, record):
        with self._lock:
            self._trace.append(record)
            self._trace = self._trace[-300:]

    @staticmethod
    def _timestamp():
        now = time.time()
        milliseconds = int(now * 1000) % 1000
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{milliseconds:03d}Z"

    @staticmethod
    def _result_error(result):
        if not isinstance(result, dict) or result.get("error_code") in (None, "OK"):
            return None
        return {
            "error_code": result.get("error_code"),
            "payload": result.get("payload", {}),
        }

    def _record_runtime_call(
        self,
        function_id,
        args,
        result,
        *,
        origin,
        error=None,
        session_id=None,
        port=None,
        duration_ms=None,
    ):
        with self._lock:
            active_session = session_id or self._session_id
            active_port = self._port if port is None else port
        if error is None:
            error = self._result_error(result)
        status = "passed" if error is None else "failed"
        record = {
            "schema_version": "douququ-runtime-call.v1",
            "timestamp": self._timestamp(),
            "ts": time.time(),
            "op": "call",
            "origin": origin,
            "session_id": active_session,
            "port": active_port,
            "function_id": function_id,
            "args": args,
            "result": result,
            "error": error,
            "duration_ms": duration_ms,
            "status": status,
        }
        self._append_trace(record)
        self._append_call_log(record)
        return record

    def _append_call_log(self, record):
        try:
            self._call_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._call_log_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str, separators=(",", ":")))
                handle.write("\n")
        except OSError as exc:
            _append_log(f"[vibe] runtime call log write failed: {exc}")

    def _record_runtime_event(self, record):
        self._append_trace(record)
        try:
            self._event_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._event_log_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        default=str,
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")
        except OSError as exc:
            _append_log(f"[vibe] runtime event log write failed: {exc}")

    def call_log(self, limit=200):
        limit = max(1, min(int(limit), 2000))
        if not self._call_log_path.is_file():
            records = []
            total_count = 0
        else:
            try:
                lines = self._call_log_path.read_text(encoding="utf-8").splitlines()
                decoded = []
                for line in lines:
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict):
                        decoded.append(item)
                total_count = len(decoded)
                records = decoded[-limit:]
            except OSError as exc:
                return {
                    "schema_version": "douququ-runtime-call-log.v1",
                    "records": [],
                    "count": 0,
                    "total_count": 0,
                    "error": str(exc),
                }
        try:
            relative_path = str(self._call_log_path.resolve().relative_to(REPO_ROOT.resolve()))
        except ValueError:
            relative_path = str(self._call_log_path)
        return {
            "schema_version": "douququ-runtime-call-log.v1",
            "path": relative_path,
            "limit": limit,
            "count": len(records),
            "total_count": total_count,
            "records": records,
        }

    def event_log(self, limit=200):
        limit = max(1, min(int(limit), 2000))
        if not self._event_log_path.is_file():
            records = []
            total_count = 0
        else:
            try:
                lines = self._event_log_path.read_text(encoding="utf-8").splitlines()
                decoded = []
                for line in lines:
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict):
                        decoded.append(item)
                total_count = len(decoded)
                records = decoded[-limit:]
            except OSError as exc:
                return {
                    "schema_version": "douququ-runtime-event.v1",
                    "records": [],
                    "count": 0,
                    "total_count": 0,
                    "error": str(exc),
                }
        try:
            relative_path = str(self._event_log_path.resolve().relative_to(REPO_ROOT.resolve()))
        except ValueError:
            relative_path = str(self._event_log_path)
        return {
            "schema_version": "douququ-runtime-event.v1",
            "path": relative_path,
            "limit": limit,
            "count": len(records),
            "total_count": total_count,
            "records": records,
        }

    def status(self):
        with self._lock:
            return {
                "status": self._status,
                "error": self._error,
                "port": self._port,
                "session_id": self._session_id,
                "session_recovery": list(self._session_recovery),
                "readiness": dict(self._readiness),
                "running": self._running,
                "trace": list(self._trace),
                "call_log": {
                    "path": str(self._call_log_path.resolve().relative_to(REPO_ROOT.resolve()))
                    if self._call_log_path.resolve().is_relative_to(REPO_ROOT.resolve())
                    else str(self._call_log_path),
                    "endpoint": "/api/vibe/call-log",
                },
                "event_source": {
                    "bank": "GalaxyVibeEvents",
                    "bank_path": self._event_bank_path,
                    "event_session": self._event_session,
                    "cursor": self._event_cursor,
                    "pump": bool(self._event_pump_task and not self._event_pump_task.done()),
                    "endpoint": "/api/vibe/event-log",
                },
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


_ansi_re = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _strip_ansi(text):
    """去掉 ANSI 颜色转义序列（如 \x1b[31;1m \x1b[0m），避免日志被污染。"""
    if not text:
        return text
    return _ansi_re.sub("", text)


def _append_log(line):
    """添加日志行并推送给所有 SSE 订阅者。"""
    line = _strip_ansi(line)
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
    if not _bind_webui_runtime_lease(getattr(proc, "pid", 0)):
        # A direct-map launcher may have left its SC2 child in staging after a
        # map-load failure. Try the exact staging ownership gate before dropping
        # the intent that is needed to identify that child safely.
        if not _cleanup_webui_staging_session():
            _discard_unbound_webui_launch_intent(getattr(proc, "pid", 0))
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
            stderr_tail_clean = [_strip_ansi(ln) for ln in stderr_tail]
            _append_log("[webui] launcher stderr summary: " + " | ".join(stderr_tail_clean))
        if stdout_tail:
            stdout_tail_clean = [_strip_ansi(ln) for ln in stdout_tail]
            # 如果有显式错误行，单独列出来，避免用户在 summary 长串中遗漏。
            if stdout_errors and not stderr_errors:
                stdout_errors_clean = [_strip_ansi(ln) for ln in stdout_errors]
                _append_log("[webui] launcher stdout 中的错误行: " + " | ".join(stdout_errors_clean[-20:]))
            _append_log("[webui] launcher stdout summary: " + " | ".join(stdout_tail_clean))
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


def _read_json_object(path):
    """Read a small runtime ownership record; malformed files are untrusted."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_json_object(path, payload):
    """Atomically persist a small runtime ownership record."""
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp_path, path)
        return True
    except OSError as exc:
        _append_log(f"[webui] 写入运行时归属记录失败: {exc}")
        return False
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass


def _remove_runtime_record(path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        _append_log(f"[webui] 删除运行时归属记录失败: {exc}")


def _get_process_info(pid):
    """Return the Windows process identity needed for fail-closed lease cleanup."""
    if os.name != "nt":
        return None
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None

    command = (
        "$p = Get-CimInstance -ClassName Win32_Process "
        f"-Filter 'ProcessId = {pid}' -ErrorAction SilentlyContinue; "
        "if ($null -ne $p) { "
        "[pscustomobject]@{ProcessId=$p.ProcessId;Name=$p.Name;"
        "CommandLineUtf16=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes([string]$p.CommandLine));"
        "CreationDate=$p.CreationDate} | "
        "ConvertTo-Json -Compress }"
    )
    try:
        completed = subprocess.run(
            [_resolve_powershell_executable(), "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    raw = completed.stdout.lstrip("\ufeff").strip()
    if not raw:
        return None
    try:
        info = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(info, dict):
        return None
    try:
        command_line_utf16 = info.pop("CommandLineUtf16", "")
        info["CommandLine"] = base64.b64decode(command_line_utf16).decode("utf-16-le")
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    return info


def _lease_pid(record, key):
    try:
        pid = int(record.get(key, 0))
    except (AttributeError, TypeError, ValueError):
        return 0
    return pid if pid > 0 else 0


def _same_path(recorded_path, expected_path):
    if not isinstance(recorded_path, str) or not recorded_path:
        return False
    try:
        return os.path.normcase(os.path.abspath(recorded_path)) == os.path.normcase(
            os.path.abspath(str(expected_path))
        )
    except OSError:
        return False


def _record_webui_launch_intent(proc, ctx):
    """Record launch provenance before the detached runtime lease is available."""
    if ctx.get("kind") != "cmre":
        return
    _write_json_object(
        WEBUI_SESSION_LEASE_PATH,
        {
            "schemaVersion": 1,
            "webuiPid": os.getpid(),
            "launcherPid": proc.pid,
            "launcher": str(LAUNCH_SCRIPT),
            "mapName": ctx["map_name"],
            "commander": ctx["commander"],
            "createdAt": time.time(),
        },
    )


def _bind_webui_runtime_lease(launcher_pid):
    """Bind a successful WebUI launch intent to the exact detached SC2 PID."""
    intent = _read_json_object(WEBUI_SESSION_LEASE_PATH)
    lease = _read_json_object(SC2_RUNTIME_LEASE_PATH)
    if not intent or not lease:
        return False
    if intent.get("launcherPid") != launcher_pid:
        return False
    if lease.get("state") != "detached" or _lease_pid(lease, "ownerPid") != launcher_pid:
        return False
    if not _same_path(intent.get("launcher"), LAUNCH_SCRIPT):
        return False
    if not _same_path(lease.get("launcher"), LAUNCH_SCRIPT):
        return False
    if lease.get("mapName") != intent.get("mapName") or lease.get("commander") != intent.get("commander"):
        return False

    runtime_pid = _lease_pid(lease, "runtimePid")
    runtime_info = _get_process_info(runtime_pid)
    if not runtime_info:
        return False
    intent.update(
        {
            "leaseOwnerSessionId": lease.get("ownerSessionId", ""),
            "runtimePid": runtime_pid,
            "runtimeCreationDate": runtime_info.get("CreationDate", ""),
            "boundAt": time.time(),
        }
    )
    return _write_json_object(WEBUI_SESSION_LEASE_PATH, intent)


def _discard_unbound_webui_launch_intent(launcher_pid):
    """Do not retain a failed launch intent as if it owned a live SC2 session."""
    intent = _read_json_object(WEBUI_SESSION_LEASE_PATH)
    if intent and intent.get("launcherPid") == launcher_pid and not intent.get("runtimePid"):
        _remove_runtime_record(WEBUI_SESSION_LEASE_PATH)


def _skip_detached_session_cleanup(reason):
    _append_log(f"[webui] detached SC2 cleanup skipped: {reason}")
    return []


def _cleanup_webui_detached_session():
    """Stop only an SC2 instance explicitly linked to this WebUI launch.

    A launcher lease by itself is insufficient: manually launched sessions create the
    same file. The WebUI intent must match the lease, runtime PID, process creation
    timestamp, and executable before taskkill is allowed. Direct-map detached
    sessions also carry the map in the command line; API KeepAlive sessions do not.
    """
    intent = _read_json_object(WEBUI_SESSION_LEASE_PATH)
    lease = _read_json_object(SC2_RUNTIME_LEASE_PATH)
    lease_state = lease.get("state") if lease else ""
    if not intent or not lease or lease_state not in {"detached", "keepalive", "ready", "api_listening"}:
        return []

    launcher_pid = _lease_pid(intent, "launcherPid")
    owner_pid = _lease_pid(lease, "ownerPid")
    runtime_pid = _lease_pid(lease, "runtimePid")
    if not launcher_pid or launcher_pid != owner_pid:
        return _skip_detached_session_cleanup("launcher PID does not match detached lease")
    if intent.get("runtimePid") and intent.get("runtimePid") != runtime_pid:
        return _skip_detached_session_cleanup("runtime PID does not match WebUI lease")
    if intent.get("leaseOwnerSessionId") and intent.get("leaseOwnerSessionId") != lease.get("ownerSessionId"):
        return _skip_detached_session_cleanup("launcher session does not match WebUI lease")
    if lease.get("mapName") != intent.get("mapName") or lease.get("commander") != intent.get("commander"):
        return _skip_detached_session_cleanup("map or commander does not match detached lease")
    if not _same_path(intent.get("launcher"), LAUNCH_SCRIPT):
        return _skip_detached_session_cleanup("WebUI launcher path is not trusted")
    if not _same_path(lease.get("launcher"), LAUNCH_SCRIPT):
        return _skip_detached_session_cleanup("WebUI lease launcher path is not trusted")
    # The original launcher must be gone. A reused owner PID is treated as untrusted.
    if _get_process_info(owner_pid) is not None:
        return _skip_detached_session_cleanup("original launcher PID is still live or reused")

    runtime_info = _get_process_info(runtime_pid)
    if not runtime_info:
        return _skip_detached_session_cleanup("detached runtime PID is not live")
    process_name = str(runtime_info.get("Name", "")).lower()
    command_line = str(runtime_info.get("CommandLine", ""))
    if process_name not in {"sc2.exe", "sc2_x64.exe"}:
        return _skip_detached_session_cleanup("runtime PID is not an SC2 game process")
    api_session = lease_state in {"keepalive", "ready", "api_listening"} and _lease_pid(lease, "port") > 0
    map_name = intent.get("mapName")
    if not api_session and (not isinstance(map_name, str) or not map_name or map_name.casefold() not in command_line.casefold()):
        # WMI can briefly return an empty CommandLine while SC2 is switching its
        # window state. Re-read once; any stable mismatch still fails closed.
        runtime_info = _get_process_info(runtime_pid) or runtime_info
        command_line = str(runtime_info.get("CommandLine", ""))
        if not isinstance(map_name, str) or not map_name or map_name.casefold() not in command_line.casefold():
            return _skip_detached_session_cleanup(
                f"runtime command line does not match leased map (expected={map_name!r}, actual={command_line!r})"
            )
    expected_creation = intent.get("runtimeCreationDate")
    if expected_creation and runtime_info.get("CreationDate") != expected_creation:
        return _skip_detached_session_cleanup("runtime creation timestamp does not match")

    if not _force_kill_process_tree(runtime_pid):
        return _skip_detached_session_cleanup(f"taskkill failed for PID {runtime_pid}")
    if not _wait_for_process_exit(runtime_pid):
        return _skip_detached_session_cleanup(f"taskkill accepted but PID {runtime_pid} is still live")
    _remove_runtime_record(SC2_RUNTIME_LEASE_PATH)
    _remove_runtime_record(WEBUI_SESSION_LEASE_PATH)
    return [f"sc2:{runtime_pid}"]


def _cleanup_webui_staging_session():
    """Stop a WebUI-owned SC2 child left behind while staging failed.

    Direct-map launches can start SC2 through SC2Switcher before the launcher
    reaches its normal detached lease transition. If the launcher then exits on
    a map-load error, keep the same fail-closed identity checks used for a
    detached session and clean only the exact map process created by this intent.
    """
    intent = _read_json_object(WEBUI_SESSION_LEASE_PATH)
    lease = _read_json_object(SC2_RUNTIME_LEASE_PATH)
    if not intent or not lease or lease.get("state") != "staging":
        return []
    launcher_pid = _lease_pid(intent, "launcherPid")
    if not launcher_pid or _get_process_info(launcher_pid) is not None:
        return _skip_detached_session_cleanup("staging launcher is still live or PID was reused")
    if lease.get("ownerPid") != launcher_pid:
        return _skip_detached_session_cleanup("staging launcher PID does not match lease")
    if not _same_path(intent.get("launcher"), LAUNCH_SCRIPT) or not _same_path(lease.get("launcher"), LAUNCH_SCRIPT):
        return _skip_detached_session_cleanup("staging launcher path is not trusted")
    if lease.get("mapName") != intent.get("mapName") or lease.get("commander") != intent.get("commander"):
        return _skip_detached_session_cleanup("staging map or commander does not match lease")

    expected_map = str(intent.get("mapName", ""))
    started_at = intent.get("createdAt", lease.get("startedAt", ""))
    candidates = []
    for pid, process_name in _list_game_processes():
        info = _get_process_info(pid)
        if not info or str(process_name).lower() not in {"sc2.exe", "sc2_x64.exe"}:
            continue
        command_line = str(info.get("CommandLine", ""))
        if not expected_map or expected_map.casefold() not in command_line.casefold():
            continue
        if started_at and str(info.get("CreationDate", "")) < str(started_at):
            continue
        candidates.append((pid, info))
    if len(candidates) != 1:
        return _skip_detached_session_cleanup(
            f"staging SC2 identity is ambiguous (expected one, found {len(candidates)})"
        )
    runtime_pid, runtime_info = candidates[0]
    if not _force_kill_process_tree(runtime_pid):
        return _skip_detached_session_cleanup(f"taskkill failed for staging PID {runtime_pid}")
    if not _wait_for_process_exit(runtime_pid):
        return _skip_detached_session_cleanup(f"taskkill accepted but staging PID {runtime_pid} is still live")
    _remove_runtime_record(SC2_RUNTIME_LEASE_PATH)
    _remove_runtime_record(WEBUI_SESSION_LEASE_PATH)
    return [f"sc2:{runtime_pid}"]


def _has_live_bound_webui_session():
    """Prevent a failed cleanup from overwriting the prior WebUI ownership record."""
    intent = _read_json_object(WEBUI_SESSION_LEASE_PATH)
    lease = _read_json_object(SC2_RUNTIME_LEASE_PATH)
    if not intent or not lease or lease.get("state") != "detached":
        return False
    runtime_pid = _lease_pid(lease, "runtimePid")
    return (
        intent.get("runtimePid") == runtime_pid
        and bool(intent.get("runtimeCreationDate"))
        and intent.get("leaseOwnerSessionId") == lease.get("ownerSessionId")
        and _get_process_info(runtime_pid) is not None
    )


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


def _wait_for_process_exit(pid, timeout=15.0):
    """Wait until a killed runtime disappears from the process table."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _get_process_info(pid) is None:
            return True
        time.sleep(0.25)
    return _get_process_info(pid) is None


def _force_stop_current_game():
    """终止当前 launcher，并只清理已绑定的 WebUI detached SC2 会话。"""
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

    killed.extend(_cleanup_webui_detached_session())
    killed.extend(_cleanup_webui_staging_session())

    if killed:
        _append_log(f"[webui] 强制重启: 已结束旧进程 {', '.join(killed)}")
    else:
        _append_log("[webui] 强制重启: 未发现由 WebUI 跟踪的 launcher")
    return killed


def _force_stop_all_game_processes():
    """Unconditionally stop every SC2 process before a WebUI restart.

    The restart action is explicitly user-authorized to replace an existing
    game, including one started outside this WebUI. Restrict the operation to
    the exact SC2 executable names and clear stale ownership records only after
    the process table is empty.
    """
    killed = []
    for pid, process_name in _list_game_processes():
        if not _force_kill_process_tree(pid):
            _append_log(f"[webui] 强制重启: 结束 {process_name}:{pid} 失败")
            continue
        if not _wait_for_process_exit(pid):
            _append_log(f"[webui] 强制重启: {process_name}:{pid} 仍在运行")
            continue
        killed.append(f"{process_name}:{pid}")

    if not _list_game_processes():
        _remove_runtime_record(SC2_RUNTIME_LEASE_PATH)
        _remove_runtime_record(WEBUI_SESSION_LEASE_PATH)

    if killed:
        _append_log(f"[webui] 无条件重启: 已结束旧进程 {', '.join(killed)}")
    else:
        _append_log("[webui] 无条件重启: 未发现 SC2/SC2Switcher 进程")
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
        # Map details are derived from the current source tree. A cached response
        # can make the WebUI appear to be showing an older scan result.
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        """Keep the editable WebUI shell fresh while developing locally."""
        static_path = self.path.split("?", 1)[0].lower()
        if static_path.endswith((".html", ".js", ".css")):
            self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

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
        if self.path == "/api/vibe/galaxy-script":
            try:
                self._send_json(_galaxy_user_script_payload())
            except (OSError, RuntimeError, ValueError) as exc:
                self._send_json({"error": str(exc)}, 500)
            return
        if self.path == "/api/vibe/sessions":
            try:
                self._send_json({"sessions": _runtime_console.sessions()})
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
            return
        if self.path.startswith("/api/vibe/call-log"):
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(self.path).query)
            try:
                limit = int(query.get("limit", [200])[0])
                self._send_json(_runtime_console.call_log(limit))
            except (TypeError, ValueError) as exc:
                self._send_json({"error": f"limit 无效: {exc}"}, 400)
            return
        if self.path.startswith("/api/vibe/event-log"):
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(self.path).query)
            try:
                limit = int(query.get("limit", [200])[0])
                self._send_json(_runtime_console.event_log(limit))
            except (TypeError, ValueError) as exc:
                self._send_json({"error": f"limit 无效: {exc}"}, 400)
            return
        if self.path == "/api/vibe/trace":
            current = _runtime_console.status()
            self._send_json({
                "schema_version": "douququ-runtime-trace.v1",
                "session_id": current.get("session_id", ""),
                "records": current.get("trace", []),
            })
            return
        if self.path == "/api/vibe/status":
            self._send_json(_runtime_console.status())
            return
        if self.path == "/api/vibe/observe":
            try:
                self._send_json({"success": True, "result": _runtime_console.observe()})
            except Exception as exc:
                self._send_json({"success": False, "error": str(exc)}, 502)
            return
        if self.path == "/api/buff-metadata":
            self._send_json(load_buff_metadata())
            return
        if self.path.startswith("/api/map-details"):
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(self.path).query)
            map_name = query.get("mapName", [""])[0]
            package_id = query.get("mapPackage", ["cmre"])[0] or "cmre"
            commander_id = query.get("commander", ["TerranAlenger3"])[0]
            if not map_name:
                self._send_json({"error": "mapName 不能为空"}, 400)
                return
            try:
                self._send_json(load_map_details(map_name, package_id, commander_id))
            except (FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
                self._send_json({
                    "schema_version": "cmre-map-details.v1",
                    "evidence_type": "static",
                    "status": "not_scanned",
                    "error": str(exc),
                }, 404)
            return
        if self.path == "/api/maps":
            try:
                self._send_json({
                    "maps": load_maps(),
                    "rebornMaps": load_reborn_maps(),
                    "revolutionMaps": load_revolution_maps(),
                })
            except (OSError, RuntimeError) as exc:
                self._send_json({"error": str(exc)}, 400)
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

        # DDS/TGA 文件：转 PNG 缓存
        cache_key = hashlib.md5(rel_path.encode("utf-8")).hexdigest()[:16]
        cache_root = MAP_PREVIEW_CACHE_DIR if rel_path.startswith("MapPreview/") else ASSETS_CACHE_DIR
        png_path = cache_root / f"{cache_key}.png"

        if not png_path.is_file():
            converter = convert_image_to_png if asset_path.suffix.lower() == ".tga" else convert_dds_to_png
            if not converter(asset_path, png_path):
                self.send_error(500, f"Image conversion failed: {rel_path}")
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
        if self.path == "/api/vibe/galaxy-script/validate":
            self._handle_vibe_galaxy_script_validate()
            return
        if self.path == "/api/vibe/galaxy-script/save":
            self._handle_vibe_galaxy_script_save()
            return
        if self.path == "/api/vibe/galaxy-script/stage":
            self._handle_vibe_galaxy_script_stage()
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
                "prefer_ai_opponent": body.get("preferAiOpponent", False),
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

    def _galaxy_script_body(self) -> str:
        body = self._read_body()
        source = body.get("source", "")
        if not isinstance(source, str):
            raise ValueError("source 必须是字符串")
        return source

    def _handle_vibe_galaxy_script_validate(self):
        try:
            validation = validate_source(self._galaxy_script_body())
            self._send_json({"success": validation["valid"], **validation})
        except Exception as exc:
            self._send_json({"success": False, "error": str(exc)}, 400)

    def _handle_vibe_galaxy_script_save(self):
        try:
            result = _save_galaxy_user_script(self._galaxy_script_body())
            self._send_json({"success": result["saved"], **result}, 200 if result["saved"] else 400)
        except Exception as exc:
            self._send_json({"success": False, "error": str(exc)}, 400)

    def _handle_vibe_galaxy_script_stage(self):
        try:
            result = _stage_galaxy_user_script(self._galaxy_script_body())
            self._send_json({"success": True, **result})
        except Exception as exc:
            self._send_json({"success": False, "error": str(exc)}, 500)

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
        """Build an explicit Revolution Overdrive map-plus-commander request."""
        map_name = body.get("mapName", "")
        faction = body.get("faction", "")
        commander = body.get("commander", "")
        if not faction and commander.startswith("RevolutionOverdrive"):
            faction = commander.removeprefix("RevolutionOverdrive")
        valid_maps = {entry["id"] for entry in load_revolution_maps()}
        native_commanders = {
            entry["id"]: entry["faction"] for entry in load_revolution_commanders()
        }
        valid_commanders = {
            entry["id"] for entry in load_commanders()
        } | set(native_commanders)
        if not commander and faction:
            commander = f"RevolutionOverdrive{faction}"
        if map_name not in valid_maps:
            self._send_json({"success": False, "error": f"未知起义狂潮地图: {map_name}"}, 400)
            return None
        if map_name == "tarcade.SC2Map":
            self._send_json({"success": False, "error": "tarcade 是入口流地图，尚不支持指挥官运行时适配"}, 400)
            return None
        if commander not in valid_commanders:
            self._send_json({"success": False, "error": f"未知起义狂潮适配指挥官: {commander}"}, 400)
            return None
        native_faction = native_commanders.get(commander, "")
        if native_faction:
            if faction and faction != native_faction:
                self._send_json({"success": False, "error": f"指挥官与阵营不一致: {commander}/{faction}"}, 400)
                return None
            faction = native_faction
        else:
            faction = ""
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
            "-Commander",
            commander,
        ]
        if faction:
            args.extend(["-Faction", faction])
        if listen_port > 0:
            args.extend(["-ListenPort", str(listen_port)])
        if os.environ.get("CMRE_WEBUI_DRY_RUN"):
            args.append("-NoLaunch")
        return {
            "kind": "revolution-overdrive",
            "args": args,
            "commander": commander,
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
        # A Revolution Overdrive map always uses its own launcher. The selected
        # manifest then stages only that commander's dependencies and overlays
        # the staged map; cross-category choices never fall back to a CMRE map.
        if body.get("packageId") == "revolution-overdrive" or body.get("mapPackage") == "revolution-overdrive":
            return self._build_revolution_launch_args(body)

        commander = body.get("commander", "TerranAlenger3")
        map_name = body.get("mapName", "亡者之夜.SC2Map")
        map_package = body.get("mapPackage", "cmre") or "cmre"
        # Keep the user-provided 斗蛐蛐 map self-identifying even when an older
        # frontend omits mapPackage from its launch payload.
        if re.search(r"斗蛐蛐|dou[-_ ]?ququ", str(map_name), re.IGNORECASE):
            map_package = "dou-ququ"
        if map_package not in {"cmre", "reborn", "revolution-overdrive", "dou-ququ"}:
            self._send_json({"success": False, "error": f"未知地图类别: {map_package}"}, 400)
            return None
        map_source_override = ""
        map_dependency_root = ""
        if map_package == "reborn":
            reborn_root = _load_local_source_binding("reborn-hots-071")
            map_source_override = str(reborn_root / map_name) if reborn_root else ""
        elif map_package == "revolution-overdrive":
            map_source_override = str(REVOLUTION_MAPS_ROOT / map_name)
            map_dependency_root = str(REVOLUTION_PACKAGE_ROOT)
        elif map_package == "dou-ququ":
            try:
                dou_ququ_root = _dou_ququ_map_root()
            except RuntimeError as exc:
                self._send_json({"success": False, "error": str(exc)}, 400)
                return None
            if dou_ququ_root is None:
                self._send_json(
                    {"success": False, "error": "未配置斗蛐蛐地图，请用 start-dou-ququ-runtime.ps1 -Map 指定原图"},
                    400,
                )
                return None
            map_source_override = str(dou_ququ_root)
        if map_package != "cmre" and (
            not map_source_override or not Path(map_source_override).is_dir()
        ):
            self._send_json(
                {"success": False, "error": f"地图源不存在或未绑定: {map_package}/{map_name}"},
                400,
            )
            return None
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
        enable_douququ = bool(body.get("enableDouQuquBehavior", False))
        enable_douququ_runtime = bool(body.get("enableDouQuquRuntime", False))
        if map_package == "dou-ququ":
            # The map package is a runtime development surface. Keep the
            # source map read-only and stage only the live VM by default;
            # static behavior/Catalog patching remains an explicit opt-in.
            enable_douququ_runtime = True
            api_minimal = True
        # 重生虫心指挥官：WebUI 透传 enableReborn + rebornCommander，
        # launcher 据此追加 -EnableReborn -RebornCommander <Name> 加载 5 个 Reborn mod 并应用
        # K5Kerrigan 替换逻辑。commander 形如 "ZergAbathur"，rebornCommander 为 "Abathur"。
        # A Reborn campaign map must load its own Reborn closure even when the
        # commander under test is official or Alenger. Only a Reborn commander
        # selection writes the cryswarmcoop commander preset.
        enable_reborn = bool(body.get("enableReborn", False)) or map_package == "reborn"
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
            # API clients attach after launcher readiness; keep the launcher
            # alive so SC2 remains protected by the runtime mutex and lease.
            args.append("-KeepAlive")
        if map_source_override:
            args.extend(["-MapSourceOverride", map_source_override])
        if map_dependency_root:
            args.extend(["-MapDependencyRootOverride", map_dependency_root])
        startup_contract = _find_startup_contract(map_name)
        if startup_contract is not None:
            args.extend(["-StartupContractOverride", str(startup_contract)])
        if api_minimal:
            args.append("-ApiMinimal")
        if enable_douququ:
            args.append("-EnableDouQuquBehavior")
        if enable_douququ_runtime:
            args.append("-EnableDouQuquRuntime")
        # 重生虫心参数透传：launcher 据此加载 5 个 Reborn mod 包并应用 K5Kerrigan 替换逻辑。
        # reborn_commander 必须是 reborn-commanders.json 中的 id（如 "Abathur"）。
        if enable_reborn:
            args.append("-EnableReborn")
        if enable_reborn and reborn_commander:
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
            "map_source_override": map_source_override,
            "enable_douququ": enable_douququ,
            "enable_douququ_runtime": enable_douququ_runtime,
            "commander": commander,
            "map_name": map_name,
            "map_package": map_package,
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
            "commander": ctx["commander"],
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
        _force_stop_all_game_processes()
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
        _force_stop_all_game_processes()
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
        _record_webui_launch_intent(proc, ctx)

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
    global DOU_QUQU_MAP_SOURCE
    parser = argparse.ArgumentParser(description="CMRE / 斗蛐蛐 WebUI 后端服务")
    parser.add_argument("--port", type=int, default=8767, help="监听端口")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument(
        "--dou-ququ-map",
        default=os.environ.get("DOU_QUQU_MAP", ""),
        help="用户斗蛐蛐 .SC2Map 原图或解包目录；仅读，运行时副本写入 artifacts",
    )
    args = parser.parse_args()
    if args.dou_ququ_map:
        DOU_QUQU_MAP_SOURCE = Path(args.dou_ququ_map).expanduser().resolve()
        if not DOU_QUQU_MAP_SOURCE.exists():
            parser.error(f"斗蛐蛐地图不存在: {DOU_QUQU_MAP_SOURCE}")

    server = ThreadingHTTPServer((args.host, args.port), CmreWebUIHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"CMRE / 斗蛐蛐 WebUI 服务已启动: {url}")
    if DOU_QUQU_MAP_SOURCE is not None:
        print(f"斗蛐蛐只读输入: {DOU_QUQU_MAP_SOURCE}")
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
