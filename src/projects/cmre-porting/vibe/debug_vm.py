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

from .function_registry import (
    FunctionRegistryError,
    invoke_registered_function,
    normalize_function_id,
    validate_invocation,
)


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
            elif op == "foreach":
                await self._foreach(instruction, scope, position)
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
        raw_function_id = instruction.get("fn", instruction.get("function_id"))
        if isinstance(raw_function_id, bool) or not isinstance(raw_function_id, (str, int)) or raw_function_id == "":
            raise DebugVmError(f"{scope}[{position}] call.fn is required")
        try:
            # Stage 26: 与宿主一致——整数/数字串 id 归一化为生成 adapter 族。
            function_id = normalize_function_id(raw_function_id)
        except FunctionRegistryError as exc:
            raise DebugVmError(f"{scope}[{position}] call.fn rejected: {exc.code}: {exc.detail}") from exc
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

    async def _foreach(self, instruction: dict[str, Any], scope: str, position: int) -> None:
        item = instruction.get("item")
        steps = instruction.get("steps")
        if not isinstance(item, str) or not item:
            raise DebugVmError(f"{scope}[{position}] foreach.item is required")
        if not isinstance(steps, list):
            raise DebugVmError(f"{scope}[{position}] foreach.steps must be an array")
        try:
            source = self._resolve(instruction.get("source"))
        except KeyError as exc:
            raise DebugVmError(f"{scope}[{position}] foreach.source does not exist") from exc
        if not isinstance(source, list):
            raise DebugVmError(f"{scope}[{position}] foreach.source must resolve to an array")
        max_items = instruction.get("max_items", 1000)
        if isinstance(max_items, bool) or not isinstance(max_items, int) or not 1 <= max_items <= 10000:
            raise DebugVmError(f"{scope}[{position}] foreach.max_items must be 1..10000")
        if len(source) > max_items:
            raise DebugVmError(f"{scope}[{position}] foreach source exceeds max_items")
        for index, value in enumerate(source):
            self._vars[item] = value
            await self._execute_steps(steps, scope=f"{scope}[{position}].foreach[{index}]")

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


# ---------------------------------------------------------------------------
# Offline session bridge (VIBE-VM-001)
# ---------------------------------------------------------------------------

DEBUG_VM_SCENARIO: dict[str, Any] = {
    "schema_version": "m7.v1",
    "name": "vibe-debug-vm-coverage",
    "description": (
        "Offline coverage bed for the debug VM: player 1 owns a terran base, "
        "player 2 is hostile so attack orders have a legal target."
    ),
    "players": [
        {"id": 1, "name": "Terran", "race": "terran", "allies": [], "is_ai": True},
        {"id": 2, "name": "Hostile", "race": "terran", "allies": [], "is_ai": True},
    ],
    "spawns": [
        {"unit_type_id": "CommandCenter", "owner_player_id": 1, "x": 0.0, "y": 0.0},
        {"unit_type_id": "SupplyDepot", "owner_player_id": 1, "x": 2.0, "y": 0.0},
        {"unit_type_id": "SCV", "owner_player_id": 1, "x": 0.0, "y": 0.0},
    ],
    "commands": [],
    "max_loops": 2000,
    "seed": 42,
    "strict": True,
    "win_condition": "annihilation",
    "initial_minerals": 250,
    "initial_vespene": 0,
}


class SimulatorSessionDebugVmBridge:
    """Offline peer of the live Host bridge, backed by a real SimulatorSession.

    Unlike a stub, every ``vibe.*`` call lands on ``SimulatorTransport`` and
    mutates a genuine simulated world, so debug programs can be proven against
    real side effects without a live SC2. ``gen.*`` stays a routing marker on
    purpose: the generated adapters only exist inside Galaxy, and fabricating
    fake effects for them offline would be a lie the runtime cannot honour.
    """

    def __init__(
        self,
        *,
        scenario: dict[str, Any] | None = None,
        catalog: str = "m7",
        session_id: str = "vm-debug",
    ) -> None:
        from .simulator_transport import SimulatorTransport

        self._transport = SimulatorTransport()
        self._session_id = session_id
        self._sequence = 0
        self._transport.open_session(session_id)
        self._send(
            "scenario.load",
            {"scenario_dict": scenario or DEBUG_VM_SCENARIO, "catalog": catalog},
            raise_on_error=True,
        )
        self._send("scenario.reset", {}, raise_on_error=True)

    @property
    def transport(self):
        """The backing transport (useful for assertions on executed counts)."""
        return self._transport

    @property
    def session(self):
        """The live SimulatorSession, for direct world inspection in tests."""
        return self._transport.session

    def _send(self, operation: str, args: dict[str, Any], *, raise_on_error: bool = False):
        from . import protocol

        self._sequence += 1
        request = protocol.make_request(
            self._session_id,
            f"{operation}-{self._sequence}",
            self._sequence,
            operation,
            args,
        )
        response = self._transport.send(request)
        if raise_on_error and response.kind == "error":
            raise DebugVmError(
                f"{operation} failed: {response.error_code}: {response.payload}"
            )
        return response

    def call(self, function_id: str, args: dict[str, Any]) -> Any:
        # gen.* adapters only exist inside the live Galaxy runtime; offline we
        # surface them as a routing marker. We still enforce the SAME argument
        # contract as every other path (via the canonical offline dispatcher):
        # valid args -> routed marker with normalized args; invalid -> an
        # error-shaped response the VM recognises (so the runtime contract is
        # uniform across all 11676 gen.* internal functions, not just vibe.*).
        if function_id.startswith("gen."):
            try:
                routed = invoke_registered_function(function_id, args)
            except FunctionRegistryError as exc:
                return {
                    "function_id": function_id,
                    "routed": "runtime",
                    "error_code": exc.code,
                    "payload": {"reason": exc.code, "detail": exc.detail},
                }
            return routed
        # Errors are returned, not raised: DebugVm owns allow_error semantics.
        return self._send("function.invoke", {"function_id": function_id, "args": args})

    def step(self, loops: int = 1) -> Any:
        return self._send("scenario.step", {"loops": int(loops)})


def _request_json(request: Any) -> str:
    """Serialize a ``protocol.Request`` dataclass to the wire JSON string."""
    from dataclasses import asdict

    return json.dumps(asdict(request))


class HostDebugVmBridge:
    """Live peer of SimulatorSessionDebugVmBridge, backed by a running Vibe Host.

    The live Galaxy Kernel owns both ``vibe.*`` real execution and ``gen.*``
    runtime dispatch, so this bridge forwards calls to a live host over the same
    typed ``protocol`` RPC. ``gen.*`` is surfaced as a routing marker without a
    connection so the VM can prove routability even before a host is attached.

    Constructing it does not open a connection; the websocket is opened lazily
    on the first online call. ``aiohttp`` is imported lazily so
    ``import vibe.debug_vm`` never fails when the dependency is absent.
    """

    def __init__(self, url: str, *, session_id: str = "vm-debug-host") -> None:
        self._url = url
        self._session_id = session_id
        self._sequence = 0
        self._ws = None
        self._client = None

    async def _ensure_connection(self):
        if self._ws is not None:
            return self._ws
        import aiohttp  # lazy: only needed for a live host
        from . import protocol

        self._client = aiohttp.ClientSession()
        self._ws = await self._client.ws_connect(self._url, max_msg_size=0)
        return self._ws

    def _make_request(self, operation: str, args: dict[str, Any]):
        from . import protocol

        self._sequence += 1
        return protocol.make_request(
            self._session_id,
            f"{operation}-{self._sequence}",
            self._sequence,
            operation,
            args,
        )

    async def call(self, function_id: str, args: dict[str, Any]) -> Any:
        if function_id.startswith("gen."):
            # Offline we still enforce the argument contract so the VM can prove
            # routability honestly; the live host would validate the same way.
            try:
                routed = invoke_registered_function(function_id, args)
            except FunctionRegistryError as exc:
                return {
                    "function_id": function_id,
                    "routed": "runtime",
                    "error_code": exc.code,
                    "payload": {"reason": exc.code, "detail": exc.detail},
                }
            return routed
        ws = await self._ensure_connection()
        request = self._make_request(
            "function.invoke", {"function_id": function_id, "args": args}
        )
        await ws.send_str(_request_json(request))
        return await self._recv(request.request_id)

    async def step(self, loops: int = 1) -> Any:
        ws = await self._ensure_connection()
        request = self._make_request("scenario.step", {"loops": int(loops)})
        await ws.send_str(_request_json(request))
        return await self._recv(request.request_id)

    async def _recv(self, request_id: str):
        import aiohttp  # lazy
        from . import protocol

        ws = self._ws
        async for message in ws:
            if message.type == aiohttp.WSMsgType.TEXT:
                response = protocol.Response(**json.loads(message.data))
                if response.request_id == request_id:
                    return response
            if message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                break
        raise DebugVmError(f"host closed without responding to {request_id}")

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
        if self._client is not None:
            await self._client.close()
