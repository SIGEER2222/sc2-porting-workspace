"""Observation encoding bridging backend obs to encoder feature vector.

The ``vibe/ml/encoder.encode_observation`` expects a dict with fields:
``own_units``, ``visible_enemies``, ``visible_allies``, ``resources``,
``mission``, ``mineral_fields``, ``vespene_geysers``, ``tech``.

Backends may not produce all fields (e.g. ``SimulatorSessionBackend.observe()``
omits ``mineral_fields`` / ``tech``). This module normalizes the observation
to include all expected fields with safe defaults before encoding.
"""

from __future__ import annotations

from typing import Any, Mapping


def normalize_observation(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Ensure observation has all fields the encoder expects, with defaults."""

    return {
        "loop": int(raw.get("loop", 0)),
        "player_id": int(raw.get("player_id", 1)),
        "own_units": list(raw.get("own_units", [])),
        "visible_enemies": list(raw.get("visible_enemies", [])),
        "visible_allies": list(raw.get("visible_allies", [])),
        "resources": dict(raw.get("resources", {})),
        "mission": dict(raw.get("mission", {})),
        "mineral_fields": list(raw.get("mineral_fields", [])),
        "vespene_geysers": list(raw.get("vespene_geysers", [])),
        "tech": dict(
            raw.get("tech", {"completed_upgrades": [], "researching": []})
        ),
    }


def encode_rl_observation(
    observation: Mapping[str, Any],
    *,
    requested_mode: str = "follow",
    base_region: tuple[float, float, float] = (85.0, 94.0, 14.0),
    support_range: float = 14.0,
) -> list[float]:
    """Encode observation into a feature vector via ``vibe/ml/encoder``.

    Falls back to a minimal flat encoding if the vibe encoder is unavailable
    (e.g. when ``vibe`` is not on ``PYTHONPATH`` during Stage 01 unit tests).
    """

    normalized = normalize_observation(observation)
    try:
        from vibe.ml.encoder import (
            FEATURE_NAMES,
            encode_observation,
            feature_schema_hash,
        )

        vector = encode_observation(
            normalized, requested_mode, base_region, support_range
        )
        if len(vector) != len(FEATURE_NAMES):
            raise AssertionError(
                f"rl_observation_length_mismatch:{len(vector)}!={len(FEATURE_NAMES)}"
            )
        return vector
    except ImportError:
        return _fallback_encode(normalized)


_FALLBACK_FEATURE_NAMES: tuple[str, ...] = (
    "minerals", "vespene", "supply_used", "supply_cap",
    "own_unit_count", "enemy_count", "mission_progress", "night",
)


def _fallback_encode(obs: dict[str, Any]) -> list[float]:
    """Minimal encoding when ``vibe/ml/encoder`` is not importable."""

    resources = obs.get("resources", {})
    mission = obs.get("mission", {})
    own = obs.get("own_units", [])
    enemies = obs.get("visible_enemies", [])
    progress = float(mission.get("progress", 0.0))
    if progress > 1.0:
        progress /= 100.0
    return [
        float(resources.get("minerals", 0)) / 1000.0,
        float(resources.get("vespene", 0)) / 1000.0,
        float(resources.get("supply_used", 0)) / 100.0,
        float(resources.get("supply_cap", 0)) / 100.0,
        float(len(own)) / 50.0,
        float(len(enemies)) / 50.0,
        max(0.0, min(1.0, progress)),
        float(mission.get("night", 0)),
    ]


def rl_feature_count() -> int:
    """Return the expected feature vector length.

    Prefers ``vibe/ml/encoder.FEATURE_NAMES``; falls back to the minimal set.
    """

    try:
        from vibe.ml.encoder import FEATURE_NAMES

        return len(FEATURE_NAMES)
    except ImportError:
        return len(_FALLBACK_FEATURE_NAMES)


__all__ = [
    "normalize_observation",
    "encode_rl_observation",
    "rl_feature_count",
]
