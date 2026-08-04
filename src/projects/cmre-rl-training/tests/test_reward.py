"""Tests for reward computation and normalization (G2)."""

from __future__ import annotations

import unittest

from cmre_rl_training.reward import RewardNormalizer, RewardTracker


def _obs(
    *,
    base_hp: float = 1500,
    supply_used: int = 5,
    enemies: list[dict] | None = None,
    workers: int = 3,
    progress: float = 0.0,
    night: int = 0,
    loop: int = 0,
    terminated: bool = False,
    end_reason: str = "",
) -> dict:
    units = [
        {"entity_id": 1, "unit_type_id": "CommandCenter", "owner": 1,
         "x": 85, "y": 94, "health": base_hp, "shields": 0, "energy": 0,
         "state": "idle", "orders": []},
    ]
    for i in range(workers):
        units.append({
            "entity_id": 10 + i, "unit_type_id": "SCV", "owner": 1,
            "x": 86, "y": 93, "health": 45, "shields": 0, "energy": 0,
            "state": "gathering", "orders": [],
        })
    return {
        "loop": loop,
        "player_id": 1,
        "own_units": units,
        "visible_enemies": enemies or [],
        "resources": {"minerals": 100, "vespene": 0,
                      "supply_used": supply_used, "supply_cap": 11},
        "mission": {
            "phase": "active", "night": night, "wave": 0,
            "terminated": terminated, "end_reason": end_reason,
            "win_condition": "survive_loops", "progress": progress,
        },
    }


class RewardTrackerTests(unittest.TestCase):
    def test_first_step_returns_zero(self) -> None:
        tracker = RewardTracker()
        reward = tracker.compute(_obs(), False)
        self.assertAlmostEqual(reward, 0.0)

    def test_base_damage_penalized(self) -> None:
        tracker = RewardTracker()
        tracker.compute(_obs(base_hp=1500), False)
        reward = tracker.compute(_obs(base_hp=1400), False)
        self.assertLess(reward, 0.0)

    def test_supply_growth_rewarded(self) -> None:
        tracker = RewardTracker()
        tracker.compute(_obs(supply_used=5), False)
        reward = tracker.compute(_obs(supply_used=8), False)
        self.assertGreater(reward, 0.0)

    def test_enemy_killed_rewarded(self) -> None:
        enemies_before = [
            {"entity_id": 100, "unit_type_id": "Zergling", "owner": 3,
             "x": 70, "y": 80, "health": 35, "shields": 0, "energy": 0,
             "state": "moving", "orders": []},
        ]
        tracker = RewardTracker()
        tracker.compute(_obs(enemies=enemies_before), False)
        reward = tracker.compute(_obs(enemies=[]), False)
        self.assertGreater(reward, 0.0)

    def test_progress_rewarded(self) -> None:
        tracker = RewardTracker()
        tracker.compute(_obs(progress=0.0), False)
        reward = tracker.compute(_obs(progress=0.5), False)
        self.assertGreater(reward, 0.0)

    def test_night_survival_bonus(self) -> None:
        tracker = RewardTracker()
        tracker.compute(_obs(night=1, loop=5), False)
        reward = tracker.compute(_obs(night=1, loop=6), False)
        self.assertGreater(reward, 0.0)

    def test_worker_growth_rewarded(self) -> None:
        tracker = RewardTracker()
        tracker.compute(_obs(workers=3), False)
        reward = tracker.compute(_obs(workers=5), False)
        self.assertGreater(reward, 0.0)

    def test_terminal_victory_bonus(self) -> None:
        tracker = RewardTracker()
        tracker.compute(_obs(loop=9), False)
        reward = tracker.compute(
            _obs(loop=10, terminated=True, end_reason="survive_loops"),
            True,
        )
        self.assertGreater(reward, 5.0)  # terminal bonus + any deltas

    def test_terminal_defeat_penalty(self) -> None:
        tracker = RewardTracker()
        tracker.compute(_obs(loop=9), False)
        reward = tracker.compute(
            _obs(loop=10, terminated=True, end_reason="base_destroyed"),
            True,
        )
        self.assertLess(reward, -5.0)

    def test_reset_clears_state(self) -> None:
        tracker = RewardTracker()
        tracker.compute(_obs(supply_used=5), False)
        tracker.compute(_obs(supply_used=10), False)
        tracker.reset()
        reward = tracker.compute(_obs(supply_used=5), False)
        self.assertAlmostEqual(reward, 0.0)


class RewardNormalizerTests(unittest.TestCase):
    def test_update_returns_normalized(self) -> None:
        norm = RewardNormalizer()
        result = norm.update(10.0)
        self.assertIsInstance(result, float)

    def test_mean_converges(self) -> None:
        norm = RewardNormalizer(alpha=0.1)
        for _ in range(100):
            norm.update(5.0)
        self.assertAlmostEqual(norm.mean, 5.0, places=1)

    def test_count_increments(self) -> None:
        norm = RewardNormalizer()
        self.assertEqual(norm.count, 0)
        norm.update(1.0)
        self.assertEqual(norm.count, 1)
        norm.update(2.0)
        self.assertEqual(norm.count, 2)

    def test_std_positive(self) -> None:
        norm = RewardNormalizer()
        norm.update(10.0)
        self.assertGreater(norm.std, 0.0)

    def test_reset_clears_stats(self) -> None:
        norm = RewardNormalizer()
        norm.update(10.0)
        norm.update(20.0)
        norm.reset()
        self.assertEqual(norm.count, 0)
        self.assertAlmostEqual(norm.mean, 0.0)


if __name__ == "__main__":
    unittest.main()
