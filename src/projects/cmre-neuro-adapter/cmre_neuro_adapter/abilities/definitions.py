"""Stable definitions for the first CMRE ability slice.

The values here are adapter contract values, not claims about authoritative SC2
catalog data.  The simulator remains responsible for applying an effect.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from ..neuro.actions import ActionDefinition


@dataclass(frozen=True)
class AbilityDefinition:
    """One public ability definition exposed to Neuro and the simulator."""

    name: str
    description: str
    schema: Mapping[str, Any]
    energy_cost: int | float
    cooldown: int
    effect_operation: str
    priority: str = "high"

    def __post_init__(self) -> None:
        for value, label in (
            (self.name, "ability name"),
            (self.description, "ability description"),
            (self.effect_operation, "effect operation"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must be a non-empty string")
        if not isinstance(self.schema, Mapping):
            raise TypeError("ability schema must be an object")
        if (
            not isinstance(self.energy_cost, (int, float))
            or isinstance(self.energy_cost, bool)
            or not math.isfinite(float(self.energy_cost))
            or self.energy_cost < 0
        ):
            raise ValueError("ability energy_cost must be a finite non-negative number")
        if not isinstance(self.cooldown, int) or isinstance(self.cooldown, bool):
            raise ValueError("ability cooldown must be a non-negative integer")
        if self.cooldown < 0:
            raise ValueError("ability cooldown must be a non-negative integer")
        if self.priority not in {"low", "medium", "high", "critical"}:
            raise ValueError(f"invalid ability priority: {self.priority}")

    @property
    def ability_id(self) -> str:
        """Stable id alias used by transport-facing callers."""

        return self.name

    @property
    def cost(self) -> int | float:
        return self.energy_cost

    @property
    def cooldown_loops(self) -> int:
        return self.cooldown

    def to_action_definition(self) -> ActionDefinition:
        return ActionDefinition(
            name=self.name,
            description=self.description,
            schema=dict(self.schema),
            priority=self.priority,
            source="cmre-ability",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "schema": dict(self.schema),
            "energy_cost": self.energy_cost,
            "cooldown": self.cooldown,
            "effect_operation": self.effect_operation,
            "priority": self.priority,
        }


_EMPTY_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


ABILITY_DEFINITIONS: tuple[AbilityDefinition, ...] = (
    AbilityDefinition(
        name="heal_allies",
        description="Restore allied units through the mission simulator.",
        schema={
            "type": "object",
            "properties": {
                "amount": {"type": "number", "minimum": 1},
            },
            "required": [],
            "additionalProperties": False,
        },
        energy_cost=25,
        cooldown=30,
        effect_operation="ability.heal_allies",
    ),
    AbilityDefinition(
        name="temporary_shields",
        description="Apply temporary shields to allied units.",
        schema={
            "type": "object",
            "properties": {
                "amount": {"type": "number", "minimum": 1},
                "duration_loops": {"type": "integer", "minimum": 1},
            },
            "required": [],
            "additionalProperties": False,
        },
        energy_cost=40,
        cooldown=45,
        effect_operation="ability.temporary_shields",
    ),
    AbilityDefinition(
        name="call_backup",
        description="Request deterministic allied reinforcements.",
        schema={
            "type": "object",
            "properties": {
                "unit_type_id": {"type": "string"},
                "count": {"type": "integer", "minimum": 1, "maximum": 20},
                "x": {"type": "number"},
                "y": {"type": "number"},
            },
            "required": [],
            "additionalProperties": False,
        },
        energy_cost=75,
        cooldown=90,
        effect_operation="ability.call_backup",
    ),
    AbilityDefinition(
        name="nuke_visible_target",
        description="Request a strike against one currently visible enemy.",
        schema={
            "type": "object",
            "properties": {
                "target_entity_id": {"type": "integer", "minimum": 0},
            },
            "required": ["target_entity_id"],
            "additionalProperties": False,
        },
        energy_cost=100,
        cooldown=120,
        effect_operation="ability.nuke_visible_target",
        priority="critical",
    ),
)


def default_ability_definitions() -> tuple[AbilityDefinition, ...]:
    """Return a fresh tuple of the stable built-in definitions."""

    return tuple(ABILITY_DEFINITIONS)


__all__ = [
    "ABILITY_DEFINITIONS",
    "AbilityDefinition",
    "default_ability_definitions",
]
