"""Bounded FIFO queue for validated Neuro actions."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass

from .actions import ActionCommand


@dataclass(frozen=True)
class QueueEviction:
    """Record describing the command removed to make room for a new one."""

    command: ActionCommand
    reason: str = "capacity"


@dataclass(frozen=True)
class QueueOffer:
    """Outcome of offering one command to the queue."""

    accepted: bool
    duplicate: bool = False
    evicted: QueueEviction | None = None


class ActionQueue:
    """A capacity-bounded FIFO queue keyed by Neuro ``action_id``."""

    def __init__(self, capacity: int = 3) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
            raise ValueError("queue capacity must be a positive integer")
        self.capacity = capacity
        self._items: deque[ActionCommand] = deque()
        self._queued_ids: set[str] = set()

    def enqueue(self, command: ActionCommand) -> QueueOffer:
        """Append a command, evicting the oldest command when full."""

        if command.action_id in self._queued_ids:
            return QueueOffer(accepted=False, duplicate=True)

        eviction: QueueEviction | None = None
        if len(self._items) >= self.capacity:
            evicted = self._items.popleft()
            self._queued_ids.remove(evicted.action_id)
            eviction = QueueEviction(evicted)

        self._items.append(command)
        self._queued_ids.add(command.action_id)
        return QueueOffer(accepted=True, evicted=eviction)

    def pop(self) -> ActionCommand | None:
        if not self._items:
            return None
        command = self._items.popleft()
        self._queued_ids.remove(command.action_id)
        return command

    def peek(self) -> ActionCommand | None:
        return self._items[0] if self._items else None

    def clear_action(self, action_name: str) -> tuple[ActionCommand, ...]:
        """Remove queued commands belonging to one action definition."""

        removed: list[ActionCommand] = []
        kept: deque[ActionCommand] = deque()
        for command in self._items:
            if command.name == action_name:
                removed.append(command)
                self._queued_ids.remove(command.action_id)
            else:
                kept.append(command)
        self._items = kept
        return tuple(removed)

    def clear_all(self) -> tuple[ActionCommand, ...]:
        removed = tuple(self._items)
        self._items.clear()
        self._queued_ids.clear()
        return removed

    @property
    def queued_action_ids(self) -> tuple[str, ...]:
        return tuple(command.action_id for command in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[ActionCommand]:
        return iter(tuple(self._items))
