"""Small, typed runtime debug VM for hot-loading Vibe test programs.

The VM executes JSON instructions outside Galaxy and calls only explicit Vibe
registry entries through a bridge. It is deliberately not Python eval, Galaxy
reflection, or a way to invoke arbitrary function names.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, Protocol

from .function_registry import FunctionRegistryError, validate_invocation


REPO_ROOT = Path(__file__).resolve().parents[4]
REGISTRY_PATH = REPO_ROOT / "tools" / "galaxy-vibe" / "kernel" / "function-registry.json"
VM_VERSION = "vibe-debug/1"


class DebugVmError(ValueError):
    """A malformed program or a failed runtime debug assertion."""


class DebugVmBridge(Protocol):
    def call(self, function_id: str, args: dict[str, Any]) -> Any:
        """Call one explicitly registered runtime function."""

    def step(self, loops: int) -> Any:
        """Advance the runtime session and return an observation summary."""


def load_function_metadata(path: Path = REGISTRY_PATH) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    functions = data.get("functions")
    if not isinstance(functions, dict):
        raise DebugVmError("function registry must contain an object at functions")
    return functions


def load_function_catalog(path: Path) -> list[dict[str, Any]]:
    """Load the generated all-functions inventory used by catalog.search."""
    data = json.loads(path.read_text(encoding="utf-8"))
    functions = data.get("functions")
    if not isinstance(functions, list):
        raise DebugVmError("function catalog must contain an array at functions")
    return functions


def _response_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    payload = getattr(response, "payload", {})
    return {
        "kind": getattr(response, "kind", "result"),
        "error_code": getattr(response, "error_code", "OK"),
        "payload": payload if isinstance(payload, dict) else {},
        "state_version": getattr(response, "state_version", 0),
        "request_id": getattr(response, "request_id", ""),
        "sequence": getattr(response, "sequence", 0),
    }


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _lookup(value: Any, path: str) -> Any:
    current = value
    if path in ("", "."):
        return current
    for token in path.split("."):
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(path)
            current = current[token]
        elif isinstance(current, list) and token.isdigit():
            current = current[int(token)]
        else:
            raise KeyError(path)
    return current


class DebugVm:
    """Execute bounded debug bytecode against a simulator or live Host bridge."""

    def __init__(
        self,
        bridge: DebugVmBridge,
        *,
        function_metadata: dict[str, dict[str, Any]] | None = None,
        catalog: list[dict[str, Any]] | None = None,
        max_instructions: int = 512,
    ) -> None:
        self.bridge = bridge
        self.function_metadata = function_metadata or load_function_metadata()
        self.catalog = catalog or []
        self.max_instructions = max(1, int(max_instructions))
        self._instruction_count = 0
        self._trace: list[dict[str, Any]] = []
        self._vars: dict[str, Any] = {}
        self._last: dict[str, Any] = {}
        self._mode = "debug"

    async def run(self, program: dict[str, Any]) -> dict[str, Any]:
        self._reset()
        self._validate_program(program)
        self._mode = str(program.get("mode", "debug"))
        try:
            await self._execute_steps(program["steps"], scope="root")
        except DebugVmError as exc:
            return self._result("failed", str(exc))
        return self._result("passed", "")

    def _reset(self) -> None:
        self._instruction_count = 0
        self._trace = []
        self._vars = {}
        self._last = {}
        self._mode = "debug"

    def _validate_program(self, program: Any) -> None:
        if not isinstance(program, dict):
            raise DebugVmError("program must be an object")
        if program.get("vm") != VM_VERSION:
            raise DebugVmError(f"unsupported vm version: {program.get('vm')!r}")
        if not isinstance(program.get("steps"), list):
            raise DebugVmError("program.steps must be an array")
        if program.get("mode", "debug") not in ("debug", "strategy"):
            raise DebugVmError("program.mode must be debug or strategy")

    async def _execute_steps(self, steps: list[Any], *, scope: str) -> None:
        for position, instruction in enumerate(steps):
            self._instruction_count += 1
            if self._instruction_count > self.max_instructions:
                raise DebugVmError("instruction budget exceeded")
            if not isinstance(instruction, dict):
                raise DebugVmError(f"{scope}[{position}] must be an object")
            op = instruction.get("op")
            if op == "call":
                await self._call(instruction, scope, position)
            elif op == "step":
                await self._step(instruction, scope, position)
            elif op == "assert":
                self._assert(instruction, scope, position)
            elif op == "set":
                self._set(instruction, scope, position)
            elif op == "repeat":
                await self._repeat(instruction, scope, position)
            elif op == "catalog.search":
                self._catalog_search(instruction, scope, position)
            else:
                raise DebugVmError(f"{scope}[{position}] unknown op: {op!r}")

    def _resolve(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self._resolve(item) for item in value]
        if isinstance(value, dict):
            if set(value) == {"$ref"}:
                return self._resolve_reference(str(value["$ref"]))
            return {key: self._resolve(item) for key, item in value.items()}
        if isinstance(value, str) and value.startswith("$"):
            return self._resolve_reference(value[1:])
        return value

    def _resolve_reference(self, reference: str) -> Any:
        if reference == "last":
            return self._last
        if reference.startswith("last."):
            return _lookup(self._last, reference[5:])
        if reference.startswith("vars."):
            return _lookup(self._vars, reference[5:])
        if reference in self._vars:
            return self._vars[reference]
        raise DebugVmError(f"unknown reference: ${reference}")

    async def _call(self, instruction: dict[str, Any], scope: str, position: int) -> None:
        function_id = instruction.get("fn", instruction.get("function_id"))
        if not isinstance(function_id, str) or not function_id:
            raise DebugVmError(f"{scope}[{position}] call.fn is required")
        metadata = self.function_metadata.get(function_id)
        if metadata is None:
            raise DebugVmError(f"function is not registered: {function_id}")
        if self._mode == "strategy" and metadata.get("debug_only", False):
            raise DebugVmError(f"debug-only function is forbidden in strategy mode: {function_id}")
        args = self._resolve(instruction.get("args", {}))
        if not isinstance(args, dict):
            raise DebugVmError(f"{scope}[{position}] call.args must be an object")
        try:
            args = validate_invocation(function_id, args, registry=self.function_metadata)
        except FunctionRegistryError as exc:
            raise DebugVmError(f"{function_id} rejected: {exc.code}: {exc.detail}") from exc
        response = _response_dict(await _maybe_await(self.bridge.call(function_id, args)))
        payload = response.get("payload", response)
        self._last = payload if isinstance(payload, dict) else {"value": payload}
        trace = {
            "index": self._instruction_count,
            "op": "call",
            "function_id": function_id,
            "args": args,
            "error_code": response.get("error_code", "OK"),
            "state_version": response.get("state_version", 0),
            "request_id": response.get("request_id", ""),
            "payload": self._last,
        }
        allowed_error = bool(instruction.get("allow_error", False))
        is_error = response.get("kind") == "error" or response.get("error_code", "OK") not in (0, "0", "OK")
        trace["status"] = "allowed-error" if is_error and allowed_error else ("failed" if is_error else "passed")
        self._trace.append(trace)
        if is_error and not allowed_error:
            raise DebugVmError(f"{function_id} failed: {response.get('error_code')}: {self._last}")
        save = instruction.get("save")
        if save is not None:
            if not isinstance(save, str) or not save:
                raise DebugVmError(f"{scope}[{position}] call.save must be a non-empty string")
            self._vars[save] = self._last

    async def _step(self, instruction: dict[str, Any], scope: str, position: int) -> None:
        loops = instruction.get("loops", 1)
        if isinstance(loops, bool) or not isinstance(loops, int) or not 1 <= loops <= 10000:
            raise DebugVmError(f"{scope}[{position}] step.loops must be 1..10000")
        response = _response_dict(await _maybe_await(self.bridge.step(loops)))
        self._last = response.get("payload", response)
        self._trace.append({
            "index": self._instruction_count,
            "op": "step",
            "loops": loops,
            "status": "passed" if response.get("error_code", "OK") in (0, "0", "OK") else "failed",
            "state_version": response.get("state_version", 0),
            "payload": self._last,
        })
        if response.get("kind") == "error" or response.get("error_code", "OK") not in (0, "0", "OK"):
            raise DebugVmError(f"step failed: {response.get('error_code')}: {self._last}")
        save = instruction.get("save")
        if save:
            self._vars[save] = self._last

    def _assert(self, instruction: dict[str, Any], scope: str, position: int) -> None:
        source = self._resolve(instruction.get("source", "$last"))
        path = instruction.get("path", "")
        try:
            actual = _lookup(source, path)
            exists = True
        except KeyError:
            actual = None
            exists = False
        passed = exists
        reason = "exists"
        for key, comparator in (
            ("equals", lambda value, expected: value == expected),
            ("not_equals", lambda value, expected: value != expected),
            ("gte", lambda value, expected: value >= expected),
            ("lte", lambda value, expected: value <= expected),
            ("contains", lambda value, expected: expected in value),
        ):
            if key in instruction:
                expected = self._resolve(instruction[key])
                passed = exists and comparator(actual, expected)
                reason = f"{key} {expected!r}"
                break
        trace = {
            "index": self._instruction_count,
            "op": "assert",
            "path": path,
            "actual": actual,
            "status": "passed" if passed else "failed",
            "reason": reason,
        }
        self._trace.append(trace)
        if not passed:
            raise DebugVmError(f"assert failed at {scope}[{position}]: {path} -> {actual!r}, expected {reason}")

    def _set(self, instruction: dict[str, Any], scope: str, position: int) -> None:
        name = instruction.get("name")
        if not isinstance(name, str) or not name:
            raise DebugVmError(f"{scope}[{position}] set.name is required")
        self._vars[name] = self._resolve(instruction.get("value"))
        self._trace.append({"index": self._instruction_count, "op": "set", "name": name, "status": "passed"})

    async def _repeat(self, instruction: dict[str, Any], scope: str, position: int) -> None:
        count = instruction.get("count")
        steps = instruction.get("steps")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10000:
            raise DebugVmError(f"{scope}[{position}] repeat.count must be 1..10000")
        if not isinstance(steps, list):
            raise DebugVmError(f"{scope}[{position}] repeat.steps must be an array")
        for index in range(count):
            await self._execute_steps(steps, scope=f"{scope}[{position}].repeat[{index}]")

    def _catalog_search(self, instruction: dict[str, Any], scope: str, position: int) -> None:
        pattern = str(instruction.get("name", "")).lower()
        kind = instruction.get("kind")
        source_id = instruction.get("source_id")
        limit = instruction.get("limit", 50)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise DebugVmError(f"{scope}[{position}] catalog.search.limit must be 1..1000")
        matches = [
            entry for entry in self.catalog
            if (not pattern or pattern in str(entry.get("name", "")).lower())
            and (not kind or entry.get("kind") == kind)
            and (not source_id or entry.get("source_id") == source_id)
        ]
        self._last = {"count": len(matches), "functions": matches[:limit]}
        self._trace.append({"index": self._instruction_count, "op": "catalog.search", "status": "passed", **self._last})
        save = instruction.get("save")
        if save:
            self._vars[save] = self._last

    def _result(self, status: str, error: str) -> dict[str, Any]:
        return {
            "vm": VM_VERSION,
            "status": status,
            "error": error,
            "instructions_executed": self._instruction_count,
            "vars": self._vars,
            "last": self._last,
            "trace": self._trace,
        }
