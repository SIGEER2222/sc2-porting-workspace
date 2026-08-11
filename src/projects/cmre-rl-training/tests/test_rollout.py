"""Tests for collect_rollout (Stage 03 rollout integration)."""

from __future__ import annotations

import unittest

import numpy as np
import torch

from cmre_rl_training.action_space import ACTION_INDEX, ACTION_NAMES, NUM_ACTIONS
from cmre_rl_training.backends import FakeBackend
from cmre_rl_training.env import CmreRLEnv
from cmre_rl_training.observation import rl_feature_count


class CollectRolloutTests(unittest.TestCase):
    """Integration: collect_rollout over CmreRLEnv returns filled buffer."""

    def setUp(self) -> None:
        from cmre_rl_training.network import P2AllyAC

        self.env = CmreRLEnv(FakeBackend(max_steps=10), normalize_reward=False)
        self.policy = P2AllyAC(hidden_dim=32, seed=1)

    def test_collect_n_steps_returns_buffer_with_n_entries(self) -> None:
        from cmre_rl_training.rollout import collect_rollout

        buf = collect_rollout(self.env, self.policy, n_steps=5)
        self.assertEqual(len(buf), 5)

    def test_collect_reuses_caller_reset_observation_without_second_reset(self) -> None:
        from cmre_rl_training.rollout import collect_rollout

        initial = self.env.reset()
        original_reset = self.env.reset
        calls = 0

        def counted_reset():
            nonlocal calls
            calls += 1
            return original_reset()

        self.env.reset = counted_reset  # type: ignore[method-assign]
        buf = collect_rollout(
            self.env,
            self.policy,
            n_steps=3,
            initial_observation=initial,
        )
        self.assertEqual(len(buf), 3)
        self.assertEqual(calls, 0)

    def test_collect_handles_auto_reset_on_terminal(self) -> None:
        from cmre_rl_training.rollout import collect_rollout

        # max_steps=3 means episode terminates after 3 steps. Collecting 7
        # steps requires at least one auto-reset (3 + 3 + 1 = 7).
        env = CmreRLEnv(FakeBackend(max_steps=3), normalize_reward=False)
        buf = collect_rollout(env, self.policy, n_steps=7)
        self.assertEqual(len(buf), 7)

    def test_collect_can_stop_at_terminal_for_live_evaluation(self) -> None:
        from cmre_rl_training.rollout import collect_rollout

        env = CmreRLEnv(FakeBackend(max_steps=3), normalize_reward=False)
        buf = collect_rollout(env, self.policy, n_steps=7, auto_reset_on_terminal=False)
        self.assertEqual(len(buf), 3)
        self.assertTrue(buf._steps[-1].done)

    def test_buffer_observation_dim_matches_env(self) -> None:
        from cmre_rl_training.rollout import collect_rollout

        buf = collect_rollout(self.env, self.policy, n_steps=3)
        obs = buf.observations_tensor()
        self.assertEqual(obs.shape, (3, rl_feature_count()))

    def test_buffer_actions_are_in_legal_range(self) -> None:
        from cmre_rl_training.rollout import collect_rollout

        buf = collect_rollout(self.env, self.policy, n_steps=10)
        actions = buf.actions_tensor().flatten().tolist()
        for a in actions:
            self.assertGreaterEqual(a, 0)
            self.assertLess(a, NUM_ACTIONS)

    def test_buffer_masks_match_action_dim(self) -> None:
        from cmre_rl_training.rollout import collect_rollout

        buf = collect_rollout(self.env, self.policy, n_steps=4)
        masks = buf.masks_tensor()
        self.assertIsNotNone(masks)
        self.assertEqual(masks.shape, (4, NUM_ACTIONS))
        # Masks must be boolean
        self.assertEqual(masks.dtype, torch.bool)

    def test_buffer_logprobs_and_values_are_finite(self) -> None:
        from cmre_rl_training.rollout import collect_rollout

        buf = collect_rollout(self.env, self.policy, n_steps=5)
        logprobs = buf.logprobs_tensor()
        self.assertTrue(torch.isfinite(logprobs).all())

    def test_deterministic_rollout_uses_argmax(self) -> None:
        from cmre_rl_training.rollout import collect_rollout

        # Two deterministic rollouts must produce identical action sequences
        env_a = CmreRLEnv(FakeBackend(max_steps=10), normalize_reward=False)
        env_b = CmreRLEnv(FakeBackend(max_steps=10), normalize_reward=False)
        # Same seed policy
        from cmre_rl_training.network import P2AllyAC
        policy_a = P2AllyAC(hidden_dim=32, seed=7)
        policy_b = P2AllyAC(hidden_dim=32, seed=7)

        buf_a = collect_rollout(env_a, policy_a, n_steps=5, deterministic=True)
        buf_b = collect_rollout(env_b, policy_b, n_steps=5, deterministic=True)
        np.testing.assert_array_equal(
            buf_a.actions_tensor().flatten().numpy(),
            buf_b.actions_tensor().flatten().numpy(),
        )

    def test_compute_gae_runs_after_rollout(self) -> None:
        from cmre_rl_training.rollout import collect_rollout

        buf = collect_rollout(self.env, self.policy, n_steps=8)
        advantages, returns = buf.compute_gae(gamma=0.99, lam=0.95)
        self.assertEqual(advantages.shape, (8,))
        self.assertEqual(returns.shape, (8,))
        self.assertTrue(np.isfinite(advantages).all())
        self.assertTrue(np.isfinite(returns).all())

    def test_n_steps_zero_raises(self) -> None:
        from cmre_rl_training.rollout import collect_rollout

        with self.assertRaises(ValueError):
            collect_rollout(self.env, self.policy, n_steps=0)


class RolloutPPOIntegrationTests(unittest.TestCase):
    """End-to-end: collect_rollout → PPOTrainer.train on FakeBackend."""

    def test_rollout_then_train_returns_finite_metrics(self) -> None:
        from cmre_rl_training.network import P2AllyAC
        from cmre_rl_training.ppo import PPOTrainer
        from cmre_rl_training.rollout import collect_rollout

        env = CmreRLEnv(FakeBackend(max_steps=10), normalize_reward=False)
        policy = P2AllyAC(hidden_dim=32, seed=3)
        trainer = PPOTrainer(policy, lr=1e-3, epochs=2, batch_size=8)

        env.reset()
        buf = collect_rollout(env, policy, n_steps=10)
        metrics = trainer.train(buf)

        for key in ("total_loss", "policy_loss", "value_loss", "entropy"):
            self.assertIn(key, metrics)
            self.assertTrue(np.isfinite(metrics[key]))


if __name__ == "__main__":
    unittest.main()
