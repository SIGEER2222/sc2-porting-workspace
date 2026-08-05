"""Stage 06 tests for map-conditioned environments and policies."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import torch

from cmre_rl_training.backends import FakeBackend
from cmre_rl_training.env import CmreRLEnv
from cmre_rl_training.map_aware import (
    MapAwareEnv,
    MapAwareP2AllyAC,
    load_map_aware_checkpoint,
    save_map_aware_checkpoint,
)
from cmre_rl_training.map_profiles import MapProfileRegistry
from cmre_rl_training.observation import rl_feature_count


class MapAwareEnvTests(unittest.TestCase):
    def test_context_is_appended_without_changing_base_encoder(self) -> None:
        profile = MapProfileRegistry().resolve("Dead of Night")
        env = MapAwareEnv(CmreRLEnv(FakeBackend(max_steps=5), normalize_reward=False), profile)
        observation = env.reset()

        self.assertEqual(env.observation_dim, rl_feature_count() + profile.context_dim)
        self.assertEqual(observation.shape, (env.observation_dim,))
        np.testing.assert_allclose(observation[-profile.context_dim:], profile.context_vector())
        self.assertFalse(env.action_mask()[5])  # attack_units: no visible enemy yet

        for _ in range(3):
            env.step("move_units")
        self.assertTrue(env.action_mask()[5])


class MapAwarePolicyTests(unittest.TestCase):
    def test_masked_forward_and_checkpoint_roundtrip(self) -> None:
        profile = MapProfileRegistry().resolve("Void Launch")
        policy = MapAwareP2AllyAC(hidden_dim=16, seed=3, context_dim=profile.context_dim)
        observation = torch.randn(2, policy.contextual_input_dim)
        mask = torch.ones(2, policy.num_actions, dtype=torch.bool)
        mask[:, 1] = False
        logits, value = policy(observation, mask)

        self.assertEqual(logits.shape, (2, policy.num_actions))
        self.assertEqual(value.shape, (2, 1))
        self.assertTrue(torch.isinf(logits[:, 1]).all())
        self.assertTrue(torch.isfinite(value).all())

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "map-aware.pt"
            save_map_aware_checkpoint(policy, path)
            loaded = load_map_aware_checkpoint(path)
            loaded_logits, loaded_value = loaded(observation, mask)
            torch.testing.assert_close(logits, loaded_logits)
            torch.testing.assert_close(value, loaded_value)

    def test_existing_bc_checkpoint_warm_starts_shared_trunk(self) -> None:
        from cmre_rl_training.network import load_bc_checkpoint_into_ac
        from vibe.ml.model import P2AllyPolicyNet, save_checkpoint

        with TemporaryDirectory() as tmp:
            bc_path = Path(tmp) / "bc.pt"
            bc_model = P2AllyPolicyNet(hidden_dim=16, seed=11)
            save_checkpoint(bc_model, bc_path)

            policy = MapAwareP2AllyAC(hidden_dim=16, seed=3, context_dim=8)
            load_bc_checkpoint_into_ac(policy, bc_path)
            np.testing.assert_allclose(
                policy.trunk[1].weight.detach().numpy(),
                bc_model.trunk[1].weight.detach().numpy(),
            )


if __name__ == "__main__":
    unittest.main()
