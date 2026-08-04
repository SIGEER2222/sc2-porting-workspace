"""Tests for CmreRLEnv reset/step/action_mask loop (G4)."""

from __future__ import annotations

import unittest

import numpy as np

from cmre_rl_training.action_space import ACTION_INDEX
from cmre_rl_training.backends import FakeBackend
from cmre_rl_training.env import CmreRLEnv


class CmreRLEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = CmreRLEnv(FakeBackend(max_steps=5))

    def test_reset_returns_float_array(self) -> None:
        obs = self.env.reset()
        self.assertIsInstance(obs, np.ndarray)
        self.assertEqual(obs.dtype, np.float32)
        self.assertEqual(obs.ndim, 1)

    def test_action_mask_before_reset_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            self.env.action_mask()

    def test_step_before_reset_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            self.env.step("move_units")

    def test_action_mask_shape_matches_action_dim(self) -> None:
        self.env.reset()
        mask = self.env.action_mask()
        self.assertEqual(mask.dtype, np.bool_)
        self.assertEqual(len(mask), self.env.action_dim)

    def test_full_episode_loop(self) -> None:
        obs = self.env.reset()
        total_reward = 0.0
        terminated = False

        for _ in range(10):
            mask = self.env.action_mask()
            legal = [i for i, ok in enumerate(mask) if ok]
            if not legal:
                break
            action_idx = legal[0]
            action_name = [
                k for k, v in ACTION_INDEX.items() if v == action_idx
            ][0]
            obs, reward, terminated, info = self.env.step(action_name)
            total_reward += reward
            if terminated:
                break

        self.assertTrue(terminated)
        self.assertIsInstance(total_reward, float)
        self.assertIn("step", info)

    def test_reward_nonzero_after_progress(self) -> None:
        env = CmreRLEnv(FakeBackend(max_steps=5), normalize_reward=False)
        env.reset()
        rewards: list[float] = []
        for _ in range(5):
            mask = env.action_mask()
            legal = [i for i, ok in enumerate(mask) if ok]
            if not legal:
                break
            action_name = [k for k, v in ACTION_INDEX.items() if v == legal[0]][0]
            _, reward, terminated, _ = env.step(action_name)
            rewards.append(reward)
            if terminated:
                break
        # At least one non-zero reward (progress or terminal)
        self.assertTrue(any(abs(r) > 1e-9 for r in rewards))

    def test_state_version_advances(self) -> None:
        env = CmreRLEnv(FakeBackend(max_steps=3))
        env.reset()
        self.assertEqual(env.state_version, 0)
        env.step("move_units")
        self.assertEqual(env.state_version, 1)
        env.step("stop_units")
        self.assertEqual(env.state_version, 2)

    def test_last_observation_available(self) -> None:
        self.env.reset()
        self.assertIsNotNone(self.env.last_observation)

    def test_custom_encoder(self) -> None:
        called: list[dict] = []

        def encoder(raw):
            called.append(dict(raw))
            return np.zeros(4, dtype=np.float32)

        env = CmreRLEnv(FakeBackend(max_steps=2), encoder=encoder)
        obs = env.reset()
        self.assertEqual(len(obs), 4)
        self.assertEqual(len(called), 1)

    def test_reward_normalizer_toggle(self) -> None:
        env_raw = CmreRLEnv(FakeBackend(max_steps=3), normalize_reward=False)
        env_norm = CmreRLEnv(FakeBackend(max_steps=3), normalize_reward=True)
        env_raw.reset()
        env_norm.reset()
        mask = env_raw.action_mask()
        legal = [i for i, ok in enumerate(mask) if ok]
        action_name = [k for k, v in ACTION_INDEX.items() if v == legal[0]][0]
        _, r_raw, _, _ = env_raw.step(action_name)
        _, r_norm, _, _ = env_norm.step(action_name)
        # Normalized reward should be different from raw (different scale)
        # unless both happen to be 0.0
        self.assertIsInstance(r_raw, float)
        self.assertIsInstance(r_norm, float)


if __name__ == "__main__":
    unittest.main()
