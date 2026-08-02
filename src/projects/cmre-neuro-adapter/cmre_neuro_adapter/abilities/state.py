"""Versioned, transport-neutral runtime state for CMRE abilities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class AbilityState:
    """State changed only by successful ability execution."""

    version: int = 1
    energy: int | float = 0
    cooldowns: tuple[tuple[str, int], ...] = ()
    use_sequence: int = 0

    def __post_init__(self) -> None:
        _non_negative_int(self.version, "version")
        _non_negative_number(self.energy, "energy")
        _non_negative_int(self.use_sequence, "use_sequence")
        raw = self.cooldowns
        if isinstance(raw, Mapping):
            items = tuple(raw.items())
        else:
            try:
                items = tuple(raw)
            except TypeError as exc:
                raise ValueError("cooldowns must be a mapping or pair sequence") from exc
        normalized: list[tuple[str, int]] = []
        for item in items:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise ValueError("cooldowns must contain name/value pairs")
            name, ready_at = item
            if not isinstance(name, str) or not name.strip():
                raise ValueError("cooldown ability names must be non-empty strings")
            _non_negative_int(ready_at, f"cooldown for {name}")
            normalized.append((name.strip(), ready_at))
        if len({name for name, _ in normalized}) != len(normalized):
            raise ValueError("cooldowns must not contain duplicate ability names")
        object.__setattr__(self, "cooldowns", tuple(sorted(normalized)))

    @classmethod
    def initial(cls, energy: int | float = 0) -> "AbilityState":
        return cls(energy=energy)

    def cooldown_until(self, ability_name: str) -> int:
        return dict(self.cooldowns).get(ability_name, 0)

    def cooldown_remaining(self, ability_name: str, loop: int) -> int:
        _non_negative_int(loop, "loop")
        return max(0, self.cooldown_until(ability_name) - loop)

    def is_ready(self, ability_name: str, loop: int) -> bool:
        return self.cooldown_remaining(ability_name, loop) == 0

    def consume(
        self,
        ability_name: str,
        *,
        energy_cost: int | float,
        ready_at_loop: int,
    ) -> "AbilityState":
        if not isinstance(ability_name, str) or not ability_name.strip():
            raise ValueError("ability name must be a non-empty string")
        _non_negative_number(energy_cost, "energy_cost")
        _non_negative_int(ready_at_loop, "ready_at_loop")
        if self.energy < energy_cost:
            raise ValueError("insufficient energy")
        cooldowns = dict(self.cooldowns)
        if ready_at_loop:
            cooldowns[ability_name.strip()] = ready_at_loop
        else:
            cooldowns.pop(ability_name.strip(), None)
        return AbilityState(
            version=self.version + 1,
            energy=self.energy - energy_cost,
            cooldowns=tuple(cooldowns.items()),
            use_sequence=self.use_sequence + 1,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "energy": self.energy,
            "cooldowns": dict(self.cooldowns),
            "use_sequence": self.use_sequence,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AbilityState":
        if not isinstance(payload, Mapping):
            raise ValueError("ability state must be an object")
        fields = {"version", "energy", "cooldowns", "use_sequence"}
        missing = fields - set(payload)
        unknown = set(payload) - fields
        if missing:
            raise ValueError(f"ability state is missing fields: {', '.join(sorted(missing))}")
        if unknown:
            raise ValueError(
                f"ability state has unsupported fields: {', '.join(sorted(unknown))}"
            )
        return cls(
            version=payload["version"],
            energy=payload["energy"],
            cooldowns=payload["cooldowns"],
            use_sequence=payload["use_sequence"],
        )

    def public_context(self, *, loop: int = 0) -> dict[str, Any]:
        return {
            "version": self.version,
            "energy": self.energy,
            "use_sequence": self.use_sequence,
            "cooldowns": dict(self.cooldowns),
            "loop": loop,
        }


AbilityRuntimeState = AbilityState


def _non_negative_int(value: Any, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")


def _non_negative_number(value: Any, label: str) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not isfinite(float(value))
        or value < 0
    ):
        raise ValueError(f"{label} must be a finite non-negative number")


__all__ = ["AbilityRuntimeState", "AbilityState"]
