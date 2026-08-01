"""Declarative observe -> invoke -> assert execution for Vibe tasks.

The runner is deliberately transport-neutral. A simulator adapter and the live
Host adapter both return the same response view, while function selection stays
bounded by the explicit function registry.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .function_registry import FunctionRegistryError, load_function_registry, validate_invocation
from . import protocol
from .simulator_transport import SimulatorTransport


REPO_ROOT = Path(__file__).resolve().parents[4]
_REF_PATTERN = re.compile(r"^\$\{([^}]+)\}$")


class TaskLoopError(ValueError):
    """A task scenario or execution policy is invalid."""


def _path_get(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise KeyError(path)
    return current


def _resolve(value: Any, captures: dict[str, dict[str, Any]]) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            ref = value["$ref"]
            if not isinstance(ref, str) or "." not in ref:
                raise TaskLoopError(f"invalid reference: {ref!r}")
            step_id, path = ref.split(".", 1)
            try:
                return _path_get(captures[step_id], path)
            except KeyError as exc:
                raise TaskLoopError(f"unresolved reference: {ref}") from exc
        return {key: _resolve(item, captures) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, captures) for item in value]
    if isinstance(value, str):
        match = _REF_PATTERN.fullmatch(value)
        if match:
            ref = match.group(1)
            if "." not in ref:
                raise TaskLoopError(f"invalid reference: {ref!r}")
            step_id, path = ref.split(".", 1)
            try:
                return _path_get(captures[step_id], path)
            except KeyError as exc:
                raise TaskLoopError(f"unresolved reference: {ref}") from exc
    return value


def _response_view(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        kind = response.get("kind", "error")
        error_code = response.get("error_code", "OK")
        payload = response.get("payload", {})
        return {
            "kind": kind,
            "request_id": response.get("request_id", ""),
            "sequence": response.get("sequence", 0),
            "operation": response.get("operation", "function.invoke"),
            "error_code": error_code,
            "payload": payload if isinstance(payload, dict) else {},
            "state_version": int(response.get("state_version", 0)),
            "ok": bool(response.get("ok", kind == "result" and error_code in (0, "OK"))),
        }
    kind = getattr(response, "kind", "error")
    error_code = getattr(response, "error_code", "INTERNAL_ERROR")
    return {
        "kind": kind,
        "request_id": getattr(response, "request_id", ""),
        "sequence": getattr(response, "sequence", 0),
        "operation": getattr(response, "operation", "function.invoke"),
        "error_code": error_code,
        "payload": getattr(response, "payload", {}) or {},
        "state_version": int(getattr(response, "state_version", 0)),
        "ok": bool(getattr(response, "is_ok", kind == "result" and error_code in (0, "OK"))),
    }


def _expectation_value(value: Any, captures: dict[str, dict[str, Any]]) -> Any:
    return _resolve(value, captures)


def _check_expectations(view: dict[str, Any], expectations: list[dict[str, Any]],
                        captures: dict[str, dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for expectation in expectations:
        if not isinstance(expectation, dict) or not isinstance(expectation.get("path"), str):
            failures.append("expectation requires a path")
            continue
        path = expectation["path"]
        try:
            actual = _path_get(view, path)
        except KeyError:
            failures.append(f"missing path: {path}")
            continue
        operators = [(key, expectation[key]) for key in ("equals", "not_equals", "gte", "lte", "exists") if key in expectation]
        if len(operators) != 1:
            failures.append(f"expectation requires exactly one operator: {path}")
            continue
        operator, expected_raw = operators[0]
        expected = _expectation_value(expected_raw, captures)
        try:
            passed = {
                "equals": actual == expected,
                "not_equals": actual != expected,
                "gte": actual >= expected,
                "lte": actual <= expected,
                "exists": bool(actual) is bool(expected),
            }[operator]
        except TypeError:
            passed = False
        if not passed:
            failures.append(f"{path} {operator} expected={expected!r} actual={actual!r}")
    return failures


@dataclass(frozen=True)
class TaskStep:
    step_id: str
    mode: str
    function_id: str
    args: dict[str, Any]
    expect: list[dict[str, Any]] = field(default_factory=list)
    retries: int = 0
    min_state_version: int | None = None
    timeout_seconds: float = 5.0


@dataclass
class TaskScenario:
    task_id: str
    steps: list[TaskStep]
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskScenario":
        if not isinstance(data, dict) or data.get("schemaVersion") != 1:
            raise TaskLoopError("task scenario schemaVersion must be 1")
        task_id = data.get("task_id") or data.get("scenario_id")
        if not isinstance(task_id, str) or not task_id:
            raise TaskLoopError("task_id is required")
        raw_steps = data.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise TaskLoopError("steps must be a non-empty list")
        registry = load_function_registry()
        steps: list[TaskStep] = []
        seen: set[str] = set()
        for raw in raw_steps:
            if not isinstance(raw, dict):
                raise TaskLoopError("each step must be an object")
            step_id = raw.get("id")
            function_id = raw.get("function_id")
            mode = raw.get("mode")
            if not isinstance(step_id, str) or not step_id or step_id in seen:
                raise TaskLoopError(f"step id must be unique: {step_id!r}")
            if function_id not in registry:
                raise TaskLoopError(f"function is not registered: {function_id!r}")
            if mode not in {"observe", "act"}:
                raise TaskLoopError(f"step {step_id} mode must be observe or act")
            side_effect = bool(registry[function_id].get("side_effect", False))
            if side_effect != (mode == "act"):
                raise TaskLoopError(f"step {step_id} mode does not match registry side_effect")
            args = raw.get("args", {})
            if not isinstance(args, dict):
                raise TaskLoopError(f"step {step_id} args must be an object")
            arg_specs = registry[function_id].get("args", {})
            unknown = sorted(set(args) - set(arg_specs))
            missing = sorted(name for name, spec in arg_specs.items()
                             if spec.get("required", False) and name not in args)
            if unknown or missing:
                raise TaskLoopError(f"step {step_id} args invalid unknown={unknown} missing={missing}")
            retries = raw.get("retries", 0)
            if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0 or retries > 5:
                raise TaskLoopError(f"step {step_id} retries must be an integer from 0 to 5")
            if mode == "act" and retries:
                raise TaskLoopError(f"step {step_id} side effects cannot be retried")
            expect = raw.get("expect", [])
            if isinstance(expect, dict):
                expect = [expect]
            if not isinstance(expect, list):
                raise TaskLoopError(f"step {step_id} expect must be an object or list")
            min_version = raw.get("min_state_version")
            if min_version is not None and (isinstance(min_version, bool) or not isinstance(min_version, int) or min_version < 0):
                raise TaskLoopError(f"step {step_id} min_state_version must be a non-negative integer")
            timeout_seconds = raw.get("timeout_seconds", 5.0)
            if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                    or timeout_seconds <= 0 or timeout_seconds > 120):
                raise TaskLoopError(
                    f"step {step_id} timeout_seconds must be greater than 0 and at most 120"
                )
            seen.add(step_id)
            steps.append(TaskStep(
                step_id, mode, function_id, args, expect, retries, min_version,
                float(timeout_seconds),
            ))
        return cls(task_id=task_id, steps=steps, metadata=data.get("metadata", {}))

    @classmethod
    def from_file(cls, path: Path) -> "TaskScenario":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8-sig")))


class TaskLoopRunner:
    """Execute a validated scenario through one function invocation callback."""

    def __init__(self, invoke: Callable[[str, dict[str, Any], float], Any]):
        self.invoke = invoke

    def run(self, scenario: TaskScenario) -> dict[str, Any]:
        captures: dict[str, dict[str, Any]] = {}
        trace: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        last_state_version = -1
        for step in scenario.steps:
            step_success = False
            step_failure = ""
            for attempt in range(step.retries + 1):
                try:
                    args = _resolve(step.args, captures)
                    args = validate_invocation(step.function_id, args)
                    raw_response = self.invoke(
                        step.function_id, args, step.timeout_seconds
                    )
                    view = _response_view(raw_response)
                    errors: list[str] = []
                    if not view["request_id"]:
                        errors.append("response missing request_id")
                    if not view["ok"]:
                        errors.append(f"response error: {view['error_code']}")
                    if view["state_version"] < last_state_version:
                        errors.append(
                            f"stale state_version {view['state_version']} < {last_state_version}"
                        )
                    if step.min_state_version is not None and view["state_version"] < step.min_state_version:
                        errors.append(
                            f"state_version {view['state_version']} < required {step.min_state_version}"
                        )
                    if not errors and view["ok"]:
                        errors.extend(_check_expectations(view, step.expect, captures))
                    trace.append({
                        "step_id": step.step_id,
                        "mode": step.mode,
                        "function_id": step.function_id,
                        "attempt": attempt + 1,
                        "request_id": view["request_id"],
                        "state_version": view["state_version"],
                        "ok": not errors,
                        "error_code": view["error_code"],
                        "payload": view["payload"],
                        "errors": errors,
                    })
                    if not errors:
                        captures[step.step_id] = view
                        last_state_version = max(last_state_version, view["state_version"])
                        step_success = True
                        break
                    step_failure = "; ".join(errors)
                except TimeoutError as exc:
                    step_failure = str(exc) or "invocation timed out"
                    trace.append({
                        "step_id": step.step_id,
                        "mode": step.mode,
                        "function_id": step.function_id,
                        "attempt": attempt + 1,
                        "ok": False,
                        "error_code": "TIMEOUT",
                        "errors": [step_failure],
                    })
                except (FunctionRegistryError, TaskLoopError, KeyError, TypeError, ValueError) as exc:
                    step_failure = str(exc)
                    trace.append({
                        "step_id": step.step_id,
                        "mode": step.mode,
                        "function_id": step.function_id,
                        "attempt": attempt + 1,
                        "ok": False,
                        "error_code": "INVALID_ARGS",
                        "errors": [step_failure],
                    })
                if attempt < step.retries:
                    continue
            if not step_success:
                failures.append({"step_id": step.step_id, "reason": step_failure})
                break
        return {
            "task_id": scenario.task_id,
            "status": "PASS" if not failures else "FAIL",
            "evidence_type": "simulator-or-runtime-pending",
            "steps_total": len(scenario.steps),
            "steps_completed": len(captures),
            "trace": trace,
            "captures": captures,
            "failures": failures,
        }


class SimulatorFunctionInvoker:
    """Deterministic function callback backed by SimulatorTransport."""

    def __init__(self, transport: SimulatorTransport, session_id: str, start_sequence: int = 0):
        self.transport = transport
        self.session_id = session_id
        self.sequence = start_sequence

    def invoke(self, function_id: str, args: dict[str, Any], timeout_seconds: float = 5.0) -> protocol.Response:
        del timeout_seconds
        self.sequence += 1
        request_id = f"task-{self.sequence:03d}"
        request = protocol.make_request(
            self.session_id,
            request_id,
            self.sequence,
            "function.invoke",
            {"function_id": function_id, "args": args},
        )
        response = self.transport.send(request)
        if response.request_id != request_id:
            raise TaskLoopError(f"response request_id mismatch: {response.request_id} != {request_id}")
        return response


def run_simulator_task(scenario: TaskScenario, scenario_path: Path) -> dict[str, Any]:
    transport = SimulatorTransport()
    session_id = f"task-loop-{scenario.task_id}"
    transport.open_session(session_id)
    invoker = SimulatorFunctionInvoker(transport, session_id, start_sequence=2)

    def control(sequence: int, request_id: str, operation: str, args: dict[str, Any] | None = None):
        return transport.send(protocol.make_request(session_id, request_id, sequence, operation, args or {}))

    loaded = control(1, "setup-load", "scenario.load", {"scenario_path": str(scenario_path)})
    reset = control(2, "setup-reset", "scenario.reset")
    if loaded.error_code != 0 or reset.error_code != 0:
        return {
            "task_id": scenario.task_id,
            "status": "FAIL",
            "evidence_type": "simulator",
            "setup": {"load": _response_view(loaded), "reset": _response_view(reset)},
            "failures": [{"step_id": "setup", "reason": "scenario setup failed"}],
        }
    result = TaskLoopRunner(invoker.invoke).run(scenario)
    result["evidence_type"] = "simulator"
    result["setup"] = {"load": _response_view(loaded), "reset": _response_view(reset)}
    result["transport"] = "SimulatorTransport"
    return result


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve_existing_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    cwd_path = Path.cwd() / path
    if cwd_path.exists():
        return cwd_path
    return REPO_ROOT / path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a declarative Vibe observe/invoke/assert task")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--backend", choices=("simulator", "host"), default="simulator")
    parser.add_argument("--simulator-setup", default=None)
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--map-path", default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    scenario = TaskScenario.from_dict(_load_json(_resolve_existing_path(args.scenario)))
    if args.backend == "simulator":
        setup_path = _resolve_existing_path(args.simulator_setup) if args.simulator_setup else None
        if setup_path is None:
            raise SystemExit("--simulator-setup is required for simulator backend")
        result = run_simulator_task(scenario, setup_path)
    else:
        if not args.map_path:
            raise SystemExit("--map-path is required for host backend")
        host_root = REPO_ROOT / "tools" / "galaxy-vibe"
        if str(host_root) not in sys.path:
            sys.path.insert(0, str(host_root))
        from host.vibe_host import VibeHost  # type: ignore
        host = VibeHost(
            sc2_port=args.port,
            artifacts_dir=Path(args.out).parent,
            require_initialization=True,
        )
        host.start_session()
        connected = host.connect_sc2(map_path=args.map_path)
        if not connected:
            result = {
                "task_id": scenario.task_id,
                "status": "FAIL",
                "evidence_type": "runtime",
                "initialization_gate": host.initialization_status,
                "failures": [{
                    "step_id": "connect",
                    "reason": host.initialization_error or "SC2 connect failed",
                }],
            }
        else:
            result = TaskLoopRunner(host.invoke_function).run(scenario)
            result["evidence_type"] = "runtime"
            result["transport"] = "VibeHost.function.invoke"
            result["initialization_gate"] = host.initialization_status
        host.close()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": result["status"], "steps": result.get("steps_completed", 0), "out": str(out)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
