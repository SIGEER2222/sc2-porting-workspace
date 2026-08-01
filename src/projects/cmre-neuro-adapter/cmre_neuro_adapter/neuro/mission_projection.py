"""Project the CMRE simulator observation into a public Neuro context.

The simulator observation is already the visibility boundary.  This module
keeps that boundary explicit by copying only documented public fields into
immutable values before any context is serialized or sent to Neuro.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .context import ContextEnvelope


class ProjectionError(ValueError):
    """Raised when an observation cannot satisfy the public context shape."""


class StaleContextError(ProjectionError):
    """Raised when a projector receives an older simulator state version."""


@dataclass(frozen=True)
class PublicUnit:
    entity_id: int
    unit_type_id: str
    owner: int
    x: int | float
    y: int | float
    health: int | float
    shields: int | float
    energy: int | float
    state: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "unit_type_id": self.unit_type_id,
            "owner": self.owner,
            "x": self.x,
            "y": self.y,
            "health": self.health,
            "shields": self.shields,
            "energy": self.energy,
            "state": self.state,
        }


@dataclass(frozen=True)
class PublicObjective:
    objective_id: str
    name: str
    status: str
    progress: int | float | None = None
    target: int | float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.objective_id,
            "name": self.name,
            "status": self.status,
        }
        if self.progress is not None:
            payload["progress"] = self.progress
        if self.target is not None:
            payload["target"] = self.target
        return payload


@dataclass(frozen=True)
class ThreatSummary:
    owner: int
    unit_type_id: str
    visible_count: int
    health_total: int | float

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "unit_type_id": self.unit_type_id,
            "visible_count": self.visible_count,
            "health_total": self.health_total,
        }


@dataclass(frozen=True)
class PublicMissionContext:
    """Immutable, visibility-limited context consumed by the Neuro layer."""

    map_name: str
    player_id: int
    context_version: int
    state_version: int
    source_loop: int
    phase: str
    night: int
    wave: int
    terminated: bool
    end_reason: str
    win_condition: str
    resources: tuple[tuple[str, int | float], ...]
    objectives: tuple[PublicObjective, ...]
    own_units: tuple[PublicUnit, ...]
    visible_enemies: tuple[PublicUnit, ...]
    threats: tuple[ThreatSummary, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return the stable public wire shape, with no simulator internals."""

        return {
            "context_version": self.context_version,
            "state_version": self.state_version,
            "source_loop": self.source_loop,
            "map": self.map_name,
            "player_id": self.player_id,
            "mission": {
                "phase": self.phase,
                "night": self.night,
                "wave": self.wave,
                "terminated": self.terminated,
                "end_reason": self.end_reason,
                "win_condition": self.win_condition,
                "resources": dict(self.resources),
                "objectives": [item.to_dict() for item in self.objectives],
            },
            "own_units": [item.to_dict() for item in self.own_units],
            "visible_enemies": [item.to_dict() for item in self.visible_enemies],
            "threats": [item.to_dict() for item in self.threats],
            "resources": dict(self.resources),
        }

    def to_json(self) -> str:
        """Serialize the context deterministically for replay and evidence."""

        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )

    def to_envelope(
        self,
        *,
        silent: bool = True,
        priority: str = "low",
    ) -> ContextEnvelope:
        """Convert the projection to the existing transport-neutral envelope."""

        return ContextEnvelope(
            name="mission_context",
            message=self.to_json(),
            silent=silent,
            priority=priority,
            source="simulator",
            loop=self.source_loop,
        )


# Observation.from_world() exposes these unit fields.  Optional simulator
# diagnostics such as max_health are intentionally not copied into the Neuro
# context.
_UNIT_FIELDS = (
    "entity_id",
    "unit_type_id",
    "owner",
    "x",
    "y",
    "health",
    "shields",
    "energy",
    "state",
)
_RESOURCE_FIELDS = ("minerals", "vespene", "supply_used", "supply_cap")


def project_observation(
    observation: Mapping[str, Any],
    *,
    map_name: str = "dead-of-night",
    context_version: int = 1,
    state_version: int | None = None,
) -> PublicMissionContext:
    """Build one immutable context from the public Observation mapping."""

    _require_non_negative_int(context_version, "context_version")
    if not isinstance(observation, Mapping):
        raise ProjectionError("observation must be an object")
    if not isinstance(map_name, str) or not map_name.strip():
        raise ProjectionError("map_name must be a non-empty string")

    player_id = _required_int(observation, "player_id")
    source_loop = _required_int(observation, "loop")
    if state_version is None:
        state_version = source_loop
    _require_non_negative_int(state_version, "state_version")

    mission = observation.get("mission", {})
    if not isinstance(mission, Mapping):
        raise ProjectionError("observation mission must be an object")
    terminated = _bool_value(mission.get("terminated", False), "mission.terminated")
    end_reason = _optional_string_value(
        mission.get("end_reason", ""), "mission.end_reason"
    )
    win_condition = _string_value(
        mission.get("win_condition", "unknown"), "mission.win_condition"
    )
    night = _non_negative_value(
        mission.get("night", mission.get("current_night", 0)), "mission.night"
    )
    wave = _non_negative_value(
        mission.get("wave", mission.get("current_wave", 0)), "mission.wave"
    )
    phase = _mission_phase(mission, terminated, end_reason)

    own_units = _units(observation.get("own_units", []), "own_units")
    visible_enemies = _units(
        observation.get("visible_enemies", []), "visible_enemies"
    )
    resources = _resources(observation.get("resources", {}))
    objectives = _objectives(
        mission.get("objectives", mission.get("objectives_status", []))
    )
    threats = _threats(visible_enemies)

    return PublicMissionContext(
        map_name=map_name.strip(),
        player_id=player_id,
        context_version=context_version,
        state_version=state_version,
        source_loop=source_loop,
        phase=phase,
        night=night,
        wave=wave,
        terminated=terminated,
        end_reason=end_reason,
        win_condition=win_condition,
        resources=resources,
        objectives=objectives,
        own_units=own_units,
        visible_enemies=visible_enemies,
        threats=threats,
    )


class MissionContextProjector:
    """Assign monotonically increasing context versions to observations."""

    def __init__(self, *, map_name: str = "dead-of-night") -> None:
        if not isinstance(map_name, str) or not map_name.strip():
            raise ValueError("map_name must be a non-empty string")
        self.map_name = map_name.strip()
        self._context_version = 0
        self._state_version = -1

    @property
    def context_version(self) -> int:
        return self._context_version

    @property
    def state_version(self) -> int:
        return self._state_version

    def project(
        self,
        observation: Mapping[str, Any],
        *,
        state_version: int,
    ) -> PublicMissionContext:
        _require_non_negative_int(state_version, "state_version")
        if state_version < self._state_version:
            raise StaleContextError(
                f"state_version {state_version} is older than {self._state_version}"
            )
        next_context_version = self._context_version + 1
        context = project_observation(
            observation,
            map_name=self.map_name,
            context_version=next_context_version,
            state_version=state_version,
        )
        self._context_version = next_context_version
        self._state_version = state_version
        return context


def _units(raw: Any, field_name: str) -> tuple[PublicUnit, ...]:
    if not isinstance(raw, (list, tuple)):
        raise ProjectionError(f"observation {field_name} must be a list")
    units = tuple(_unit(item, field_name) for item in raw)
    return tuple(sorted(units, key=lambda item: (item.entity_id, item.owner)))


def _unit(raw: Any, field_name: str) -> PublicUnit:
    if not isinstance(raw, Mapping):
        raise ProjectionError(f"{field_name} entries must be objects")
    missing = [name for name in _UNIT_FIELDS if name not in raw]
    if missing:
        raise ProjectionError(f"{field_name} entry missing fields: {', '.join(missing)}")
    entity_id = _required_int(raw, "entity_id")
    owner = _required_int(raw, "owner")
    if entity_id < 0 or owner < 0:
        raise ProjectionError(f"{field_name} entity_id and owner must be non-negative")
    return PublicUnit(
        entity_id=entity_id,
        unit_type_id=_string_value(raw["unit_type_id"], "unit_type_id"),
        owner=owner,
        x=_number_value(raw["x"], "x"),
        y=_number_value(raw["y"], "y"),
        health=_number_value(raw["health"], "health"),
        shields=_number_value(raw["shields"], "shields"),
        energy=_number_value(raw["energy"], "energy"),
        state=_string_value(raw["state"], "state"),
    )


def _resources(raw: Any) -> tuple[tuple[str, int | float], ...]:
    if not isinstance(raw, Mapping):
        raise ProjectionError("observation resources must be an object")
    values = {
        key: _number_value(raw[key], f"resources.{key}")
        for key in _RESOURCE_FIELDS
        if key in raw
    }
    return tuple(sorted(values.items()))


def _objectives(raw: Any) -> tuple[PublicObjective, ...]:
    if not isinstance(raw, (list, tuple)):
        raise ProjectionError("mission objectives must be a list")
    result: list[PublicObjective] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ProjectionError("mission objective entries must be objects")
        raw_id = item.get("id", item.get("objective_id", item.get("name", index)))
        objective_id = _string_value(raw_id, "objective.id")
        name = _string_value(item.get("name", objective_id), "objective.name")
        status = _string_value(item.get("status", "unknown"), "objective.status")
        progress = (
            _number_value(item["progress"], "objective.progress")
            if "progress" in item
            else None
        )
        target = (
            _number_value(item["target"], "objective.target")
            if "target" in item
            else None
        )
        result.append(PublicObjective(objective_id, name, status, progress, target))
    return tuple(sorted(result, key=lambda item: item.objective_id))


def _threats(units: tuple[PublicUnit, ...]) -> tuple[ThreatSummary, ...]:
    grouped: dict[tuple[int, str], list[int | float]] = {}
    for unit in units:
        grouped.setdefault((unit.owner, unit.unit_type_id), []).append(unit.health)
    return tuple(
        ThreatSummary(
            owner=owner,
            unit_type_id=unit_type_id,
            visible_count=len(health_values),
            health_total=sum(health_values),
        )
        for (owner, unit_type_id), health_values in sorted(grouped.items())
    )


def _mission_phase(mission: Mapping[str, Any], terminated: bool, end_reason: str) -> str:
    explicit = mission.get("phase", mission.get("mission_phase"))
    if explicit is not None:
        return _string_value(explicit, "mission.phase")
    if not terminated:
        return "active"
    if end_reason in {"victory", "all_objectives_success", "survive_loops", "max_loops_reached"}:
        return "victory"
    return "defeat"


def _required_int(mapping: Mapping[str, Any], key: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProjectionError(f"{key} must be an integer")
    return value


def _require_non_negative_int(value: Any, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProjectionError(f"{name} must be a non-negative integer")


def _non_negative_value(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProjectionError(f"{name} must be a non-negative integer")
    return value


def _number_value(value: Any, name: str) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ProjectionError(f"{name} must be numeric")
    return value


def _string_value(value: Any, name: str) -> str:
    if not isinstance(value, str):
        value = str(value) if isinstance(value, (int, float)) else None
    if not isinstance(value, str) or not value.strip():
        raise ProjectionError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_string_value(value: Any, name: str) -> str:
    if value == "":
        return ""
    return _string_value(value, name)


def _bool_value(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ProjectionError(f"{name} must be boolean")
    return value


__all__ = [
    "MissionContextProjector",
    "ProjectionError",
    "PublicMissionContext",
    "PublicObjective",
    "PublicUnit",
    "StaleContextError",
    "ThreatSummary",
    "project_observation",
]
