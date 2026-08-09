"""Reward computation from observation transitions.

Derives dense (per-step) and terminal rewards from the public mission context
without accessing hidden simulator state. All signals come from fields already
present in the observation dict: ``own_units``, ``visible_enemies``,
``resources``, ``mission``.

Reward-design contract (verified 2026-08-08)
--------------------------------------------
EVERY per-step term MUST be a function of an *action-dependent* quantity, not
of elapsed time. A previous revision weighted ``W_PROGRESS = 5.0`` (mission
progress = night-survival elapsed time) and ``W_NIGHT_SURVIVAL``. Those terms
are identical for every action inside an episode, so the per-step TD target
collapsed to ``f(loop)`` and the GAE advantage carried only the tiny
kill/army deltas -> advantage SNR ~ 0 -> PPO could not learn (trained == random
at raw_reward ~ 429). They are intentionally removed. Survival is still
rewarded emergently: a longer episode accumulates more army/kill shaping and
ends on the terminal victory/defeat credit.
"""

from __future__ import annotations

from typing import Any, Mapping

_BASE_TYPES = frozenset({"CommandCenter", "OrbitalCommand", "PlanetaryFortress"})
_WORKER_TYPES = frozenset({"SCV", "Probe", "Drone"})
_NON_COMBAT_TYPES = (
    _WORKER_TYPES
    | _BASE_TYPES
    | {
        "Barracks", "Factory", "Starport", "EngineeringBay", "Armory",
        "GhostAcademy", "FusionCore", "BarracksTechLab", "FactoryTechLab",
        "StarportTechLab", "Medivac", "Bunker", "SupplyDepot", "Refinery",
    }
)
_VICTORY_REASONS = frozenset({
    "victory", "all_objectives_success", "survive_loops", "max_loops_reached",
})

# Reward weights (tunable).
#
# All weights below are ACTION-DEPENDENT: they respond to production (supply /
# worker / army deltas), combat (enemy damage / kills / threat), base defense,
# or terminal outcome. None of them is a function of elapsed time.
#
# N5 experiment (2026-08-09), RESULT = reward lever EXHAUSTED offline:
# A hard-scenario verdict (dead-of-night-hard, start_minerals=150, 5Z2H@dist7,
# 40 iters, ent_floor 0.5) was run with W_ENEMY_KILLED raised 1.0->1.5 and
# W_ENEMY_HP_DELTA 0.02->0.05 to make *engaging+killing* dominate the gradient
# (a constant W_WORKER_PRESENCE term was tried first but REJECTED by
# test_reward.py's time-driven regression guards). Outcome: trained-stochastic
# army 1.9 / raw 7529 vs random army 2.5 / raw 8964 -> STILL below random;
# trained-greedy collapsed to army 0.0 (argmax locks a degenerate action).
# Conclusion: the offline simulator's fidelity (passive mining does NOT
# accumulate, terminal victory/defeat credit is dead because end_reason is
# always '') is the hard ceiling, NOT the reward shape. The kill-weight raise
# was reverted to baseline below (it did not help and slightly hurt). REMAINING
# path = N5b live sim2real (stage08-10 real MissionEngine issues win/lose
# terminals). These weights stay at the verified-stable baseline.
W_BASE_HP_DELTA = 0.004      # defend the base: reward recovered/kept HP
W_SUPPLY_DELTA = 0.10        # economy: bigger army cap / more units produced
W_ARMY_DELTA = 0.50          # actually training a combat unit (clear build signal)
W_ENEMY_HP_DELTA = 0.02      # damage dealt to enemies (action-driven)
W_ENEMY_KILLED = 1.0         # confirmed kill (strong, unambiguous gradient)
W_WORKER_DELTA = 0.10        # economy: more workers gathering
W_ENEMY_PRESENCE = -0.05     # threat penalty: fewer live enemies near base is better
W_ARMY_PRESENCE = 0.10       # sustained fighting force (potential-like shaping)
W_TERMINAL_VICTORY = 10.0
W_TERMINAL_DEFEAT = -10.0


class RewardTracker:
    """Track previous observation state for delta-based reward computation."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._prev_base_hp: float = 0.0
        self._prev_supply_used: int = 0
        self._prev_army_count: int = 0
        self._prev_enemy_count: int = 0
        self._prev_enemy_hp: float = 0.0
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

        bases = [u for u in own_units if str(u.get("unit_type_id", "")) in _BASE_TYPES]
        workers = [u for u in own_units if str(u.get("unit_type_id", "")) in _WORKER_TYPES]
        army = [u for u in own_units if str(u.get("unit_type_id", "")) not in _NON_COMBAT_TYPES]
        base_hp = sum(float(u.get("health", 0)) for u in bases)
        army_count = len(army)
        supply_used = int(resources.get("supply_used", 0))
        enemy_count = len(enemies)
        enemy_hp = sum(float(u.get("health", 0)) for u in enemies)
        loop = int(obs.get("loop", 0))

        if not self._initialized:
            self._prev_base_hp = base_hp
            self._prev_supply_used = supply_used
            self._prev_army_count = army_count
            self._prev_enemy_count = enemy_count
            self._prev_enemy_hp = enemy_hp
            self._prev_worker_count = len(workers)
            self._prev_loop = loop
            self._initialized = True
            return 0.0

        reward = 0.0

        # Base survival: only the HP *delta* is rewarded. A constant "alive"
        # bonus would be identical for every action and carry no gradient; the
        # raw fixed-point HP value (~1.5M * 1e-4) also produced a ~153.0
        # constant per step that zeroed the policy gradient entirely.
        base_hp_delta = base_hp - self._prev_base_hp
        reward += base_hp_delta * W_BASE_HP_DELTA

        # Economic growth: reward supply and worker increases (production).
        supply_delta = supply_used - self._prev_supply_used
        reward += supply_delta * W_SUPPLY_DELTA

        # Army growth: reward actually training combat units.
        army_delta = army_count - self._prev_army_count
        if army_delta > 0:
            reward += army_delta * W_ARMY_DELTA

        # Combat: damage and kills.
        enemy_hp_delta = self._prev_enemy_hp - enemy_hp
        reward += enemy_hp_delta * W_ENEMY_HP_DELTA
        enemy_count_delta = self._prev_enemy_count - enemy_count
        if enemy_count_delta > 0:
            reward += enemy_count_delta * W_ENEMY_KILLED

        # Worker growth.
        worker_delta = len(workers) - self._prev_worker_count
        reward += worker_delta * W_WORKER_DELTA

        # Dense state shaping (policy-controllable): a larger own army and fewer
        # visible enemies are continuously rewarded, pulling the policy toward
        # "build and keep a fighting force". Unlike a constant base-alive
        # bonus, these terms *change* with the policy's own choices, so they
        # carry a real, dense gradient.
        reward += W_ENEMY_PRESENCE * enemy_count
        reward += W_ARMY_PRESENCE * army_count

        # Terminal reward.
        if terminated:
            mission = dict(obs.get("mission", {}))
            end_reason = str(mission.get("end_reason", ""))
            if end_reason in _VICTORY_REASONS:
                reward += W_TERMINAL_VICTORY
            else:
                reward += W_TERMINAL_DEFEAT

        # Update previous state.
        self._prev_base_hp = base_hp
        self._prev_supply_used = supply_used
        self._prev_army_count = army_count
        self._prev_enemy_count = enemy_count
        self._prev_enemy_hp = enemy_hp
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
