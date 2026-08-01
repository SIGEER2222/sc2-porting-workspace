"""Public economy summary derived from a projected simulator context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..neuro.mission_projection import PublicMissionContext


@dataclass(frozen=True)
class EconomyContext:
    resources: tuple[tuple[str, int | float], ...]

    @classmethod
    def from_context(cls, context: PublicMissionContext) -> "EconomyContext":
        return cls(tuple(sorted(context.resources)))

    def to_dict(self) -> dict[str, Any]:
        return {"resources": dict(self.resources)}


__all__ = ["EconomyContext"]
