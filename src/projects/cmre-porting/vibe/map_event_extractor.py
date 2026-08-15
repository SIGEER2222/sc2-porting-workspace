"""Static extraction of map-owned units and scripted unit-producing events.

This module deliberately does not execute Galaxy. It reports three separate
source layers so a launcher can decide what is map-owned and what may be
adapted for a commander:

* ``preplaced``: ObjectUnit entries from the unpacked map;
* ``galaxy``: explicit unit creation calls and event helpers in MapScript;
* ``gamedata``: create/spawn/drop entries in map-local GameData XML.

Every finding carries its source file, line when available, and confidence.
The output is an inventory for adapter authoring, not runtime evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional


_FUNCTION_RE = re.compile(
    r"^\s*(?:bool|void|int|fixed|string|unit|point|region|timer|trigger|"
    r"playergroup|unitgroup|bank|abilcmd|order)\s+([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{"
)
_TRIGGER_DECL_RE = re.compile(r"^\s*trigger\s+([A-Za-z_]\w*)\s*;")
_CALL_RE = re.compile(
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<args>[^;\n]*)\)"
)
_STRING_RE = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')
_INTEGER_RE = re.compile(r"(?<![A-Za-z_])-?\d+(?![A-Za-z_])")
_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_ASSIGNMENT_RE = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<expression>"
    r"(?:RegionFromId|RegionFromName|RegionRandomPoint|PointWithOffsetPolar|Point)\s*\([^;]+\))"
)

_DIRECT_UNIT_CALLS = (
    "createunit",
    "createunits",
    "createunitswithdefaultfacing",
    "unitcreate",
    "unitcargo",
)
_EVENT_NAME_MARKERS = (
    "drop",
    "spawn",
    "wave",
    "attack",
    "create",
    "cargo",
    "rescue",
    "escort",
    "convoy",
    "event",
    "objective",
    "initial",
)
_NON_UNIT_LITERALS = {
    "",
    "Z",
    "Terran",
    "Zerg",
    "Protoss",
    "Neutral",
    "PingDiamond",
    "PingAlert",
    "PingWarning",
    "c_timeGame",
}
_NON_UNIT_PREFIXES = (
    "ping",
    "sound",
    "music",
    "portrait",
    "dialog",
    "ui",
    "route",
    "gt_",
    "gf_",
    "gv_",
    "lib",
    "obj",
    "auto",
)
_STRUCTURE_MARKERS = (
    "bunker",
    "base",
    "commandcenter",
    "hatchery",
    "lair",
    "hive",
    "nexus",
    "townhall",
    "facility",
    "tower",
    "cannon",
    "turret",
    "barracks",
    "factory",
    "starport",
    "gateway",
    "pylon",
    "spire",
    "den",
    "pool",
    "warren",
    "chamber",
)

_TIMING_CALLS = {
    "wait",
    "timerstart",
    "triggeraddeventtimeperiodic",
    "triggeraddeventtime",
    "triggeraddeventtimer",
}
_LOCATION_CALL_RE = re.compile(
    r"\b(?:RegionRandomPoint|RegionFromId|RegionFromName|RegionCircle|"
    r"PointWithOffsetPolar|Point|UnitGetPosition)\s*\(",
    re.IGNORECASE,
)
_EVENT_KIND_ZH = {
    "airdrop": "空投",
    "wave": "攻击波次",
    "spawn": "生成",
    "mission": "任务事件",
    "initialization": "初始化",
    "objective": "目标事件",
    "event": "事件",
    "script_create": "脚本创建",
    "gamedata": "数据定义",
}
_SYMBOL_WORD_ZH = {
    "ai": "AI",
    "attack": "攻击",
    "attacked": "受到攻击",
    "boss": "首领",
    "barricade": "路障",
    "cargo": "运输舱",
    "create": "创建",
    "defender": "防守者",
    "destroy": "摧毁",
    "drop": "空投",
    "event": "事件",
    "infested": "感染体",
    "initial": "初始化",
    "location": "位置",
    "night": "夜晚",
    "objective": "目标",
    "prepare": "准备",
    "random": "随机",
    "rescue": "营救",
    "send": "发送",
    "special": "特殊",
    "spawn": "生成",
    "start": "开始",
    "target": "目标",
    "transport": "运输机",
    "update": "更新",
    "wave": "波次",
    "white": "白噪音",
}

# These are only a last-resort display fallback. The extractor prefers the
# map/mod zhCN GameStrings files and keeps the catalog id in every record.
_FALLBACK_UNIT_NAMES_ZH = {
    "Baneling": "\u7206\u866b",
    "BroodLord": "\u6bcd\u5de2\u9886\u4e3b",
    "Hydralisk": "\u523a\u86c7",
    "InfestedAbominationBurrowed": "\u88ab\u611f\u67d3\u7684\u5f02\u53d8\u4f53",
    "InfestedCivilianBurrowed": "\u88ab\u611f\u67d3\u7684\u5e73\u6c11\uff08\u5730\u4e0b\uff09",
    "InfestedExploderBurrowed": "\u88ab\u611f\u67d3\u7684\u7206\u70b8\u4f53\uff08\u5730\u4e0b\uff09",
    "InfestedTerranCampaignBurrowed": "\u88ab\u611f\u67d3\u7684\u4eba\u7c7b\uff08\u5730\u4e0b\uff09",
    "Choker": "\u7f20\u7ed5\u8005",
    "Hunterling": "\u730e\u6740\u8005",
    "Kaboomer": "\u7206\u70b8\u8005",
    "Marine": "\u9646\u6218\u961f\u5458",
    "NydusCanal": "\u5730\u9053\u866b\u96a7\u9053",
    "Roach": "\u87d1\u8782",
    "SCV": "SCV\uff08\u5de5\u4eba\uff09",
    "Scourge": "\u5de8\u87f9",
    "Spotter": "\u89c2\u5bdf\u8005",
    "Stank": "\u81ed\u866b",
    "Zergling": "\u5b7d\u79cd",
}


def _strip_line_comment(line: str) -> str:
    """Remove a Galaxy line comment without touching quoted strings."""

    escaped = False
    quoted = False
    for index, char in enumerate(line):
        if char == "\\" and quoted:
            escaped = not escaped
            continue
        if char == '"' and not escaped:
            quoted = not quoted
        if not quoted and line[index : index + 2] == "//":
            return line[:index]
        escaped = False
    return line


def _split_args(value: str) -> list[str]:
    """Split a Galaxy argument list without breaking nested calls or strings."""

    result: list[str] = []
    start = 0
    depth = 0
    quoted = False
    escaped = False
    for index, char in enumerate(value):
        if char == "\\" and quoted:
            escaped = not escaped
            continue
        if char == '"' and not escaped:
            quoted = not quoted
        if not quoted:
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif char == "," and depth == 0:
                result.append(value[start:index].strip())
                start = index + 1
        escaped = False
    tail = value[start:].strip()
    if tail or value.strip():
        result.append(tail)
    return result


def _balanced_call(text: str, start: int) -> str:
    """Return the complete call expression beginning at ``start``."""

    open_index = text.find("(", start)
    if open_index < 0:
        return text[start:].strip()
    depth = 0
    quoted = False
    escaped = False
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "\\" and quoted:
            escaped = not escaped
            continue
        if char == '"' and not escaped:
            quoted = not quoted
        if not quoted:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1].strip()
        escaped = False
    return text[start:].strip()


def _find_call_expression(text: str, call_name: str) -> str:
    match = re.search(rf"\b{re.escape(call_name)}\s*\(", text, re.IGNORECASE)
    return _balanced_call(text, match.start()) if match else ""


def _xml_tag_lines(path: Path, tag: str, attribute: str) -> dict[str, list[int]]:
    """Index XML start-tag lines for source traceability."""

    result: dict[str, list[int]] = {}
    pattern = re.compile(
        rf"<{re.escape(tag)}\b[^>]*\b{re.escape(attribute)}\s*=\s*['\"]([^'\"]+)['\"]",
        re.IGNORECASE,
    )
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return result
    for line_number, line in enumerate(lines, start=1):
        for match in pattern.finditer(line):
            result.setdefault(match.group(1), []).append(line_number)
    return result


def _xml_id_lines(path: Path) -> dict[str, list[int]]:
    """Index any catalog element id for GameData source locations."""

    result: dict[str, list[int]] = {}
    pattern = re.compile(r"<([A-Za-z_][\w:.-]*)\b[^>]*\bid\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return result
    for line_number, line in enumerate(lines, start=1):
        for match in pattern.finditer(line):
            result.setdefault(match.group(2), []).append(line_number)
    return result


def _xml_line_for(lines: dict[str, list[int]], key: Any, used: Counter) -> Optional[int]:
    values = lines.get(str(key), [])
    index = used[str(key)]
    if index >= len(values):
        return values[-1] if values else None
    used[str(key)] += 1
    return values[index]


def _parse_localized_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return values
    for original in lines:
        line = original.strip()
        if not line or line.startswith("//") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values.setdefault(key.strip(), value.strip())
    return values


@lru_cache(maxsize=8)
def _load_localization_roots(root_names: tuple[str, ...]) -> dict[str, str]:
    """Load zhCN unit names and map text from configured local source roots."""

    values: dict[str, str] = {}
    seen_files: set[str] = set()
    for root_name in root_names:
        root = Path(root_name)
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else list(root.rglob("*.txt"))
        for path in sorted(candidates, key=lambda item: item.as_posix().casefold()):
            normalized = path.as_posix().casefold()
            if "zhcn.sc2data/localizeddata/" not in normalized:
                continue
            if path.name not in {"GameStrings.txt", "ObjectStrings.txt", "TriggerStrings.txt"}:
                continue
            if normalized in seen_files:
                continue
            seen_files.add(normalized)
            values.update(_parse_localized_file(path))
    return values


def _unit_name_zh(unit_type: str, localized: dict[str, str]) -> str:
    return (
        localized.get(f"Unit/Name/{unit_type}")
        or localized.get(f"Unit/{unit_type}")
        or _FALLBACK_UNIT_NAMES_ZH.get(unit_type)
        or unit_type
    )


def _symbol_name_zh(symbol: str) -> str:
    raw = re.sub(r"^(?:gf_|gt_|gv_|libNtve_gf_|lib[A-Za-z]+_gf_)", "", symbol)
    words = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+", raw)
    translated = []
    for word in words:
        translated.append(_SYMBOL_WORD_ZH.get(word.casefold(), word))
    return " ".join(translated) if translated else symbol


def _region_name_zh(name: str) -> str:
    replacements = (
        ("Destroyers Spawn", "\u6467\u6bc1\u8005\u751f\u6210\u533a"),
        ("Destroyers", "\u6467\u6bc1\u8005"),
        ("Barricade", "\u8def\u969c"),
        ("Spawn", "\u751f\u6210"),
        ("Area Revealer", "\u533a\u57df\u663e\u9732"),
        ("Attack", "\u653b\u51fb"),
        ("Location", "\u4f4d\u7f6e"),
        ("NorthWest", "\u897f\u5317"),
        ("NorthEast", "\u4e1c\u5317"),
        ("SouthWest", "\u897f\u5357"),
        ("SouthEast", "\u4e1c\u5357"),
        (" NW ", " \u897f\u5317 "),
        (" NE ", " \u4e1c\u5317 "),
        (" SW ", " \u897f\u5357 "),
        (" SE ", " \u4e1c\u5357 "),
    )
    translated = name
    for source, target in replacements:
        translated = translated.replace(source, target)
    return translated


def _format_seconds(value: Optional[float]) -> str:
    if value is None:
        return ""
    return str(int(value)) if value.is_integer() else f"{value:g}"


def _line_context(lines: list[str]) -> tuple[list[Optional[str]], list[dict]]:
    contexts: list[Optional[str]] = []
    declarations: list[dict] = []
    current: Optional[str] = None
    body_depth: Optional[int] = None
    brace_depth = 0

    for line_number, original in enumerate(lines, start=1):
        line = _strip_line_comment(original)
        match = _FUNCTION_RE.match(line)
        if match:
            current = match.group(1)
            body_depth = brace_depth + line.count("{") - line.count("}")
            declarations.append({"name": current, "line": line_number})
        trigger_match = _TRIGGER_DECL_RE.match(line)
        if trigger_match:
            name = trigger_match.group(1)
            if any(marker in name.lower() for marker in _EVENT_NAME_MARKERS):
                declarations.append({"name": name, "line": line_number})
        contexts.append(current)
        brace_depth += line.count("{") - line.count("}")
        if current is not None and body_depth is not None and brace_depth < body_depth:
            current = None
            body_depth = None
    return contexts, declarations


def _event_kind(name: str, symbol: str) -> str:
    lowered = f"{name} {symbol}".lower()
    if "drop" in lowered or "cargo" in lowered:
        return "airdrop"
    if "wave" in lowered or "attack" in lowered:
        return "wave"
    if "spawn" in lowered:
        return "spawn"
    if "rescue" in lowered or "escort" in lowered or "convoy" in lowered:
        return "mission"
    if "initial" in lowered or "init" in lowered:
        return "initialization"
    if "objective" in lowered:
        return "objective"
    if "event" in lowered or "trigger" in lowered:
        return "event"
    return "script_create"


def _is_unit_literal(value: str, *, direct_call: bool) -> bool:
    if not _TOKEN_RE.fullmatch(value) or value in _NON_UNIT_LITERALS:
        return False
    lowered = value.lower()
    if lowered.startswith(_NON_UNIT_PREFIXES):
        return False
    if lowered.endswith(("_func", "func")) or "trigger" in lowered and lowered.startswith(("gt", "auto")):
        return False
    if not direct_call and len(value) < 3:
        return False
    if not direct_call and lowered.endswith(("model", "portrait", "sound")):
        return False
    return True


def _timing_from_call(call_name: str, args: str) -> Optional[dict]:
    lowered = call_name.casefold()
    if lowered not in _TIMING_CALLS:
        return None
    parts = _split_args(args)
    if lowered == "wait":
        expression = parts[0] if parts else ""
        try:
            seconds = float(expression)
        except ValueError:
            seconds = None
        clock = parts[1] if len(parts) > 1 else ""
        return {
            "kind": "wait",
            "seconds": seconds,
            "expression": expression,
            "clock": clock,
            "text_zh": (
                f"等待 {_format_seconds(seconds)} 秒"
                if seconds is not None
                else f"等待时间参数 {expression or '未解析'}"
            ),
        }
    if lowered == "timerstart":
        expression = parts[1] if len(parts) > 1 else ""
        try:
            seconds = float(expression)
        except ValueError:
            seconds = None
        clock = parts[3] if len(parts) > 3 else ""
        return {
            "kind": "timer_start",
            "seconds": seconds,
            "expression": expression,
            "clock": clock,
            "timer": parts[0] if parts else "",
            "text_zh": (
                f"启动 {_format_seconds(seconds)} 秒计时器"
                if seconds is not None
                else f"启动计时器（时间参数 {expression or '未解析'}）"
            ),
        }
    if lowered == "triggeraddeventtimeperiodic":
        expression = parts[1] if len(parts) > 1 else ""
        try:
            seconds = float(expression)
        except ValueError:
            seconds = None
        clock = parts[2] if len(parts) > 2 else ""
        return {
            "kind": "periodic",
            "seconds": seconds,
            "expression": expression,
            "clock": clock,
            "trigger": parts[0] if parts else "",
            "text_zh": (
                f"每 {_format_seconds(seconds)} 秒触发一次"
                if seconds is not None
                else f"按周期参数 {expression or '未解析'} 触发"
            ),
        }
    if lowered == "triggeraddeventtime":
        expression = parts[1] if len(parts) > 1 else ""
        try:
            seconds = float(expression)
        except ValueError:
            seconds = None
        clock = parts[2] if len(parts) > 2 else ""
        return {
            "kind": "time_event",
            "seconds": seconds,
            "expression": expression,
            "clock": clock,
            "trigger": parts[0] if parts else "",
            "text_zh": (
                f"游戏时间 {_format_seconds(seconds)} 秒时触发"
                if seconds is not None
                else f"按时间参数 {expression or '未解析'} 触发"
            ),
        }
    return {
        "kind": "timer_event",
        "seconds": None,
        "expression": parts[1] if len(parts) > 1 else "",
        "clock": "",
        "trigger": parts[0] if parts else "",
        "text_zh": "计时器事件触发",
    }


def _region_reference(expression: str, region_by_id: dict[str, dict], region_by_name: dict[str, dict]) -> Optional[dict]:
    expression = expression.strip()
    match = re.search(r"RegionFromId\s*\(\s*(\d+)\s*\)", expression, re.IGNORECASE)
    if match:
        return region_by_id.get(match.group(1)) or {"id": int(match.group(1))}
    match = re.search(r"RegionFromName\s*\(\s*\"([^\"]+)\"\s*\)", expression, re.IGNORECASE)
    if match:
        return region_by_name.get(match.group(1)) or {"name": match.group(1)}
    return region_by_id.get(expression) or region_by_name.get(expression)


def _relative_path(path: Path, source_root: Optional[Path]) -> str:
    if source_root is not None:
        try:
            return path.resolve().relative_to(source_root.resolve()).as_posix()
        except ValueError:
            pass
    return path.name


def _is_structure(unit_type: str) -> bool:
    lowered = unit_type.lower()
    return any(marker in lowered for marker in _STRUCTURE_MARKERS)


class MapEventExtractor:
    """Extract map-owned units and unit-producing script/data events."""

    def __init__(
        self,
        map_dir: str | Path,
        *,
        source_root: str | Path | None = None,
        localization_roots: Iterable[str | Path] | None = None,
    ):
        self.map_dir = Path(map_dir)
        self.source_root = Path(source_root) if source_root is not None else None
        self.localization_roots = tuple(Path(item) for item in (localization_roots or ()))
        self._localized = _load_localization_roots(tuple(
            str(item.resolve()) for item in (self.localization_roots + (self.map_dir,))
        ))
        self._timings: list[dict] = []
        self.regions = self._extract_regions()
        self._regions_by_id = {str(item["id"]): item for item in self.regions}
        self._regions_by_name = {
            item["name"]: item for item in self.regions if item.get("name")
        }

    def extract(self) -> dict:
        if not self.map_dir.is_dir():
            raise FileNotFoundError(f"map directory not found: {self.map_dir}")
        preplaced = self._extract_preplaced()
        galaxy_events, galaxy_declarations = self._extract_galaxy()
        gamedata_events = self._extract_gamedata()
        all_events = [*galaxy_events, *gamedata_events]
        unit_counts = Counter(item["unit_type"] for item in preplaced)
        scripted_units = Counter(
            unit_type
            for event in all_events
            for unit_type in event.get("unit_types", [])
        )
        event_counts = Counter(event["event_kind"] for event in all_events)
        return {
            "schema_version": "cmre-map-unit-events.v2",
            "evidence_type": "static",
            "runtime_claim": "none; this inventory is static source analysis",
            "map_name": self.map_dir.name,
            "map_path": _relative_path(self.map_dir, self.source_root),
            "map_metadata": {
                "name_zh": self._localized.get("DocInfo/Name", self.map_dir.stem),
                "description_zh": self._localized.get("DocInfo/DescLong", ""),
            },
            "preplaced": preplaced,
            "events": all_events,
            "timings": self._timings,
            "regions": self.regions,
            "event_declarations": galaxy_declarations,
            "unit_catalog": self._unit_catalog(preplaced, all_events),
            "summary": {
                "preplaced_count": len(preplaced),
                "preplaced_unit_counts": dict(sorted(unit_counts.items())),
                "scripted_event_count": len(all_events),
                "scripted_unit_counts": dict(sorted(scripted_units.items())),
                "event_counts": dict(sorted(event_counts.items())),
                "structure_count": sum(1 for item in preplaced if item["is_structure"]),
                "player_ids": sorted({item["player_id"] for item in preplaced}),
                "region_count": len(self.regions),
                "timing_count": len(self._timings),
            },
        }

    def _unit_catalog(self, preplaced: list[dict], events: list[dict]) -> list[dict]:
        unit_types = {
            item["unit_type"] for item in preplaced
        }
        unit_types.update(
            unit_type
            for event in events
            for unit_type in event.get("unit_types", [])
        )
        return [
            {
                "id": unit_type,
                "name_zh": _unit_name_zh(unit_type, self._localized),
                "catalog_id": unit_type,
            }
            for unit_type in sorted(unit_types, key=str.casefold)
        ]

    def _extract_regions(self) -> list[dict]:
        path = self.map_dir / "Regions"
        if not path.is_file():
            return []
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            return []
        region_lines = _xml_tag_lines(path, "region", "id")
        used_lines: Counter = Counter()
        regions = []
        for element in root.findall(".//region"):
            region_id = element.get("id", "")
            name_node = element.find("name")
            name = name_node.get("value", "") if name_node is not None else ""
            shapes = []
            for shape in element.findall("shape"):
                shape_record: dict[str, Any] = {"type": shape.get("type", "unknown")}
                center = shape.find("center")
                if center is not None:
                    coords = center.get("value", "").split(",")
                    try:
                        shape_record["center"] = [float(coords[0]), float(coords[1])]
                    except (IndexError, ValueError):
                        shape_record["center_expression"] = center.get("value", "")
                radius = shape.find("radius")
                if radius is not None:
                    try:
                        shape_record["radius"] = float(radius.get("value", ""))
                    except ValueError:
                        shape_record["radius_expression"] = radius.get("value", "")
                for child_name in ("min", "max", "point", "vertex"):
                    values = [node.get("value", "") for node in shape.findall(child_name)]
                    if values:
                        shape_record[child_name] = values
                shapes.append(shape_record)
            line = _xml_line_for(region_lines, region_id, used_lines)
            regions.append({
                "id": int(region_id) if region_id.isdigit() else region_id,
                "name": name,
                "name_zh": _region_name_zh(name),
                "shapes": shapes,
                "source_file": _relative_path(path, self.source_root),
                "line": line,
                "source": {
                    "file": _relative_path(path, self.source_root),
                    "line": line,
                },
            })
        return regions

    def _location_details(
        self,
        args: str,
        region_variables: dict[str, str],
        point_variables: dict[str, str],
    ) -> Optional[dict]:
        match = _LOCATION_CALL_RE.search(args)
        if not match:
            variable = args.strip()
            expression = region_variables.get(variable) or point_variables.get(variable)
            if expression:
                return self._location_details(expression, region_variables, point_variables)
            return None
        expression = _balanced_call(args, match.start())
        call_name = re.match(r"([A-Za-z_]\w*)", expression).group(1)
        lowered = call_name.casefold()
        inside = expression[expression.find("(") + 1 : -1]
        if lowered == "regionrandompoint":
            reference_expression = inside.strip()
            reference = region_variables.get(reference_expression, reference_expression)
            region = _region_reference(reference, self._regions_by_id, self._regions_by_name)
            result = {
                "kind": "region_random_point",
                "expression": expression,
                "random": True,
                "region_expression": reference,
            }
            if region:
                result["region"] = region
            return result
        if lowered in {"regionfromid", "regionfromname"}:
            region = _region_reference(expression, self._regions_by_id, self._regions_by_name)
            return {
                "kind": "region",
                "expression": expression,
                "region": region,
            }
        if lowered == "point":
            parts = _split_args(inside)
            coordinates = []
            for part in parts[:3]:
                try:
                    coordinates.append(float(part))
                except ValueError:
                    break
            return {
                "kind": "point",
                "expression": expression,
                "coordinates": coordinates or None,
            }
        if lowered == "unitgetposition":
            return {"kind": "unit_position", "expression": expression}
        return {"kind": "point_expression", "expression": expression}

    def _timing_text(self, timing: Optional[dict]) -> str:
        if not timing:
            return "未在当前源码上下文中确定时间"
        text = timing.get("text_zh", "")
        clock = timing.get("clock")
        return f"{text}（时钟：{clock}）" if clock else text

    def _event_content_zh(self, event: dict) -> str:
        kind = _EVENT_KIND_ZH.get(event.get("event_kind", ""), "事件")
        units = []
        names = event.get("unit_names_zh", {})
        for unit_type in event.get("unit_types", []):
            label = names.get(unit_type, unit_type)
            quantity = event.get("quantity_hint")
            units.append(
                f"{quantity} × {label}（{unit_type}）"
                if quantity is not None and len(event.get("unit_types", [])) == 1
                else f"{label}（{unit_type}）"
            )
        action = "、".join(units) if units else "未解析单位"
        location = event.get("location_text_zh", "位置未解析")
        return f"{kind}：生成/提供 {action}；位置：{location}。"

    def _extract_preplaced(self) -> list[dict]:
        path = self.map_dir / "Objects"
        if not path.is_file():
            return []
        root = ET.parse(path).getroot()
        object_lines = _xml_tag_lines(path, "ObjectUnit", "Id")
        used_lines: Counter = Counter()
        results = []
        for element in root.iter("ObjectUnit"):
            unit_type = element.get("UnitType", "").strip()
            if not unit_type:
                continue
            position = element.get("Position", "0,0,0").split(",")
            try:
                x = float(position[0])
                y = float(position[1])
            except (IndexError, ValueError):
                continue
            try:
                player_id = int(element.get("Player", "0"))
            except ValueError:
                player_id = 0
            try:
                object_id = int(element.get("Id", ""))
            except ValueError:
                object_id = None
            line_number = _xml_line_for(object_lines, object_id, used_lines)
            results.append(
                {
                    "source_kind": "preplaced",
                    "source_file": _relative_path(path, self.source_root),
                    "line": line_number,
                    "source": {
                        "file": _relative_path(path, self.source_root),
                        "line": line_number,
                    },
                    "object_id": object_id,
                    "unit_type": unit_type,
                    "unit_name_zh": _unit_name_zh(unit_type, self._localized),
                    "player_id": player_id,
                    "x": x,
                    "y": y,
                    "is_structure": _is_structure(unit_type),
                    "confidence": "high",
                }
            )
        return results

    def _extract_galaxy(self) -> tuple[list[dict], list[dict]]:
        path = self.map_dir / "MapScript.galaxy"
        if not path.is_file():
            return [], []
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        contexts, declarations = _line_context(lines)
        declaration_by_name = {item["name"]: item["line"] for item in declarations}
        declarations = [
            {
                **item,
                "name_zh": _symbol_name_zh(item["name"]),
                "source_file": _relative_path(path, self.source_root),
                "source": {
                    "file": _relative_path(path, self.source_root),
                    "line": item["line"],
                },
            }
            for item in declarations
        ]
        events = []
        region_variables: dict[str, str] = {}
        point_variables: dict[str, str] = {}
        last_timing: dict[str, dict] = {}
        for line_number, original in enumerate(lines, start=1):
            line = _strip_line_comment(original)
            if not line.strip():
                continue
            symbol = contexts[line_number - 1] or "<global>"
            for assignment in _ASSIGNMENT_RE.finditer(line):
                variable = assignment.group("name")
                expression = assignment.group("expression")
                if expression.casefold().startswith(("regionfromid", "regionfromname")):
                    region_variables[variable] = expression
                else:
                    point_variables[variable] = expression
            for match in _CALL_RE.finditer(line):
                call_name = match.group("name")
                lowered = call_name.lower()
                timing = _timing_from_call(call_name, match.group("args"))
                source_file = _relative_path(path, self.source_root)
                source = {"file": source_file, "line": line_number}
                if timing:
                    timing_record = {
                        "source_kind": "galaxy_timing",
                        "source_file": source_file,
                        "line": line_number,
                        "source": source,
                        "symbol": symbol,
                        "symbol_zh": _symbol_name_zh(symbol),
                        "call": call_name,
                        "event_kind": "timing",
                        "timing": timing,
                        "trigger_point": {
                            "function": symbol,
                            "function_zh": _symbol_name_zh(symbol),
                            "call": call_name,
                            "declaration_line": declaration_by_name.get(symbol),
                            "source": source,
                        },
                        "evidence": original.strip(),
                    }
                    self._timings.append(timing_record)
                    last_timing[symbol] = timing
                if not any(marker in lowered for marker in _EVENT_NAME_MARKERS):
                    continue
                direct_call = (
                    not lowered.startswith("trigger")
                    and any(marker in lowered for marker in _DIRECT_UNIT_CALLS)
                )
                literals = [value.replace('\\"', '"') for value in _STRING_RE.findall(match.group("args"))]
                # Trigger registration/creation calls carry ability ids,
                # trigger names, and catalog tokens, not spawned unit types.
                if lowered.startswith("trigger") and not direct_call:
                    literals = []
                unit_types = [
                    value for value in literals
                    if _is_unit_literal(value, direct_call=direct_call)
                ]
                if not unit_types:
                    continue
                parts = _split_args(match.group("args"))
                quantity_hint = None
                if direct_call and parts:
                    try:
                        quantity_hint = int(parts[0])
                    except ValueError:
                        pass
                if quantity_hint is None:
                    quantity_match = _INTEGER_RE.search(match.group("args"))
                    quantity_hint = int(quantity_match.group(0)) if quantity_match else None
                timing = dict(last_timing.get(symbol, {})) or None
                location = self._location_details(
                    match.group("args"), region_variables, point_variables
                )
                event = {
                    "source_kind": "galaxy_create" if direct_call else "galaxy_event",
                    "source_file": source_file,
                    "line": line_number,
                    "source": source,
                    "symbol": symbol,
                    "symbol_zh": _symbol_name_zh(symbol),
                    "call": call_name,
                    "event_kind": _event_kind(call_name, symbol),
                    "unit_types": unit_types,
                    "unit_names_zh": {
                        unit_type: _unit_name_zh(unit_type, self._localized)
                        for unit_type in unit_types
                    },
                    "quantity_hint": quantity_hint,
                    "timing": timing,
                    "time_text_zh": self._timing_text(timing),
                    "location": location,
                    "location_text_zh": self._location_text_zh(location),
                    "trigger_point": {
                        "function": symbol,
                        "function_zh": _symbol_name_zh(symbol),
                        "call": call_name,
                        "declaration_line": declaration_by_name.get(symbol),
                        "source": source,
                    },
                    "confidence": "high" if direct_call else "medium",
                    "evidence": original.strip(),
                }
                event["content_zh"] = self._event_content_zh(event)
                events.append(event)
        return events, declarations

    def _location_text_zh(self, location: Optional[dict]) -> str:
        if not location:
            return "位置未解析"
        if location.get("kind") == "region_random_point":
            region = location.get("region") or {}
            label = region.get("name_zh") or (
                f"区域 {region.get('id')}" if region.get("id") is not None else location.get("region_expression", "未知区域")
            )
            return f"{label}内随机点"
        if location.get("kind") == "region":
            region = location.get("region") or {}
            return region.get("name_zh") or f"区域 {region.get('id', '未解析')}"
        coordinates = location.get("coordinates")
        if coordinates:
            return "坐标 (" + ", ".join(f"{value:g}" for value in coordinates) + ")"
        return f"表达式 {location.get('expression', '未解析')}"

    def _extract_gamedata(self) -> list[dict]:
        root = self.map_dir / "Base.SC2Data" / "GameData"
        if not root.is_dir():
            return []
        events = []
        for path in sorted(root.glob("*.xml")):
            if path.name.lower() not in {
                "effectdata.xml",
                "abildata.xml",
                "behaviordata.xml",
                "gamedata.xml",
            }:
                continue
            try:
                xml_root = ET.parse(path).getroot()
            except ET.ParseError:
                continue
            element_lines = _xml_id_lines(path)
            used_lines: Counter = Counter()
            for element in xml_root.iter():
                tag = element.tag.rsplit("}", 1)[-1]
                identity = f"{tag} {element.get('id', '')}".lower()
                if not any(marker in identity for marker in ("createunit", "spawn", "drop", "cargo")):
                    continue
                unit_types = []
                for key, value in element.attrib.items():
                    key_lower = key.lower()
                    if key_lower not in {"unit", "unittype", "unitid", "value", "link", "spawnunit"}:
                        continue
                    if _is_unit_literal(value, direct_call=False):
                        unit_types.append(value)
                for child in element.iter():
                    if child is element:
                        continue
                    for key, value in child.attrib.items():
                        key_lower = key.lower()
                        if key_lower not in {"unit", "unittype", "unitid", "value", "link", "spawnunit"}:
                            continue
                        if _is_unit_literal(value, direct_call=False):
                            unit_types.append(value)
                unit_types = sorted(set(unit_types))
                if not unit_types:
                    continue
                symbol = element.get("id", tag)
                source_file = _relative_path(path, self.source_root)
                line_number = _xml_line_for(element_lines, symbol, used_lines)
                source = {"file": source_file, "line": line_number}
                event = {
                    "source_kind": "gamedata",
                    "source_file": source_file,
                    "line": line_number,
                    "source": source,
                    "symbol": symbol,
                    "symbol_zh": _symbol_name_zh(symbol),
                    "call": tag,
                    "event_kind": _event_kind(tag, symbol),
                    "unit_types": unit_types,
                    "unit_names_zh": {
                        unit_type: _unit_name_zh(unit_type, self._localized)
                        for unit_type in unit_types
                    },
                    "quantity_hint": None,
                    "timing": None,
                    "time_text_zh": "数据定义未声明运行时触发时间",
                    "location": None,
                    "location_text_zh": "由数据定义或调用方决定",
                    "trigger_point": {
                        "function": symbol,
                        "function_zh": _symbol_name_zh(symbol),
                        "call": tag,
                        "declaration_line": line_number,
                        "source": source,
                    },
                    "confidence": "medium",
                    "evidence": ET.tostring(element, encoding="unicode")[:500],
                }
                event["content_zh"] = self._event_content_zh(event)
                events.append(event)
        return events


def discover_map_dirs(root: str | Path) -> list[Path]:
    path = Path(root)
    if path.is_dir() and (path / "Objects").is_file():
        return [path]
    direct = [item for item in path.glob("*.SC2Map") if item.is_dir()]
    if direct:
        return sorted(direct, key=lambda item: item.name)
    return sorted(
        (
            item
            for item in path.rglob("*.SC2Map")
            if item.is_dir() and ((item / "Objects").is_file() or (item / "MapScript.galaxy").is_file())
        ),
        key=lambda item: item.as_posix(),
    )


def extract_map_tree(root: str | Path) -> dict:
    root_path = Path(root)
    maps = [
        MapEventExtractor(map_dir, source_root=root_path).extract()
        for map_dir in discover_map_dirs(root_path)
    ]
    return {
        "schema_version": "cmre-map-unit-events.v2",
        "evidence_type": "static",
        "runtime_claim": "none; this inventory is static source analysis",
        "source_root": root_path.name,
        "map_count": len(maps),
        "maps": maps,
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maps-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    payload = extract_map_tree(args.maps_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"map_count": payload["map_count"], "output": args.output.as_posix()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
