"""Runtime state serialization for the independent transport domain."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..mission.mission_state import RuntimeState
from .migrations import StateValidationError


_FIELDS = frozenset(
    {"version", "context_version", "active_action_names", "queued_action_ids", "ready"}
)


def encode_runtime_state(state: RuntimeState) -> dict[str, Any]:
    if not isinstance(state, RuntimeState):
        raise StateValidationError("runtime state has the wrong type")
    _validate(state.version, state.context_version, state.active_action_names,
              state.queued_action_ids, state.ready)
    return {
        "active_action_names": list(state.active_action_names),
        "context_version": state.context_version,
        "queued_action_ids": list(state.queued_action_ids),
        "ready": state.ready,
        "version": state.version,
    }


def decode_runtime_state(payload: Mapping[str, Any]) -> RuntimeState:
    _check_fields(payload)
    version = payload["version"]
    context_version = payload["context_version"]
    active = _names(payload["active_action_names"], "active_action_names")
    queued = _names(payload["queued_action_ids"], "queued_action_ids")
    ready = payload["ready"]
    _validate(version, context_version, active, queued, ready)
    return RuntimeState(version, context_version, active, queued, ready)


def _check_fields(payload: Any) -> None:
    if not isinstance(payload, Mapping):
        raise StateValidationError("runtime payload must be an object")
    keys = set(payload)
    missing = _FIELDS - keys
    if missing:
        raise StateValidationError(
            f"runtime payload is missing fields: {', '.join(sorted(missing))}"
        )
    unknown = keys - _FIELDS
    if unknown:
        raise StateValidationError(
            f"runtime payload has unsupported fields: {', '.join(sorted(unknown))}"
        )


def _validate(
    version: Any,
    context_version: Any,
    active: Any,
    queued: Any,
    ready: Any,
) -> None:
    for value, label in (
        (version, "runtime version"),
        (context_version, "context version"),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise StateValidationError(f"{label} must be a non-negative integer")
    if not isinstance(ready, bool):
        raise StateValidationError("runtime ready must be boolean")


def _names(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise StateValidationError(f"runtime {label} must be a list")
    names = tuple(value)
    if not all(isinstance(name, str) and name.strip() for name in names):
        raise StateValidationError(f"runtime {label} must contain non-empty strings")
    return names


__all__ = ["decode_runtime_state", "encode_runtime_state"]
