"""Public production summary derived only from own visible units."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from ..neuro.mission_projection import PublicMissionContext


BASE_UNIT_TYPES = frozenset(
    {"CommandCenter", "OrbitalCommand", "PlanetaryFortress", "Nexus", "Hatchery"}
)


@dataclass(frozen=True)
class ProductionContext:
    own_unit_counts: tuple[tuple[str, int], ...]
    base_count: int
    base_unit_types: tuple[str, ...]

    @classmethod
    def from_context(cls, context: PublicMissionContext) -> "ProductionContext":
        counts = Counter(unit.unit_type_id for unit in context.own_units)
        base_types = tuple(
            sorted(
                unit.unit_type_id
                for unit in context.own_units
                if unit.unit_type_id in BASE_UNIT_TYPES
            )
        )
        return cls(tuple(sorted(counts.items())), len(base_types), base_types)

    def to_dict(self) -> dict[str, Any]:
        return {
            "own_unit_counts": dict(self.own_unit_counts),
            "base_count": self.base_count,
            "base_unit_types": list(self.base_unit_types),
        }


__all__ = ["BASE_UNIT_TYPES", "ProductionContext"]
