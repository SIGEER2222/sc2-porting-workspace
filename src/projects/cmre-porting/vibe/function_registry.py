"""Explicit typed Vibe function registry shared by Host and Simulator.

The JSON registry is metadata, not executable code. Python dispatch is an
explicit map and the Galaxy Kernel has a matching explicit map. This keeps the
function-level API typed without reintroducing arbitrary reflection.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


REGISTRY_PATH = Path(__file__).resolve().parents[4] / "tools" / "galaxy-vibe" / "kernel" / "function-registry.json"


class FunctionRegistryError(ValueError):
    """A rejected function ID or typed argument set."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


# 注册表现在是 7MB+ / 11910 条，而它曾经在每次 validate_invocation 里被重新读盘+解析。
# 一次 function.invoke 会解析两遍（normalize_request_args + wire_function_args），
# 跑一轮全量校验能打出 80GB 量级的磁盘 I/O，并且在高频读下偶发读到空内容。
# 这里按 (mtime_ns, size) 做缓存：文件一改就自然失效，既保住「改注册表立刻生效」的
# 开发体验，又不再重复解析。
_REGISTRY_CACHE: dict[Path, tuple[tuple[int, int], dict[str, dict[str, Any]]]] = {}


def load_function_registry(path: Path = REGISTRY_PATH) -> dict[str, dict[str, Any]]:
    try:
        st = path.stat()
        stamp: tuple[int, int] | None = (st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = None
    if stamp is not None:
        cached = _REGISTRY_CACHE.get(path)
        if cached is not None and cached[0] == stamp:
            return cached[1]
    data = json.loads(path.read_text(encoding="utf-8"))
    functions = data.get("functions")
    if not isinstance(functions, dict) or not functions:
        raise FunctionRegistryError("INVALID_REGISTRY", "functions must be a non-empty object")
    if stamp is not None:
        _REGISTRY_CACHE[path] = (stamp, functions)
    return functions


def _validate_scalar(name: str, value: Any, spec: dict[str, Any]) -> Any:
    type_name = spec.get("type")
    if type_name == "string":
        if not isinstance(value, str):
            raise FunctionRegistryError("INVALID_ARGS", f"{name} must be a string")
        if len(value) > int(spec.get("maxLength", 2**31 - 1)):
            raise FunctionRegistryError("INVALID_ARGS", f"{name} exceeds maxLength")
        if any(ch in value for ch in (";", "=", '"', "\\")):
            raise FunctionRegistryError("INVALID_ARGS", f"{name} contains a wire-unsafe character")
        if spec.get("enum") and value not in spec["enum"]:
            raise FunctionRegistryError("INVALID_ARGS", f"{name} is not an allowed value")
        if spec.get("pattern") and re.fullmatch(spec["pattern"], value) is None:
            raise FunctionRegistryError("INVALID_ARGS", f"{name} has an invalid format")
        return value
    if type_name == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise FunctionRegistryError("INVALID_ARGS", f"{name} must be an integer")
        normalized = value
    elif type_name == "fixed":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FunctionRegistryError("INVALID_ARGS", f"{name} must be numeric")
        normalized = float(value)
    else:
        raise FunctionRegistryError("INVALID_REGISTRY", f"unsupported type for {name}: {type_name}")
    if "min" in spec and normalized < spec["min"]:
        raise FunctionRegistryError("INVALID_ARGS", f"{name} is below minimum")
    if "max" in spec and normalized > spec["max"]:
        raise FunctionRegistryError("INVALID_ARGS", f"{name} is above maximum")
    return normalized


def coerce_cli_args(function_id: Any, raw_args: dict[str, str]) -> dict[str, Any]:
    """Convert REPL key=value strings into the registry's declared scalar types."""
    functions = load_function_registry()
    spec = functions.get(function_id)
    if spec is None:
        raise FunctionRegistryError("FUNCTION_NOT_FOUND", str(function_id))
    coerced: dict[str, Any] = {}
    for name, raw in raw_args.items():
        arg_spec = spec.get("args", {}).get(name)
        if arg_spec is None:
            coerced[name] = raw
            continue
        type_name = arg_spec.get("type")
        try:
            if type_name == "integer":
                coerced[name] = int(raw, 10)
            elif type_name == "fixed":
                coerced[name] = float(raw)
            else:
                coerced[name] = raw
        except (TypeError, ValueError) as exc:
            raise FunctionRegistryError("INVALID_ARGS", f"{name} has invalid {type_name} syntax") from exc
    return validate_invocation(function_id, coerced)


def normalize_function_id(function_id: Any) -> str:
    """Stage 26: integer function ids resolve to the generated adapter family."""
    if isinstance(function_id, bool):
        raise FunctionRegistryError("FUNCTION_NOT_FOUND", str(function_id))
    if isinstance(function_id, int):
        return f"gen.{function_id}"
    if isinstance(function_id, str) and function_id.isdigit():
        return f"gen.{int(function_id)}"
    if not isinstance(function_id, str):
        raise FunctionRegistryError("FUNCTION_NOT_FOUND", str(function_id))
    return function_id


def validate_invocation(function_id: Any, args: Any, *, registry: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    functions = registry or load_function_registry()
    function_id = normalize_function_id(function_id)
    if function_id not in functions:
        raise FunctionRegistryError("FUNCTION_NOT_FOUND", str(function_id))
    if not isinstance(args, dict):
        raise FunctionRegistryError("INVALID_ARGS", "args must be an object")
    spec = functions[function_id]
    arg_specs = spec.get("args", {})
    unknown = sorted(set(args) - set(arg_specs))
    if unknown:
        raise FunctionRegistryError("INVALID_ARGS", f"unknown args: {','.join(unknown)}")
    normalized: dict[str, Any] = {}
    for name, arg_spec in arg_specs.items():
        if name not in args:
            if arg_spec.get("required", False):
                raise FunctionRegistryError("INVALID_ARGS", f"missing required arg: {name}")
            if "default" in arg_spec:
                normalized[name] = arg_spec["default"]
            continue
        normalized[name] = _validate_scalar(name, args[name], arg_spec)
    return normalized


def normalize_request_args(request_args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not isinstance(request_args, dict):
        raise FunctionRegistryError("INVALID_ARGS", "function.invoke args must be an object")
    function_id = normalize_function_id(request_args.get("function_id"))
    call_args = request_args.get("args", {})
    return function_id, validate_invocation(function_id, call_args)


def wire_function_args(function_id: Any, args: Any) -> dict[str, Any]:
    function_id = normalize_function_id(function_id)
    normalized = validate_invocation(function_id, args)
    wire = {"function_id": function_id}
    for name, value in normalized.items():
        wire[f"arg_{name}"] = value
    wire["arg_names"] = ",".join(sorted(normalized))
    return wire


def invoke_registered_function(
    function_id: Any,
    args: Any,
    *,
    registry: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Canonical offline dispatcher covering every registered internal function.

    Routing is an explicit family map, never reflection:

    * ``vibe.test.ping`` — diagnostic, answered right here.
    * other ``vibe.*``   — owned by ``SimulatorTransport._dispatch_function``
      (real simulated side effects); this layer confirms the route.
    * ``gen.*``          — owned by the generated Galaxy adapters, which only
      exist inside the SC2 runtime; offline we confirm the route only and
      deliberately do NOT fabricate side effects.

    ``registry`` lets callers sweep a preloaded registry without re-reading the
    7MB JSON once per function.
    """
    canonical = normalize_function_id(function_id)
    normalized = validate_invocation(canonical, args, registry=registry)
    if canonical == "vibe.test.ping":
        return {
            "function_id": canonical,
            "message": "pong",
            "nonce": normalized.get("nonce", ""),
        }
    if canonical.startswith("vibe."):
        return {"function_id": canonical, "routed": "simulator", "args": normalized}
    if canonical.startswith("gen."):
        return {"function_id": canonical, "routed": "runtime", "args": normalized}
    raise FunctionRegistryError("FUNCTION_NOT_FOUND", str(function_id))
