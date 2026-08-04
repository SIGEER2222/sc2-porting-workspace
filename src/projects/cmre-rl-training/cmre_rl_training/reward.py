"""Reward computation from observation transitions.

Derives dense (per-step) and terminal rewards from the public mission context
without accessing hidden simulator state. All signals come from fields already
present in the observation dict: ``own_units``, ``visible_enemies``,
``resources``, ``mission``.
"""

from __future__ import annotations

from typing import Any, Mapping

_BASE_TYPES = frozenset({"CommandCenter", "OrbitalCommand", "PlanetaryFortress"})
_WORKER_TYPES = frozenset({"SCV", "Probe", "Drone"})
_VICTORY_REASONS = frozenset({
    "victory", "all_objectives_success", "survive_loops", "max_loops_reached",
})

# Reward weights (tunable)
W_BASE_HP_DELTA = 0.01
W_BASE_HP_ALIVE = 0.0001
W_SUPPLY_DELTA = 0.05
W_ENEMY_HP_DELTA = 0.002
W_ENEMY_KILLED = 0.1
W_PROGRESS = 5.0
W_NIGHT_SURVIVAL = 0.01
W_WORKER_DELTA = 0.02
W_TERMINAL_VICTORY = 10.0
W_TERMINAL_DEFEAT = -10.0


class RewardTracker:
    """Track previous observation state for delta-based reward computation."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._prev_base_hp: float = 0.0
        self._prev_supply_used: int = 0
        self._prev_enemy_count: int = 0
        self._prev_enemy_hp: float = 0.0
        self._prev_progress: float = 0.0
        self._prev_night: int = 0
        self._prev_worker_count: int = 0
        self._prev_loop: int = 0
        self._initialized: bool = False

    def compute(
        self,
        obs: Mapping[str, Any],
        terminated: bool,
        info: Mapping[str, Any] | None = None,
        prev_obs: Mapping[str, Any] | None = None,
    ) -> float:
        """Compute reward from observation transition.

        On the first call after ``reset()``, returns 0.0 and initializes state.
        """

        own_units = list(obs.get("own_units", []))
        enemies = list(obs.get("visible_enemies", []))
        resources = dict(obs.get("resources", {}))
        mission = dict(obs.get("mission", {}))

        bases = [u for u in own_units if str(u.get("unit_type_id", "")) in _BASE_TYPES]
        workers = [u for u in own_units if str(u.get("unit_type_id", "")) in _WORKER_TYPES]
        base_hp = sum(float(u.get("health", 0)) for u in bases)
        supply_used = int(resources.get("supply_used", 0))
        enemy_count = len(enemies)
        enemy_hp = sum(float(u.get("health", 0)) for u in enemies)
        progress = float(mission.get("progress", 0.0))
        if progress > 1.0:
            progress /= 100.0
        night = int(mission.get("night", 0))
        loop = int(obs.get("loop", 0))

        if not self._initialized:
            self._prev_base_hp = base_hp
            self._prev_supply_used = supply_used
            self._prev_enemy_count = enemy_count
            self._prev_enemy_hp = enemy_hp
            self._prev_progress = progress
            self._prev_night = night
            self._prev_worker_count = len(workers)
            self._prev_loop = loop
            self._initialized = True
            return 0.0

        reward = 0.0

        # Base survival: penalize HP loss, small bonus for keeping base alive
        base_hp_delta = base_hp - self._prev_base_hp
        reward += base_hp_delta * W_BASE_HP_DELTA
        reward += base_hp * W_BASE_HP_ALIVE

        # Economic growth: reward supply increase
        supply_delta = supply_used - self._prev_supply_used
        reward += supply_delta * W_SUPPLY_DELTA

        # Enemy killed: reward damage and kills
        enemy_hp_delta = self._prev_enemy_hp - enemy_hp
        reward += enemy_hp_delta * W_ENEMY_HP_DELTA
        enemy_count_delta = self._prev_enemy_count - enemy_count
        if enemy_count_delta > 0:
            reward += enemy_count_delta * W_ENEMY_KILLED

        # Mission progress
        progress_delta = progress - self._prev_progress
        reward += progress_delta * W_PROGRESS

        # Night survival bonus
        if night > 0 and night == self._prev_night:
            reward += W_NIGHT_SURVIVAL

        # Worker growth
        worker_delta = len(workers) - self._prev_worker_count
        reward += worker_delta * W_WORKER_DELTA

        # Terminal reward
        if terminated:
            end_reason = str(mission.get("end_reason", ""))
            if end_reason in _VICTORY_REASONS:
                reward += W_TERMINAL_VICTORY
            else:
                reward += W_TERMINAL_DEFEAT

        # Update previous state
        self._prev_base_hp = base_hp
        self._prev_supply_used = supply_used
        self._prev_enemy_count = enemy_count
        self._prev_enemy_hp = enemy_hp
        self._prev_progress = progress
        self._prev_night = night
        self._prev_worker_count = len(workers)
        self._prev_loop = loop

        return reward


class RewardNormalizer:
    """Running mean/std normalization for reward shaping.

    Uses exponential moving average to track reward statistics online.
    """

    def __init__(self, alpha: float = 0.001) -> None:
        self._alpha = float(alpha)
        self._mean: float = 0.0
        self._var: float = 1.0
        self._count: int = 0

    @property
    def mean(self) -> float:
        return self._mean

    @property
    def std(self) -> float:
        return max(1e-6, self._var ** 0.5)

    @property
    def count(self) -> int:
        return self._count

    def update(self, reward: float) -> float:
        """Normalize a reward value and update running statistics."""
        self._count += 1
        delta = reward - self._mean
        self._mean += self._alpha * delta
        self._var = (1 - self._alpha) * self._var + self._alpha * delta * delta
        return (reward - self._mean) / self.std

    def reset(self) -> None:
        self._mean = 0.0
        self._var = 1.0
        self._count = 0


__all__ = ["RewardTracker", "RewardNormalizer"]
