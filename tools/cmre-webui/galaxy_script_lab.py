"""Validation and persistence helpers for the editable Galaxy runtime module."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

USER_SCRIPT_NAME = "LibDouQuquUser.galaxy"
USER_FUNCTION_ID = "douququ.user.run"
USER_FUNCTION_SIGNATURE = re.compile(
    r"\bstring\s+libDouQuquUser_gf_Run\s*\(\s*string\s+argsJson\s*\)"
)
FORBIDDEN_TOKENS = (
    "void InitMap",
    "void MapScript",
    "libVibeKernel_gf_RegisterEntryPoints",
    "libVibeKernel_gv_currentSession =",
)


def source_sha256(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _balanced(source: str, opening: str, closing: str) -> bool:
    depth = 0
    in_string = False
    escaped = False
    for char in source:
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
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not in_string


def validate_source(source: str) -> dict:
    diagnostics: list[dict[str, str]] = []
    if not isinstance(source, str):
        return {"valid": False, "diagnostics": [{"level": "error", "message": "source 必须是字符串"}]}
    if source.startswith("\ufeff"):
        diagnostics.append({"level": "error", "message": "Galaxy 源码不能包含 UTF-8 BOM"})
    if not source.strip():
        diagnostics.append({"level": "error", "message": "源码不能为空"})
    if len(source.encode("utf-8")) > 64 * 1024:
        diagnostics.append({"level": "error", "message": "源码超过 64 KiB 限制"})
    if USER_FUNCTION_SIGNATURE.search(source) is None:
        diagnostics.append({"level": "error", "message": "缺少固定入口 string libDouQuquUser_gf_Run(string argsJson)"})
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("include ") and stripped != 'include "LibVibeKernel_h"':
            diagnostics.append({"level": "error", "message": f"只允许 include LibVibeKernel_h: {stripped}"})
    for token in FORBIDDEN_TOKENS:
        if token in source:
            diagnostics.append({"level": "error", "message": f"源码不能包含受保护结构: {token}"})
    for opening, closing, label in (("{", "}", "大括号"), ("(", ")", "小括号"), ("[", "]", "方括号")):
        if not _balanced(source, opening, closing):
            diagnostics.append({"level": "error", "message": f"{label}不平衡"})
    if "libVibeKernel_gf_MakeResponse" not in source:
        diagnostics.append({"level": "warning", "message": "入口未调用 libVibeKernel_gf_MakeResponse，SC2 RPC 可能无法解析返回值"})
    if not diagnostics:
        diagnostics.append({"level": "info", "message": "结构检查通过；最终编译结果以重载后的 SC2 ScriptError gate 为准"})
    return {
        "valid": not any(item["level"] == "error" for item in diagnostics),
        "diagnostics": diagnostics,
        "function_id": USER_FUNCTION_ID,
        "sha256": source_sha256(source),
        "bytes": len(source.encode("utf-8")),
    }


def read_source(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")
