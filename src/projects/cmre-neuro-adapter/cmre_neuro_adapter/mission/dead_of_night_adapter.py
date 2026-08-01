"""Dead of Night mission lifecycle adapter above the offline Neuro runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Mapping

from ..neuro.actions import ActionDefinition
from ..neuro.context import ContextEnvelope
from ..neuro.mission_projection import PublicMissionContext
from ..neuro.runtime import NeuroRuntime
from .mission_state import (
    CampaignState,
    MissionEvent,
    MissionSnapshot,
    MissionState,
    RuntimeState,
)
from .objective_context import objective_events
from .tactical_context import tactical_events


PRODUCTION_ACTIONS = frozenset(
    {"produce_unit", "research_upgrade", "set_rally"}
)
DEFAULT_BUILDING_TYPES = frozenset(
    {"CommandCenter", "Barracks", "Factory", "Starport", "Bunker"}
)


@dataclass(frozen=True)
class MissionUpdate:
    snapshot: MissionSnapshot
    events: tuple[MissionEvent, ...]
    envelope: ContextEnvelope | None
    emitted: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot.to_dict(),
            "events": [event.to_dict() for event in self.events],
            "context_emitted": self.emitted,
            "reason": self.reason,
            "envelope": None if self.envelope is None else {
                "name": self.envelope.name,
                "message": self.envelope.message,
                "loop": self.envelope.loop,
            },
        }


class DeadOfNightAdapter:
    """Own mission projection and lifecycle policy, not mission authority."""

    def __init__(
        self,
        *,
        runtime: NeuroRuntime | None = None,
        actions: Mapping[str, ActionDefinition] | None = None,
        campaign_id: str = "cmre",
        map_name: str = "dead-of-night",
        building_types: set[str] | frozenset[str] = DEFAULT_BUILDING_TYPES,
    ) -> None:
        if not campaign_id.strip() or not map_name.strip():
            raise ValueError("campaign_id and map_name must not be empty")
        if actions is not None:
            for name, action in actions.items():
                if name != action.name:
                    raise ValueError("action mapping key must match action.name")
        self.runtime = runtime
        self.actions = dict(actions or {})
        self.campaign = CampaignState(campaign_id.strip(), 1)
        self.map_name = map_name.strip()
        self.building_types = frozenset(building_types)
        self._mission_version = 0
        self._runtime_version = 0
        self._event_sequence = 0
        self._previous_context: PublicMissionContext | None = None
        self._last_semantic_key: str | None = None
        self._snapshot: MissionSnapshot | None = None

    @property
    def snapshot(self) -> MissionSnapshot | None:
        return self._snapshot

    def allowed_actions(
        self,
        context: PublicMissionContext,
        *,
        no_build: bool = False,
        paused: bool = False,
        blocking: bool = False,
    ) -> tuple[ActionDefinition, ...]:
        if context.terminated or context.phase in {"victory", "failure"}:
            return ()
        if paused or blocking:
            return ()
        actions = self.actions.values()
        if no_build:
            actions = (action for action in actions if action.name not in PRODUCTION_ACTIONS)
        return tuple(sorted(actions, key=lambda action: action.name))

    def ingest(
        self,
        context: PublicMissionContext,
        *,
        no_build: bool = False,
        paused: bool = False,
        blocking: bool = False,
        force: bool = False,
    ) -> MissionUpdate:
        if context.map_name != self.map_name:
            raise ValueError(
                f"unexpected map '{context.map_name}', expected '{self.map_name}'"
            )
        for name, value in (
            ("no_build", no_build),
            ("paused", paused),
            ("blocking", blocking),
            ("force", force),
        ):
            if not isinstance(value, bool):
                raise TypeError(f"{name} must be boolean")

        self._mission_version += 1
        allowed = self.allowed_actions(
            context, no_build=no_build, paused=paused, blocking=blocking
        )
        mission = MissionState.from_context(
            context,
            version=self._mission_version,
            no_build=no_build,
            paused=paused,
            blocking=blocking,
        )
        events = self._events(context)
        self._runtime_version += 1
        runtime_state = RuntimeState(
            version=self._runtime_version,
            context_version=context.context_version,
            active_action_names=tuple(action.name for action in allowed),
            queued_action_ids=(),
            ready=self.runtime.ready if self.runtime is not None else False,
        )
        snapshot = MissionSnapshot(self.campaign, mission, runtime_state)
        semantic_key = self._semantic_key(context, no_build, paused, blocking)
        emitted = force or bool(events) or semantic_key != self._last_semantic_key
        envelope = None
        if emitted:
            envelope = context.to_envelope(
                priority="high" if context.terminated or events else "low"
            )
        if force:
            reason = "forced"
        elif events:
            reason = "event"
        elif emitted:
            reason = "changed"
        else:
            reason = "deduplicated"
        self._previous_context = context
        self._last_semantic_key = semantic_key
        self._snapshot = snapshot
        return MissionUpdate(snapshot, events, envelope, emitted, reason)

    async def sync(
        self,
        context: PublicMissionContext,
        *,
        no_build: bool = False,
        paused: bool = False,
        blocking: bool = False,
        force: bool = False,
    ) -> MissionUpdate:
        """Ingest state and apply the phase action policy to ``NeuroRuntime``."""

        update = self.ingest(
            context,
            no_build=no_build,
            paused=paused,
            blocking=blocking,
            force=force,
        )
        if self.runtime is None:
            return update

        self.runtime.set_paused(paused)
        self.runtime.set_blocking(blocking)
        self.runtime.set_update_in_progress(blocking)
        if context.terminated:
            await self.runtime.end_mission()
        else:
            await self.runtime.update_actions(
                self.allowed_actions(
                    context,
                    no_build=no_build,
                    paused=paused,
                    blocking=blocking,
                )
            )
            if self.runtime.ready and not self.runtime.state.in_mission:
                await self.runtime.start_mission()
        state = self.runtime.state
        snapshot = replace(
            update.snapshot,
            runtime=replace(
                update.snapshot.runtime,
                active_action_names=state.active_actions,
                queued_action_ids=state.queued_action_ids,
                ready=self.runtime.ready,
            ),
        )
        result = replace(update, snapshot=snapshot)
        self._snapshot = snapshot
        return result

    def _events(self, current: PublicMissionContext) -> tuple[MissionEvent, ...]:
        if self._previous_context is None:
            return ()
        raw_events = (
            objective_events(self._previous_context, current)
            + tactical_events(
                self._previous_context,
                current,
                building_unit_types=self.building_types,
            )
        )
        events: list[MissionEvent] = []
        for event in raw_events:
            self._event_sequence += 1
            events.append(
                MissionEvent(
                    event.kind,
                    event.source_loop,
                    {"sequence": self._event_sequence, **dict(event.payload)},
                )
            )
        return tuple(events)

    @staticmethod
    def _semantic_key(
        context: PublicMissionContext,
        no_build: bool,
        paused: bool,
        blocking: bool,
    ) -> str:
        payload = context.to_dict()
        payload.pop("context_version", None)
        payload.pop("state_version", None)
        payload.pop("source_loop", None)
        payload["lifecycle"] = {
            "no_build": no_build,
            "paused": paused,
            "blocking": blocking,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


__all__ = [
    "DeadOfNightAdapter",
    "MissionUpdate",
    "PRODUCTION_ACTIONS",
]
