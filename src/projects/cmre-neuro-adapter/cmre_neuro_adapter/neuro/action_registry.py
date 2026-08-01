"""Lifecycle management for actions exposed to Neuro."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .actions import ActionDefinition
from .action_queue import ActionQueue
from .messages import NeuroMessageBuilder
from .sender import Sender


@dataclass(frozen=True)
class RegistryChange:
    """Names changed by one registry synchronization."""

    registered: tuple[str, ...] = ()
    unregistered: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()

    @property
    def changed(self) -> tuple[str, ...]:
        return tuple(
            name for name in self.registered if name in self.unregistered
        )


class ActionRegistry:
    """Keep the local action set authoritative and synchronize it with Neuro."""

    def __init__(
        self,
        sender: Sender,
        *,
        queue: ActionQueue | None = None,
        builder: NeuroMessageBuilder | None = None,
    ) -> None:
        self._sender = sender
        self._queue = queue
        self._builder = builder or NeuroMessageBuilder()
        self._active: dict[str, ActionDefinition] = {}

    @property
    def active_actions(self) -> tuple[ActionDefinition, ...]:
        return tuple(self._active[name] for name in sorted(self._active))

    @property
    def active_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._active))

    def get(self, name: str) -> ActionDefinition | None:
        return self._active.get(name)

    async def sync(
        self,
        actions: Iterable[ActionDefinition],
        *,
        emit: bool = True,
    ) -> RegistryChange:
        """Replace the active set and emit unregister/register in that order."""

        incoming = self._normalize(actions)
        current_names = set(self._active)
        incoming_names = set(incoming)

        removed = sorted(current_names - incoming_names)
        changed = sorted(
            name
            for name in current_names & incoming_names
            if _fingerprint(self._active[name]) != _fingerprint(incoming[name])
        )
        new = sorted(incoming_names - current_names)
        unchanged = sorted(incoming_names - set(changed) - set(new))
        unregister_names = sorted(set(removed) | set(changed))
        register_names = sorted(set(new) | set(changed))

        for name in removed + changed:
            if self._queue is not None:
                self._queue.clear_action(name)

        self._active = incoming

        if emit and unregister_names:
            await self._sender.send(self._builder.actions_unregister(unregister_names))
        if emit and register_names:
            await self._sender.send(
                self._builder.actions_register(
                    [incoming[name] for name in register_names]
                )
            )

        return RegistryChange(
            registered=tuple(register_names),
            unregistered=tuple(unregister_names),
            unchanged=tuple(unchanged),
        )

    async def register_many(
        self,
        actions: Iterable[ActionDefinition],
        *,
        emit: bool = True,
    ) -> RegistryChange:
        """Alias expressing the batch registration operation."""

        return await self.sync(actions, emit=emit)

    async def unregister(self, name: str, *, emit: bool = True) -> RegistryChange:
        """Remove one action and any queued commands that target it."""

        if name not in self._active:
            return RegistryChange()
        return await self.sync(
            (action for action_name, action in self._active.items() if action_name != name),
            emit=emit,
        )

    async def reregister_all(self) -> None:
        """Send the complete active set after reconnect or a Neuro request."""

        await self._sender.send(
            self._builder.actions_register(list(self.active_actions))
        )

    @staticmethod
    def _normalize(actions: Iterable[ActionDefinition]) -> dict[str, ActionDefinition]:
        normalized: dict[str, ActionDefinition] = {}
        for action in actions:
            if not isinstance(action, ActionDefinition):
                raise TypeError("registry entries must be ActionDefinition values")
            if action.name in normalized:
                raise ValueError(f"duplicate action name: {action.name}")
            normalized[action.name] = action
        return normalized


def _fingerprint(action: ActionDefinition) -> str:
    return json.dumps(
        action.to_registration_dict(),
        sort_keys=True,
        separators=(",", ":"),
        default=repr,
    )
