"""Pure ability requirement checks and deterministic effect requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..neuro.actions import ActionCommand
from ..neuro.mission_projection import PublicMissionContext
from ..neuro.schemas import SchemaValidationError, validate_action_arguments
from .definitions import AbilityDefinition
from .registry import AbilityRegistry
from .state import AbilityState


@dataclass(frozen=True)
class AbilityEffectRequest:
    """A simulator-owned effect request with deterministic correlation data."""

    ability_name: str
    operation: str
    arguments: Mapping[str, Any]
    sequence: int
    source_loop: int

    @property
    def ability_id(self) -> str:
        return self.ability_name

    @property
    def args(self) -> Mapping[str, Any]:
        return self.arguments

    def to_dict(self) -> dict[str, Any]:
        return {
            "ability": self.ability_name,
            "operation": self.operation,
            "arguments": dict(self.arguments),
            "sequence": self.sequence,
            "source_loop": self.source_loop,
        }


@dataclass(frozen=True)
class AbilityResult:
    """Result of a pure ability validation/execution decision."""

    ability_name: str
    success: bool
    code: str
    message: str
    state: AbilityState
    effect: AbilityEffectRequest | None = None
    action_id: str | None = None
    source_loop: int | None = None

    @property
    def ability_id(self) -> str:
        return self.ability_name

    @property
    def error_code(self) -> str:
        return self.code

    @property
    def effect_request(self) -> AbilityEffectRequest | None:
        return self.effect

    @property
    def next_state(self) -> AbilityState:
        return self.state

    @property
    def operation(self) -> str:
        return self.effect.operation if self.effect is not None else "ability.rejected"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ability": self.ability_name,
            "success": self.success,
            "code": self.code,
            "message": self.message,
            "state": self.state.to_dict(),
            "effect": None if self.effect is None else self.effect.to_dict(),
            "action_id": self.action_id,
            "source_loop": self.source_loop,
        }


class AbilityExecutor:
    """Evaluate abilities without mutating mission context or simulator state."""

    def __init__(self, registry: AbilityRegistry | None = None) -> None:
        self.registry = registry or AbilityRegistry()

    def execute(
        self,
        ability: str | AbilityDefinition | ActionCommand | None = None,
        arguments: Mapping[str, Any] | None = None,
        context: PublicMissionContext | None = None,
        state: AbilityState | None = None,
        *,
        loop: int | None = None,
        ability_name: str | None = None,
    ) -> AbilityResult:
        if ability is None:
            ability = ability_name
        elif ability_name is not None:
            raise TypeError("provide either ability or ability_name, not both")
        action_id: str | None = None
        if isinstance(ability, ActionCommand):
            action_id = ability.action_id
            name = ability.name
            if arguments is None:
                arguments = ability.args
        elif isinstance(ability, AbilityDefinition):
            name = ability.name
        else:
            name = ability
        if not isinstance(name, str) or not name.strip():
            raise ValueError("ability name must be a non-empty string")
        if not isinstance(context, PublicMissionContext):
            raise TypeError("context must be a PublicMissionContext")
        current_state = state or AbilityState()
        if not isinstance(current_state, AbilityState):
            raise TypeError("state must be an AbilityState")
        current_loop = context.source_loop if loop is None else loop
        if not isinstance(current_loop, int) or isinstance(current_loop, bool) or current_loop < 0:
            raise ValueError("loop must be a non-negative integer")

        definition = self.registry.get(name.strip())
        if definition is None:
            return self._failure(
                name.strip(), current_state, "unknown_ability", "unknown ability", action_id, current_loop
            )

        normalized = _normalize_arguments(definition, arguments)
        try:
            checked = validate_action_arguments(normalized, definition.schema)
        except SchemaValidationError as exc:
            return self._failure(
                definition.name,
                current_state,
                "invalid_arguments",
                str(exc),
                action_id,
                current_loop,
            )
        args = checked or {}

        if context.terminated or context.phase in {"victory", "defeat", "failure"}:
            return self._failure(
                definition.name,
                current_state,
                "mission_ended",
                "mission is not active",
                action_id,
                current_loop,
            )
        if current_state.energy < definition.energy_cost:
            return self._failure(
                definition.name,
                current_state,
                "insufficient_energy",
                "insufficient ability energy",
                action_id,
                current_loop,
            )
        remaining = current_state.cooldown_remaining(definition.name, current_loop)
        if remaining:
            return self._failure(
                definition.name,
                current_state,
                "cooldown_active",
                f"ability cooldown active for {remaining} loop(s)",
                action_id,
                current_loop,
            )

        if definition.name == "nuke_visible_target":
            target_id = args["target_entity_id"]
            visible = any(
                unit.entity_id == target_id
                and unit.owner != context.player_id
                and unit.state != "dead"
                for unit in context.visible_enemies
            )
            if not visible:
                return self._failure(
                    definition.name,
                    current_state,
                    "target_not_visible",
                    f"target entity {target_id} is not currently visible",
                    action_id,
                    current_loop,
                )

        next_state = current_state.consume(
            definition.name,
            energy_cost=definition.energy_cost,
            ready_at_loop=current_loop + definition.cooldown,
        )
        effect = AbilityEffectRequest(
            ability_name=definition.name,
            operation=definition.effect_operation,
            arguments=dict(args),
            sequence=next_state.use_sequence,
            source_loop=current_loop,
        )
        return AbilityResult(
            ability_name=definition.name,
            success=True,
            code="accepted",
            message="ability effect request created",
            state=next_state,
            effect=effect,
            action_id=action_id,
            source_loop=current_loop,
        )

    def _failure(
        self,
        name: str,
        state: AbilityState,
        code: str,
        message: str,
        action_id: str | None,
        loop: int,
    ) -> AbilityResult:
        return AbilityResult(
            ability_name=name,
            success=False,
            code=code,
            message=message,
            state=state,
            action_id=action_id,
            source_loop=loop,
        )


def _normalize_arguments(
    definition: AbilityDefinition,
    arguments: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    if arguments is None:
        return {}
    if not isinstance(arguments, Mapping):
        return arguments  # type: ignore[return-value]
    normalized = dict(arguments)
    if (
        definition.name == "nuke_visible_target"
        and "target_entity_id" not in normalized
        and "target_id" in normalized
    ):
        normalized["target_entity_id"] = normalized.pop("target_id")
    return normalized


__all__ = ["AbilityEffectRequest", "AbilityExecutor", "AbilityResult"]
