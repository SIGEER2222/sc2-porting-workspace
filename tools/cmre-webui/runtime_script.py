"""Compile a small hot runtime script into the existing Vibe Debug VM format.

This is intentionally not an arbitrary Galaxy compiler.  SC2 compiles Galaxy when
it loads the map, so a live process can only execute behavior that was already
compiled into the runtime bridge.  The script language below is a thin,
auditable text surface over those registered function.invoke calls.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

VM_VERSION = "vibe-debug/1"
SCRIPT_SCHEMA_VERSION = "douququ-runtime-script.v1"
RULES_SCHEMA_VERSION = "douququ-runtime-rules.v1"
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CALL_RE = re.compile(
    r"^(?:(?:let|var)\s+(?P<let>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*)?"
    r"call\s+(?P<fn>[^\s{]+)\s*(?P<args>\{.*\})?"
    r"(?:\s+as\s+(?P<as>[A-Za-z_][A-Za-z0-9_]*))?$"
)
SET_RE = re.compile(r"^(?:let|var|set)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.+)$")
STEP_RE = re.compile(r"^(?:step|Step)\s*\(?\s*(?P<loops>\d+)\s*\)?$")
ASSERT_RE = re.compile(
    r"^assert\s+(?P<left>[$A-Za-z_][A-Za-z0-9_.$]*)"
    r"(?:\s*(?P<op>==|!=|>=|<=|contains)\s*(?P<right>.+)|\s+exists)?$"
)
FUNC_RE = re.compile(
    r"^(?:(?:let|var)\s+(?P<let>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*)?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\((?P<args>.*)\)"
    r"(?:\s+as\s+(?P<as>[A-Za-z_][A-Za-z0-9_]*))?$"
)
RULE_HEADER_RE = re.compile(
    r'^rule\s+"(?P<id>[^"]+)"\s+on\s+(?P<event>[A-Za-z_][A-Za-z0-9_]*)'
    r'(?:\s+where\s+(?P<where>.+))?$'
)
CONDITION_RE = re.compile(
    r"^(?P<left>(?:event|payload)?\.?[A-Za-z_][A-Za-z0-9_.]*)"
    r"(?:\s*(?P<op>==|!=|>=|<=|>|<|contains)\s*(?P<right>.+)|\s+exists)$"
)


class RuntimeScriptError(ValueError):
    """Raised when a hot runtime script cannot be compiled safely."""


@dataclass(frozen=True)
class Statement:
    line: int
    text: str


def _sha256(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _strip_comment(line: str) -> str:
    in_string = False
    escaped = False
    for index, char in enumerate(line):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "#":
            return line[:index]
        elif char == "/" and index + 1 < len(line) and line[index + 1] == "/":
            return line[:index]
    return line


def _split_statements(source: str) -> list[Statement]:
    statements: list[Statement] = []
    buffer: list[str] = []
    start_line = 1
    depth = 0
    in_string = False
    escaped = False

    for line_no, raw_line in enumerate(source.splitlines(), start=1):
        line = _strip_comment(raw_line).strip()
        if not line and not buffer:
            continue
        if not buffer:
            start_line = line_no
        for char in line:
            if in_string:
                buffer.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                buffer.append(char)
            elif char in "[{(":
                depth += 1
                buffer.append(char)
            elif char in "]})":
                depth -= 1
                if depth < 0:
                    raise RuntimeScriptError(f"line {line_no}: closing delimiter without opener")
                buffer.append(char)
            elif char == ";" and depth == 0:
                text = "".join(buffer).strip()
                if text:
                    statements.append(Statement(start_line, text))
                buffer = []
                start_line = line_no
            else:
                buffer.append(char)
        if depth == 0 and buffer:
            text = "".join(buffer).strip()
            if text:
                statements.append(Statement(start_line, text))
            buffer = []
        elif buffer:
            buffer.append(" ")
    if in_string:
        raise RuntimeScriptError("unterminated string literal")
    if depth != 0:
        raise RuntimeScriptError("unbalanced delimiters")
    text = "".join(buffer).strip()
    if text:
        statements.append(Statement(start_line, text))
    return statements


def _json_value(raw: str, *, line: int) -> Any:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeScriptError(f"line {line}: invalid JSON value: {exc.msg}") from exc


def _json_object(raw: str | None, *, line: int) -> dict[str, Any]:
    if raw is None or not raw.strip():
        return {}
    value = _json_value(raw, line=line)
    if not isinstance(value, dict):
        raise RuntimeScriptError(f"line {line}: call args must be a JSON object")
    return value


def _json_args(raw: str, *, line: int) -> list[Any]:
    if not raw.strip():
        return []
    value = _json_value(f"[{raw}]", line=line)
    if not isinstance(value, list):
        raise RuntimeScriptError(f"line {line}: function args must parse as a JSON array")
    return value


def _save_target(match: re.Match[str]) -> str | None:
    return match.group("let") or match.group("as")


def _validate_save(name: str | None, *, line: int) -> None:
    if name is not None and IDENT_RE.match(name) is None:
        raise RuntimeScriptError(f"line {line}: invalid save name {name!r}")


def _left_ref(left: str, *, line: int) -> tuple[str, str]:
    ref = left[1:] if left.startswith("$") else left
    if ref == "last":
        return "$last", ""
    if ref.startswith("last."):
        return "$last", ref[5:]
    if ref.startswith("vars."):
        ref = ref[5:]
    if "." not in ref:
        return f"$vars.{ref}", ""
    name, path = ref.split(".", 1)
    if IDENT_RE.match(name) is None:
        raise RuntimeScriptError(f"line {line}: invalid assertion source {left!r}")
    return f"$vars.{name}", path


def _assert_step(match: re.Match[str], *, line: int) -> dict[str, Any]:
    source, path = _left_ref(match.group("left"), line=line)
    step: dict[str, Any] = {"op": "assert", "source": source, "path": path}
    op = match.group("op")
    if op is None:
        return step
    right = _json_value(match.group("right"), line=line)
    key = {"==": "equals", "!=": "not_equals", ">=": "gte", "<=": "lte", "contains": "contains"}[op]
    step[key] = right
    return step


def _call_step(function_id: str, args: dict[str, Any], save: str | None, *, line: int) -> dict[str, Any]:
    _validate_save(save, line=line)
    step: dict[str, Any] = {"op": "call", "fn": function_id, "args": args}
    if save:
        step["save"] = save
    return step


def _alias_step(name: str, args: list[Any], save: str | None, *, line: int) -> dict[str, Any]:
    normalized = name.lower()
    if normalized == "unitcreate":
        if len(args) != 4:
            raise RuntimeScriptError(f"line {line}: UnitCreate(owner, unit_type, x, y) expects 4 args")
        owner, unit_type, x, y = args
        return _call_step(
            "douququ.unit.spawn",
            {"owner": owner, "unit_type": unit_type, "x": x, "y": y},
            save,
            line=line,
        )
    if normalized in {"playersetminerals", "setminerals"}:
        if len(args) != 2:
            raise RuntimeScriptError(f"line {line}: PlayerSetMinerals(owner, minerals) expects 2 args")
        return _call_step(
            "douququ.player.set_minerals",
            {"owner": args[0], "minerals": args[1]},
            save,
            line=line,
        )
    if normalized in {"snapshot", "douququsnapshot"}:
        if args:
            raise RuntimeScriptError(f"line {line}: Snapshot() expects no args")
        return _call_step("douququ.snapshot", {}, save, line=line)
    if normalized in {"runtimestatus", "status"}:
        if args:
            raise RuntimeScriptError(f"line {line}: RuntimeStatus() expects no args")
        return _call_step("douququ.runtime.status", {}, save, line=line)
    if normalized in {"replacescarabprojectile", "scarabprojectilereplace"}:
        if len(args) != 1:
            raise RuntimeScriptError(f"line {line}: ReplaceScarabProjectile(ammo_unit) expects 1 arg")
        return _call_step(
            "vibe.catalog.set",
            {"catalog": "effect", "entry": "ScarabLM", "field": "AmmoUnit", "player": 1, "value": args[0]},
            save,
            line=line,
        )

    if normalized == "unitsetlife":
        if len(args) != 2:
            raise RuntimeScriptError(f"line {line}: UnitSetLife(unit_tag, life) expects 2 args")
        return _call_step(
            "douququ.unit.set_life",
            {"unit_tag": args[0], "life": args[1]},
            save,
            line=line,
        )
    if normalized == "unitkill":
        if len(args) != 2:
            raise RuntimeScriptError(f"line {line}: UnitKill(killer_tag, victim_tag) expects 2 args")
        return _call_step(
            "douququ.kill",
            {"killer_tag": args[0], "victim_tag": args[1]},
            save,
            line=line,
        )
    if normalized == "step":
        if len(args) != 1 or isinstance(args[0], bool) or not isinstance(args[0], int):
            raise RuntimeScriptError(f"line {line}: Step(loops) expects one integer arg")
        return {"op": "step", "loops": args[0]}
    raise RuntimeScriptError(
        f"line {line}: unknown script function {name!r}; use call <function_id> {{...}} for registered functions"
    )


def _compile_statement(statement: Statement) -> dict[str, Any]:
    text = statement.text
    line = statement.line
    if match := STEP_RE.match(text):
        loops = int(match.group("loops"))
        if loops < 1 or loops > 10000:
            raise RuntimeScriptError(f"line {line}: step loops must be 1..10000")
        return {"op": "step", "loops": loops}
    if match := CALL_RE.match(text):
        return _call_step(
            match.group("fn"),
            _json_object(match.group("args"), line=line),
            _save_target(match),
            line=line,
        )
    if match := ASSERT_RE.match(text):
        return _assert_step(match, line=line)
    if match := FUNC_RE.match(text):
        return _alias_step(match.group("name"), _json_args(match.group("args"), line=line), _save_target(match), line=line)
    if match := SET_RE.match(text):
        return {"op": "set", "name": match.group("name"), "value": _json_value(match.group("value"), line=line)}
    raise RuntimeScriptError(f"line {line}: unsupported statement {text!r}")


def _brace_delta(line: str) -> int:
    visible = _strip_comment(line)
    in_string = False
    escape = False
    depth = 0
    for char in visible:
        if escape:
            escape = False
            continue
        if char == "\\" and in_string:
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
    return depth


def _split_rule_blocks(source: str) -> list[tuple[int, str, str]]:
    blocks: list[tuple[int, str, str]] = []
    header_line = 0
    header = ""
    body_lines: list[str] = []
    depth = 0
    for line_no, raw_line in enumerate(source.splitlines(), start=1):
        visible = _strip_comment(raw_line).strip()
        if depth == 0:
            if not visible:
                continue
            if "{" not in visible:
                raise RuntimeScriptError(f"line {line_no}: rule header must end with {{")
            before, after = raw_line.split("{", 1)
            header_line = line_no
            header = before.strip()
            if not header.startswith("rule "):
                raise RuntimeScriptError(f"line {line_no}: expected rule header")
            depth = 1 + _brace_delta(after)
            if depth < 0:
                raise RuntimeScriptError(f"line {line_no}: unmatched rule close brace")
            if depth == 0:
                body_lines = [after.rsplit("}", 1)[0]]
                blocks.append((header_line, header, "\n".join(body_lines)))
                body_lines = []
            else:
                body_lines = [after]
            continue
        body_lines.append(raw_line)
        depth += _brace_delta(raw_line)
        if depth < 0:
            raise RuntimeScriptError(f"line {line_no}: unmatched rule close brace")
        if depth == 0:
            if "}" in body_lines[-1]:
                body_lines[-1] = body_lines[-1].rsplit("}", 1)[0]
            blocks.append((header_line, header, "\n".join(body_lines)))
            body_lines = []
    if depth != 0:
        raise RuntimeScriptError(f"line {header_line}: unclosed rule block")
    return blocks


def _split_conditions(where: str, *, line: int) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    in_string = False
    escape = False
    index = 0
    while index < len(where):
        char = where[index]
        if escape:
            current.append(char)
            escape = False
            index += 1
            continue
        if char == "\\" and in_string:
            current.append(char)
            escape = True
            index += 1
            continue
        if char == '"':
            current.append(char)
            in_string = not in_string
            index += 1
            continue
        if not in_string and where[index:index + 5].lower() == " and ":
            part = "".join(current).strip()
            if not part:
                raise RuntimeScriptError(f"line {line}: empty rule condition")
            parts.append(part)
            current = []
            index += 5
            continue
        current.append(char)
        index += 1
    part = "".join(current).strip()
    if not part:
        raise RuntimeScriptError(f"line {line}: empty rule condition")
    parts.append(part)
    return parts


def _compile_rule_conditions(where: str | None, *, line: int) -> list[dict[str, Any]]:
    if where is None or not where.strip():
        return []
    conditions = []
    for raw in _split_conditions(where.strip(), line=line):
        match = CONDITION_RE.match(raw)
        if not match:
            raise RuntimeScriptError(f"line {line}: invalid rule condition {raw!r}")
        left = match.group("left")
        if left.startswith(".") or ".." in left:
            raise RuntimeScriptError(f"line {line}: invalid rule condition path {left!r}")
        path = left if left.startswith(("event.", "payload.")) else f"payload.{left}"
        op = match.group("op") or "exists"
        condition = {"path": path, "op": op}
        if op != "exists":
            condition["value"] = _json_value(match.group("right"), line=line)
        conditions.append(condition)
    return conditions


def compile_runtime_rules(source: str) -> dict[str, Any]:
    """Compile dynamic event rules that run through the existing Debug VM."""
    if not isinstance(source, str):
        raise RuntimeScriptError("source must be a string")
    if source.startswith("\ufeff"):
        raise RuntimeScriptError("source must not contain UTF-8 BOM")
    if len(source.encode("utf-8")) > 64 * 1024:
        raise RuntimeScriptError("source exceeds 64 KiB limit")
    blocks = _split_rule_blocks(source)
    if not blocks:
        raise RuntimeScriptError("source contains no rule blocks")
    rules = []
    seen = set()
    for line, header, body in blocks:
        match = RULE_HEADER_RE.match(header)
        if not match:
            raise RuntimeScriptError(f"line {line}: invalid rule header {header!r}")
        rule_id = match.group("id").strip()
        if not rule_id:
            raise RuntimeScriptError(f"line {line}: rule id must not be blank")
        if rule_id in seen:
            raise RuntimeScriptError(f"line {line}: duplicate rule id {rule_id!r}")
        seen.add(rule_id)
        event_type = match.group("event")
        statements = _split_statements(body)
        if not statements:
            raise RuntimeScriptError(f"line {line}: rule {rule_id!r} contains no executable statements")
        rules.append({
            "id": rule_id,
            "event_type": event_type,
            "conditions": _compile_rule_conditions(match.group("where"), line=line),
            "program": {"vm": VM_VERSION, "mode": "debug", "steps": [_compile_statement(statement) for statement in statements]},
        })
    return {
        "schema_version": RULES_SCHEMA_VERSION,
        "source_sha256": _sha256(source),
        "rule_count": len(rules),
        "compile_boundary": "current_vibe_session",
        "galaxy_compile_boundary": "next_sc2_map_load",
        "diagnostics": [
            {
                "level": "info",
                "message": "Compiled dynamic event rules to Vibe Debug VM programs; Galaxy source still changes only on next map load.",
            }
        ],
        "rules": rules,
    }


def compile_runtime_script(source: str) -> dict[str, Any]:
    """Compile text into a VM program that runs in the current Vibe session."""
    if not isinstance(source, str):
        raise RuntimeScriptError("source must be a string")
    if source.startswith("\ufeff"):
        raise RuntimeScriptError("source must not contain UTF-8 BOM")
    if len(source.encode("utf-8")) > 32 * 1024:
        raise RuntimeScriptError("source exceeds 32 KiB limit")
    statements = _split_statements(source)
    if not statements:
        raise RuntimeScriptError("source contains no executable statements")
    steps = [_compile_statement(statement) for statement in statements]
    return {
        "schema_version": SCRIPT_SCHEMA_VERSION,
        "source_sha256": _sha256(source),
        "statement_count": len(statements),
        "compile_boundary": "current_vibe_session",
        "galaxy_compile_boundary": "next_sc2_map_load",
        "diagnostics": [
            {
                "level": "info",
                "message": "Compiled to Vibe Debug VM; this does not hot-compile arbitrary Galaxy source.",
            }
        ],
        "program": {"vm": VM_VERSION, "mode": "debug", "steps": steps},
    }
