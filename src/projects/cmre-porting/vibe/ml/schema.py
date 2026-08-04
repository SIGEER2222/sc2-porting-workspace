"""Stable labels and wire shape for P2 model decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


HEAD_LABELS: dict[str, tuple[str, ...]] = {
    "economy": (
        "gather_minerals", "gather_gas", "train_worker", "build_supply",
        "maintain_economy",
    ),
    "production": (
        "no_op", "build_refinery", "build_barracks", "build_factory",
        "train_marine", "train_marauder", "research_upgrade",
    ),
    "tactical": (
        "follow", "regroup", "defend_base", "assist_attack", "retreat", "hold",
    ),
    "command": (
        "none", "follow", "regroup", "defend_base", "assist_attack", "retreat", "hold",
    ),
}


@dataclass(frozen=True)
class P2Intent:
    """A model decision before map-specific ability resolution.

    The intent deliberately carries no Galaxy ability ID. The runtime adapter
    resolves that ID from the current map/catalog after validating ownership,
    alliance, visibility, and the observation version.
    """

    schema: str
    decision_id: str
    observation_version: int
    issuer_player_id: int
    economy: str
    production: str
    tactical: str
    command: str
    confidence: float
    probabilities: dict[str, dict[str, float]] = field(default_factory=dict)
    target_entity_id: int = 0
    target_x: float = 0.0
    target_y: float = 0.0

    def __post_init__(self) -> None:
        if int(self.issuer_player_id) != 2:
            raise ValueError("p2_intent_issuer_must_be_2")
        for head, label in (
            ("economy", self.economy), ("production", self.production),
            ("tactical", self.tactical), ("command", self.command),
        ):
            if label not in HEAD_LABELS[head]:
                raise ValueError(f"unknown_{head}_label:{label}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("intent_confidence_out_of_range")

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "decision_id": self.decision_id,
            "observation_version": int(self.observation_version),
            "issuer_player_id": int(self.issuer_player_id),
            "economy": self.economy,
            "production": self.production,
            "tactical": self.tactical,
            "command": self.command,
            "confidence": float(self.confidence),
            "probabilities": {
                str(head): {str(label): float(value) for label, value in values.items()}
                for head, values in self.probabilities.items()
            },
            "target_entity_id": int(self.target_entity_id),
            "target_x": float(self.target_x),
            "target_y": float(self.target_y),
        }

    @classmethod
    def from_dict(cls, payload: Mapping) -> "P2Intent":
        return cls(
            schema=str(payload["schema"]),
            decision_id=str(payload["decision_id"]),
            observation_version=int(payload["observation_version"]),
            issuer_player_id=int(payload["issuer_player_id"]),
            economy=str(payload["economy"]),
            production=str(payload["production"]),
            tactical=str(payload["tactical"]),
            command=str(payload["command"]),
            confidence=float(payload["confidence"]),
            probabilities={
                str(head): {str(label): float(value) for label, value in values.items()}
                for head, values in dict(payload.get("probabilities", {})).items()
            },
            target_entity_id=int(payload.get("target_entity_id", 0)),
            target_x=float(payload.get("target_x", 0.0)),
            target_y=float(payload.get("target_y", 0.0)),
        )
