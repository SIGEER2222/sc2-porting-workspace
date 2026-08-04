"""Tests for RolloutBuffer + GAE + PPOTrainer (Stage 03 G3, G4)."""

from __future__ import annotations

import unittest
from typing import Any, Mapping

import numpy as np
import torch

from cmre_rl_training.action_space import NUM_ACTIONS
from cmre_rl_training.observation import rl_feature_count


class RolloutBufferGAETests(unittest.TestCase):
    """G3-gae: GAE advantage computation with lambda=0.95."""

    def _buffer(self, n: int = 5):
        from cmre_rl_training.ppo import RolloutBuffer

        feature_dim = rl_feature_count()
        buf = RolloutBuffer(capacity=n, obs_dim=feature_dim, action_dim=1)
        return buf

    def test_store_increments_length(self) -> None:
        buf = self._buffer(3)
        self.assertEqual(len(buf), 0)
        buf.store(
            obs=np.zeros(rl_feature_count(), dtype=np.float32),
            action=np.array([0], dtype=np.int64),
            logprob=np.array(0.0, dtype=np.float32),
            value=np.array(0.0, dtype=np.float32),
            reward=1.0,
            done=False,
            mask=np.ones(NUM_ACTIONS, dtype=bool),
        )
        self.assertEqual(len(buf), 1)

    def test_compute_gae_simple_terminal_sequence(self) -> None:
        # Rewards [1, 1, 1, 1, 1], values 0, all not-terminal except last.
        # gamma=1, lambda=1 → A_t = sum_{k>=t} r_k
        # With lambda=1, gamma=1: A_t = r_t + A_{t+1}
        # So A_4 = r_4 = 1, A_3 = r_3 + A_4 = 2, ..., A_0 = 5.
        # Returns = A + V = A + 0 = A.
        buf = self._buffer(5)
        feature_dim = rl_feature_count()
        for _ in range(4):
            buf.store(
                obs=np.zeros(feature_dim, dtype=np.float32),
                action=np.array([0], dtype=np.int64),
                logprob=np.array(0.0, dtype=np.float32),
                value=np.array(0.0, dtype=np.float32),
                reward=1.0,
                done=False,
                mask=np.ones(NUM_ACTIONS, dtype=bool),
            )
        buf.store(
            obs=np.zeros(feature_dim, dtype=np.float32),
            action=np.array([0], dtype=np.int64),
            logprob=np.array(0.0, dtype=np.float32),
            value=np.array(0.0, dtype=np.float32),
            reward=1.0,
            done=True,
            mask=np.ones(NUM_ACTIONS, dtype=bool),
        )
        advantages, returns = buf.compute_gae(gamma=1.0, lam=1.0, normalize=False)
        self.assertEqual(advantages.shape, (5,))
        self.assertEqual(returns.shape, (5,))
        # A_0 = 5, A_1 = 4, ..., A_4 = 1
        np.testing.assert_allclose(advantages.tolist(), [5.0, 4.0, 3.0, 2.0, 1.0], rtol=1e-5)
        np.testing.assert_allclose(returns.tolist(), [5.0, 4.0, 3.0, 2.0, 1.0], rtol=1e-5)

    def test_compute_gae_lambda_zero_equals_td_error(self) -> None:
        # lambda=0 → A_t = r_t + gamma * V_{t+1} * (1 - done) - V_t
        buf = self._buffer(3)
        feature_dim = rl_feature_count()
        rewards = [1.0, 2.0, 3.0]
        values = [0.5, 1.0, 2.0]
        for i in range(3):
            buf.store(
                obs=np.zeros(feature_dim, dtype=np.float32),
                action=np.array([0], dtype=np.int64),
                logprob=np.array(0.0, dtype=np.float32),
                value=np.array(values[i], dtype=np.float32),
                reward=rewards[i],
                done=(i == 2),
                mask=np.ones(NUM_ACTIONS, dtype=bool),
            )
        advantages, returns = buf.compute_gae(gamma=0.99, lam=0.0, normalize=False)
        # A_2 = r_2 - V_2 = 3 - 2 = 1
        # A_1 = r_1 + 0.99 * V_2 - V_1 = 2 + 0.99*2 - 1 = 2.98
        # A_0 = r_0 + 0.99 * V_1 - V_0 = 1 + 0.99*1 - 0.5 = 1.49
        expected_adv = [1.49, 2.98, 1.0]
        np.testing.assert_allclose(advantages.tolist(), expected_adv, rtol=1e-5)
        # Returns = A + V
        expected_ret = [a + v for a, v in zip(expected_adv, values)]
        np.testing.assert_allclose(returns.tolist(), expected_ret, rtol=1e-5)

    def test_compute_gae_lambda_0_95_blends_td_and_mc(self) -> None:
        # lambda=0.95 → A_t = delta_t + gamma*lambda*(1-done)*A_{t+1}
        # Where delta_t = r_t + gamma*V_{t+1}*(1-done) - V_t
        buf = self._buffer(3)
        feature_dim = rl_feature_count()
        rewards = [1.0, 1.0, 1.0]
        values = [0.5, 0.5, 0.5]
        for i in range(3):
            buf.store(
                obs=np.zeros(feature_dim, dtype=np.float32),
                action=np.array([0], dtype=np.int64),
                logprob=np.array(0.0, dtype=np.float32),
                value=np.array(values[i], dtype=np.float32),
                reward=rewards[i],
                done=(i == 2),
                mask=np.ones(NUM_ACTIONS, dtype=bool),
            )
        gamma, lam = 0.99, 0.95
        advantages, returns = buf.compute_gae(gamma=gamma, lam=lam, normalize=False)
        # Manual:
        # delta_2 = 1 + 0 - 0.5 = 0.5, A_2 = 0.5
        # delta_1 = 1 + 0.99*0.5 - 0.5 = 0.995, A_1 = 0.995 + 0.99*0.95*0.5 = 0.995 + 0.47025 = 1.46525
        # delta_0 = 1 + 0.99*0.5 - 0.5 = 0.995, A_0 = 0.995 + 0.99*0.95*1.46525 = 0.995 + 1.378067625 = 2.373067625
        expected_adv = [2.373067625, 1.46525, 0.5]
        np.testing.assert_allclose(advantages.tolist(), expected_adv, rtol=1e-5)

    def test_compute_gae_resets_after_clear(self) -> None:
        buf = self._buffer(3)
        feature_dim = rl_feature_count()
        buf.store(
            obs=np.zeros(feature_dim, dtype=np.float32),
            action=np.array([0], dtype=np.int64),
            logprob=np.array(0.0, dtype=np.float32),
            value=np.array(0.0, dtype=np.float32),
            reward=1.0,
            done=True,
            mask=np.ones(NUM_ACTIONS, dtype=bool),
        )
        buf.compute_gae()
        buf.clear()
        self.assertEqual(len(buf), 0)

    def test_compute_gae_normalizes_advantages_by_default(self) -> None:
        # With normalize=True (default), advantages should have ~zero mean and unit std
        buf = self._buffer(10)
        feature_dim = rl_feature_count()
        for i in range(10):
            buf.store(
                obs=np.zeros(feature_dim, dtype=np.float32),
                action=np.array([0], dtype=np.int64),
                logprob=np.array(0.0, dtype=np.float32),
                value=np.array(0.0, dtype=np.float32),
                reward=float(i),
                done=(i == 9),
                mask=np.ones(NUM_ACTIONS, dtype=bool),
            )
        advantages, _ = buf.compute_gae(gamma=0.99, lam=0.95, normalize=True)
        self.assertAlmostEqual(float(advantages.mean()), 0.0, places=4)
        self.assertAlmostEqual(float(advantages.std()), 1.0, places=4)


class PPOTrainerConvergenceTests(unittest.TestCase):
    """G4-ppo-converge: PPO improves reward on a learnable mini-scenario (≥100 steps)."""

    class _MiniLearnableBackend:
        """2-action toy backend where action 0 yields +1, action 1 yields -1.

        Observation is a constant vector (state-independent reward), so the
        policy must learn to always pick action 0. This is the simplest
        learnable problem that exercises the full PPO machinery.
        """

        def __init__(self, *, max_steps: int = 5) -> None:
            self._max_steps = max_steps
            self._step_count = 0

        @property
        def state_version(self) -> int:
            return self._step_count

        def reset(self) -> dict[str, Any]:
            self._step_count = 0
            return self._observation()

        def step(
            self, action_id: str, args: Mapping[str, Any]
        ) -> tuple[dict[str, Any], bool, dict[str, Any]]:
            self._step_count += 1
            reward = 1.0 if action_id == "action_a" else -1.0
            info: dict[str, Any] = {
                "action_id": action_id,
                "reward_signal": reward,
            }
            terminated = self._step_count >= self._max_steps
            return self._observation(), terminated, info

        def _observation(self) -> dict[str, Any]:
            return {
                "loop": self._step_count,
                "player_id": 1,
                "own_units": [
                    {
                        "entity_id": 1,
                        "unit_type_id": "Marine",
                        "owner": 1,
                        "x": 0, "y": 0,
                        "health": 45, "shields": 0, "energy": 0,
                        "state": "idle", "orders": [],
                    }
                ],
                "visible_enemies": [],
                "visible_allies": [],
                "resources": {
                    "minerals": 100,
                    "vespene": 0,
                    "supply_used": 1,
                    "supply_cap": 11,
                    "state_version": self._step_count,
                },
                "mission": {
                    "phase": "active",
                    "night": 0,
                    "wave": 0,
                    "terminated": False,
                    "end_reason": "",
                    "win_condition": "survive_loops",
                    "progress": self._step_count / self._max_steps,
                    "state_version": self._step_count,
                },
                "mineral_fields": [],
                "vespene_geysers": [],
                "tech": {"completed_upgrades": [], "researching": []},
            }

    def _mini_env(self, *, max_steps: int = 5):
        from cmre_rl_training.env import CmreRLEnv

        # Use custom reward override: ignore reward tracker, use info["reward_signal"]
        class _MiniEnv(CmreRLEnv):
            def step(self, action_id, args=None):
                obs, terminated, info = self.backend.step(action_id, args or {})
                reward = float(info.get("reward_signal", 0.0))
                self._step_count += 1
                obs_vector = self._encoder(obs)
                info = {**info, "step": self._step_count, "state_version": self.backend.state_version}
                return obs_vector, reward, bool(terminated), info

        return _MiniEnv(self._MiniLearnableBackend(max_steps=max_steps), normalize_reward=False)

    def test_ppo_trains_for_100_steps_and_finite_losses(self) -> None:
        from cmre_rl_training.network import P2AllyAC
        from cmre_rl_training.ppo import PPOTrainer
        from cmre_rl_training.rollout import collect_rollout

        env = self._mini_env()
        policy = P2AllyAC(hidden_dim=32, seed=1)
        trainer = PPOTrainer(
            policy,
            lr=3e-3,
            clip=0.2,
            gamma=0.99,
            lam=0.95,
            epochs=4,
            batch_size=16,
            ent_coef=0.01,
            vf_coef=0.5,
        )

        total_steps = 0
        loss_history: list[float] = []
        for _ in range(20):  # 20 rollouts × 5 steps = 100 steps
            env.reset()
            buf = collect_rollout(env, policy, n_steps=5)
            metrics = trainer.train(buf)
            loss_history.append(float(metrics["total_loss"]))
            total_steps += len(buf)
        self.assertGreaterEqual(total_steps, 100)
        # All losses must be finite
        self.assertTrue(all(np.isfinite(loss_history)))

    def test_ppo_learns_to_prefer_action_a_over_b(self) -> None:
        from cmre_rl_training.network import P2AllyAC
        from cmre_rl_training.ppo import PPOTrainer
        from cmre_rl_training.rollout import collect_rollout

        # Use 1-step episodes so each rollout is a single decision with a clean
        # reward signal (+1 for action_a, -1 for action_b). This avoids the
        # advantage-canceling effect that occurs in short normalized rollouts.
        env = self._mini_env(max_steps=1)
        policy = P2AllyAC(hidden_dim=32, seed=42)
        # Disable advantage normalization: with 1-step episodes the advantage
        # equals (reward - value) and should not be rescaled.
        trainer = PPOTrainer(
            policy,
            lr=5e-3,
            clip=0.2,
            epochs=4,
            batch_size=8,
            normalize_advantages=False,
            ent_coef=0.0,  # disable entropy bonus for cleaner signal
        )

        from cmre_rl_training.action_space import ACTION_INDEX

        action_a_idx = ACTION_INDEX["move_units"]
        action_b_idx = ACTION_INDEX["stop_units"]

        class _TwoActionEnv:
            """Restrict action space to {move_units, stop_units} with reward signal."""

            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

            @property
            def backend(self):
                return self._inner.backend

            @property
            def observation_dim(self):
                return self._inner.observation_dim

            @property
            def action_dim(self):
                return self._inner.action_dim

            def reset(self):
                return self._inner.reset()

            def action_mask(self):
                full = self._inner.action_mask().copy()
                mask = np.zeros_like(full)
                mask[action_a_idx] = True
                mask[action_b_idx] = True
                return mask

            def step(self, action_id):
                backend_action = "action_a" if action_id == "move_units" else "action_b"
                obs, terminated, info = self._inner.backend.step(backend_action, {})
                reward = float(info["reward_signal"])
                self._inner._step_count += 1
                obs_vector = self._inner._encoder(obs)
                info = {
                    **info,
                    "step": self._inner._step_count,
                    "state_version": self._inner.backend.state_version,
                }
                return obs_vector, reward, bool(terminated), info

        two_env = _TwoActionEnv(env)

        # Baseline: count action_a picks over 20 single-step episodes (sampling).
        a_picks_before = self._count_action_a(policy, two_env, episodes=20, deterministic=False)

        # Train: 50 rollouts × 1 step = 50 gradient updates worth of data.
        for _ in range(50):
            two_env.reset()
            buf = collect_rollout(two_env, policy, n_steps=1)
            trainer.train(buf)

        a_picks_after = self._count_action_a(policy, two_env, episodes=20, deterministic=False)

        # Policy must pick action_a more often after training.
        self.assertGreater(a_picks_after, a_picks_before)
        # And the policy should pick action_a majority of the time after training.
        self.assertGreater(a_picks_after, 10)  # >50% of 20 episodes

    def _count_action_a(self, policy, env, *, episodes: int, deterministic: bool = True) -> int:
        from cmre_rl_training.action_space import ACTION_INDEX

        action_a_idx = ACTION_INDEX["move_units"]
        action_b_idx = ACTION_INDEX["stop_units"]
        policy.eval()
        picks = 0
        with torch.no_grad():
            for _ in range(episodes):
                obs = env.reset()
                done = False
                while not done:
                    mask = env.action_mask()
                    obs_t = torch.as_tensor(obs, dtype=torch.float32).unsqueeze(0)
                    mask_t = torch.as_tensor(mask, dtype=torch.bool).unsqueeze(0)
                    logits, _ = policy(obs_t, mask_t)
                    relevant = torch.tensor([action_a_idx, action_b_idx])
                    sub_logits = logits[0, relevant]
                    if deterministic:
                        action_idx = int(relevant[int(sub_logits.argmax())].item())
                    else:
                        # Sample restricted to the 2 legal actions
                        probs = torch.softmax(sub_logits, dim=-1)
                        choice = torch.multinomial(probs, 1).item()
                        action_idx = int(relevant[choice].item())
                    action_name = "move_units" if action_idx == action_a_idx else "stop_units"
                    if action_idx == action_a_idx:
                        picks += 1
                    obs, _, done, _ = env.step(action_name)
        policy.train()
        return picks


if __name__ == "__main__":
    unittest.main()
