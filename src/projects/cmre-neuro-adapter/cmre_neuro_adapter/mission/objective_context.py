"""Public objective change detection."""

from __future__ import annotations

from ..neuro.mission_projection import PublicMissionContext
from .mission_state import MissionEvent


def objective_events(
    previous: PublicMissionContext, current: PublicMissionContext
) -> tuple[MissionEvent, ...]:
    previous_items = {item.objective_id: item for item in previous.objectives}
    current_items = {item.objective_id: item for item in current.objectives}
    events: list[MissionEvent] = []
    for objective_id in sorted(set(previous_items) | set(current_items)):
        before = previous_items.get(objective_id)
        after = current_items.get(objective_id)
        before_dict = None if before is None else before.to_dict()
        after_dict = None if after is None else after.to_dict()
        if before_dict != after_dict:
            events.append(
                MissionEvent(
                    "objective_changed",
                    current.source_loop,
                    {
                        "objective_id": objective_id,
                        "before": before_dict,
                        "after": after_dict,
                    },
                )
            )
    return tuple(events)


__all__ = ["objective_events"]
