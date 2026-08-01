"""Dead of Night phase and high-priority event arbitration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .decision_contracts import AllyObservation, DecisionRequest, MissionSummary


class MissionPhase(StrEnum):
    STARTING = "starting"
    BUILDUP = "buildup"
    NIGHT_DEFENSE = "night_defense"
    STABILIZE = "stabilize"
    EXPAND = "expand"
    CLEAR_OBJECTIVE = "clear_objective"
    RETREAT = "retreat"
    MISSION_END = "mission_end"


class DecisionEvent(StrEnum):
    BASE_THREAT = "base_threat"
    LOW_HEALTH = "low_health"
    NIGHT_STARTED = "night_started"
    OBJECTIVES_COMPLETE = "objectives_complete"
    MISSION_DEFEAT = "mission_defeat"
    MISSION_VICTORY = "mission_victory"


@dataclass(frozen=True)
class PhaseDecision:
    phase: MissionPhase
    events: tuple[DecisionEvent, ...]
    reason: str


class MissionPhaseArbiter:
    """Pure phase machine; game adapters only provide observations."""

    def __init__(self) -> None:
        self.phase = MissionPhase.STARTING

    def evaluate(self, observation: AllyObservation) -> PhaseDecision:
        mission = observation.mission
        events = self._events(observation)
        if mission.mission_over:
            next_phase = MissionPhase.MISSION_END
            reason = "mission_defeat" if mission.defeat else "mission_victory"
        elif observation.has_base_threat:
            next_phase = MissionPhase.NIGHT_DEFENSE
            reason = "base_threat_requires_defense"
        elif observation.low_health_combat_units > 0 and observation.army_supply > 0:
            next_phase = MissionPhase.RETREAT
            reason = "low_health_units_require_retreat"
        elif mission.night_active:
            next_phase = MissionPhase.NIGHT_DEFENSE
            reason = "night_active"
        elif self.phase == MissionPhase.STARTING:
            next_phase = MissionPhase.BUILDUP
            reason = "initialization_complete"
        elif (
            mission.objective_count > 0
            and mission.completed_objectives < mission.objective_count
            and observation.army_supply >= 12
        ):
            next_phase = MissionPhase.CLEAR_OBJECTIVE
            reason = "army_ready_for_objective"
        elif observation.bases < 2 and observation.workers >= 16:
            next_phase = MissionPhase.EXPAND
            reason = "economy_ready_to_expand"
        else:
            next_phase = MissionPhase.STABILIZE
            reason = "no_override_event"
        self.phase = next_phase
        return PhaseDecision(next_phase, events, reason)

    def requests(
        self, observation: AllyObservation, decision: PhaseDecision
    ) -> tuple[DecisionRequest, ...]:
        loop = observation.loop
        phase = decision.phase.value
        requests: list[DecisionRequest] = []
        if decision.phase == MissionPhase.MISSION_END:
            return ()
        if decision.phase == MissionPhase.NIGHT_DEFENSE:
            requests.append(
                DecisionRequest(
                    "defend_base",
                    loop,
                    phase,
                    reason=decision.reason,
                    priority_override=0,
                )
            )
        elif decision.phase == MissionPhase.RETREAT:
            requests.append(
                DecisionRequest(
                    "retreat_damaged_units",
                    loop,
                    phase,
                    reason=decision.reason,
                    priority_override=0,
                )
            )
        elif decision.phase == MissionPhase.EXPAND:
            requests.append(
                DecisionRequest("expand", loop, phase, reason=decision.reason)
            )
        elif decision.phase == MissionPhase.CLEAR_OBJECTIVE:
            requests.append(
                DecisionRequest("push_objective", loop, phase, reason=decision.reason)
            )
        else:
            requests.extend(
                (
                    DecisionRequest(
                        "produce_composition", loop, phase, reason="maintain_army"
                    ),
                    DecisionRequest(
                        "research_upgrade", loop, phase, reason="maintain_tech"
                    ),
                )
            )
        return tuple(requests)

    @staticmethod
    def _events(observation: AllyObservation) -> tuple[DecisionEvent, ...]:
        events: list[DecisionEvent] = []
        mission: MissionSummary = observation.mission
        if observation.has_base_threat:
            events.append(DecisionEvent.BASE_THREAT)
        if observation.low_health_combat_units > 0:
            events.append(DecisionEvent.LOW_HEALTH)
        if mission.night_active:
            events.append(DecisionEvent.NIGHT_STARTED)
        if mission.objectives_complete:
            events.append(DecisionEvent.OBJECTIVES_COMPLETE)
        if mission.mission_over:
            events.append(
                DecisionEvent.MISSION_DEFEAT
                if mission.defeat
                else DecisionEvent.MISSION_VICTORY
            )
        return tuple(events)
