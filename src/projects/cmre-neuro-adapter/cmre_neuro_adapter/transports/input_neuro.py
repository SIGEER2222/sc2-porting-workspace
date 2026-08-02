"""Input fallback transport for explicitly bound actions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..neuro.actions import ActionCommand, ExecutionResult
from .common import (
    TransportError,
    TransportExecutionResult,
    TransportStatus,
    failed_result,
    result_from_raw,
)


@dataclass(frozen=True)
class InputBinding:
    kind: str
    value: str

    def __post_init__(self) -> None:
        if self.kind not in {"key", "mouse", "text", "custom"}:
            raise ValueError("input binding kind is unsupported")
        if not self.value.strip():
            raise ValueError("input binding value must not be empty")


@runtime_checkable
class InputSink(Protocol):
    def send(
        self, binding: InputBinding, command: ActionCommand
    ) -> Mapping[str, Any] | ExecutionResult | None: ...


class InputTransport:
    """Dispatch only actions with explicit bindings; it cannot observe or publish context."""

    name = "input"

    def __init__(
        self,
        sink: InputSink,
        bindings: Mapping[str, InputBinding | str],
    ) -> None:
        if not isinstance(sink, InputSink):
            raise TypeError("sink does not implement InputSink")
        if not isinstance(bindings, Mapping):
            raise TypeError("bindings must be an object")
        normalized: dict[str, InputBinding] = {}
        for name, binding in bindings.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("input action names must be non-empty strings")
            if isinstance(binding, str):
                binding = InputBinding("key", binding)
            if not isinstance(binding, InputBinding):
                raise TypeError("input bindings must be InputBinding values or strings")
            normalized[name.strip()] = binding
        self.sink = sink
        self.bindings = normalized
        self._connected = False
        self._generation = 0
        self._reconnects = 0
        self._last_error: str | None = None
        self._results: dict[str, TransportExecutionResult] = {}

    @property
    def status(self) -> TransportStatus:
        return TransportStatus(
            name=self.name,
            connected=self._connected,
            generation=self._generation,
            reconnects=self._reconnects,
            last_error=self._last_error,
        )

    def connect(self) -> TransportStatus:
        self._connected = True
        self._generation += 1
        self._last_error = None
        return self.status

    def disconnect(self) -> TransportStatus:
        self._connected = False
        return self.status

    def reconnect(self) -> TransportStatus:
        self._reconnects += 1
        self._connected = False
        return self.connect()

    def dispatch(self, command: ActionCommand) -> TransportExecutionResult:
        if not isinstance(command, ActionCommand):
            raise TypeError("command must be an ActionCommand")
        duplicate = self._results.get(command.action_id)
        if duplicate is not None:
            return TransportExecutionResult(
                action_id=duplicate.action_id,
                success=duplicate.success,
                message=duplicate.message,
                operation=duplicate.operation,
                loop=duplicate.loop,
                transport=duplicate.transport,
                state_version=duplicate.state_version,
                duplicate=True,
            )
        if not self._connected:
            return self._remember(
                failed_result(
                    command,
                    transport=self.name,
                    code="not_connected",
                    message="input transport is not connected",
                )
            )
        binding = self.bindings.get(command.name)
        if binding is None:
            return self._remember(
                failed_result(
                    command,
                    transport=self.name,
                    code="unsupported_action",
                    message=f"no input binding for action '{command.name}'",
                )
            )
        try:
            result = result_from_raw(
                command,
                self.sink.send(binding, command),
                transport=self.name,
                default_operation="input.dispatch",
            )
        except Exception as exc:
            result = failed_result(
                command,
                transport=self.name,
                code=exc.code if isinstance(exc, TransportError) else "input_failed",
                message=str(exc),
            )
            self._last_error = result.message
        else:
            self._last_error = None
        return self._remember(result)

    def execute(self, command: ActionCommand) -> TransportExecutionResult:
        return self.dispatch(command)

    def observe(self) -> None:
        raise TransportError("observation_unsupported", "input transport cannot observe SC2 state")

    def publish_context(self, _: Any) -> None:
        raise TransportError("context_unsupported", "input transport cannot publish Neuro context")

    def _remember(self, result: TransportExecutionResult) -> TransportExecutionResult:
        self._results[result.action_id] = result
        return result


InputNeuroTransport = InputTransport


__all__ = ["InputBinding", "InputNeuroTransport", "InputSink", "InputTransport"]
