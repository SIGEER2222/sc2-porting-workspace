"""Validated registry for high-level AI ally intents."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from .decision_contracts import (
    ActionDecision,
    ActionResult,
    ActionSpec,
    ActionStatus,
    AllyObservation,
    DecisionRequest,
)


Precondition = Callable[[AllyObservation, DecisionRequest], bool | str]


@dataclass
class _ActiveAction:
    request: DecisionRequest
    accepted_loop: int
    status: ActionStatus = ActionStatus.ACCEPTED


class ActionRegistry:
    """Register, validate, and track intent actions.

    The registry never calls Ares or SC2. Its executor field is an adapter name consumed by the
    runtime boundary, which keeps validation and replay independent from the game process.
    """

    def __init__(self) -> None:
        self._specs: dict[str, ActionSpec] = {}
        self._preconditions: dict[str, list[Precondition]] = {}
        self._active: dict[str, _ActiveAction] = {}
        self._last_applied_loop: dict[str, int] = {}

    @property
    def specs(self) -> tuple[ActionSpec, ...]:
        return tuple(
            sorted(self._specs.values(), key=lambda spec: (spec.priority, spec.name))
        )

    def register(self, spec: ActionSpec, *preconditions: Precondition) -> None:
        if not spec.name or not spec.name.isidentifier():
            raise ValueError(f"invalid action name: {spec.name!r}")
        if spec.priority < 0:
            raise ValueError("action priority must be non-negative")
        if spec.cooldown_loops < 0 or spec.timeout_loops < 0:
            raise ValueError("action cooldown and timeout must be non-negative")
        if not spec.allowed_phases:
            raise ValueError("action must allow at least one phase")
        if not spec.required_arguments.issubset(spec.argument_types):
            raise ValueError("required arguments must have declared types")
        if spec.name in self._specs:
            raise ValueError(f"action already registered: {spec.name}")
        self._specs[spec.name] = spec
        self._preconditions[spec.name] = list(preconditions)

    def get(self, action_name: str) -> ActionSpec:
        try:
            return self._specs[action_name]
        except KeyError as exc:
            raise KeyError(f"unknown action: {action_name}") from exc

    def evaluate(
        self, observation: AllyObservation, request: DecisionRequest
    ) -> ActionDecision:
        spec = self._specs.get(request.action_name)
        if spec is None:
            return ActionDecision(request, False, "unknown_action", 10_000)

        priority = request.priority_override
        if priority is None:
            priority = spec.priority
        if request.phase not in spec.allowed_phases:
            return ActionDecision(request, False, "phase_not_allowed", priority)

        missing = spec.required_arguments - request.arguments.keys()
        if missing:
            return ActionDecision(
                request, False, f"missing_arguments:{sorted(missing)}", priority
            )
        for name, expected_type in spec.argument_types.items():
            if name in request.arguments and not isinstance(
                request.arguments[name], expected_type
            ):
                return ActionDecision(
                    request, False, f"invalid_argument_type:{name}", priority
                )
        unexpected = request.arguments.keys() - spec.argument_types.keys()
        if unexpected:
            return ActionDecision(
                request, False, f"unexpected_arguments:{sorted(unexpected)}", priority
            )

        last_loop = self._last_applied_loop.get(request.action_name)
        if last_loop is not None and request.loop - last_loop < spec.cooldown_loops:
            return ActionDecision(request, False, "cooldown", priority)

        if request.action_name in self._active:
            return ActionDecision(request, False, "already_active", priority)

        for precondition in self._preconditions[request.action_name]:
            result = precondition(observation, request)
            if result is not True:
                return ActionDecision(request, False, str(result), priority)
        return ActionDecision(request, True, "accepted", priority)

    def accept(
        self, observation: AllyObservation, request: DecisionRequest
    ) -> ActionDecision:
        decision = self.evaluate(observation, request)
        if decision.accepted:
            self._active[request.action_name] = _ActiveAction(request, request.loop)
        return decision

    def active_request(self, action_name: str) -> DecisionRequest | None:
        active = self._active.get(action_name)
        return active.request if active else None

    def transition(
        self,
        request: DecisionRequest,
        loop: int,
        status: ActionStatus,
        reason: str = "",
    ) -> ActionResult:
        if status in {
            ActionStatus.ACCEPTED,
            ActionStatus.QUEUED,
            ActionStatus.ISSUED,
        }:
            active = self._active.get(request.action_name)
            if active is None or active.request.request_id != request.request_id:
                raise ValueError("cannot transition an inactive request")
            active.status = status
            spec = self.get(request.action_name)
            return ActionResult(
                action_name=request.action_name,
                request_id=request.request_id,
                request_loop=request.loop,
                status=status,
                loop=loop,
                reason=reason,
                executor=spec.executor,
            )
        return self.complete(request, loop, status, reason)

    def complete(
        self,
        request: DecisionRequest,
        loop: int,
        status: ActionStatus,
        reason: str = "",
    ) -> ActionResult:
        spec = self.get(request.action_name)
        active = self._active.get(request.action_name)
        if active is None:
            raise ValueError("cannot complete an inactive action")
        if active.request.request_id != request.request_id:
            raise ValueError("request does not match active action")
        if status in {
            ActionStatus.ACCEPTED,
            ActionStatus.QUEUED,
            ActionStatus.ISSUED,
        }:
            raise ValueError("intermediate status must use transition")
        self._active.pop(request.action_name, None)
        if status == ActionStatus.APPLIED:
            self._last_applied_loop[request.action_name] = loop
        return ActionResult(
            action_name=request.action_name,
            request_loop=request.loop,
            status=status,
            loop=loop,
            reason=reason,
            executor=spec.executor,
            request_id=request.request_id,
        )

    def expire(self, loop: int) -> tuple[ActionResult, ...]:
        results: list[ActionResult] = []
        for action_name, active in tuple(self._active.items()):
            spec = self._specs[action_name]
            if spec.timeout_loops and loop - active.accepted_loop >= spec.timeout_loops:
                results.append(
                    self.complete(active.request, loop, ActionStatus.EXPIRED, "timeout")
                )
        return tuple(results)

    def cancel(self, request: DecisionRequest, loop: int, reason: str) -> ActionResult:
        return self.complete(request, loop, ActionStatus.CANCELLED, reason)

    def accepted_candidates(
        self, observation: AllyObservation, requests: Iterable[DecisionRequest]
    ) -> tuple[ActionDecision, ...]:
        decisions = [self.evaluate(observation, request) for request in requests]
        return tuple(
            sorted(
                decisions,
                key=lambda item: (
                    not item.accepted,
                    item.priority,
                    item.request.action_name,
                ),
            )
        )
