"""Build and parse messages at the Neuro WebSocket boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .actions import ActionDefinition, ExecutionResult
from .context import ContextEnvelope
from .errors import ContractErrorCode, ContractViolation

INCOMING_COMMANDS = {"action", "actions/reregister_all", "startup"}
PRIORITIES = {"low", "medium", "high", "critical"}


@dataclass(frozen=True)
class IncomingMessage:
    command: str
    data: Mapping[str, Any] | None


class NeuroMessageBuilder:
    """Build game-to-Neuro messages compatible with the reference project."""

    def __init__(self, game_title: str = "StarCraft 2") -> None:
        if not game_title.strip():
            raise ValueError("game_title must not be empty")
        self.game_title = game_title

    def startup(self) -> dict[str, Any]:
        return {"command": "startup", "game": self.game_title}

    def context(self, envelope: ContextEnvelope) -> dict[str, Any]:
        return {
            "command": "context",
            "game": self.game_title,
            "data": {"message": envelope.message, "silent": envelope.silent},
        }

    def actions_register(self, actions: list[ActionDefinition]) -> dict[str, Any]:
        return {
            "command": "actions/register",
            "game": self.game_title,
            "data": {"actions": [action.to_registration_dict() for action in actions]},
        }

    def actions_unregister(self, action_names: list[str]) -> dict[str, Any]:
        normalized = _non_empty_strings(action_names, "action_names")
        return {
            "command": "actions/unregister",
            "game": self.game_title,
            "data": {"action_names": normalized},
        }

    def actions_force(
        self,
        query: str,
        action_names: list[str],
        state: str | None = None,
        ephemeral_context: bool = False,
        priority: str = "low",
    ) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("force-action query must not be empty")
        if priority not in PRIORITIES:
            raise ValueError(f"invalid force-action priority: {priority}")
        data: dict[str, Any] = {
            "query": query,
            "ephemeral_context": ephemeral_context,
            "priority": priority,
            "action_names": _non_empty_strings(action_names, "action_names"),
        }
        if state is not None:
            data["state"] = state
        return {"command": "actions/force", "game": self.game_title, "data": data}

    def action_result(self, result: ExecutionResult) -> dict[str, Any]:
        data: dict[str, Any] = {"id": result.action_id, "success": result.success}
        if result.message:
            data["message"] = result.message
        return {"command": "action/result", "game": self.game_title, "data": data}


def parse_incoming_message(payload: str | Mapping[str, Any]) -> IncomingMessage:
    """Parse one Neuro-to-game message and reject malformed commands."""

    decoded: Any
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ContractViolation(
                ContractErrorCode.INVALID_JSON, "invalid Neuro message JSON"
            ) from exc
    else:
        decoded = payload

    if not isinstance(decoded, Mapping):
        raise ContractViolation(
            ContractErrorCode.INVALID_MESSAGE, "Neuro message must be an object"
        )
    command = decoded.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ContractViolation(
            ContractErrorCode.INVALID_MESSAGE,
            "Neuro message command must be a non-empty string",
        )
    if command not in INCOMING_COMMANDS:
        raise ContractViolation(
            ContractErrorCode.UNKNOWN_COMMAND, f"unknown Neuro command: {command}"
        )

    data = decoded.get("data")
    if command == "actions/reregister_all":
        if data is not None and not isinstance(data, Mapping):
            raise ContractViolation(
                ContractErrorCode.INVALID_MESSAGE,
                "reregister data must be an object when present",
            )
        return IncomingMessage(command=command, data=data)
    if not isinstance(data, Mapping):
        raise ContractViolation(
            ContractErrorCode.MISSING_DATA,
            f"Neuro command '{command}' requires an object data field",
        )
    return IncomingMessage(command=command, data=data)


def _non_empty_strings(values: list[str], field_name: str) -> list[str]:
    if not values:
        raise ValueError(f"{field_name} must not be empty")
    normalized = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must contain non-empty strings")
        normalized.append(value.strip())
    return normalized
