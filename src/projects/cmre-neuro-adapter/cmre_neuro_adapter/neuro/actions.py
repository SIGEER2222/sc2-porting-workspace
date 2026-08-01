"""Action contracts shared by Neuro sessions and CMRE transports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ActionDefinition:
    """An action currently available to Neuro.

    ``uses`` is local lifecycle state and is intentionally omitted from the
    Neuro registration payload. The description may expose remaining uses to
    the model, while the runtime remains authoritative for consumption.
    """

    name: str
    description: str
    schema: Mapping[str, Any] = field(default_factory=dict)
    uses: int | None = None
    priority: str = "low"
    source: str = "cmre"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("action name must not be empty")
        if not self.description.strip():
            raise ValueError("action description must not be empty")
        if self.uses is not None and self.uses < 0:
            raise ValueError("action uses must be non-negative or None")
        if self.priority not in {"low", "medium", "high", "critical"}:
            raise ValueError(f"invalid action priority: {self.priority}")

    def to_registration_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
        }
        if self.schema:
            payload["schema"] = dict(self.schema)
        return payload


@dataclass(frozen=True)
class ActionCommand:
    """A validated command received from Neuro."""

    action_id: str
    name: str
    args: Mapping[str, Any] | None
    received_at: float

    def __post_init__(self) -> None:
        if not self.action_id.strip():
            raise ValueError("action_id must not be empty")
        if not self.name.strip():
            raise ValueError("action name must not be empty")


@dataclass(frozen=True)
class ExecutionResult:
    """Result of dispatching one Neuro action into a CMRE transport."""

    action_id: str
    success: bool
    message: str
    operation: str
    loop: int | None = None

    def __post_init__(self) -> None:
        if not self.action_id.strip():
            raise ValueError("action_id must not be empty")
        if not self.operation.strip():
            raise ValueError("operation must not be empty")
