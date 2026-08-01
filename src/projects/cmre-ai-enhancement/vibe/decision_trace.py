"""Stable, JSON-friendly decision trace output."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Iterable

from .decision_contracts import DecisionFrame


class DecisionTrace:
    def __init__(self) -> None:
        self.frames: list[DecisionFrame] = []

    def append(self, frame: DecisionFrame) -> None:
        self.frames.append(frame)

    def to_records(self) -> list[dict]:
        return [asdict(frame) for frame in self.frames]

    def digest(self) -> str:
        payload = json.dumps(
            self.to_records(), sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_jsonl(self) -> str:
        return "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
            + "\n"
            for record in self.to_records()
        )

    def extend(self, frames: Iterable[DecisionFrame]) -> None:
        self.frames.extend(frames)
