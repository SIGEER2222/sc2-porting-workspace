"""Extract map-owned attack plans from a Galaxy ``MapScript.galaxy`` file.

The simulator cannot execute the original campaign trigger graph, but the
adapter still needs to consume the source graph instead of maintaining a
second hand-written wave table.  This module intentionally extracts only the
deterministic, replay-relevant surface:

* day/night duration and the source night boundaries;
* normal ``gf_AIAttackWaveFromDirection`` calls;
* special ``gf_AISendInfestedAttackWave`` calls, including their waits;
* the night-defender unit recipe used by ``gf_AINightDefenderSpawn``.
* the persistent ``AIWhiteNoiseSpawning`` service and its per-night quotas;
* delayed ``HybridReinforcements`` counts and defend-area source regions.

Every emitted item keeps its source trigger and call index.  The result is an
auditable source model, not a claim that Galaxy control flow has been fully
interpreted by the Python simulator.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Iterable


LOOPS_PER_SECOND = 22.4
DIFFICULTY_INDEX = {"casual": 0, "normal": 1, "hard": 2, "brutal": 3}

DIRECTION_BY_SYMBOL = {
    "ge_AttackDirection_NorthWestP2": "north_west",
    "ge_AttackDirection_NorthEast": "north_east",
    "ge_AttackDirection_SouthEastP1": "south_east",
    "ge_AttackDirection_SouthWest": "south_west",
}

SPECIAL_TO_SIM = {
    "Hunterling": "Zergling",
    "Spotter": "Mutalisk",
    "Choker": "Roach",
    "Kaboomer": "Baneling",
    "Stank": "Ultralisk",
}

SPECIAL_TYPE_CANDIDATES = ("Hunterling", "Spotter", "Kaboomer", "Choker")
GENERIC_ATTACK_TRIGGERS = ("gt_AttackWave01", "gt_AttackWave02", "gt_AttackWave03", "gt_AttackWave05")

FORCE_BUCKETS = {
    "2Smaller": {"units": 12, "source_type_counts": {"InfestedCivilian": 8, "InfestedTerranCampaign": 4}},
    "3Small": {"units": 20, "source_type_counts": {"InfestedCivilian": 14, "InfestedTerranCampaign": 6}},
    "4Medium": {"units": 28, "source_type_counts": {"InfestedCivilian": 18, "InfestedTerranCampaign": 8, "InfestedAbomination": 2}},
}

DEFENDER_TO_SOURCE = {
    "InfestedCivilianBurrowed": "InfestedCivilian",
    "InfestedTerranCampaignBurrowed": "InfestedTerranCampaign",
    "InfestedAbominationBurrowed": "InfestedAbomination",
    "InfestedExploderBurrowed": "InfestedExploder",
}


def _split_top_level(value: str) -> list[str]:
    parts: list[str] = []
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
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
    parts.append(value[start:].strip())
    return parts


def _balanced_call(source: str, open_paren: int) -> tuple[str, int]:
    depth = 0
    quoted = False
    escaped = False
    for index in range(open_paren, len(source)):
        char = source[index]
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
                return source[open_paren + 1 : index], index + 1
    raise ValueError("unterminated Galaxy call")


def _function_body(source: str, function_name: str) -> str:
    function_symbols = [function_name]
    if not function_name.endswith("_Func"):
        function_symbols.append(f"{function_name}_Func")
    pattern = re.compile(
        rf"\b(?:bool|void|int|fixed|point|string|unit|trigger)\s+"
        rf"(?:{'|'.join(re.escape(symbol) for symbol in function_symbols)})"
        rf"\s*\([^)]*\)\s*\{{"
    )
    match = pattern.search(source)
    if match is None:
        raise ValueError(f"MapScript function not found: {function_name}")
    open_brace = source.find("{", match.start(), match.end())
    depth = 0
    quoted = False
    escaped = False
    for index in range(open_brace, len(source)):
        char = source[index]
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
                return source[open_brace + 1 : index]
    raise ValueError(f"MapScript function has no closing brace: {function_name}")


def _call_arguments(body: str, function_name: str) -> Iterable[tuple[int, list[str], int]]:
    pattern = re.compile(rf"\b{re.escape(function_name)}\s*\(")
    for match in pattern.finditer(body):
        arguments, end = _balanced_call(body, match.end() - 1)
        yield match.start(), _split_top_level(arguments), end


def _matching_brace(body: str, open_brace: int) -> int:
    depth = 0
    quoted = False
    escaped = False
    for index in range(open_brace, len(body)):
        char = body[index]
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
                return index
    raise ValueError("unterminated Galaxy block")


def _numbered_branch_blocks(body: str) -> dict[int, str]:
    """Return bodies for simple ``if (value == N)`` Galaxy branches."""

    blocks: dict[int, str] = {}
    pattern = re.compile(
        r"if\s*\(\s*(?:\(\s*)?([A-Za-z_]\w*)\s*==\s*(\d+)\s*"
        r"(?:\)\s*)?\)\s*\{"
    )
    for match in pattern.finditer(body):
        open_brace = body.find("{", match.start(), match.end())
        try:
            close_brace = _matching_brace(body, open_brace)
        except ValueError:
            continue
        blocks.setdefault(int(match.group(2)), body[open_brace + 1 : close_brace])
    return blocks


def _assignment_expression(body: str, name: str) -> str | None:
    match = re.search(rf"\b{re.escape(name)}\s*=\s*([^;]+);", body)
    return match.group(1).strip() if match else None


def _loop_spans(body: str, difficulty: str) -> list[tuple[int, int, int]]:
    """Return ``(start, end, iterations)`` for bounded Galaxy ``for`` loops."""

    assignments: dict[str, str] = {}
    for match in re.finditer(r"\b(?:const\s+int\s+)?([A-Za-z_]\w*)\s*=\s*([^;]+);", body):
        assignments[match.group(1)] = match.group(2).strip()
    spans: list[tuple[int, int, int]] = []
    for match in re.finditer(r"\bfor\s*\([^;]+;\s*[^;]+<=\s*([A-Za-z_]\w*|[-+]?\d+)\s*;[^)]*\)\s*\{", body):
        open_brace = body.find("{", match.start(), match.end())
        try:
            close_brace = _matching_brace(body, open_brace)
        except ValueError:
            continue
        expression = assignments.get(match.group(1), match.group(1))
        iterations = _integer_value(expression, difficulty)
        if iterations <= 0 and expression.isdigit():
            iterations = int(expression)
        spans.append((match.start(), close_brace + 1, max(1, iterations)))
    return spans


def _loop_multiplier(body: str, position: int, difficulty: str) -> int:
    multiplier = 1
    for start, end, iterations in _loop_spans(body, difficulty):
        if start < position < end:
            multiplier *= iterations
    return multiplier


def _difficulty_value(expression: str, difficulty: str) -> int | float | bool | None:
    expression = expression.strip()
    if expression.lower() == "true":
        return True
    if expression.lower() == "false":
        return False
    number = re.fullmatch(r"[-+]?\d+(?:\.\d+)?", expression)
    if number:
        value = float(expression) if "." in expression else int(expression)
        return value
    marker = re.search(r"(?:Minimum)?DifficultyValue(?:Int|Fixed|Real|CoopInteger|CoopReal)?\s*\(", expression)
    if marker is None:
        return None
    try:
        arguments, _ = _balanced_call(expression, marker.end() - 1)
    except ValueError:
        return None
    values = _split_top_level(arguments)
    index = DIFFICULTY_INDEX.get(difficulty, 1)
    if len(values) < 4:
        return None
    return _difficulty_value(values[index], difficulty)


def _integer_value(expression: str, difficulty: str) -> int:
    value = _difficulty_value(expression, difficulty)
    if isinstance(value, bool) or value is None:
        return 0
    return int(round(float(value)))


def _float_value(expression: str, difficulty: str) -> float:
    value = _difficulty_value(expression, difficulty)
    if isinstance(value, bool) or value is None:
        return 0.0
    return float(value)


def _wait_seconds(body: str, end: int) -> float:
    return sum(
        _float_value(match.group(1), "normal")
        for match in re.finditer(r"\bWait\s*\(\s*([-+]?\d+(?:\.\d+)?)\s*,", body[:end])
    )


def _direction(expression: str, assignments: dict[str, str]) -> tuple[str | None, list[str]]:
    expression = expression.strip()
    direct = next((value for key, value in DIRECTION_BY_SYMBOL.items() if key in expression), None)
    if direct:
        return direct, [direct]
    variable = re.fullmatch(r"([A-Za-z_]\w*)\[(\d+)\]", expression)
    if variable:
        resolved = assignments.get(f"{variable.group(1)}[{variable.group(2)}]")
        if resolved:
            return None, [
                assignments[key]
                for key in sorted(assignments)
                if key.startswith(f"{variable.group(1)}[")
            ]
    return None, sorted(set(DIRECTION_BY_SYMBOL.values()))


def _direction_assignments(body: str) -> dict[str, str]:
    assignments: dict[str, str] = {}
    pattern = re.compile(
        r"\b([A-Za-z_]\w*\[\d+\])\s*=\s*(ge_AttackDirection_\w+)\s*;"
    )
    for match in pattern.finditer(body):
        direction = DIRECTION_BY_SYMBOL.get(match.group(2))
        if direction:
            assignments[match.group(1)] = direction
    return assignments


def _normal_trigger_names(source: str) -> dict[int, str]:
    names: dict[int, str] = {}
    pattern = re.compile(r"\b(gt_AINormalInfestedAttacksNight(\d+)[A-Za-z0-9_]+)_Func\b")
    for match in pattern.finditer(source):
        names.setdefault(int(match.group(2)), match.group(1))
    repeat = "gt_AINormalInfestedAttacksKillNightRepeat"
    if f"{repeat}_Func" in source:
        names.setdefault(6, repeat)
    return names


def _normal_wave_calls(source: str, difficulty: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for night, trigger_name in sorted(_normal_trigger_names(source).items()):
        body = _function_body(source, trigger_name)
        assignments = _direction_assignments(body)
        for call_index, (position, arguments, end) in enumerate(
            _call_arguments(body, "gf_AIAttackWaveFromDirection"), start=1
        ):
            if len(arguments) < 5:
                continue
            direction, direction_options = _direction(arguments[0], assignments)
            calls.append(
                {
                    "night": night,
                    "source_trigger": trigger_name,
                    "source_call_index": call_index,
                    "offset_seconds": round(_wait_seconds(body, position), 3),
                    "direction": direction,
                    "direction_options": direction_options,
                    "delay_loops": _integer_value(arguments[1], difficulty),
                    "source_type_counts": {
                        "InfestedCivilian": _integer_value(arguments[2], difficulty),
                        "InfestedTerranCampaign": _integer_value(arguments[3], difficulty),
                        "InfestedAbomination": _integer_value(arguments[4], difficulty),
                    },
                    "selection_mode": "source_call",
                }
            )
    return calls


def _special_wave_calls(source: str, difficulty: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    pattern = re.compile(
        r"\b(gt_AISpecialInfestedAttacks(?P<type>Hunterling|Spotter|Choker|Kaboomer|Boss)"
        r"Night(?P<night>\d+))_Func\b"
    )
    trigger_names: dict[str, tuple[str, int]] = {}
    for match in pattern.finditer(source):
        trigger_names.setdefault(
            match.group(1),
            (match.group("type"), int(match.group("night"))),
        )
    for trigger_name, (special_type, night) in sorted(trigger_names.items()):
        body = _function_body(source, trigger_name)
        for call_index, (position, arguments, _end) in enumerate(
            _call_arguments(body, "gf_AISendInfestedAttackWave"), start=1
        ):
            if len(arguments) < 2:
                continue
            source_type = arguments[1].strip().strip('"') or special_type
            raid = bool(_difficulty_value(arguments[2], difficulty)) if len(arguments) > 2 else False
            flank = bool(_difficulty_value(arguments[3], difficulty)) if len(arguments) > 3 else False
            calls.append(
                {
                    "night": night,
                    "source_trigger": trigger_name,
                    "source_call_index": call_index,
                    "offset_seconds": round(_wait_seconds(body, position), 3),
                    "source_special_type": source_type,
                    "simulator_unit_type": SPECIAL_TO_SIM.get(source_type, "Zergling"),
                    "count": _integer_value(arguments[0], difficulty),
                    "raid": raid,
                    "flank": flank,
                    "direction_options": (
                        ["south_west", "north_east"]
                        if flank
                        else ["south_east", "north_west"]
                    ),
                    "selection_mode": "source_call_superset",
                    "activation": "selected_special_type" if special_type != "Boss" else "boss_branch",
                }
            )
        for call_index, (position, _arguments, _end) in enumerate(
            _call_arguments(body, "gf_AISpawnNydusWorm"), start=1
        ):
            calls.append(
                {
                    "night": night,
                    "source_trigger": trigger_name,
                    "source_call_index": call_index,
                    "offset_seconds": round(_wait_seconds(body, position), 3),
                    "source_special_type": "NydusWorm",
                    "simulator_unit_type": "Ultralisk",
                    "count": _loop_multiplier(body, position, difficulty),
                    "raid": False,
                    "flank": False,
                    "selection_mode": "source_action_projection",
                    "activation": "boss_type_nydus",
                    "force_plan": "nydus_spawn_profile",
                }
            )
    return calls


def _generic_attack_calls(source: str) -> list[dict[str, Any]]:
    """Extract the map-owned cooperative force sends near night end.

    These triggers delegate composition to the SC2 cooperative AI force
    builder.  MapScript supplies only resource and tech buckets, so those
    fields are preserved as a source boundary instead of being mistaken for
    an exact unit census.
    """

    calls: list[dict[str, Any]] = []
    for night, caller in sorted(_normal_trigger_names(source).items()):
        body = _function_body(source, caller)
        remaining_match = re.search(
            r"TimerGetRemaining\(gv_globalDayNightTimer\)\s*<=\s*([-+]?\d+(?:\.\d+)?)",
            body,
        )
        if remaining_match is None:
            continue
        remaining_seconds = float(remaining_match.group(1))
        for position, arguments, _end in _call_arguments(body, "TriggerExecute"):
            if not arguments or arguments[0].strip() not in GENERIC_ATTACK_TRIGGERS:
                continue
            trigger_name = arguments[0].strip()
            trigger_body = _function_body(source, trigger_name)
            resource_match = re.findall(
                r"\blv_resourceAmount\s*=\s*libCOMI_ge_CoopAIAttackWaveBuckets__([A-Za-z0-9]+)\s*;",
                trigger_body,
            )
            tech_match = re.findall(
                r"\blv_techLevel\s*=\s*libCOMI_ge_CoopAITechLevelBuckets__([A-Za-z0-9]+)\s*;",
                trigger_body,
            )
            if not resource_match or not tech_match:
                continue
            calls.append(
                {
                    "night": night,
                    "source_trigger": trigger_name,
                    "source_caller": caller,
                    "source_call_index": len(calls) + 1,
                    "offset_seconds": round(_wait_seconds(body, position), 3),
                    "timing_mode": "night_end_minus_seconds",
                    "night_end_remaining_seconds": remaining_seconds,
                    "resource_bucket": resource_match[-1],
                    "tech_bucket": tech_match[-1],
                    "force_builder": "libCOMI_gf_CreateCoopDropForceinTransportsatLocationandWaitforthemtospawn",
                    "composition_source": "cooperative_ai_engine",
                    "selection_mode": "source_trigger_call",
                }
            )
    return calls


def _nydus_force_profile(source: str, difficulty: str) -> dict[str, Any]:
    body = _function_body(source, "auto_gf_AISpawnNydusWorm_TriggerFunc")
    stages: list[dict[str, Any]] = []
    repeats: dict[int, int] = {}
    for match in re.finditer(r"lv_stageRepeat\[(\d+)\]\s*=\s*([^;]+);", body):
        repeats[int(match.group(1))] = _integer_value(match.group(2), difficulty)
    for match in re.finditer(r"if\s*\(auto\w+_val\s*==\s*(\d+)\)\s*\{", body):
        open_brace = body.find("{", match.start(), match.end())
        try:
            block = body[open_brace + 1 : _matching_brace(body, open_brace)]
        except ValueError:
            continue
        resource_match = re.search(r"lv_resourceSize\s*=\s*libCOMI_ge_CoopAIAttackWaveBuckets__([A-Za-z0-9]+)", block)
        tech_match = re.search(r"lv_techLevel\s*=\s*libCOMI_ge_CoopAITechLevelBuckets__([A-Za-z0-9]+)", block)
        if resource_match and tech_match:
            stage = int(match.group(1))
            stages.append(
                {
                    "stage": stage,
                    "repeat_count": repeats.get(stage, 0),
                    "resource_bucket": resource_match.group(1),
                    "tech_bucket": tech_match.group(1),
                }
            )
    timer_calls = list(_call_arguments(body, "TimerStart"))
    initial_cooldown_expression = (
        timer_calls[0][1][1]
        if timer_calls and len(timer_calls[0][1]) > 1
        else "20.0"
    )
    return {
        "source_trigger": "auto_gf_AISpawnNydusWorm_TriggerFunc",
        "initial_delay_seconds": round(
            _float_value(initial_cooldown_expression, difficulty),
            3,
        ),
        "repeat_interval_seconds": 60.0,
        "post_spawn_delay_seconds": 6.0,
        "stage_plan": stages,
        "max_spawned_units": 100,
        "composition_source": "cooperative_ai_engine",
        "source_note": "Each stage delegates unit composition to CreateCoopAttackForce; MapScript supplies only buckets.",
    }


def _white_noise_spawn_profile(source: str, difficulty: str) -> dict[str, Any]:
    """Extract the persistent night spawn service configured by the map.

    ``gt_AIWhiteNoiseSpawning`` is not a one-shot attack trigger.  It wakes at
    night, picks live infestation structures without replacement, creates the
    configured quotas, then sleeps for ``gv_whiteNoiseSpawnCooldown``.  The
    source function that supplies those quotas is deterministic per night, so
    retain it as a service profile for the replay planner.
    """

    body = _function_body(source, "gt_AIUpdateSpawnSettingsClassic")
    branches = _numbered_branch_blocks(body)
    source_names = {
        "gv_infestedAberrationQty": "InfestedAbomination",
        "gv_infestedVolatileQty": "InfestedExploder",
        "gv_infestedMarineQty": "InfestedTerranCampaign",
        "gv_infestedTerranQty": "InfestedCivilian",
    }
    profiles: list[dict[str, Any]] = []
    for night in range(1, 6):
        branch = branches.get(night)
        if branch is None:
            continue
        quantities = {
            source_name: _integer_value(expression, difficulty)
            for variable, source_name in source_names.items()
            if (expression := _assignment_expression(branch, variable)) is not None
        }
        cooldown_expression = _assignment_expression(branch, "gv_whiteNoiseSpawnCooldown")
        profiles.append(
            {
                "night": night,
                "source_quantities": quantities,
                "cooldown_seconds": (
                    _float_value(cooldown_expression, difficulty)
                    if cooldown_expression is not None
                    else 30.0
                ),
                "source_trigger": "gt_AIUpdateSpawnSettingsClassic_Func",
            }
        )

    return {
        "source_trigger": "gt_AIWhiteNoiseSpawning_Func",
        "settings_trigger": "gt_AIUpdateSpawnSettingsClassic_Func",
        "profiles": profiles,
        "night_6_mode": "inherit_previous_quantities",
        "night_6_cooldown_seconds": 20.0,
        "spawn_spacing_seconds": 0.1,
        "source_group": "gv_infestedStructuresGroup",
        "selection_mode": "random_live_infested_structure_without_replacement",
        "unit_type_order": [
            "InfestedAbomination",
            "InfestedExploder",
            "InfestedTerranCampaign",
            "InfestedCivilian",
        ],
        "composition_source": "MapScript.galaxy",
    }


def _hybrid_reinforcement_profile(source: str, difficulty: str) -> dict[str, Any]:
    """Extract the delayed per-night Hybrid reinforcement quotas."""

    body = _function_body(source, "gt_HybridReinforcements")
    branches = _numbered_branch_blocks(body)
    profiles: list[dict[str, Any]] = []
    for night in range(1, 5):
        branch = branches.get(night)
        if branch is None:
            continue
        light_expression = _assignment_expression(branch, "lv_hybridCountLight")
        heavy_expression = _assignment_expression(branch, "lv_hybridCountHeavy")
        profiles.append(
            {
                "night": night,
                "light_count": (
                    _integer_value(light_expression, difficulty)
                    if light_expression is not None
                    else 0
                ),
                "heavy_count": (
                    _integer_value(heavy_expression, difficulty)
                    if heavy_expression is not None
                    else 0
                ),
                "source_trigger": "gt_HybridReinforcements_Func",
            }
        )

    # The source else branch is the night 5+ profile.  Keep it explicit so a
    # future map with a different night count does not silently lose the
    # late-game reinforcement rule.
    fallback_light = 0
    fallback_heavy = 0
    if profiles:
        fallback_light = profiles[-1]["light_count"]
        fallback_heavy = profiles[-1]["heavy_count"]
    return {
        "source_trigger": "gt_HybridReinforcements_Func",
        "delay_seconds": 60.0,
        "profiles": profiles,
        "fallback_profile": {
            "night_min": 5,
            "light_count": fallback_light,
            "heavy_count": fallback_heavy,
        },
        "defend_region_ids": [9, 39, 10, 12, 11],
        "source_unit_types": {
            "light": "HybridLight",
            "heavy": "HybridHeavy",
        },
        "simulator_unit_types": {
            "light": "Marauder",
            "heavy": "Ultralisk",
        },
        "composition_source": "MapScript.galaxy",
        "selection_mode": "random_valid_hybrid_defend_area",
    }


def _condition_range(body: str, position: int) -> tuple[int, int | None] | None:
    candidates: list[tuple[int, int, int]] = []
    for match in re.finditer(
        r"if\s*\(\(gv_nightNumber\s*>=\s*(\d+)\)\s*&&\s*\(gv_nightNumber\s*<\s*(\d+)\)\)\s*\{",
        body,
    ):
        open_brace = body.find("{", match.start(), match.end())
        depth = 0
        for index in range(open_brace, len(body)):
            if body[index] == "{":
                depth += 1
            elif body[index] == "}":
                depth -= 1
                if depth == 0:
                    if open_brace < position < index:
                        candidates.append((index - open_brace, int(match.group(1)), int(match.group(2))))
                    break
    if not candidates:
        single = re.search(r"if\s*\(\(gv_nightNumber\s*>=\s*(\d+)\)\)\s*\{", body)
        if single:
            open_brace = body.find("{", single.start(), single.end())
            depth = 0
            for index in range(open_brace, len(body)):
                if body[index] == "{":
                    depth += 1
                elif body[index] == "}":
                    depth -= 1
                    if depth == 0:
                        if open_brace < position < index:
                            return int(single.group(1)), None
                        break
        return None
    _, minimum, maximum = min(candidates)
    return minimum, maximum


def _night_defender_rules(source: str, difficulty: str) -> list[dict[str, Any]]:
    trigger = "auto_gf_AINightDefenderSpawn_TriggerFunc"
    body = _function_body(source, trigger)
    rules: list[dict[str, Any]] = []
    loop_assignments = list(re.finditer(r"\bauto\w+_n\s*=\s*([^;]+);", body))
    for position, arguments, _end in _call_arguments(body, "libNtve_gf_CreateUnitsAtPoint2"):
        if len(arguments) < 2:
            continue
        unit_count = _integer_value(arguments[0], difficulty)
        unit_type = arguments[1].strip().strip('"')
        assignment = next(
            (item for item in reversed(loop_assignments) if item.end() <= position),
            None,
        )
        iterations = _integer_value(assignment.group(1), difficulty) if assignment else 1
        night_range = _condition_range(body, position)
        if night_range:
            minimum, maximum_exclusive = night_range
        else:
            minimum, maximum_exclusive = 1, None
        rules.append(
            {
                "night_min": minimum,
                "night_max_exclusive": maximum_exclusive,
                "source_unit_type": DEFENDER_TO_SOURCE.get(unit_type, unit_type),
                "source_unit_type_raw": unit_type,
                "simulator_unit_type": {
                    "InfestedCivilian": "Marine",
                    "InfestedTerranCampaign": "Marine",
                    "InfestedAbomination": "Roach",
                    "InfestedExploder": "Baneling",
                }.get(DEFENDER_TO_SOURCE.get(unit_type, unit_type), "Zergling"),
                "count_per_structure": max(0, unit_count * iterations),
                "source_expression": assignment.group(1).strip() if assignment else "1",
                "source": trigger,
            }
        )
    return [rule for rule in rules if rule["count_per_structure"] > 0]


def extract_map_script(map_source: str | Path, *, difficulty: str = "normal") -> dict[str, Any]:
    """Extract a replay-ready source model from ``MapScript.galaxy``."""

    if difficulty not in DIFFICULTY_INDEX:
        raise ValueError(f"unsupported map difficulty: {difficulty}")
    path = Path(map_source) / "MapScript.galaxy"
    source = path.read_text(encoding="utf-8-sig")
    first_day = _float_value(re.search(r"gv_day_Duration_First\s*=\s*([^;]+);", source).group(1), difficulty)  # type: ignore[union-attr]
    day_match = re.search(r"gv_day_Duration\s*=\s*([^;]+);", source)
    night_match = re.search(r"gv_night_Duration\s*=\s*([^;]+);", source)
    defender_cooldown_match = re.search(r"gv_nightDefenderCooldown\s*=\s*([^;]+);", source)
    defender_threshold_match = re.search(r"gv_nightDefenderSpawnLifeThreshold\s*=\s*([^;]+);", source)
    if day_match is None or night_match is None:
        raise ValueError("MapScript is missing day/night duration assignments")
    day_seconds = _float_value(day_match.group(1), difficulty)
    night_seconds = _float_value(night_match.group(1), difficulty)
    normal_calls = _normal_wave_calls(source, difficulty)
    special_calls = _special_wave_calls(source, difficulty)
    total_nights = max(
        [int(item["night"]) for item in normal_calls + special_calls if int(item["night"]) > 0]
        or [0]
    )
    first_day_loops = round(first_day * LOOPS_PER_SECOND)
    day_loops = round(day_seconds * LOOPS_PER_SECOND)
    night_loops = round(night_seconds * LOOPS_PER_SECOND)
    nights = []
    for night in range(1, total_nights + 1):
        start = first_day_loops + (night - 1) * (day_loops + night_loops)
        nights.append(
            {
                "night_number": night,
                "start_loop": start,
                "end_loop": start + night_loops,
                "end_loop_exclusive": start + night_loops,
                "difficulty": "light" if night < 4 else "heavy" if night >= 6 else "medium",
            }
        )
    generic_calls = _generic_attack_calls(source)
    defender_rules = _night_defender_rules(source, difficulty)
    white_noise_profile = _white_noise_spawn_profile(source, difficulty)
    hybrid_profile = _hybrid_reinforcement_profile(source, difficulty)
    return {
        "source": "MapScript.galaxy",
        "source_path": path.name,
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "difficulty": difficulty,
        "loops_per_second": LOOPS_PER_SECOND,
        "durations_seconds": {
            "day_first": first_day,
            "day": day_seconds,
            "night": night_seconds,
        },
        "day_first_loops": first_day_loops,
        "day_loops": day_loops,
        "night_loops": night_loops,
        "cycle_loops": day_loops + night_loops,
        "night_defender_cooldown_seconds": (
            _float_value(defender_cooldown_match.group(1), difficulty)
            if defender_cooldown_match
            else 30.0
        ),
        "night_defender_life_threshold": (
            _float_value(defender_threshold_match.group(1), difficulty)
            if defender_threshold_match
            else 150.0
        ),
        "nights": nights,
        "normal_attack_calls": normal_calls,
        "special_attack_calls": special_calls,
        "generic_attack_calls": generic_calls,
        "nydus_force_profile": _nydus_force_profile(source, difficulty),
        "white_noise_spawn_profile": white_noise_profile,
        "hybrid_reinforcement_profile": hybrid_profile,
        "special_selection": {
            "source_variable": "gv_specialInfestedAttacks_InfestedTypes[1..2]",
            "candidates": list(SPECIAL_TYPE_CANDIDATES),
            "selection_mode": "random_pair_without_replacement",
            "active_slots": 2,
        },
        "night_defender_rules": defender_rules,
        "normal_attack_call_count": len(normal_calls),
        "special_attack_call_count": len(special_calls),
        "generic_attack_call_count": len(generic_calls),
        "night_defender_rule_count": len(defender_rules),
        "white_noise_profile_count": len(white_noise_profile["profiles"]),
        "hybrid_profile_count": len(hybrid_profile["profiles"]),
    }


__all__ = ["extract_map_script"]
