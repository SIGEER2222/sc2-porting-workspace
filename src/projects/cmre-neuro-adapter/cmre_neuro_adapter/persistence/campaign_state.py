"""Campaign state serialization for the independent campaign domain."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..mission.mission_state import CampaignState
from .migrations import StateValidationError


_FIELDS = frozenset({"id", "version"})


def encode_campaign_state(state: CampaignState) -> dict[str, Any]:
    if not isinstance(state, CampaignState):
        raise StateValidationError("campaign state has the wrong type")
    if not isinstance(state.campaign_id, str) or not state.campaign_id.strip():
        raise StateValidationError("campaign id must be a non-empty string")
    _version(state.version, "campaign version")
    return {"id": state.campaign_id, "version": state.version}


def decode_campaign_state(payload: Mapping[str, Any]) -> CampaignState:
    _check_fields(payload, "campaign")
    campaign_id = payload["id"]
    version = payload["version"]
    if not isinstance(campaign_id, str) or not campaign_id.strip():
        raise StateValidationError("campaign id must be a non-empty string")
    _version(version, "campaign version")
    return CampaignState(campaign_id, version)


def _check_fields(payload: Any, domain: str) -> None:
    if not isinstance(payload, Mapping):
        raise StateValidationError(f"{domain} payload must be an object")
    keys = set(payload)
    missing = _FIELDS - keys
    if missing:
        raise StateValidationError(
            f"{domain} payload is missing fields: {', '.join(sorted(missing))}"
        )
    unknown = keys - _FIELDS
    if unknown:
        raise StateValidationError(
            f"{domain} payload has unsupported fields: {', '.join(sorted(unknown))}"
        )


def _version(value: Any, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise StateValidationError(f"{label} must be a non-negative integer")


__all__ = ["decode_campaign_state", "encode_campaign_state"]
