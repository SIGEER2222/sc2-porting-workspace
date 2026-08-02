"""Persistence codec for the independent ability runtime domain."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..abilities.state import AbilityState
from .migrations import StateValidationError


_FIELDS = frozenset({"version", "energy", "cooldowns", "use_sequence"})


def encode_ability_state(state: AbilityState) -> dict[str, Any]:
    if not isinstance(state, AbilityState):
        raise StateValidationError("ability state has the wrong type")
    try:
        payload = state.to_dict()
        AbilityState.from_dict(payload)
    except (TypeError, ValueError) as exc:
        raise StateValidationError(f"invalid ability state: {exc}") from exc
    return payload


def decode_ability_state(payload: Mapping[str, Any]) -> AbilityState:
    if not isinstance(payload, Mapping):
        raise StateValidationError("ability payload must be an object")
    keys = set(payload)
    missing = _FIELDS - keys
    unknown = keys - _FIELDS
    if missing:
        raise StateValidationError(
            f"ability payload is missing fields: {', '.join(sorted(missing))}"
        )
    if unknown:
        raise StateValidationError(
            f"ability payload has unsupported fields: {', '.join(sorted(unknown))}"
        )
    try:
        return AbilityState.from_dict(payload)
    except (TypeError, ValueError) as exc:
        raise StateValidationError(f"invalid ability state: {exc}") from exc


__all__ = ["decode_ability_state", "encode_ability_state"]
