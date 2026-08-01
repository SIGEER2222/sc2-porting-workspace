"""Pure decision coordinator bridging phase intent to registered actions."""

from __future__ import annotations

from dataclasses import replace

from .action_registry import ActionRegistry
from .decision_contracts import ActionSpec, ActionStatus, AllyObservation, DecisionFrame
from .decision_trace import DecisionTrace
from .mission_phase import MissionPhase, MissionPhaseArbiter


class DecisionCoordinator:
    """Select one explainable high-level intent per observation."""

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
        phase_decision = self.arbiter.evaluate(observation)
        requests = self.arbiter.requests(observation, phase_decision)
        candidates = self.registry.accepted_candidates(observation, requests)
        selected = next(
            (candidate for candidate in candidates if candidate.accepted), None
        )
        if selected is not None:
            accepted = self.registry.accept(observation, selected.request)
            selected = accepted
        frame = DecisionFrame(
            loop=observation.loop,
            phase=phase_decision.phase.value,
            observation=observation,
            candidates=candidates,
            selected=selected,
            results=self.registry.expire(observation.loop),
        )
        self.trace.append(frame)
        return frame

    def complete_selected(
        self, frame: DecisionFrame, loop: int, status: ActionStatus, reason: str = ""
    ) -> DecisionFrame:
        if frame.selected is None:
            return frame
        result = self.registry.complete(frame.selected.request, loop, status, reason)
        updated = replace(frame, results=frame.results + (result,))
        self.trace.frames[-1] = updated
        return updated


def build_default_registry() -> ActionRegistry:
    registry = ActionRegistry()
    active_phases = frozenset(
        phase.value for phase in MissionPhase if phase != MissionPhase.MISSION_END
    )
    registry.register(
        ActionSpec(
            "defend_base",
            "Assign combat units to the highest-priority base threat.",
            priority=20,
            allowed_phases=frozenset({MissionPhase.NIGHT_DEFENSE.value}),
            executor="ares.combat.defend_base",
        )
    )
    registry.register(
        ActionSpec(
            "retreat_damaged_units",
            "Move damaged combat units to a safe rally point.",
            priority=10,
            allowed_phases=frozenset(
                {MissionPhase.RETREAT.value, MissionPhase.NIGHT_DEFENSE.value}
            ),
            executor="ares.combat.retreat",
        )
    )
    registry.register(
        ActionSpec(
            "expand",
            "Start one safe expansion when the economy can support it.",
            priority=40,
            allowed_phases=frozenset(
                {
                    MissionPhase.EXPAND.value,
                    MissionPhase.BUILDUP.value,
                    MissionPhase.STABILIZE.value,
                }
            ),
            executor="ares.macro.expand",
            cooldown_loops=88,
            timeout_loops=176,
        ),
        lambda obs, _request: True if obs.bases < 3 else "max_bases_reached",
    )
    registry.register(
        ActionSpec(
            "produce_composition",
            "Maintain the configured Raynor army composition.",
            priority=60,
            allowed_phases=active_phases,
            executor="ares.macro.production",
            cooldown_loops=22,
        ),
        lambda obs, _request: True if obs.supply_remaining > 0 else "supply_blocked",
    )
    registry.register(
        ActionSpec(
            "research_upgrade",
            "Research the next available army upgrade.",
            priority=70,
            allowed_phases=frozenset(
                {
                    MissionPhase.BUILDUP.value,
                    MissionPhase.STABILIZE.value,
                    MissionPhase.EXPAND.value,
                }
            ),
            executor="ares.macro.research",
            cooldown_loops=44,
        ),
        lambda obs, _request: (
            True
            if obs.minerals >= 50 and obs.vespene >= 25
            else "insufficient_resources"
        ),
    )
    registry.register(
        ActionSpec(
            "push_objective",
            "Move the main combat group toward the current mission objective.",
            priority=50,
            allowed_phases=frozenset(
                {MissionPhase.CLEAR_OBJECTIVE.value, MissionPhase.STABILIZE.value}
            ),
            executor="ares.combat.push_objective",
            timeout_loops=220,
        ),
        lambda obs, _request: True if obs.army_supply >= 12 else "army_not_ready",
    )
    return registry
