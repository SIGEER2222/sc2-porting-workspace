"""Map-independent tactical context and deterministic map profile lookup.

Profiles provide a small, stable context vector to the shared policy. They do
not encode a complete map script; current observations remain the authority for
units, threats, resources, and mission progress.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


MAP_CONTEXT_SCHEMA = "cmre-map-context.v1"
MAP_FAMILIES: tuple[str, ...] = (
    "survival",
    "defense",
    "escort",
    "assault",
    "unknown",
)
MAP_CONTEXT_NAMES: tuple[str, ...] = tuple(
    [f"family.{family}" for family in MAP_FAMILIES]
    + ["profile.known", "mission.night_cycle", "map.scale"]
)


def normalize_map_id(map_name: str) -> str:
    """Normalize human/map-file names without relying on a fixed map list."""

    if not isinstance(map_name, str) or not map_name.strip():
        raise ValueError("map_name must be a non-empty string")
    raw = map_name.strip()
    normalized = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    if normalized.endswith("-sc2map"):
        normalized = normalized[:-len("-sc2map")].rstrip("-")
    if normalized:
        return normalized
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    return f"map-{digest}"


@dataclass(frozen=True)
class TacticalZone:
    """Optional map-owned anchor; coordinates are world-space values."""

    name: str
    x: float
    y: float


@dataclass(frozen=True)
class MapProfile:
    """Stable metadata used to condition a shared policy across maps."""

    map_id: str
    family: str = "unknown"
    win_condition: str = "unknown"
    known: bool = False
    night_cycle: bool = False
    map_size: tuple[float, float] = (192.0, 192.0)
    strategic_zones: tuple[TacticalZone, ...] = ()

    def __post_init__(self) -> None:
        if not self.map_id.strip():
            raise ValueError("map_id must not be empty")
        if self.family not in MAP_FAMILIES:
            raise ValueError(f"unknown map family: {self.family}")
        if len(self.map_size) != 2 or any(float(value) <= 0 for value in self.map_size):
            raise ValueError("map_size must contain two positive values")

    @property
    def context_dim(self) -> int:
        return len(MAP_CONTEXT_NAMES)

    def context_vector(self) -> tuple[float, ...]:
        family_values = [1.0 if family == self.family else 0.0 for family in MAP_FAMILIES]
        scale = min(1.0, max(self.map_size) / 512.0)
        return tuple(family_values + [float(self.known), float(self.night_cycle), scale])

    def point_for(self, role: str, observation: Mapping[str, Any]) -> tuple[float, float]:
        """Choose a target from profile anchors and current visible state."""

        role = str(role).strip().lower()
        for zone in self.strategic_zones:
            if zone.name == role:
                return float(zone.x), float(zone.y)

        enemies = _points(observation.get("visible_enemies", ()))
        own = _points(observation.get("own_units", ()))
        minerals = _points(observation.get("mineral_fields", ()))
        if role in {"attack", "harass", "assault"} and enemies:
            return _centroid(enemies)
        if role in {"resource", "gather"} and minerals:
            return _centroid(minerals)
        if own:
            return _centroid(own)
        return 85.0, 94.0


class MapProfileRegistry:
    """Resolve known maps and provide a safe family-level fallback."""

    def __init__(self, profiles: Mapping[str, MapProfile] | None = None) -> None:
        self._profiles: dict[str, MapProfile] = {}
        for profile in (profiles or _default_profiles()).values():
            self.register(profile)

    def register(self, profile: MapProfile) -> None:
        self._profiles[normalize_map_id(profile.map_id)] = profile

    def resolve(self, map_name: str) -> MapProfile:
        map_id = normalize_map_id(map_name)
        profile = self._profiles.get(map_id)
        if profile is not None:
            return profile
        family = _infer_family(map_id)
        return MapProfile(
            map_id=map_id,
            family=family,
            win_condition="unknown",
            known=False,
            night_cycle=family == "survival",
        )

    def resolve_observation(self, observation: Mapping[str, Any]) -> MapProfile:
        raw_name = observation.get("map_name", observation.get("map"))
        if not raw_name:
            mission = observation.get("mission", {})
            raw_name = mission.get("map", "unknown-map") if isinstance(mission, Mapping) else "unknown-map"
        return self.resolve(str(raw_name))

    @property
    def profiles(self) -> tuple[MapProfile, ...]:
        return tuple(self._profiles[key] for key in sorted(self._profiles))


def map_context_schema_hash() -> str:
    payload = json.dumps(
        {"schema": MAP_CONTEXT_SCHEMA, "features": MAP_CONTEXT_NAMES},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _default_profiles() -> dict[str, MapProfile]:
    return {
        "dead-of-night": MapProfile(
            map_id="dead-of-night",
            family="survival",
            win_condition="survive_nights",
            known=True,
            night_cycle=True,
        ),
        "void-launch": MapProfile(
            map_id="void-launch",
            family="defense",
            win_condition="defend_objectives",
            known=True,
        ),
        "oblivion-express": MapProfile(
            map_id="oblivion-express",
            family="escort",
            win_condition="escort_payload",
            known=True,
        ),
        "temple-of-the-past": MapProfile(
            map_id="temple-of-the-past",
            family="defense",
            win_condition="defend_objectives",
            known=True,
        ),
        "mist-opportunities": MapProfile(
            map_id="mist-opportunities",
            family="assault",
            win_condition="complete_objectives",
            known=True,
        ),
    }


def _infer_family(map_id: str) -> str:
    if any(token in map_id for token in ("night", "dead", "survival")):
        return "survival"
    if any(token in map_id for token in ("defend", "temple", "lock", "fort")):
        return "defense"
    if any(token in map_id for token in ("escort", "express", "payload")):
        return "escort"
    if any(token in map_id for token in ("assault", "mist", "attack")):
        return "assault"
    return "unknown"


def _points(values: Any) -> list[tuple[float, float]]:
    if not isinstance(values, (list, tuple)):
        return []
    points: list[tuple[float, float]] = []
    for value in values:
        if not isinstance(value, Mapping):
            continue
        try:
            points.append((float(value.get("x", 0.0)), float(value.get("y", 0.0))))
        except (TypeError, ValueError):
            continue
    return points


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


__all__ = [
    "MAP_CONTEXT_NAMES",
    "MAP_CONTEXT_SCHEMA",
    "MAP_FAMILIES",
    "MapProfile",
    "MapProfileRegistry",
    "TacticalZone",
    "map_context_schema_hash",
    "normalize_map_id",
]
