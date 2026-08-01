"""Context contracts sent from CMRE to Neuro."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextEnvelope:
    """One auditable context update.

    ``name`` and ``source`` remain local metadata. The Neuro wire payload uses
    only ``message`` and ``silent`` to remain compatible with the reference API.
    """

    name: str
    message: str
    silent: bool = True
    priority: str = "low"
    source: str = "cmre"
    loop: int | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("context name must not be empty")
        if not self.message.strip():
            raise ValueError("context message must not be empty")
        if self.priority not in {"low", "medium", "high", "critical"}:
            raise ValueError(f"invalid context priority: {self.priority}")
        if self.loop is not None and self.loop < 0:
            raise ValueError("context loop must be non-negative or None")
