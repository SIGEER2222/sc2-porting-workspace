"""Pure decision-control facade for the Dead of Night ally.

The controller owns intent selection and lifecycle bookkeeping. Ares adapters consume the selected
high-level action through ``executor``; this module never constructs SC2 protocol orders.
"""

from __future__ import annotations

from dataclasses import replace

from .action_registry import ActionRegistry
from .decision_contracts import (
    ActionResult,
    ActionStatus,
    AllyObservation,
    DecisionFrame,
    DecisionRequest,
)
from .decision_trace import DecisionTrace
from .mission_phase import MissionPhaseArbiter


class DecisionController:
    """Select and track one validated high-level intent at a time."""

    def __init__(
        self,
        registry: ActionRegistry | None = None,
        arbiter: MissionPhaseArbiter | None = None,
        trace: DecisionTrace | None = None,
    ) -> None:
        self.registry = registry or build_default_registry()
        self.arbiter = arbiter or MissionPhaseArbiter()
        self.trace = trace or DecisionTrace()

    def decide(self, observation: AllyObservation) -> DecisionFrame:
        """Evaluate the current phase, validate candidates, and accept one intent."""
        expired = self.registry.expire(observation.loop)
        phase = self.arbiter.evaluate(observation)
        requests = self.arbiter.requests(observation, phase)
        candidates = self.registry.accepted_candidates(observation, requests)
        selected = next((candidate for candidate in candidates if candidate.accepted), None)
        if selected is not None:
            selected = self.registry.accept(observation, selected.request)

        frame = DecisionFrame(
            loop=observation.loop,
            phase=phase.phase.value,
            observation=observation,
            candidates=candidates,
            selected=selected,
            results=expired,
        )
        self.trace.append(frame)
        return frame

    def transition_selected(
        self,
        frame: DecisionFrame,
        loop: int,
        status: ActionStatus,
        reason: str = "",
    ) -> DecisionFrame:
        if frame.selected is None:
            return frame
        result = self.registry.transition(frame.selected.request, loop, status, reason)
        return self._replace_last(frame, result)

    def complete_selected(
        self,
        frame: DecisionFrame,
        loop: int,
        status: ActionStatus,
        reason: str = "",
    ) -> DecisionFrame:
        if frame.selected is None:
            return frame
        result = self.registry.complete(frame.selected.request, loop, status, reason)
        return self._replace_last(frame, result)

    def cancel_selected(
        self, frame: DecisionFrame, loop: int, reason: str
    ) -> DecisionFrame:
        return self.complete_selected(frame, loop, ActionStatus.CANCELLED, reason)

    def expire(self, loop: int) -> tuple[ActionResult, ...]:
        return self.registry.expire(loop)

    def _replace_last(self, frame: DecisionFrame, result: ActionResult) -> DecisionFrame:
        updated = replace(frame, results=frame.results + (result,))
        if self.trace.frames and self.trace.frames[-1] is frame:
            self.trace.frames[-1] = updated
        return updated


def build_default_registry() -> ActionRegistry:
    """Build the bounded intents exposed to the Ares adapter."""
    from .decision_control import build_default_registry as _build_default_registry

    return _build_default_registry()


__all__ = ["DecisionController", "build_default_registry"]
