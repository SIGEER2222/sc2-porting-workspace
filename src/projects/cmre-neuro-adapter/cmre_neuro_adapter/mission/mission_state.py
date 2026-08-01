"""Versioned campaign, mission, and runtime state records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..neuro.mission_projection import PublicMissionContext


@dataclass(frozen=True)
class MissionEvent:
    kind: str
    source_loop: int
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source_loop": self.source_loop,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class CampaignState:
    campaign_id: str
    version: int

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.campaign_id, "version": self.version}


@dataclass(frozen=True)
class MissionState:
    version: int
    source_state_version: int
    source_loop: int
    map_name: str
    phase: str
    night: int
    wave: int
    terminated: bool
    outcome: str
    no_build: bool
    paused: bool
    blocking: bool
    context: PublicMissionContext
    economy: Any
    production: Any
    tactical: Any

    @classmethod
    def from_context(
        cls,
        context: PublicMissionContext,
        *,
        version: int,
        no_build: bool,
        paused: bool,
        blocking: bool,
    ) -> "MissionState":
        from .economy_context import EconomyContext
        from .production_context import ProductionContext
        from .tactical_context import TacticalContext

        outcome = "in_progress"
        if context.terminated:
            outcome = "victory" if context.phase == "victory" else "failure"
        return cls(
            version=version,
            source_state_version=context.state_version,
            source_loop=context.source_loop,
            map_name=context.map_name,
            phase=context.phase,
            night=context.night,
            wave=context.wave,
            terminated=context.terminated,
            outcome=outcome,
            no_build=no_build,
            paused=paused,
            blocking=blocking,
            context=context,
            economy=EconomyContext.from_context(context),
            production=ProductionContext.from_context(context),
            tactical=TacticalContext.from_context(context),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source_state_version": self.source_state_version,
            "source_loop": self.source_loop,
            "map": self.map_name,
            "phase": self.phase,
            "night": self.night,
            "wave": self.wave,
            "terminated": self.terminated,
            "outcome": self.outcome,
            "no_build": self.no_build,
            "paused": self.paused,
            "blocking": self.blocking,
            "economy": self.economy.to_dict(),
            "production": self.production.to_dict(),
            "tactical": self.tactical.to_dict(),
        }


@dataclass(frozen=True)
class RuntimeState:
    version: int
    context_version: int
    active_action_names: tuple[str, ...]
    queued_action_ids: tuple[str, ...]
    ready: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "context_version": self.context_version,
            "active_action_names": list(self.active_action_names),
            "queued_action_ids": list(self.queued_action_ids),
            "ready": self.ready,
        }


@dataclass(frozen=True)
class MissionSnapshot:
    campaign: CampaignState
    mission: MissionState
    runtime: RuntimeState

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign": self.campaign.to_dict(),
            "mission": self.mission.to_dict(),
            "runtime": self.runtime.to_dict(),
        }


__all__ = [
    "CampaignState",
    "MissionEvent",
    "MissionSnapshot",
    "MissionState",
    "RuntimeState",
]
