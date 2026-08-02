"""Typed SC2 command actions shared by Neuro-facing transports.

The reference Neuro integration exposes high-level campaign actions and emits
movement/combat activity as context. CMRE needs a transport-neutral command
surface as well, so this module provides explicit routes for the simulator,
SC2 API, and input adapters without exposing arbitrary ability names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .actions import ActionCommand, ActionDefinition
from .schemas import validate_action_arguments


_BASE_PROPERTIES: dict[str, dict[str, Any]] = {
    "entity_ids": {
        "type": "array",
        "items": {"type": "integer", "minimum": 1},
        "minItems": 1,
        "maxItems": 64,
    },
    "issuer_player_id": {"type": "integer", "minimum": 1, "maximum": 15},
    "target_entity_id": {"type": "integer", "minimum": 0},
    "target_x": {"type": "number"},
    "target_y": {"type": "number"},
    "unit_type_id": {"type": "string"},
    "upgrade_id": {"type": "string"},
    "ability_id": {"type": "string"},
    "expected_state_version": {"type": "integer", "minimum": 0},
}


@dataclass(frozen=True)
class BasicActionRoute:
    """One public action mapped to a fixed simulator/SC2 command kind."""

    name: str
    command_kind: str
    description: str
    required: tuple[str, ...]

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": dict(_BASE_PROPERTIES),
            "required": list(self.required),
            "additionalProperties": False,
        }

    def definition(self) -> ActionDefinition:
        return ActionDefinition(
            name=self.name,
            description=self.description,
            schema=self.schema,
            priority="medium",
            source="cmre-basic-command",
        )

    def to_operation_args(self, arguments: Mapping[str, Any] | None) -> dict[str, Any]:
        checked = validate_action_arguments(arguments, self.schema) or {}
        result: dict[str, Any] = {
            "entity_ids": list(checked["entity_ids"]),
            "issuer_player_id": checked["issuer_player_id"],
            "kind": self.command_kind,
        }
        for key in (
            "target_entity_id",
            "target_x",
            "target_y",
            "unit_type_id",
            "ability_id",
        ):
            if key in checked:
                result[key] = checked[key]
        if "upgrade_id" in checked:
            # The simulator's RESEARCH command uses unit_type_id for the
            # upgrade identifier; the public action keeps the clearer name.
            result["unit_type_id"] = checked["upgrade_id"]
        return result


_ROUTES: tuple[BasicActionRoute, ...] = (
    BasicActionRoute(
        "move_units", "move", "Move one or more units to a map position.",
        ("entity_ids", "issuer_player_id", "target_x", "target_y"),
    ),
    BasicActionRoute(
        "stop_units", "stop", "Stop one or more units immediately.",
        ("entity_ids", "issuer_player_id"),
    ),
    BasicActionRoute(
        "hold_units", "hold_position", "Hold one or more units in place.",
        ("entity_ids", "issuer_player_id"),
    ),
    BasicActionRoute(
        "patrol_units", "patrol", "Patrol one or more units to a map position.",
        ("entity_ids", "issuer_player_id", "target_x", "target_y"),
    ),
    BasicActionRoute(
        "attack_move_units", "attack_move", "Move units while engaging enemies.",
        ("entity_ids", "issuer_player_id", "target_x", "target_y"),
    ),
    BasicActionRoute(
        "attack_units", "attack_unit", "Attack one visible unit target.",
        ("entity_ids", "issuer_player_id", "target_entity_id"),
    ),
    BasicActionRoute(
        "gather_resources", "smart", "Send workers to a mineral or gas target.",
        ("entity_ids", "issuer_player_id", "target_entity_id"),
    ),
    BasicActionRoute(
        "build_structure", "build", "Build a structure at a map position.",
        ("entity_ids", "issuer_player_id", "unit_type_id", "target_x", "target_y"),
    ),
    BasicActionRoute(
        "produce_unit", "train", "Queue a unit at a production structure.",
        ("entity_ids", "issuer_player_id", "unit_type_id"),
    ),
    BasicActionRoute(
        "research_upgrade", "research", "Research an upgrade at a facility.",
        ("entity_ids", "issuer_player_id", "upgrade_id"),
    ),
    BasicActionRoute(
        "cast_point_ability", "cast_point", "Cast an ability at a map position.",
        ("entity_ids", "issuer_player_id", "ability_id", "target_x", "target_y"),
    ),
    BasicActionRoute(
        "cast_unit_ability", "cast_unit", "Cast an ability on a unit target.",
        ("entity_ids", "issuer_player_id", "ability_id", "target_entity_id"),
    ),
    BasicActionRoute(
        "cast_no_target_ability", "cast_no_target", "Cast an ability without a target.",
        ("entity_ids", "issuer_player_id", "ability_id"),
    ),
    BasicActionRoute(
        "repair_units", "repair", "Repair an allied mechanical unit or structure.",
        ("entity_ids", "issuer_player_id", "target_entity_id"),
    ),
    BasicActionRoute(
        "morph_unit", "morph", "Morph one or more units to a declared unit type.",
        ("entity_ids", "issuer_player_id", "unit_type_id"),
    ),
    BasicActionRoute(
        "cancel_order", "cancel", "Cancel a unit or structure order.",
        ("entity_ids", "issuer_player_id"),
    ),
    BasicActionRoute(
        "load_units", "load", "Load units into a transport.",
        ("entity_ids", "issuer_player_id", "target_entity_id"),
    ),
    BasicActionRoute(
        "unload_units", "unload", "Unload units at a map position.",
        ("entity_ids", "issuer_player_id", "target_x", "target_y"),
    ),
    BasicActionRoute(
        "rally_producer", "rally", "Set a production structure rally position.",
        ("entity_ids", "issuer_player_id", "target_x", "target_y"),
    ),
)

BASIC_ACTION_ROUTES: Mapping[str, BasicActionRoute] = {
    route.name: route for route in _ROUTES
}


def basic_action_definitions() -> tuple[ActionDefinition, ...]:
    """Return deterministic action definitions for optional registration."""

    return tuple(route.definition() for route in _ROUTES)


def basic_action_operations() -> dict[str, str]:
    """Return the explicit action-to-transport operation map."""

    return {route.name: "unit.order" for route in _ROUTES}


def route_basic_action(command: ActionCommand) -> tuple[str, dict[str, Any]]:
    """Convert a basic action into the canonical ``unit.order`` payload."""

    if not isinstance(command, ActionCommand):
        raise TypeError("command must be an ActionCommand")
    route = BASIC_ACTION_ROUTES.get(command.name)
    if route is None:
        raise KeyError(f"unknown basic action: {command.name}")
    return "unit.order", route.to_operation_args(command.args)


__all__ = [
    "BASIC_ACTION_ROUTES",
    "BasicActionRoute",
    "basic_action_definitions",
    "basic_action_operations",
    "route_basic_action",
]
