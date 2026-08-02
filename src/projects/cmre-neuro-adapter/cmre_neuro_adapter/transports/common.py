"""Shared, dependency-free transport result and lifecycle contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from ..neuro.actions import ActionCommand, ExecutionResult


class TransportError(RuntimeError):
    """A transport boundary failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("transport error code must be a non-empty string")
        super().__init__(message)
        self.code = code.strip()
        self.message = message


@dataclass(frozen=True)
class TransportStatus:
    name: str
    connected: bool
    generation: int
    reconnects: int = 0
    last_error: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("transport name must not be empty")
        for value, label in (
            (self.generation, "generation"),
            (self.reconnects, "reconnects"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"transport {label} must be a non-negative integer")


@dataclass(frozen=True)
class TransportExecutionResult(ExecutionResult):
    """Execution result carrying transport, version, and duplicate metadata."""

    transport: str = "transport"
    state_version: int | None = None
    duplicate: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.transport.strip():
            raise ValueError("transport must not be empty")
        if (
            self.state_version is not None
            and (
                not isinstance(self.state_version, int)
                or isinstance(self.state_version, bool)
                or self.state_version < 0
            )
        ):
            raise ValueError("state_version must be a non-negative integer or None")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def expected_state_version(command: ActionCommand) -> int | None:
    args = command.args
    if args is None:
        return None
    if not isinstance(args, Mapping):
        raise ValueError("action args must be an object")
    value = args.get("expected_state_version")
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("expected_state_version must be a non-negative integer")
    return value


def failed_result(
    command: ActionCommand,
    *,
    transport: str,
    code: str,
    message: str,
    state_version: int | None = None,
    duplicate: bool = False,
) -> TransportExecutionResult:
    return TransportExecutionResult(
        action_id=command.action_id,
        success=False,
        message=message,
        operation=code,
        loop=state_version,
        transport=transport,
        state_version=state_version,
        duplicate=duplicate,
    )


def result_from_raw(
    command: ActionCommand,
    raw: Mapping[str, Any] | ExecutionResult | None,
    *,
    transport: str,
    default_operation: str,
    state_version: int | None = None,
) -> TransportExecutionResult:
    if isinstance(raw, ExecutionResult):
        if raw.action_id != command.action_id:
            raise TransportError(
                "correlation_mismatch",
                f"result action_id {raw.action_id!r} does not match {command.action_id!r}",
            )
        return TransportExecutionResult(
            action_id=raw.action_id,
            success=raw.success,
            message=raw.message,
            operation=raw.operation,
            loop=raw.loop,
            transport=transport,
            state_version=state_version,
        )
    if raw is None:
        return TransportExecutionResult(
            action_id=command.action_id,
            success=True,
            message="transport accepted action",
            operation=default_operation,
            loop=state_version,
            transport=transport,
            state_version=state_version,
        )
    if not isinstance(raw, Mapping):
        raise TransportError("invalid_result", "transport result must be an object")
    success = raw.get("success", True)
    message = raw.get("message", "transport accepted action" if success else "transport rejected action")
    operation = raw.get("operation", default_operation)
    version = raw.get("state_version", state_version)
    loop = raw.get("loop", version)
    if not isinstance(success, bool):
        raise TransportError("invalid_result", "transport result success must be boolean")
    if not isinstance(message, str) or not message.strip():
        raise TransportError("invalid_result", "transport result message must be non-empty")
    if not isinstance(operation, str) or not operation.strip():
        raise TransportError("invalid_result", "transport result operation must be non-empty")
    if version is not None and (not isinstance(version, int) or isinstance(version, bool) or version < 0):
        raise TransportError("invalid_result", "transport result state_version must be non-negative")
    if loop is not None and (not isinstance(loop, int) or isinstance(loop, bool) or loop < 0):
        raise TransportError("invalid_result", "transport result loop must be non-negative")
    return TransportExecutionResult(
        action_id=command.action_id,
        success=success,
        message=message,
        operation=operation,
        loop=loop,
        transport=transport,
        state_version=version,
    )


__all__ = [
    "TransportError",
    "TransportExecutionResult",
    "TransportStatus",
    "canonical_json",
    "expected_state_version",
    "failed_result",
    "result_from_raw",
]
