"""Evidence records used by adapter stages and runtime gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class EvidenceType(str, Enum):
    STATIC = "static"
    SIMULATOR = "simulator"
    RUNTIME = "runtime"
    INFERENCE = "inference"


@dataclass(frozen=True)
class EvidenceRecord:
    claim: str
    evidence_type: EvidenceType
    source: str
    command: str | None = None
    passed: bool | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.claim.strip():
            raise ValueError("evidence claim must not be empty")
        if not self.source.strip():
            raise ValueError("evidence source must not be empty")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "claim": self.claim,
            "evidence_type": self.evidence_type.value,
            "source": self.source,
            "details": dict(self.details),
        }
        if self.command is not None:
            payload["command"] = self.command
        if self.passed is not None:
            payload["passed"] = self.passed
        return payload
