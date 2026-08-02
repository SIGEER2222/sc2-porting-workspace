"""Definition registry and public ability context projection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..neuro.actions import ActionDefinition
from ..neuro.mission_projection import PublicMissionContext
from .definitions import AbilityDefinition, default_ability_definitions
from .state import AbilityState


class AbilityRegistry:
    """Keep a deterministic, validated set of available abilities."""

    def __init__(
        self,
        definitions: Iterable[AbilityDefinition] | Mapping[str, AbilityDefinition] | None = None,
    ) -> None:
        values = (
            default_ability_definitions() if definitions is None else definitions
        )
        if isinstance(values, Mapping):
            values = values.values()
        normalized: dict[str, AbilityDefinition] = {}
        for definition in values:
            if not isinstance(definition, AbilityDefinition):
                raise TypeError("ability registry entries must be AbilityDefinition values")
            if definition.name in normalized:
                raise ValueError(f"duplicate ability name: {definition.name}")
            normalized[definition.name] = definition
        self._definitions = normalized

    @property
    def definitions(self) -> tuple[AbilityDefinition, ...]:
        return tuple(self._definitions[name] for name in sorted(self._definitions))

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))

    def get(self, name: str) -> AbilityDefinition | None:
        return self._definitions.get(name)

    def require(self, name: str) -> AbilityDefinition:
        definition = self.get(name)
        if definition is None:
            raise KeyError(f"unknown ability: {name}")
        return definition

    def action_definitions(self) -> tuple[ActionDefinition, ...]:
        return tuple(definition.to_action_definition() for definition in self.definitions)

    def to_context(
        self,
        state: AbilityState,
        *,
        loop: int = 0,
        mission: PublicMissionContext | None = None,
    ) -> dict[str, Any]:
        """Project only ability definitions and public readiness state."""

        if not isinstance(state, AbilityState):
            raise TypeError("state must be an AbilityState")
        if not isinstance(loop, int) or isinstance(loop, bool) or loop < 0:
            raise ValueError("loop must be a non-negative integer")
        mission_active = mission is None or not mission.terminated
        abilities = []
        for definition in self.definitions:
            remaining = state.cooldown_remaining(definition.name, loop)
            abilities.append(
                {
                    "name": definition.name,
                    "description": definition.description,
                    "schema": dict(definition.schema),
                    "energy_cost": definition.energy_cost,
                    "cooldown": definition.cooldown,
                    "cooldown_remaining": remaining,
                    "available": (
                        mission_active
                        and state.energy >= definition.energy_cost
                        and remaining == 0
                    ),
                }
            )
        return {
            "version": state.version,
            "energy": state.energy,
            "use_sequence": state.use_sequence,
            "abilities": abilities,
        }

    context = to_context


__all__ = ["AbilityRegistry"]
