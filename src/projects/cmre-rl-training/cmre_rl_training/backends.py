"""RL backend protocol and fake backend for offline testing.

The ``RlBackend`` protocol is the minimal surface that ``CmreRLEnv`` requires.
``FakeBackend`` provides a deterministic, dependency-free implementation for
Stage 01 unit tests — no SC2 executable or simulator needed.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable


@runtime_checkable
class RlBackend(Protocol):
    """Minimal backend surface required by ``CmreRLEnv``.

    Backends return a raw observation dict (not ``PublicMissionContext``) so
    that fields like ``mineral_fields`` and ``tech`` survive for the encoder.
    """

    @property
    def state_version(self) -> int:
        ...

    def reset(self) -> Mapping[str, Any]:
        ...

    def step(
        self, action_id: str, args: Mapping[str, Any]
    ) -> tuple[Mapping[str, Any], bool, dict[str, Any]]:
        ...


class FakeBackend:
    """Deterministic fake backend for Stage 01 unit tests.

    Simulates a coop PvE scenario with a Command Center, SCV, and Marine.
    Minerals accumulate passively; enemies appear after step 2; the scenario
    terminates at ``max_steps`` with a victory end_reason.
    """

    def __init__(self, *, max_steps: int = 10) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be >= 1")
        self._max_steps = max_steps
        self._step_count = 0
        self._minerals = 100
        self._units: list[dict[str, Any]] = []
        self._enemies: list[dict[str, Any]] = []
        self._base_hp = 1500

    @property
    def state_version(self) -> int:
        return self._step_count

    def reset(self) -> dict[str, Any]:
        self._step_count = 0
        self._minerals = 100
        self._base_hp = 1500
        self._units = [
            {
                "entity_id": 1,
                "unit_type_id": "CommandCenter",
                "owner": 1,
                "x": 85, "y": 94,
                "health": 1500, "shields": 0, "energy": 0,
                "state": "idle", "orders": [],
            },
            {
                "entity_id": 2,
                "unit_type_id": "SCV",
                "owner": 1,
                "x": 86, "y": 93,
                "health": 45, "shields": 0, "energy": 0,
                "state": "gathering",
                "orders": [{"kind": "gather", "target_entity_id": 200}],
            },
            {
                "entity_id": 3,
                "unit_type_id": "Marine",
                "owner": 1,
                "x": 87, "y": 92,
                "health": 45, "shields": 0, "energy": 0,
                "state": "idle", "orders": [],
            },
        ]
        self._enemies = []
        return self._observation()

    def step(
        self, action_id: str, args: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool, dict[str, Any]]:
        self._step_count += 1
        self._minerals += 12  # passive income per step

        # Enemies appear after step 2
        if self._step_count == 3:
            self._enemies = [
                {
                    "entity_id": 100,
                    "unit_type_id": "Zergling",
                    "owner": 3,
                    "x": 70, "y": 80,
                    "health": 35, "shields": 0, "energy": 0,
                    "state": "moving", "orders": [{"kind": "attack_move"}],
                },
            ]

        # Simulate enemy attacks on base at step 5
        if self._step_count == 5 and self._enemies:
            self._base_hp = max(0, self._base_hp - 50)
            for unit in self._units:
                if unit["unit_type_id"] == "CommandCenter":
                    unit["health"] = self._base_hp

        # Simulate killing enemy at step 7
        if self._step_count == 7:
            self._enemies = []

        # Add a Marine at step 4 (production)
        if self._step_count == 4 and len(self._units) < 4:
            self._units.append({
                "entity_id": 4,
                "unit_type_id": "Marine",
                "owner": 1,
                "x": 88, "y": 91,
                "health": 45, "shields": 0, "energy": 0,
                "state": "idle", "orders": [],
            })

        terminated = self._step_count >= self._max_steps
        info: dict[str, Any] = {
            "action_id": action_id,
            "step": self._step_count,
            "dispatched_success": True,
        }
        return self._observation(), terminated, info

    def _observation(self) -> dict[str, Any]:
        return {
            "loop": self._step_count,
            "player_id": 1,
            "own_units": [dict(u) for u in self._units],
            "visible_enemies": [dict(e) for e in self._enemies],
            "visible_allies": [],
            "resources": {
                "minerals": self._minerals,
                "vespene": 0,
                "supply_used": 4 + (1 if self._step_count >= 4 else 0),
                "supply_cap": 11,
                "state_version": self._step_count,
            },
            "mission": {
                "phase": "victory" if self._step_count >= self._max_steps else "active",
                "night": 0 if self._step_count < 5 else 1,
                "wave": 0 if self._step_count < 3 else 1,
                "terminated": self._step_count >= self._max_steps,
                "end_reason": (
                    "survive_loops"
                    if self._step_count >= self._max_steps
                    else ""
                ),
                "win_condition": "survive_loops",
                "progress": self._step_count / self._max_steps,
                "state_version": self._step_count,
            },
            "mineral_fields": [
                {"entity_id": 200, "x": 80, "y": 90},
            ],
            "vespene_geysers": [
                {"entity_id": 201, "x": 82, "y": 88},
            ],
            "tech": {
                "completed_upgrades": [],
                "researching": [],
            },
        }


__all__ = ["RlBackend", "FakeBackend"]
