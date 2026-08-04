"""Tests for DomainRandomization parameter sampling (G5)."""

from __future__ import annotations

import unittest

from cmre_rl_training.domain_randomization import (
    ENEMY_DAMAGE_RANGE,
    FOG_RANGE,
    STRUCTURE_HEALTH_RANGE,
    TIME_SCALE_RANGE,
    WAVE_STRENGTH_RANGE,
    DomainRandomization,
    ScenarioParams,
)


class DomainRandomizationTests(unittest.TestCase):
    def test_sample_returns_scenario_params(self) -> None:
        dr = DomainRandomization()
        params = dr.sample()
        self.assertIsInstance(params, ScenarioParams)

    def test_wave_strength_in_range(self) -> None:
        dr = DomainRandomization()
        for _ in range(100):
            params = dr.sample()
            self.assertGreaterEqual(
                params.wave_strength_scale, WAVE_STRENGTH_RANGE[0]
            )
            self.assertLessEqual(
                params.wave_strength_scale, WAVE_STRENGTH_RANGE[1]
            )

    def test_time_scale_in_range(self) -> None:
        dr = DomainRandomization()
        for _ in range(100):
            params = dr.sample()
            self.assertGreaterEqual(params.time_scale, TIME_SCALE_RANGE[0])
            self.assertLessEqual(params.time_scale, TIME_SCALE_RANGE[1])

    def test_fog_range_in_range(self) -> None:
        dr = DomainRandomization()
        for _ in range(100):
            params = dr.sample()
            self.assertGreaterEqual(params.fog_range, FOG_RANGE[0])
            self.assertLessEqual(params.fog_range, FOG_RANGE[1])

    def test_enemy_damage_in_range(self) -> None:
        dr = DomainRandomization()
        for _ in range(100):
            params = dr.sample()
            self.assertGreaterEqual(
                params.enemy_damage_scale, ENEMY_DAMAGE_RANGE[0]
            )
            self.assertLessEqual(
                params.enemy_damage_scale, ENEMY_DAMAGE_RANGE[1]
            )

    def test_structure_health_in_range(self) -> None:
        dr = DomainRandomization()
        for _ in range(100):
            params = dr.sample()
            self.assertGreaterEqual(
                params.structure_health_scale, STRUCTURE_HEALTH_RANGE[0]
            )
            self.assertLessEqual(
                params.structure_health_scale, STRUCTURE_HEALTH_RANGE[1]
            )

    def test_seed_is_non_negative(self) -> None:
        dr = DomainRandomization()
        for _ in range(100):
            params = dr.sample()
            self.assertGreaterEqual(params.seed, 0)

    def test_deterministic_with_base_seed(self) -> None:
        dr1 = DomainRandomization(seed=42)
        dr2 = DomainRandomization(seed=42)
        for _ in range(10):
            p1 = dr1.sample()
            p2 = dr2.sample()
            self.assertEqual(p1, p2)

    def test_call_count_increments(self) -> None:
        dr = DomainRandomization()
        self.assertEqual(dr.call_count, 0)
        dr.sample()
        self.assertEqual(dr.call_count, 1)
        dr.sample()
        self.assertEqual(dr.call_count, 2)

    def test_to_dict(self) -> None:
        dr = DomainRandomization(seed=1)
        params = dr.sample()
        d = params.to_dict()
        self.assertIn("seed", d)
        self.assertIn("wave_strength_scale", d)
        self.assertIn("time_scale", d)
        self.assertIn("fog_range", d)


if __name__ == "__main__":
    unittest.main()
