"""Public tactical summaries and observation-derived event detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable

from ..neuro.mission_projection import PublicMissionContext, PublicUnit

if TYPE_CHECKING:
    from .mission_state import MissionEvent


@dataclass(frozen=True)
class TacticalContext:
    own_unit_count: int
    visible_enemy_count: int
    threats: tuple[dict[str, Any], ...]

    @classmethod
    def from_context(cls, context: PublicMissionContext) -> "TacticalContext":
        return cls(
            own_unit_count=len(context.own_units),
            visible_enemy_count=len(context.visible_enemies),
            threats=tuple(item.to_dict() for item in context.threats),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "own_unit_count": self.own_unit_count,
            "visible_enemy_count": self.visible_enemy_count,
            "threats": list(self.threats),
        }


def tactical_events(
    previous: PublicMissionContext,
    current: PublicMissionContext,
    *,
    building_unit_types: Iterable[str] = (),
) -> tuple["MissionEvent", ...]:
    """Return deterministic wave, building, death, and terminal events."""

    from .mission_state import MissionEvent

    events: list[MissionEvent] = []
    if current.wave > previous.wave:
        events.append(
            MissionEvent(
                "wave_spawned",
                current.source_loop,
                {"from_wave": previous.wave, "to_wave": current.wave},
            )
        )
    if current.phase != previous.phase:
        events.append(
            MissionEvent(
                "mission_phase_changed",
                current.source_loop,
                {"from": previous.phase, "to": current.phase},
            )
        )

    building_types = set(building_unit_types)
    previous_units = _unit_map(previous.own_units)
    current_units = _unit_map(current.own_units)
    for entity_id in sorted(set(current_units) - set(previous_units)):
        unit = current_units[entity_id]
        if unit.unit_type_id in building_types:
            events.append(
                MissionEvent(
                    "building_completed",
                    current.source_loop,
                    {"entity_id": entity_id, "unit_type_id": unit.unit_type_id},
                )
            )

    for visibility, old_units, new_units in (
        ("self", previous.own_units, current.own_units),
        ("enemy", previous.visible_enemies, current.visible_enemies),
    ):
        old_map = _unit_map(old_units)
        new_map = _unit_map(new_units)
        for entity_id in sorted(set(old_map) - set(new_map)):
            unit = old_map[entity_id]
            events.append(
                MissionEvent(
                    "unit_died",
                    current.source_loop,
                    {
                        "entity_id": entity_id,
                        "unit_type_id": unit.unit_type_id,
                        "visibility": visibility,
                    },
                )
            )
        for entity_id in sorted(set(old_map) & set(new_map)):
            if old_map[entity_id].state != "dead" and new_map[entity_id].state == "dead":
                unit = new_map[entity_id]
                events.append(
                    MissionEvent(
                        "unit_died",
                        current.source_loop,
                        {
                            "entity_id": entity_id,
                            "unit_type_id": unit.unit_type_id,
                            "visibility": visibility,
                        },
                    )
                )

    if current.terminated and not previous.terminated:
        events.append(
            MissionEvent(
                "mission_ended",
                current.source_loop,
                {
                    "outcome": current.phase,
                    "end_reason": current.end_reason,
                },
            )
        )
    return tuple(events)


def _unit_map(units: Iterable[PublicUnit]) -> dict[int, PublicUnit]:
    return {unit.entity_id: unit for unit in units}


__all__ = ["TacticalContext", "tactical_events"]
