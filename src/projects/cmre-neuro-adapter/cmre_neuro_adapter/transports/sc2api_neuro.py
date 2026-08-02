"""Async SC2 API transport boundary with injected client and no SC2 dependency."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from ..neuro.actions import ActionCommand, ExecutionResult
from ..neuro.mission_projection import MissionContextProjector, PublicMissionContext
from .common import (
    TransportError,
    TransportExecutionResult,
    TransportStatus,
    expected_state_version,
    failed_result,
    result_from_raw,
)


@runtime_checkable
class Sc2ApiClient(Protocol):
    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def observe(self, player_id: int) -> Mapping[str, Any]: ...

    async def dispatch(self, command: ActionCommand) -> Mapping[str, Any] | ExecutionResult: ...


class Sc2ApiTransport:
    """Map an injected SC2 API client to public context and typed results."""

    name = "sc2api"

    def __init__(
        self,
        client: Sc2ApiClient,
        *,
        player_id: int = 1,
        map_name: str = "dead-of-night",
        timeout: float = 10.0,
    ) -> None:
        if not isinstance(player_id, int) or isinstance(player_id, bool) or player_id < 0:
            raise ValueError("player_id must be a non-negative integer")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("timeout must be positive")
        if not isinstance(client, Sc2ApiClient):
            raise TypeError("client does not implement Sc2ApiClient")
        self.client = client
        self.player_id = player_id
        self.timeout = float(timeout)
        self._projector = MissionContextProjector(map_name=map_name)
        self._connected = False
        self._generation = 0
        self._reconnects = 0
        self._last_error: str | None = None
        self._last_context: PublicMissionContext | None = None
        self._state_version: int | None = None
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

    @property
    def last_context(self) -> PublicMissionContext | None:
        return self._last_context

    async def connect(self) -> TransportStatus:
        try:
            await self._call(self.client.connect)
        except Exception as exc:
            self._last_error = str(exc)
            raise self._as_error("connect_failed", exc) from exc
        self._connected = True
        self._generation += 1
        self._last_error = None
        return self.status

    async def disconnect(self) -> TransportStatus:
        try:
            await self._call(self.client.close)
        except Exception as exc:
            self._last_error = str(exc)
            self._connected = False
            raise self._as_error("disconnect_failed", exc) from exc
        self._connected = False
        return self.status

    async def reconnect(self) -> TransportStatus:
        self._reconnects += 1
        if self._connected:
            await self.disconnect()
        return await self.connect()

    async def observe(self) -> PublicMissionContext:
        self._require_connected()
        try:
            raw = await self._call(self.client.observe, self.player_id)
            if isinstance(raw, PublicMissionContext):
                context = raw
            else:
                if not isinstance(raw, Mapping):
                    raise TransportError("invalid_observation", "SC2 API observation must be an object")
                state_version = raw.get("state_version", raw.get("loop"))
                context = self._projector.project(raw, state_version=state_version)
        except Exception as exc:
            self._last_error = str(exc)
            if isinstance(exc, TransportError):
                raise
            raise self._as_error("observation_failed", exc) from exc
        self._last_context = context
        self._state_version = context.state_version
        self._last_error = None
        return context

    async def dispatch(self, command: ActionCommand) -> TransportExecutionResult:
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
                    message="SC2 API transport is not connected",
                )
            )
        try:
            expected = expected_state_version(command)
            current = self._state_version
            if expected is not None and current is not None and expected != current:
                return self._remember(
                    failed_result(
                        command,
                        transport=self.name,
                        code="stale_state",
                        message=f"stale state: expected {expected}, current {current}",
                        state_version=current,
                    )
                )
            raw = await self._call(self.client.dispatch, command)
            result = result_from_raw(
                command,
                raw,
                transport=self.name,
                default_operation="sc2api.dispatch",
                state_version=current,
            )
        except asyncio.TimeoutError as exc:
            result = failed_result(
                command,
                transport=self.name,
                code="timeout",
                message="SC2 API request timed out",
            )
            self._last_error = result.message
        except Exception as exc:
            result = failed_result(
                command,
                transport=self.name,
                code=exc.code if isinstance(exc, TransportError) else "dispatch_failed",
                message=str(exc),
                state_version=self._last_context.state_version if self._last_context else None,
            )
            self._last_error = result.message
        else:
            self._last_error = None
            if result.state_version is not None:
                self._state_version = result.state_version
        return self._remember(result)

    async def execute(self, command: ActionCommand) -> TransportExecutionResult:
        return await self.dispatch(command)

    async def _call(self, function: Any, *args: Any) -> Any:
        value = function(*args)
        if inspect.isawaitable(value):
            return await asyncio.wait_for(value, timeout=self.timeout)
        return value

    def _require_connected(self) -> None:
        if not self._connected:
            raise TransportError("not_connected", "SC2 API transport is not connected")

    def _remember(self, result: TransportExecutionResult) -> TransportExecutionResult:
        self._results[result.action_id] = result
        return result

    @staticmethod
    def _as_error(code: str, exc: Exception) -> TransportError:
        if isinstance(exc, asyncio.TimeoutError):
            return TransportError("timeout", "SC2 API request timed out")
        return TransportError(code, str(exc))


SC2APITransport = Sc2ApiTransport


__all__ = ["SC2APITransport", "Sc2ApiClient", "Sc2ApiTransport"]
