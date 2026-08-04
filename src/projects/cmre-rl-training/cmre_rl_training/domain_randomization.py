"""Domain Randomization for sim2real transfer.

Randomizes simulator parameters per episode to reduce the sim-to-real gap.
Each parameter controls a different aspect of scenario difficulty or timing.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class ScenarioParams:
    """Randomized parameters for one episode."""

    seed: int
    wave_strength_scale: float
    time_scale: float
    fog_range: float
    enemy_damage_scale: float
    structure_health_scale: float

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "wave_strength_scale": self.wave_strength_scale,
            "time_scale": self.time_scale,
            "fog_range": self.fog_range,
            "enemy_damage_scale": self.enemy_damage_scale,
            "structure_health_scale": self.structure_health_scale,
        }


# Default ranges (tunable)
SEED_RANGE = (0, 999_999)
WAVE_STRENGTH_RANGE = (0.8, 1.2)
TIME_SCALE_RANGE = (0.8, 1.2)
FOG_RANGE = (10.0, 20.0)
ENEMY_DAMAGE_RANGE = (0.7, 1.0)
STRUCTURE_HEALTH_RANGE = (0.5, 1.0)


class DomainRandomization:
    """Sample randomized scenario parameters per episode.

    Parameters
    ----------
    seed
        Optional base seed for reproducibility. If provided, each call to
        ``sample()`` produces deterministic results given the same call count.
    """

    def __init__(
        self,
        *,
        seed: int | None = None,
        wave_strength_range: tuple[float, float] = WAVE_STRENGTH_RANGE,
        time_scale_range: tuple[float, float] = TIME_SCALE_RANGE,
        fog_range: tuple[float, float] = FOG_RANGE,
        enemy_damage_range: tuple[float, float] = ENEMY_DAMAGE_RANGE,
        structure_health_range: tuple[float, float] = STRUCTURE_HEALTH_RANGE,
    ) -> None:
        self._rng = random.Random(seed)
        self._seed_base = seed
        self._call_count = 0
        self._wave_strength_range = wave_strength_range
        self._time_scale_range = time_scale_range
        self._fog_range = fog_range
        self._enemy_damage_range = enemy_damage_range
        self._structure_health_range = structure_health_range

    def sample(self) -> ScenarioParams:
        """Sample one set of randomized parameters."""

        self._call_count += 1
        if self._seed_base is not None:
            ep_seed = self._seed_base * 1000 + self._call_count
        else:
            ep_seed = self._rng.randint(*SEED_RANGE)

        return ScenarioParams(
            seed=ep_seed,
            wave_strength_scale=round(
                self._rng.uniform(*self._wave_strength_range), 4
            ),
            time_scale=round(
                self._rng.uniform(*self._time_scale_range), 4
            ),
            fog_range=round(
                self._rng.uniform(*self._fog_range), 2
            ),
            enemy_damage_scale=round(
                self._rng.uniform(*self._enemy_damage_range), 4
            ),
            structure_health_scale=round(
                self._rng.uniform(*self._structure_health_range), 4
            ),
        )

    @property
    def call_count(self) -> int:
        return self._call_count


__all__ = ["DomainRandomization", "ScenarioParams"]
