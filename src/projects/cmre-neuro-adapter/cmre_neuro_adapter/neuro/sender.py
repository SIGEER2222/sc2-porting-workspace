"""Minimal asynchronous sender boundary used by the offline runtime core."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Sender(Protocol):
    """Transport boundary for already-built Neuro payloads."""

    async def send(self, payload: Mapping[str, Any]) -> None:
        """Send one payload without knowing how the transport is implemented."""


class MemorySender:
    """In-memory sender for deterministic unit tests and local replay."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send(self, payload: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping):
            raise TypeError("sender payload must be a mapping")
        self.messages.append(deepcopy(dict(payload)))

    def clear(self) -> None:
        self.messages.clear()
