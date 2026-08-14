#!/usr/bin/env python3
"""Build a fail-closed startup/unit contract from an original SC2 map.

The scanner deliberately reports facts and unresolved expressions separately.
It does not infer a commander base or worker from a race.  The resulting JSON
is consumed by the launcher as the source-of-truth guard for map adaptation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Iterable


SC2_MAP_SUFFIX = ".SC2Map"
PLAYER_IDS = (1, 2)
SPAWN_ANCHOR_TYPES = {"ACHeroSpawnPlacement"}
MISSION_START_STRUCTURE_TYPES = {"CODResearchFacility"}
CREATE_NAMES = (
    "UnitCreate",
    "libNtve_gf_CreateUnitsWithDefaultFacing",
    "libNtve_gf_CreateUnitsAtPoint2",
    "libNtve_gf_CreateUnitsAtPoint",
)
CREATE_PATTERN = re.compile(
    r"(?P<name>UnitCreate|libNtve_gf_CreateUnitsWithDefaultFacing|"
    r"libNtve_gf_CreateUnitsAtPoint2|libNtve_gf_CreateUnitsAtPoint)\s*\("
)
FUNCTION_PATTERN = re.compile(
    r"(?m)^\s*(?:static\s+)?(?:bool|void|int|fixed|string|text|unit|"
    r"unitgroup|point|region|playergroup|trigger|bank|timer|color|"
    r"funcref\s*<[^>]+>)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^\n]*\)\s*\{"
)
UNIT_FROM_ID_PATTERN = re.compile(r"\bUnitFromId\s*\((?P<arg>[^\n()]*)\)")
UNIT_GROUP_PATTERN = re.compile(r"\bUnitGroup\s*\(")
PREVENT_DEFEAT_PATTERN = re.compile(r"c_targetFilterPreventDefeat")
MAP_INIT_PATTERN = re.compile(r"TriggerAddEventMapInit\s*\(\s*(?P<trigger>[A-Za-z_][A-Za-z0-9_]*)")
START_LOCATION_PATTERN = re.compile(r"\bPlayerStartLocation\s*\(\s*(?P<arg>[^\n()]*)\)")
TRIGGER_EXECUTE_PATTERN = re.compile(r"\bTriggerExecute\s*\(\s*(?P<trigger>[A-Za-z_][A-Za-z0-9_]*)")
TRIGGER_MAP_INIT_PATTERN = re.compile(
    r"\bTriggerAddEventMapInit\s*\(\s*(?P<trigger>[A-Za-z_][A-Za-z0-9_]*)"
)
GENERIC_CALL_PATTERN = re.compile(r"\b(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(")
STARTUP_COMMENT_MARKERS = {
    "initialization",
    "initial gameplay",
    "worker start harvesting",
    "timer startup",
    "starting game q",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def line_excerpt(text: str, offset: int) -> str:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    if end < 0:
        end = len(text)
    return text[start:end].strip()


def split_arguments(value: str) -> list[str]:
    """Split a Galaxy call while respecting nested calls and quoted strings."""

    result: list[str] = []
    start = 0
    depth = 0
    quoted = False
    escaped = False
    for index, char in enumerate(value):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            result.append(value[start:index].strip())
            start = index + 1
    result.append(value[start:].strip())
    return result


def balanced_call(text: str, open_offset: int) -> tuple[str, int] | None:
    depth = 1
    quoted = False
    escaped = False
    for index in range(open_offset, len(text)):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[open_offset:index], index + 1
    return None


def function_at(text: str, offset: int) -> tuple[str, int] | None:
    candidates = list(FUNCTION_PATTERN.finditer(text, 0, offset + 1))
    if not candidates:
        return None
    candidate = candidates[-1]
    depth = 0
    quoted = False
    escaped = False
    for index in range(candidate.end() - 1, len(text)):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return candidate.group("name"), line_number(text, candidate.start())
    return candidate.group("name"), line_number(text, candidate.start())


def player_scope(expression: str) -> str:
    value = expression.strip()
    normalized = value.upper()
    if value == "1" or "P1_USER" in normalized or "PLAYER_01_USER" in normalized:
        return "P1"
    if value == "2" or "P2_USER" in normalized or "PLAYER_02_USER" in normalized:
        return "P2"
    return "unknown"


def literal_string(expression: str) -> str | None:
    value = expression.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return None


def localized_trigger_names(map_dir: Path) -> dict[str, str]:
    """Read trigger names only for human-readable evidence; IDs remain authoritative."""

    names: dict[str, str] = {}
    for locale in ("zhCN", "enUS"):
        path = map_dir / f"{locale}.SC2Data" / "LocalizedData" / "TriggerStrings.txt"
        if not path.exists():
            continue
        for line in read_text(path).splitlines():
            if not line.startswith("Trigger/Name/") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            trigger_id = key.rsplit("/", 1)[-1]
            names.setdefault(trigger_id, value.strip())
    return names


def trigger_param_value(
    param: ET.Element,
    elements: dict[tuple[str, str], ET.Element],
    seen: set[tuple[str, str]] | None = None,
) -> dict:
    """Resolve a TriggerData Param without evaluating expressions."""

    seen = set() if seen is None else seen
    key = (param.get("Type", "Param"), param.get("Id", ""))
    if key in seen:
        return {"kind": "unknown", "reason": "param_cycle", "id": key[1]}
    seen.add(key)
    value = next((child.text.strip() for child in param if child.tag == "Value" and child.text), None)
    value_type = next((child.get("Type") for child in param if child.tag == "ValueType"), None)
    preset = next((child for child in param if child.tag == "Preset"), None)
    value_element = next((child for child in param if child.tag == "ValueElement"), None)
    function_call = next((child for child in param if child.get("Type") == "FunctionCall"), None)
    result = {"id": param.get("Id"), "valueType": value_type}
    if value is not None:
        result.update({"kind": "literal", "value": value})
    elif preset is not None:
        result.update(
            {
                "kind": "preset",
                "library": preset.get("Library"),
                "presetId": preset.get("Id"),
            }
        )
    elif value_element is not None:
        result.update(
            {
                "kind": "element_ref",
                "elementType": value_element.get("Type"),
                "elementId": value_element.get("Id"),
            }
        )
    elif function_call is not None:
        result.update(
            {
                "kind": "function_call_ref",
                "functionCallId": function_call.get("Id"),
            }
        )
    else:
        result.update({"kind": "unknown", "reason": "param_has_no_resolvable_value"})
    return result


def trigger_function_call(
    call: ET.Element,
    elements: dict[tuple[str, str], ET.Element],
) -> dict:
    function_def = next((child for child in call if child.get("Type") == "FunctionDef"), None)
    record = {
        "id": call.get("Id"),
        "functionDef": (
            {
                "library": function_def.get("Library"),
                "id": function_def.get("Id"),
            }
            if function_def is not None
            else None
        ),
        "parameters": [],
    }
    for parameter in (child for child in call if child.tag == "Parameter"):
        param_key = ("Param", parameter.get("Id", ""))
        param = elements.get(param_key)
        if param is None:
            record["parameters"].append(
                {"id": parameter.get("Id"), "kind": "unknown", "reason": "param_reference_missing"}
            )
        else:
            record["parameters"].append(trigger_param_value(param, elements))
    return record


def scan_triggers(map_dir: Path) -> dict:
    """Parse the SC2 TriggerData registry and retain startup action order."""

    path = map_dir / "Triggers"
    if not path.exists():
        return {
            "path": "Triggers",
            "sha256": None,
            "status": "unknown",
            "unknowns": [{"kind": "missing_file", "path": "Triggers"}],
        }
    root = ET.parse(path).getroot()
    elements = {
        (node.get("Type"), node.get("Id")): node
        for node in root.findall("Element")
        if node.get("Type") and node.get("Id")
    }
    names = localized_trigger_names(map_dir)
    unknowns: list[dict] = []
    trigger_records: list[dict] = []
    startup_records: list[dict] = []
    for (element_type, element_id), trigger in elements.items():
        if element_type != "Trigger":
            continue
        comments: list[str] = []
        actions: list[dict] = []
        for index, reference in enumerate(trigger):
            reference_role = reference.tag
            reference_type = reference.get("Type")
            reference_id = reference.get("Id")
            target = elements.get((reference_type, reference_id))
            if reference_type == "Comment":
                if target is None:
                    unknowns.append(
                        {"kind": "trigger_comment_missing", "triggerId": element_id, "referenceId": reference_id}
                    )
                    continue
                comments.append(" ".join("".join(target.itertext()).split()))
                continue
            if reference_role not in {"Action", "Condition"}:
                continue
            if target is None or target.get("Type") != "FunctionCall":
                unknowns.append(
                    {"kind": "trigger_action_missing", "triggerId": element_id, "referenceId": reference_id}
                )
                continue
            call = trigger_function_call(target, elements)
            call["sequence"] = index
            call["role"] = reference_role
            actions.append(call)
        marker_comments = {comment.casefold() for comment in comments}
        name = names.get(element_id, "")
        startup = bool(marker_comments & STARTUP_COMMENT_MARKERS) or bool(
            re.match(r"(?i)^(init\b|start game\b|ai - start\b)", name)
        )
        record = {
            "id": element_id,
            "name": name,
            "startup": startup,
            "comments": comments,
            "actions": actions,
        }
        trigger_records.append(record)
        if startup:
            startup_records.append(record)
    return {
        "path": "Triggers",
        "sha256": sha256(path),
        "status": "complete" if not unknowns else "complete_with_unknowns",
        "elementCount": len(elements),
        "triggerCount": len(trigger_records),
        "startupTriggerCount": len(startup_records),
        "triggers": sorted(trigger_records, key=lambda item: item["id"]),
        "startupTriggers": sorted(startup_records, key=lambda item: item["id"]),
        "unknowns": unknowns,
    }


def source_function_bodies(source: dict, path: Path) -> dict[str, str]:
    text = read_text(path)
    bodies: dict[str, str] = {}
    matches = list(FUNCTION_PATTERN.finditer(text))
    for match in matches:
        body_start = text.find("{", match.end() - 1)
        if body_start < 0:
            continue
        depth = 0
        end = body_start
        for end in range(body_start, len(text)):
            if text[end] == "{":
                depth += 1
            elif text[end] == "}":
                depth -= 1
                if depth == 0:
                    break
        bodies[match.group("name")] = text[body_start + 1 : end]
    return bodies


def function_name_from_trigger_value(value: str) -> str | None:
    match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)", value.strip())
    return f"{match.group(1)}_Func" if match else None


def startup_call_graph(map_script_path: Path, logic_sources: list[dict], source_paths: list[Path]) -> dict:
    """Trace map-init and TriggerExecute/callback calls conservatively."""

    bodies: dict[str, str] = {}
    function_sources: dict[str, str] = {}
    for source, path in zip(logic_sources, source_paths):
        source_bodies = source_function_bodies(source, path)
        for name, body in source_bodies.items():
            bodies.setdefault(name, body)
            function_sources.setdefault(name, source["path"])
    map_text = read_text(map_script_path)
    roots = sorted(set(TRIGGER_MAP_INIT_PATTERN.findall(map_text)))
    reachable: list[str] = []
    queue = [f"{trigger}_Func" for trigger in roots]
    seen: set[str] = set()
    while queue:
        function = queue.pop(0)
        if function in seen:
            continue
        seen.add(function)
        reachable.append(function)
        body = bodies.get(function)
        if body is None:
            continue
        for called in GENERIC_CALL_PATTERN.findall(body):
            candidates = (called, f"{called}_Func")
            for candidate in candidates:
                if candidate in bodies and candidate not in seen:
                    queue.append(candidate)
        # LoadCoopMission(map, callbackTrigger) is a callback edge that is not
        # represented as a normal Galaxy function call. The scanner only
        # follows a literal trigger variable when the expression is explicit.
        for call_name in ("libCOMI_gf_LoadCoopMission", "libCOOC_gf_LoadCoopMission"):
            if call_name not in body:
                continue
            call = re.search(
                rf"\b{re.escape(call_name)}\s*\((?P<args>[^;]+)\)", body,
                re.DOTALL,
            )
            if call is None:
                continue
            args = split_arguments(call.group("args"))
            if len(args) > 1:
                callback = function_name_from_trigger_value(args[1])
                if callback and callback in bodies and callback not in seen:
                    queue.append(callback)
    reachable_triggers = sorted(
        {
            trigger[:-5]
            for trigger in reachable
            if trigger.endswith("_Func")
        }
    )
    reachable_creations = [
        item
        for source in logic_sources
        for item in source["dynamicCreations"]
        if item["function"] in seen
    ]
    return {
        "mapInitTriggers": roots,
        "reachableTriggers": reachable_triggers,
        "reachableFunctions": [
            {"name": name, "source": function_sources.get(name)} for name in reachable
        ],
        "reachableDynamicCreationSites": reachable_creations,
        "unknowns": [
            {"kind": "map_init_trigger_function_missing", "trigger": trigger}
            for trigger in roots
            if f"{trigger}_Func" not in bodies
        ],
    }


def scan_logic_source(path: Path, source_kind: str, source_root: Path) -> dict:
    text = read_text(path)
    source_name = path.relative_to(source_root).as_posix() if path.is_relative_to(source_root) else path.name
    functions = []
    for match in FUNCTION_PATTERN.finditer(text):
        functions.append({"name": match.group("name"), "line": line_number(text, match.start())})

    dynamic_creations = []
    for match in CREATE_PATTERN.finditer(text):
        call = balanced_call(text, match.end())
        if call is None:
            continue
        arguments_text, end_offset = call
        arguments = split_arguments(arguments_text)
        if len(arguments) < 4:
            continue
        type_index = 1
        owner_index = 3
        unit_type = literal_string(arguments[type_index]) if len(arguments) > type_index else None
        owner_expression = arguments[owner_index] if len(arguments) > owner_index else ""
        function = function_at(text, match.start())
        dynamic_creations.append(
            {
                "source": source_name,
                "sourceKind": source_kind,
                "line": line_number(text, match.start()),
                "function": function[0] if function else "unknown",
                "functionLine": function[1] if function else None,
                "call": match.group("name"),
                "unitType": unit_type if unit_type is not None else "unknown",
                "unitTypeExpression": arguments[type_index],
                "ownerScope": player_scope(owner_expression),
                "ownerExpression": owner_expression,
                "countExpression": arguments[0],
                "classification": (
                    "replacement_source" if unit_type == "K5Kerrigan" else
                    "player_dynamic_unit" if player_scope(owner_expression) in {"P1", "P2"} else
                    "dynamic_unit_unknown_owner"
                ),
                "excerpt": line_excerpt(text, match.start()),
                "endLine": line_number(text, end_offset),
            }
        )

    unit_from_id = []
    for match in UNIT_FROM_ID_PATTERN.finditer(text):
        function = function_at(text, match.start())
        unit_from_id.append(
            {
                "source": source_name,
                "sourceKind": source_kind,
                "line": line_number(text, match.start()),
                "function": function[0] if function else "unknown",
                "idExpression": match.group("arg").strip(),
                "excerpt": line_excerpt(text, match.start()),
            }
        )

    references = {
        "preventDefeat": [],
        "mapInit": [],
        "startLocation": [],
        "unitGroup": [],
    }
    for match in PREVENT_DEFEAT_PATTERN.finditer(text):
        function = function_at(text, match.start())
        references["preventDefeat"].append(
            {
                "source": source_name,
                "sourceKind": source_kind,
                "line": line_number(text, match.start()),
                "function": function[0] if function else "unknown",
                "excerpt": line_excerpt(text, match.start()),
            }
        )
    for match in MAP_INIT_PATTERN.finditer(text):
        references["mapInit"].append(
            {
                "source": source_name,
                "sourceKind": source_kind,
                "line": line_number(text, match.start()),
                "trigger": match.group("trigger"),
                "excerpt": line_excerpt(text, match.start()),
            }
        )
    for match in START_LOCATION_PATTERN.finditer(text):
        function = function_at(text, match.start())
        references["startLocation"].append(
            {
                "source": source_name,
                "sourceKind": source_kind,
                "line": line_number(text, match.start()),
                "function": function[0] if function else "unknown",
                "playerExpression": match.group("arg").strip(),
                "playerScope": player_scope(match.group("arg")),
                "excerpt": line_excerpt(text, match.start()),
            }
        )

    for match in UNIT_GROUP_PATTERN.finditer(text):
        call = balanced_call(text, match.end())
        if call is None:
            continue
        arguments_text, _ = call
        arguments = split_arguments(arguments_text)
        if len(arguments) < 2:
            continue
        function = function_at(text, match.start())
        unit_type = literal_string(arguments[0])
        owner_expression = arguments[1]
        references["unitGroup"].append(
            {
                "source": source_name,
                "sourceKind": source_kind,
                "line": line_number(text, match.start()),
                "function": function[0] if function else "unknown",
                "unitType": unit_type if unit_type is not None else "unknown",
                "unitTypeExpression": arguments[0],
                "ownerScope": player_scope(owner_expression),
                "ownerExpression": owner_expression,
                "excerpt": line_excerpt(text, match.start()),
            }
        )

    return {
        "path": source_name,
        "kind": source_kind,
        "sha256": sha256(path),
        "functionCount": len(functions),
        "functions": functions,
        "dynamicCreations": dynamic_creations,
        "unitFromId": unit_from_id,
        "references": references,
    }


def replacement_contract(logic_sources: list[dict]) -> dict:
    """Describe Reborn's source-unit replacement dependency explicitly."""

    commander_start = next(
        (
            function
            for source in logic_sources
            for function in source["functions"]
            if function["name"] == "lib48DF4533_gt_CommanderStart_Func"
        ),
        None,
    )
    k5_references = [
        item
        for source in logic_sources
        for item in source["references"]["unitGroup"]
        if item["unitType"] in {"K5Kerrigan", "K5KerriganBurrowed"}
        and item["function"] == "lib48DF4533_gt_CommanderStart_Func"
    ]
    target_types = sorted(
        {
            item["unitType"]
            for source in logic_sources
            for item in source["dynamicCreations"]
            if item["function"] == "lib48DF4533_gt_CommanderStart_Func"
            and item["unitType"] not in {"unknown", "K5Kerrigan", "K5KerriganBurrowed"}
        }
    )
    enabled = commander_start is not None and bool(k5_references)
    return {
        "enabled": enabled,
        "sourceUnitTypes": ["K5Kerrigan", "K5KerriganBurrowed"] if enabled else [],
        "sourceProvision": (
            "launcher_adapter_before_commander_start" if enabled else "not_required"
        ),
        "sourcePlayers": [1, 14] if enabled else [],
        "requiredFunction": commander_start,
        "referenceCount": len(k5_references),
        "targetUnitTypes": target_types,
        "references": k5_references,
    }


def object_unit_record(node: ET.Element, source_name: str) -> dict:
    flags = {item.get("Index"): item.get("Value") for item in node.findall("Flag")}
    unit_type = node.get("UnitType") or "unknown"
    if unit_type in SPAWN_ANCHOR_TYPES:
        role = "spawn_anchor"
    elif unit_type in MISSION_START_STRUCTURE_TYPES:
        role = "mission_start_structure"
    else:
        role = "player_preplaced_unit"
    return {
        "id": node.get("Id"),
        "player": int(node.get("Player")),
        "unitType": unit_type,
        "role": role,
        "name": node.get("Name"),
        "position": node.get("Position"),
        "hidden": flags.get("UnitHidden") == "1",
        "flags": flags,
        "source": source_name,
    }


def scan_map(map_dir: Path, source_root: Path, dependency_files: list[Path]) -> dict:
    objects_path = map_dir / "Objects"
    script_path = map_dir / "MapScript.galaxy"
    triggers_path = map_dir / "Triggers"
    if not objects_path.exists() or not script_path.exists() or not triggers_path.exists():
        raise ValueError(f"map is missing Objects, MapScript.galaxy, or Triggers: {map_dir}")
    source_name = map_dir.relative_to(source_root).as_posix()
    root = ET.parse(objects_path).getroot()
    static_units = [
        object_unit_record(node, source_name + "/Objects")
        for node in root.findall(".//ObjectUnit")
        if node.get("Player") in {"1", "2"}
    ]
    map_logic = scan_logic_source(script_path, "map_script", map_dir)
    logic_sources = [map_logic]
    for dependency in dependency_files:
        if dependency.exists():
            logic_sources.append(scan_logic_source(dependency, "dependency", dependency.parent))
    trigger_contract = scan_triggers(map_dir)
    source_paths = [script_path] + [dependency for dependency in dependency_files if dependency.exists()]
    call_graph = startup_call_graph(script_path, logic_sources, source_paths)
    dynamic = [item for source in logic_sources for item in source["dynamicCreations"]]
    unit_from_id = [item for source in logic_sources for item in source["unitFromId"]]
    references = {
        key: [item for source in logic_sources for item in source["references"][key]]
        for key in ("preventDefeat", "mapInit", "startLocation", "unitGroup")
    }
    replacements = replacement_contract(logic_sources)
    by_player = {
        f"P{player}": [item for item in static_units if item["player"] == player]
        for player in PLAYER_IDS
    }
    unknowns = list(trigger_contract["unknowns"]) + list(call_graph["unknowns"])
    for item in dynamic:
        if item["unitType"] == "unknown" or item["ownerScope"] == "unknown":
            unknowns.append(
                {
                    "kind": "dynamic_creation",
                    "source": item["source"],
                    "line": item["line"],
                    "function": item["function"],
                    "unitTypeExpression": item["unitTypeExpression"],
                    "ownerExpression": item["ownerExpression"],
                }
            )
    return {
        "map": map_dir.name,
        "sourcePath": source_name,
        "sourceFiles": {
            "Objects": {"path": source_name + "/Objects", "sha256": sha256(objects_path)},
            "MapScript.galaxy": {"path": source_name + "/MapScript.galaxy", "sha256": sha256(script_path)},
            "Triggers": {"path": source_name + "/Triggers", "sha256": sha256(triggers_path)},
        },
        "staticPlayerUnits": by_player,
        "staticPlayerUnitSummary": {
            player: dict(sorted(Counter(unit["unitType"] for unit in units).items()))
            for player, units in by_player.items()
        },
        "logicSources": logic_sources,
        "dynamicCreationSites": dynamic,
        "unitFromIdReferences": unit_from_id,
        "references": references,
        "triggers": trigger_contract,
        "startupCallGraph": call_graph,
        "initialization": {
            "mapInitTriggers": sorted({item["trigger"] for item in references["mapInit"]}),
            "triggerStartupNames": sorted(
                {
                    trigger["name"]
                    for trigger in trigger_contract["startupTriggers"]
                    if trigger["name"]
                }
            ),
            "triggerStartupIds": sorted(trigger["id"] for trigger in trigger_contract["startupTriggers"]),
            "startingGameQ": next(
                (
                    trigger
                    for trigger in trigger_contract["triggers"]
                    if "starting game q" in {comment.casefold() for comment in trigger["comments"]}
                ),
                None,
            ),
            "functionsWithInitName": sorted(
                {
                    item["name"]
                    for source in logic_sources
                    for item in source["functions"]
                    if "Init" in item["name"] or "Initialization" in item["name"]
                }
            ),
            "startLocationScopes": sorted({item["playerScope"] for item in references["startLocation"]}),
        },
        "adaptation": {
            "preplacedPlayerObjects": "preserve_exactly",
            "spawnAnchors": sorted(
                {
                    unit["unitType"]
                    for unit in static_units
                    if unit["role"] == "spawn_anchor"
                }
            ),
            "missionStartStructures": sorted(
                {
                    unit["unitType"]
                    for unit in static_units
                    if unit["role"] == "mission_start_structure"
                }
            ),
            "preventDefeatEvidence": "present" if references["preventDefeat"] else "not_found_in_scanned_sources",
            "commanderBaseAndWorker": "runtime_commander_profile_required",
            "rebornReplacementSource": replacements,
            "protectedPlayerUnitTypes": sorted({unit["unitType"] for unit in static_units}),
            "dynamicPlayerUnitTypes": sorted(
                {
                    item["unitType"]
                    for item in dynamic
                    if item["ownerScope"] in {"P1", "P2"}
                    and item["unitType"] != "unknown"
                }
            ),
            "reachableDynamicPlayerUnitTypes": sorted(
                {
                    item["unitType"]
                    for item in call_graph["reachableDynamicCreationSites"]
                    if item["ownerScope"] in {"P1", "P2"} and item["unitType"] != "unknown"
                }
            ),
            "unresolved": unknowns,
        },
        "status": "static_complete_runtime_pending" if not unknowns else "static_complete_with_unknowns",
    }


def map_directories(source_root: Path) -> list[Path]:
    if source_root.name.endswith(SC2_MAP_SUFFIX):
        return [source_root]
    return sorted(path for path in source_root.iterdir() if path.is_dir() and path.name.endswith(SC2_MAP_SUFFIX))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--artifact-out", type=Path)
    parser.add_argument(
        "--launcher-out",
        type=Path,
        help="write a compact source-hash/startup contract for the approved launcher",
    )
    parser.add_argument("--dependency-file", type=Path, action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = args.source_root.resolve()
    maps = map_directories(source_root)
    if not maps:
        raise SystemExit(f"no .SC2Map directories found under {source_root}")
    records = [scan_map(path, source_root, [dependency.resolve() for dependency in args.dependency_file]) for path in maps]
    output = {
        "schemaVersion": 1,
        "contract": "cmre-map-startup-unit-adaptation",
        "evidenceType": "static",
        "sourceRoot": source_root.name,
        "mapCount": len(records),
        "maps": records,
        "workflow": {
            "sourceOfTruth": "original map Objects + original map MapScript.galaxy + explicitly listed dependency Galaxy files",
            "unknownPolicy": "fail_closed",
            "runtimeGate": "approved launcher must verify source hashes, initialization markers, P1/P2 census, and same-window ScriptError absence",
        },
    }
    for path in (args.out, args.artifact_out):
        if path is None:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.launcher_out is not None:
        dependency_files = []
        seen_dependency_paths = set()
        for record in records:
            for source in record["logicSources"]:
                if source["kind"] != "dependency" or source["path"] in seen_dependency_paths:
                    continue
                seen_dependency_paths.add(source["path"])
                dependency_files.append({"path": source["path"], "sha256": source["sha256"]})
        compact = {
            "schemaVersion": 1,
            "contract": output["contract"],
            "evidenceType": "static",
            "sourceRoot": output["sourceRoot"],
            "dependencyFiles": dependency_files,
            "maps": [
                {
                    "map": record["map"],
                    "sourcePath": record["sourcePath"],
                    "sourceFiles": record["sourceFiles"],
                    "staticPlayerUnitSummary": record["staticPlayerUnitSummary"],
                    "analysis": {
                        "status": record["status"],
                        "contractStatus": (
                            "ready"
                            if record["triggers"]["status"] == "complete"
                            and not record["startupCallGraph"]["unknowns"]
                            else "incomplete"
                        ),
                        "triggerStatus": record["triggers"]["status"],
                        "triggerCount": record["triggers"]["triggerCount"],
                        "startupTriggerCount": record["triggers"]["startupTriggerCount"],
                        "startupTriggerIds": record["initialization"]["triggerStartupIds"],
                        "startingGameQ": record["initialization"]["startingGameQ"],
                        "mapInitTriggers": record["startupCallGraph"]["mapInitTriggers"],
                        "reachableFunctions": record["startupCallGraph"]["reachableFunctions"],
                        "reachableDynamicCreationSites": record["startupCallGraph"]["reachableDynamicCreationSites"],
                        "unknownCount": len(record["adaptation"]["unresolved"]),
                    },
                    "adaptation": {
                        "protectedPlayerUnitTypes": record["adaptation"]["protectedPlayerUnitTypes"],
                        "dynamicPlayerUnitTypes": record["adaptation"]["dynamicPlayerUnitTypes"],
                        "spawnAnchors": record["adaptation"]["spawnAnchors"],
                        "missionStartStructures": record["adaptation"]["missionStartStructures"],
                        "rebornReplacementSource": record["adaptation"]["rebornReplacementSource"],
                    },
                }
                for record in records
            ],
            "workflow": output["workflow"],
        }
        args.launcher_out.parent.mkdir(parents=True, exist_ok=True)
        args.launcher_out.write_text(
            json.dumps(compact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps({"maps": len(records), "out": str(args.out), "unknownDynamicSites": sum(len(item["adaptation"]["unresolved"]) for item in records)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ET.ParseError, ValueError) as exc:
        print(f"scan_map_startup_contract: {exc}", file=sys.stderr)
        raise SystemExit(2)
