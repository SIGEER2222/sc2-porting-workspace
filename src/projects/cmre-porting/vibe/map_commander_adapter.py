"""Resolve map + commander startup adapters from project-owned JSON data."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional


TOKEN_RE = re.compile(r"^[A-Za-z0-9_]+$")


def load_adapter_config(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported map commander adapter schema")
    if not isinstance(payload.get("map_rules"), list):
        raise ValueError("map_rules must be a list")
    if not isinstance(payload.get("commander_rules"), list):
        raise ValueError("commander_rules must be a list")
    return payload


def _first_matching_rule(rules: list[Mapping[str, Any]], value: str) -> dict[str, Any]:
    for rule in rules:
        pattern = str(rule.get("pattern", ""))
        if pattern and re.search(pattern, value, re.IGNORECASE):
            return dict(rule)
    return {}


def _safe_tokens(values: Any, field: str) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError(f"{field} must be a list")
    result = []
    for value in values:
        token = str(value)
        if not TOKEN_RE.fullmatch(token):
            raise ValueError(f"{field} contains unsafe catalog token: {token}")
        result.append(token)
    return list(dict.fromkeys(result))


def _expand_replacement(value: Any, startup: Mapping[str, Any]) -> str:
    """Resolve symbolic replacement targets against the selected commander."""

    token = str(value)
    aliases = {
        "commander.startingStructure": str(startup.get("startingStructure", "CommandCenter")),
        "commander.startingWorker": str(startup.get("startingWorker", "SCV")),
    }
    return aliases.get(token, token)


def resolve_adapter(
    config: Mapping[str, Any],
    *,
    map_name: str,
    commander_id: str,
    commander_profile: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    map_rule = _first_matching_rule(list(config.get("map_rules", [])), map_name)
    commander_rule = _first_matching_rule(list(config.get("commander_rules", [])), commander_id)
    profile = dict(commander_profile or {})

    startup = dict(config.get("defaults", {}).get("startup", {}))
    startup.update(commander_rule.get("startup", {}))
    # Existing commander profiles contain the real custom catalog ids. They
    # outrank race defaults; a map rule may still make an explicit override.
    startup.update(profile)
    startup.update(map_rule.get("startup", {}))

    map_unit_policy = dict(config.get("defaults", {}).get("map_unit_policy", {}))
    map_unit_policy.update(map_rule.get("map_unit_policy", {}))
    result = {
        "schema_version": 1,
        "map_id": str(map_rule.get("id", "generic")),
        "map_name": map_name,
        "commander_id": commander_id,
        "commander_rule_id": str(commander_rule.get("id", "generic")),
        "startup": {
            "startingStructure": str(startup.get("startingStructure", "CommandCenter")),
            "startingWorker": str(startup.get("startingWorker", "SCV")),
            "workerCount": int(startup.get("workerCount", 5)),
            "vanillaRemovals": _safe_tokens(startup.get("vanillaRemovals", []), "vanillaRemovals"),
        },
        "map_unit_policy": {
            "mode": str(map_unit_policy.get("mode", "preserve_native")),
            "removeUnitTypes": _safe_tokens(map_unit_policy.get("removeUnitTypes", []), "removeUnitTypes"),
            "protectedUnitTypes": _safe_tokens(map_unit_policy.get("protectedUnitTypes", []), "protectedUnitTypes"),
            "anchorUnitTypes": _safe_tokens(map_unit_policy.get("anchorUnitTypes", []), "anchorUnitTypes"),
        },
        "event_unit_replacements": {
            str(source): _expand_replacement(target, startup)
            for source, target in dict(map_rule.get("event_unit_replacements", {})).items()
        },
        "evidence": {
            "map_rule": str(map_rule.get("id", "generic")),
            "commander_rule": str(commander_rule.get("id", "generic")),
            "source": "project-owned map_commander_adapters.json",
        },
    }
    protected = set(result["map_unit_policy"]["protectedUnitTypes"])
    result["startup"]["vanillaRemovals"] = [
        item for item in result["startup"]["vanillaRemovals"]
        if item not in protected
    ]
    result["startup"]["vanillaRemovals"] = list(dict.fromkeys(
        result["startup"]["vanillaRemovals"]
        + result["map_unit_policy"]["removeUnitTypes"]
    ))
    return result


def resolve_from_files(
    config_path: str | Path,
    *,
    map_name: str,
    commander_id: str,
    commander_profile: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    return resolve_adapter(
        load_adapter_config(config_path),
        map_name=map_name,
        commander_id=commander_id,
        commander_profile=commander_profile,
    )
