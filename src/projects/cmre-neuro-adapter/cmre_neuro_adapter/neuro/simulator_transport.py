"""Simulator-backed dispatch and context transport for the Neuro runtime."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .actions import ActionCommand, ExecutionResult
from .mission_projection import MissionContextProjector, PublicMissionContext


@runtime_checkable
class SimulatorBackend(Protocol):
    """Minimal backend surface required by the adapter.

    Backends return the already public Observation shape.  They do not expose
    their world object to this adapter.
    """

    @property
    def state_version(self) -> int:
        ...

    @property
    def supported_actions(self) -> Collection[str]:
        ...

    def observe(self, player_id: int) -> Mapping[str, Any]:
        ...

    def execute(
        self, operation: str, args: Mapping[str, Any]
    ) -> Mapping[str, Any] | ExecutionResult:
        ...


@dataclass(frozen=True)
class SimulatorExecutionResult(ExecutionResult):
    """Execution result carrying simulator version and duplicate metadata."""

    state_version: int = 0
    duplicate: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if (
            not isinstance(self.state_version, int)
            or isinstance(self.state_version, bool)
            or self.state_version < 0
        ):
            raise ValueError("state_version must be a non-negative integer")


class SimulatorTransport:
    """Translate Neuro commands into an explicit simulator operation map."""

    name = "simulator"

    def __init__(
        self,
        backend: SimulatorBackend,
        *,
        action_operations: Mapping[str, str] | None = None,
        player_id: int = 1,
        map_name: str = "dead-of-night",
    ) -> None:
        if not isinstance(player_id, int) or isinstance(player_id, bool) or player_id < 0:
            raise ValueError("player_id must be a non-negative integer")
        if not isinstance(backend, SimulatorBackend):
            raise TypeError("backend does not implement SimulatorBackend")
        self.backend = backend
        self.player_id = player_id
        self._projector = MissionContextProjector(map_name=map_name)
        self._action_operations = self._normalize_operations(
            action_operations, backend.supported_actions
        )
        self._results: dict[str, SimulatorExecutionResult] = {}
        self._last_context: PublicMissionContext | None = None

    @property
    def supported_actions(self) -> tuple[str, ...]:
        return tuple(sorted(self._action_operations))

    @property
    def last_context(self) -> PublicMissionContext | None:
        return self._last_context

    @property
    def state_version(self) -> int:
        return _state_version(self.backend)

    def observe(self) -> PublicMissionContext:
        """Read one public Observation and assign its next context version."""

        observation = self.backend.observe(self.player_id)
        context = self._projector.project(
            observation,
            state_version=_state_version(self.backend),
        )
        self._last_context = context
        return context

    def dispatch(
        self,
        command: ActionCommand,
        *,
        expected_state_version: int | None = None,
    ) -> SimulatorExecutionResult:
        """Dispatch one command with correlation, stale-state, and idempotency."""

        if not isinstance(command, ActionCommand):
            raise TypeError("command must be an ActionCommand")
        duplicate = self._results.get(command.action_id)
        if duplicate is not None:
            return SimulatorExecutionResult(
                action_id=duplicate.action_id,
                success=duplicate.success,
                message=duplicate.message,
                operation=duplicate.operation,
                loop=duplicate.loop,
                state_version=duplicate.state_version,
                duplicate=True,
            )

        args = _args(command)
        embedded_version = args.get("expected_state_version")
        if embedded_version is not None:
            if expected_state_version is not None and embedded_version != expected_state_version:
                return self._remember(
                    _failed(
                        command,
                        operation="invalid_state_version",
                        message="conflicting expected_state_version values",
                        state_version=_state_version(self.backend),
                    )
                )
            expected_state_version = embedded_version
            args = {key: value for key, value in args.items() if key != "expected_state_version"}

        if expected_state_version is not None:
            try:
                _validate_version(expected_state_version, "expected_state_version")
            except ValueError as exc:
                return self._remember(
                    _failed(
                        command,
                        operation="invalid_state_version",
                        message=str(exc),
                        state_version=_state_version(self.backend),
                    )
                )
            current_version = _state_version(self.backend)
            if current_version != expected_state_version:
                return self._remember(
                    _failed(
                        command,
                        operation="stale_state",
                        message=(
                            f"stale state: expected {expected_state_version}, "
                            f"current {current_version}"
                        ),
                        state_version=current_version,
                    )
                )

        operation = self._action_operations.get(command.name)
        if operation is None:
            return self._remember(
                _failed(
                    command,
                    operation="unsupported_action",
                    message=f"unsupported action: {command.name}",
                    state_version=_state_version(self.backend),
                )
            )

        try:
            raw = self.backend.execute(operation, args)
            result = self._result_from_backend(command, operation, raw)
        except Exception as exc:  # Boundary turns backend failures into typed results.
            result = _failed(
                command,
                operation="dispatch",
                message=f"dispatch failed: {exc}",
                state_version=_state_version(self.backend),
            )
        return self._remember(result)

    def execute(
        self,
        command: ActionCommand,
        *,
        expected_state_version: int | None = None,
    ) -> SimulatorExecutionResult:
        """Alias used by dispatchers injected into ``NeuroRuntime``."""

        return self.dispatch(
            command,
            expected_state_version=expected_state_version,
        )

    def _result_from_backend(
        self,
        command: ActionCommand,
        operation: str,
        raw: Mapping[str, Any] | ExecutionResult,
    ) -> SimulatorExecutionResult:
        current_version = _state_version(self.backend)
        if isinstance(raw, ExecutionResult):
            if raw.action_id != command.action_id:
                raise ValueError(
                    f"backend returned action_id {raw.action_id!r}, "
                    f"expected {command.action_id!r}"
                )
            return SimulatorExecutionResult(
                action_id=command.action_id,
                success=raw.success,
                message=raw.message,
                operation=raw.operation,
                loop=raw.loop if raw.loop is not None else current_version,
                state_version=current_version,
            )
        if not isinstance(raw, Mapping):
            raise TypeError("backend result must be an object")
        success = raw.get("success", True)
        if not isinstance(success, bool):
            raise TypeError("backend result success must be boolean")
        message = raw.get("message", "applied" if success else "rejected")
        if not isinstance(message, str):
            raise TypeError("backend result message must be a string")
        loop = raw.get("loop", current_version)
        if not isinstance(loop, int) or isinstance(loop, bool) or loop < 0:
            raise TypeError("backend result loop must be a non-negative integer")
        return SimulatorExecutionResult(
            action_id=command.action_id,
            success=success,
            message=message,
            operation=str(raw.get("operation", operation)),
            loop=loop,
            state_version=current_version,
        )

    def _remember(self, result: SimulatorExecutionResult) -> SimulatorExecutionResult:
        self._results[result.action_id] = result
        return result

    @staticmethod
    def _normalize_operations(
        action_operations: Mapping[str, str] | None,
        backend_actions: Collection[str],
    ) -> dict[str, str]:
        raw = action_operations
        if raw is None:
            raw = {name: name for name in backend_actions}
        if not isinstance(raw, Mapping):
            raise TypeError("action_operations must be an object")
        normalized: dict[str, str] = {}
        for action_name, operation in raw.items():
            if (
                not isinstance(action_name, str)
                or not action_name.strip()
                or not isinstance(operation, str)
                or not operation.strip()
            ):
                raise ValueError("action operation names must be non-empty strings")
            normalized[action_name.strip()] = operation.strip()
        return normalized


class SimulatorSessionBackend:
    """Public-contract wrapper for the existing CMRE ``SimulatorSession``.

    The wrapper imports the source simulator lazily and only forwards
    ``Observation.from_world`` plus explicit session operations.  It never
    hands the simulator world object to the Neuro adapter.
    """

    def __init__(
        self,
        session: Any,
        *,
        action_operations: Mapping[str, str],
    ) -> None:
        if not isinstance(action_operations, Mapping):
            raise TypeError("action_operations must be an object")
        self.session = session
        self._action_operations = dict(action_operations)

    @property
    def supported_actions(self) -> tuple[str, ...]:
        return tuple(sorted(self._action_operations))

    @property
    def state_version(self) -> int:
        world = getattr(self.session, "world", None)
        clock = getattr(world, "clock", None)
        now = getattr(clock, "now", None)
        return int(getattr(now, "loop", 0))

    def observe(self, player_id: int) -> Mapping[str, Any]:
        world = getattr(self.session, "world", None)
        if world is None:
            raise RuntimeError("simulator world is not loaded")
        from vibe.contracts import Observation

        observation = Observation.from_world(world, player_id)
        mission = dict(observation.mission)
        mission.update(self.session.query_mission())
        return {
            "loop": observation.loop,
            "player_id": observation.player_id,
            "own_units": list(observation.own_units),
            "visible_enemies": list(observation.visible_enemies),
            "resources": dict(observation.resources),
            "mission": mission,
        }

    def execute(self, operation: str, args: Mapping[str, Any]) -> Mapping[str, Any]:
        if operation == "unit.order":
            return self.session.unit_order(
                list(args["entity_ids"]),
                str(args["kind"]),
                int(args["issuer_player_id"]),
                int(args.get("target_entity_id", 0)),
                float(args.get("target_x", 0.0)),
                float(args.get("target_y", 0.0)),
                str(args.get("unit_type_id", "")),
                str(args.get("ability_id", "")),
            )
        if operation == "unit.spawn":
            return self.session.unit_spawn(
                str(args["unit_type_id"]),
                int(args["owner_player_id"]),
                float(args["x"]),
                float(args["y"]),
            )
        if operation == "unit.kill":
            return self.session.unit_kill(int(args["entity_id"]))
        if operation == "player.set_resource":
            return self.session.player_set_resource(
                int(args["player_id"]),
                args.get("minerals"),
                args.get("vespene"),
            )
        if operation == "scenario.step":
            result = self.session.scenario_step(int(args.get("loops", 1)))
            return {
                "loop": result.loop,
                "terminated": self.session.terminated,
                "end_reason": getattr(self.session, "end_reason", ""),
            }
        raise ValueError(f"unsupported simulator operation: {operation}")


def _args(command: ActionCommand) -> Mapping[str, Any]:
    if command.args is None:
        return {}
    if not isinstance(command.args, Mapping):
        raise TypeError("action args must be an object")
    return command.args


def _state_version(backend: SimulatorBackend) -> int:
    value = backend.state_version
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("backend state_version must be a non-negative integer")
    return value


def _validate_version(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _failed(
    command: ActionCommand,
    *,
    operation: str,
    message: str,
    state_version: int,
) -> SimulatorExecutionResult:
    return SimulatorExecutionResult(
        action_id=command.action_id,
        success=False,
        message=message,
        operation=operation,
        loop=state_version,
        state_version=state_version,
    )


__all__ = [
    "SimulatorBackend",
    "SimulatorExecutionResult",
    "SimulatorSessionBackend",
    "SimulatorTransport",
]
