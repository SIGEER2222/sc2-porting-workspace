"""Offline Neuro runtime state machine and action dispatcher boundary."""

from __future__ import annotations

import inspect
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .action_queue import ActionQueue
from .actions import ActionCommand, ActionDefinition, ExecutionResult
from .action_registry import ActionRegistry, RegistryChange
from .context import ContextEnvelope
from .errors import ContractErrorCode, ContractViolation
from .messages import NeuroMessageBuilder, parse_incoming_message
from .schemas import SchemaValidationError, validate_action_arguments
from .sender import Sender
from .session import NeuroSessionIdentity


Dispatcher = Callable[
    [ActionCommand], ExecutionResult | Awaitable[ExecutionResult]
]


@dataclass(frozen=True)
class RuntimeSnapshot:
    connected: bool
    identified: bool
    in_mission: bool
    paused: bool
    blocking: bool
    update_in_progress: bool
    active_actions: tuple[str, ...]
    queued_action_ids: tuple[str, ...]
    identity: NeuroSessionIdentity | None


class NeuroRuntime:
    """Coordinate connection, action lifecycle, queueing, and safe dispatch."""

    def __init__(
        self,
        sender: Sender,
        *,
        dispatcher: Dispatcher | None = None,
        queue_capacity: int = 3,
        game_title: str = "StarCraft 2",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sender = sender
        self._builder = NeuroMessageBuilder(game_title)
        self._queue = ActionQueue(queue_capacity)
        self._registry = ActionRegistry(
            sender,
            queue=self._queue,
            builder=self._builder,
        )
        self._dispatcher = dispatcher
        self._clock = clock
        self._connected = False
        self._identified = False
        self._in_mission = False
        self._paused = False
        self._blocking = False
        self._update_in_progress = False
        self._identity: NeuroSessionIdentity | None = None
        self._seen_action_ids: set[str] = set()

    @property
    def registry(self) -> ActionRegistry:
        return self._registry

    @property
    def queue(self) -> ActionQueue:
        return self._queue

    @property
    def state(self) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            connected=self._connected,
            identified=self._identified,
            in_mission=self._in_mission,
            paused=self._paused,
            blocking=self._blocking,
            update_in_progress=self._update_in_progress,
            active_actions=self._registry.active_names,
            queued_action_ids=self._queue.queued_action_ids,
            identity=self._identity,
        )

    @property
    def ready(self) -> bool:
        return self._connected and self._identified

    async def connect(self) -> None:
        if self._connected:
            return
        self._connected = True
        self._identified = False
        self._identity = None
        await self._sender.send(self._builder.startup())

    async def disconnect(self) -> None:
        self._connected = False
        self._identified = False
        self._identity = None
        self._in_mission = False
        self._paused = False
        self._blocking = False
        self._update_in_progress = False

    async def identify(self, identity: NeuroSessionIdentity) -> None:
        if not self._connected:
            raise RuntimeError("cannot identify while disconnected")
        self._identity = identity
        self._identified = True
        await self._registry.reregister_all()

    async def handle_message(
        self,
        payload: str | Mapping[str, Any],
        *,
        received_at: float | None = None,
    ) -> NeuroSessionIdentity | ExecutionResult | None:
        """Handle one parsed Neuro message without requiring a live transport."""

        message = parse_incoming_message(payload)
        if message.command == "startup":
            assert message.data is not None
            identity = NeuroSessionIdentity.from_startup_data(message.data)
            await self.identify(identity)
            return identity
        if message.command == "actions/reregister_all":
            await self.reregister_all()
            return None
        assert message.data is not None
        return await self.receive_action(message.data, received_at=received_at)

    async def receive_action(
        self,
        data: Mapping[str, Any],
        *,
        received_at: float | None = None,
    ) -> ExecutionResult:
        """Validate, acknowledge, and queue one Neuro action command."""

        action_id = _required_action_string(data, ("id", "action_id"), "action id")
        name = _required_action_string(
            data,
            ("name", "action", "action_name"),
            "action name",
        )
        arguments = data.get("arguments", data.get("args"))
        if arguments is not None and not isinstance(arguments, Mapping):
            return await self._reject(
                action_id,
                "action arguments must be an object",
            )

        if not self.ready:
            return await self._reject(action_id, "runtime is not identified")
        if action_id in self._seen_action_ids:
            return await self._reject(action_id, "duplicate action_id")

        action = self._registry.get(name)
        if action is None:
            return await self._reject(action_id, f"unknown action: {name}")

        try:
            normalized_arguments = validate_action_arguments(arguments, action.schema)
        except SchemaValidationError as exc:
            return await self._reject(action_id, str(exc))

        command = ActionCommand(
            action_id=action_id,
            name=name,
            args=normalized_arguments,
            received_at=self._clock() if received_at is None else received_at,
        )
        offer = self._queue.enqueue(command)
        if not offer.accepted:
            return await self._reject(action_id, "duplicate action_id")
        self._seen_action_ids.add(action_id)

        if offer.evicted is not None:
            await self.publish_context(
                ContextEnvelope(
                    name="action_queue_eviction",
                    message=(
                        f"Queue capacity evicted action '{offer.evicted.command.action_id}' "
                        f"before accepting '{action_id}'."
                    ),
                    silent=True,
                    priority="medium",
                    source="runtime",
                )
            )

        result = ExecutionResult(
            action_id=action_id,
            success=True,
            message="action accepted and queued",
            operation="queued",
        )
        await self._emit_result(result)
        return result

    async def update_actions(
        self, actions: Iterable[ActionDefinition]
    ) -> RegistryChange:
        """Replace actions locally and emit only when the runtime is ready."""

        return await self._registry.sync(actions, emit=self.ready)

    async def reregister_all(self) -> bool:
        if not self.ready:
            return False
        await self._registry.reregister_all()
        return True

    async def publish_context(self, envelope: ContextEnvelope) -> bool:
        if not self.ready:
            return False
        await self._sender.send(self._builder.context(envelope))
        return True

    async def start_mission(self) -> None:
        if not self.ready:
            raise RuntimeError("cannot start mission before Neuro identity")
        self._in_mission = True

    async def end_mission(self) -> None:
        await self._registry.sync([], emit=self.ready)
        self._queue.clear_all()
        self._in_mission = False
        self._paused = False
        self._blocking = False
        self._update_in_progress = False

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def set_blocking(self, blocking: bool) -> None:
        self._blocking = blocking

    def set_update_in_progress(self, updating: bool) -> None:
        self._update_in_progress = updating

    async def dispatch_next(self) -> ExecutionResult | None:
        """Dispatch one action only during a safe mission execution window."""

        if not self._in_mission or self._paused or self._blocking or self._update_in_progress:
            return None
        command = self._queue.pop()
        if command is None:
            return None

        if self._dispatcher is None:
            result = ExecutionResult(
                action_id=command.action_id,
                success=False,
                message="no action dispatcher configured",
                operation="dispatch",
            )
        else:
            try:
                result = self._dispatcher(command)
                if inspect.isawaitable(result):
                    result = await result
                if not isinstance(result, ExecutionResult):
                    raise TypeError("dispatcher must return ExecutionResult")
                if result.action_id != command.action_id:
                    raise ValueError("dispatcher returned a mismatched action_id")
            except Exception as exc:  # Boundary converts adapter failures to action results.
                result = ExecutionResult(
                    action_id=command.action_id,
                    success=False,
                    message=f"dispatch failed: {exc}",
                    operation="dispatch",
                )

        await self._emit_result(result)
        return result

    async def process_next(self) -> ExecutionResult | None:
        """Readable alias for the queue scheduling operation."""

        return await self.dispatch_next()

    async def _reject(self, action_id: str, message: str) -> ExecutionResult:
        result = ExecutionResult(
            action_id=action_id,
            success=False,
            message=message,
            operation="rejected",
        )
        await self._emit_result(result)
        return result

    async def _emit_result(self, result: ExecutionResult) -> None:
        if self._connected:
            await self._sender.send(self._builder.action_result(result))


Runtime = NeuroRuntime


def _required_action_string(
    data: Mapping[str, Any], keys: tuple[str, ...], label: str
) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ContractViolation(
        ContractErrorCode.INVALID_MESSAGE,
        f"action data requires a non-empty {label}",
    )
