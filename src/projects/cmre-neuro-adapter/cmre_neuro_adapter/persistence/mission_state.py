"""Mission snapshot serialization at the public Stage 04 visibility boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..mission.mission_state import MissionState
from ..neuro.mission_projection import project_observation
from .migrations import StateValidationError


_FIELDS = frozenset(
    {
        "blocking",
        "context",
        "economy",
        "map",
        "night",
        "no_build",
        "outcome",
        "paused",
        "phase",
        "production",
        "source_loop",
        "source_state_version",
        "tactical",
        "terminated",
        "version",
        "wave",
    }
)


def encode_mission_state(state: MissionState) -> dict[str, Any]:
    if not isinstance(state, MissionState):
        raise StateValidationError("mission state has the wrong type")
    payload = state.to_dict()
    payload["context"] = state.context.to_dict()
    _validate_payload_shape(payload)
    return payload


def decode_mission_state(payload: Mapping[str, Any]) -> MissionState:
    _validate_payload_shape(payload)
    context_payload = payload["context"]
    context = _decode_context(context_payload)
    try:
        state = MissionState.from_context(
            context,
            version=_integer(payload["version"], "mission version"),
            no_build=_boolean(payload["no_build"], "no_build"),
            paused=_boolean(payload["paused"], "paused"),
            blocking=_boolean(payload["blocking"], "blocking"),
        )
    except (TypeError, ValueError) as exc:
        raise StateValidationError(f"invalid mission state: {exc}") from exc

    expected = encode_mission_state(state)
    if dict(payload) != expected:
        raise StateValidationError(
            "mission summaries or version fields do not match the public context"
        )
    return state


def _decode_context(payload: Any):
    if not isinstance(payload, Mapping):
        raise StateValidationError("mission context must be an object")
    required = {
        "context_version",
        "map",
        "mission",
        "own_units",
        "player_id",
        "resources",
        "source_loop",
        "state_version",
        "threats",
        "visible_enemies",
    }
    missing = required - set(payload)
    if missing:
        raise StateValidationError(
            f"mission context is missing fields: {', '.join(sorted(missing))}"
        )
    mission = payload["mission"]
    if not isinstance(mission, Mapping):
        raise StateValidationError("mission context mission field must be an object")
    observation = {
        "player_id": payload["player_id"],
        "loop": payload["source_loop"],
        "mission": dict(mission),
        "resources": payload["resources"],
        "own_units": payload["own_units"],
        "visible_enemies": payload["visible_enemies"],
    }
    try:
        context = project_observation(
            observation,
            map_name=payload["map"],
            context_version=payload["context_version"],
            state_version=payload["state_version"],
        )
    except (TypeError, ValueError) as exc:
        raise StateValidationError(f"invalid public mission context: {exc}") from exc
    if context.to_dict() != dict(payload):
        raise StateValidationError("mission context contains unsupported or inconsistent fields")
    return context


def _validate_payload_shape(payload: Any) -> None:
    if not isinstance(payload, Mapping):
        raise StateValidationError("mission payload must be an object")
    keys = set(payload)
    missing = _FIELDS - keys
    if missing:
        raise StateValidationError(
            f"mission payload is missing fields: {', '.join(sorted(missing))}"
        )
    unknown = keys - _FIELDS
    if unknown:
        raise StateValidationError(
            f"mission payload has unsupported fields: {', '.join(sorted(unknown))}"
        )


def _integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise StateValidationError(f"{label} must be a non-negative integer")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise StateValidationError(f"{label} must be boolean")
    return value


__all__ = ["decode_mission_state", "encode_mission_state"]
