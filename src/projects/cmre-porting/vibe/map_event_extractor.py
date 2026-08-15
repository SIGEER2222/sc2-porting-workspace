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
from pathlib import Path
from typing import Iterable, Optional


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
    if not direct_call and len(value) < 3:
        return False
    if not direct_call and lowered.endswith(("model", "portrait", "sound")):
        return False
    return True


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

    def __init__(self, map_dir: str | Path, *, source_root: str | Path | None = None):
        self.map_dir = Path(map_dir)
        self.source_root = Path(source_root) if source_root is not None else None

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
            "schema_version": "cmre-map-unit-events.v1",
            "evidence_type": "static",
            "runtime_claim": "none; this inventory is static source analysis",
            "map_name": self.map_dir.name,
            "map_path": _relative_path(self.map_dir, self.source_root),
            "preplaced": preplaced,
            "events": all_events,
            "event_declarations": galaxy_declarations,
            "summary": {
                "preplaced_count": len(preplaced),
                "preplaced_unit_counts": dict(sorted(unit_counts.items())),
                "scripted_event_count": len(all_events),
                "scripted_unit_counts": dict(sorted(scripted_units.items())),
                "event_counts": dict(sorted(event_counts.items())),
                "structure_count": sum(1 for item in preplaced if item["is_structure"]),
                "player_ids": sorted({item["player_id"] for item in preplaced}),
            },
        }

    def _extract_preplaced(self) -> list[dict]:
        path = self.map_dir / "Objects"
        if not path.is_file():
            return []
        root = ET.parse(path).getroot()
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
            results.append(
                {
                    "source_kind": "preplaced",
                    "source_file": _relative_path(path, self.source_root),
                    "line": None,
                    "object_id": object_id,
                    "unit_type": unit_type,
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
        events = []
        for line_number, original in enumerate(lines, start=1):
            line = _strip_line_comment(original)
            if not line.strip():
                continue
            symbol = contexts[line_number - 1] or "<global>"
            for match in _CALL_RE.finditer(line):
                call_name = match.group("name")
                lowered = call_name.lower()
                if not any(marker in lowered for marker in _EVENT_NAME_MARKERS):
                    continue
                direct_call = any(marker in lowered for marker in _DIRECT_UNIT_CALLS)
                literals = [value.replace('\\"', '"') for value in _STRING_RE.findall(match.group("args"))]
                unit_types = [
                    value for value in literals
                    if _is_unit_literal(value, direct_call=direct_call)
                ]
                if not unit_types:
                    continue
                quantity_match = _INTEGER_RE.search(match.group("args"))
                quantity_hint = int(quantity_match.group(0)) if quantity_match else None
                events.append(
                    {
                        "source_kind": "galaxy_create" if direct_call else "galaxy_event",
                        "source_file": _relative_path(path, self.source_root),
                        "line": line_number,
                        "symbol": symbol,
                        "call": call_name,
                        "event_kind": _event_kind(call_name, symbol),
                        "unit_types": unit_types,
                        "quantity_hint": quantity_hint,
                        "confidence": "high" if direct_call else "medium",
                        "evidence": original.strip(),
                    }
                )
        return events, declarations

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
                events.append(
                    {
                        "source_kind": "gamedata",
                        "source_file": _relative_path(path, self.source_root),
                        "line": None,
                        "symbol": element.get("id", tag),
                        "call": tag,
                        "event_kind": _event_kind(tag, element.get("id", "")),
                        "unit_types": unit_types,
                        "quantity_hint": None,
                        "confidence": "medium",
                        "evidence": ET.tostring(element, encoding="unicode")[:500],
                    }
                )
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
        "schema_version": "cmre-map-unit-events.v1",
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
