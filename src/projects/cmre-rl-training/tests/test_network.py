"""Tests for P2AllyAC actor-critic network (Stage 03 G1, G2, G5)."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import torch

from cmre_rl_training.action_space import NUM_ACTIONS
from cmre_rl_training.observation import rl_feature_count


class P2AllyACContractTests(unittest.TestCase):
    """G1-network: forward produces (logits[B,19], value[B,1]) with mask applied."""

    def setUp(self) -> None:
        from cmre_rl_training.network import P2AllyAC

        self.feature_dim = rl_feature_count()
        self.policy = P2AllyAC(hidden_dim=32, seed=7)
        self.batch = 4
        self.obs = torch.randn(self.batch, self.feature_dim)
        # Mask: first half of actions legal, second half illegal
        self.mask = torch.zeros(self.batch, NUM_ACTIONS, dtype=torch.bool)
        self.mask[:, : NUM_ACTIONS // 2] = True

    def test_forward_returns_logits_and_value_tuples(self) -> None:
        from cmre_rl_training.network import P2AllyAC

        policy = P2AllyAC(hidden_dim=16, seed=1)
        obs = torch.randn(2, self.feature_dim)
        logits, value = policy(obs)
        self.assertIsInstance(logits, torch.Tensor)
        self.assertIsInstance(value, torch.Tensor)
        self.assertEqual(logits.shape, (2, NUM_ACTIONS))
        self.assertEqual(value.shape, (2, 1))

    def test_forward_unbatched_input_promotes_to_batch(self) -> None:
        from cmre_rl_training.network import P2AllyAC

        policy = P2AllyAC(hidden_dim=16, seed=1)
        obs = torch.randn(self.feature_dim)
        logits, value = policy(obs)
        self.assertEqual(logits.shape, (1, NUM_ACTIONS))
        self.assertEqual(value.shape, (1, 1))

    def test_forward_with_mask_blocks_illegal_actions(self) -> None:
        logits, _ = self.policy(self.obs, self.mask)
        # Illegal logits should be -inf
        illegal = ~self.mask
        self.assertTrue(torch.isinf(logits[illegal]).all())
        self.assertTrue((logits[illegal] < 0).all())
        # Legal logits should be finite
        legal = self.mask
        self.assertTrue(torch.isfinite(logits[legal]).all())

    def test_forward_without_mask_keeps_all_logits_finite(self) -> None:
        logits, _ = self.policy(self.obs)
        self.assertTrue(torch.isfinite(logits).all())

    def test_action_dim_matches_action_space(self) -> None:
        self.assertEqual(self.policy.num_actions, NUM_ACTIONS)

    def test_trunk_inherits_from_p2_ally_policy_net(self) -> None:
        from vibe.ml.model import P2AllyPolicyNet

        self.assertIsInstance(self.policy, P2AllyPolicyNet)
        # BC heads are preserved
        self.assertIn("economy", self.policy.heads)
        self.assertIn("production", self.policy.heads)
        self.assertIn("tactical", self.policy.heads)
        self.assertIn("command", self.policy.heads)

    def test_bc_heads_still_callable_via_super_forward(self) -> None:
        # Subclass must not break the BC forward path (used for Stage 04 BC load)
        bc_outputs = super(type(self.policy), self.policy).forward(self.obs)
        self.assertIsInstance(bc_outputs, dict)
        self.assertEqual(set(bc_outputs.keys()), {"economy", "production", "tactical", "command"})

    def test_value_head_is_scalar_per_state(self) -> None:
        _, value = self.policy(self.obs)
        self.assertEqual(value.shape[-1], 1)


class P2AllyACMaskEdgeCases(unittest.TestCase):
    def test_all_illegal_mask_produces_finite_via_no_mask_path(self) -> None:
        from cmre_rl_training.network import P2AllyAC

        policy = P2AllyAC(hidden_dim=16, seed=1)
        obs = torch.randn(1, rl_feature_count())
        mask = torch.zeros(1, NUM_ACTIONS, dtype=torch.bool)
        # All illegal -> would produce all -inf logits; ensure no NaN from softmax
        # Caller should avoid this; here we only verify it doesn't crash
        logits, _ = policy(obs, mask)
        self.assertTrue(torch.isinf(logits).all())


class P2AllyACCheckpointTests(unittest.TestCase):
    """G5-checkpoint: save/load RL checkpoint roundtrip is consistent."""

    def setUp(self) -> None:
        from cmre_rl_training.network import P2AllyAC

        self.feature_dim = rl_feature_count()
        self.policy = P2AllyAC(hidden_dim=32, seed=42)
        self.obs = torch.randn(3, self.feature_dim)
        self.mask = torch.ones(3, NUM_ACTIONS, dtype=torch.bool)

    def test_save_load_roundtrip_preserves_outputs(self) -> None:
        from cmre_rl_training.network import load_rl_checkpoint, save_rl_checkpoint

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.pt"
            save_rl_checkpoint(self.policy, path)
            self.assertTrue(path.exists())

            loaded = load_rl_checkpoint(path, device="cpu")
            loaded.eval()
            self.policy.eval()

            with torch.no_grad():
                logits_a, value_a = self.policy(self.obs, self.mask)
                logits_b, value_b = loaded(self.obs, self.mask)

            torch.testing.assert_close(logits_a, logits_b)
            torch.testing.assert_close(value_a, value_b)

    def test_checkpoint_payload_includes_schema_and_state_dict(self) -> None:
        from cmre_rl_training.network import save_rl_checkpoint

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.pt"
            save_rl_checkpoint(self.policy, path)
            payload = torch.load(path, map_location="cpu", weights_only=False)
            self.assertIn("schema", payload)
            self.assertIn("state_dict", payload)
            self.assertIn("policy_config", payload)
            self.assertEqual(payload["num_actions"], NUM_ACTIONS)

    def test_checkpoint_includes_bc_heads_and_action_value_heads(self) -> None:
        from cmre_rl_training.network import save_rl_checkpoint

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.pt"
            save_rl_checkpoint(self.policy, path)
            payload = torch.load(path, map_location="cpu", weights_only=False)
            keys = set(payload["state_dict"].keys())
            # BC trunk + 4 heads
            self.assertIn("trunk.1.weight", keys)
            self.assertIn("heads.economy.weight", keys)
            # RL action + value heads
            self.assertIn("action_head.weight", keys)
            self.assertIn("value_head.weight", keys)


class P2AllyACBCLoadTests(unittest.TestCase):
    """G2-bc-load: BC checkpoint loads trunk + 4 heads, leaves AC heads intact."""

    def test_load_bc_checkpoint_preserves_ac_head_initialization(self) -> None:
        from cmre_rl_training.network import P2AllyAC, load_bc_checkpoint_into_ac
        from vibe.ml.model import P2AllyPolicyNet, save_checkpoint

        # Create a BC checkpoint with random weights
        bc_model = P2AllyPolicyNet(hidden_dim=32, seed=99)
        with TemporaryDirectory() as tmp:
            bc_path = Path(tmp) / "bc.pt"
            save_checkpoint(bc_model, bc_path)

            # Create an AC policy with different seed (random AC heads)
            ac = P2AllyAC(hidden_dim=32, seed=7)
            # Snapshot AC head weights BEFORE BC load (should remain unchanged)
            action_before = ac.action_head.weight.detach().clone()
            value_before = ac.value_head.weight.detach().clone()

            # Snapshot BC trunk weights for comparison
            bc_trunk_weight = bc_model.trunk[1].weight.detach().clone()

            load_bc_checkpoint_into_ac(ac, bc_path)

            # Trunk must match BC
            torch.testing.assert_close(ac.trunk[1].weight, bc_trunk_weight)
            # AC heads must NOT have changed (BC load only touches trunk + 4 BC heads)
            torch.testing.assert_close(ac.action_head.weight, action_before)
            torch.testing.assert_close(ac.value_head.weight, value_before)

    def test_load_bc_checkpoint_into_mismatched_hidden_dim_raises(self) -> None:
        from cmre_rl_training.network import P2AllyAC, load_bc_checkpoint_into_ac
        from vibe.ml.model import P2AllyPolicyNet, save_checkpoint

        bc_model = P2AllyPolicyNet(hidden_dim=64, seed=1)
        ac = P2AllyAC(hidden_dim=32, seed=2)
        with TemporaryDirectory() as tmp:
            bc_path = Path(tmp) / "bc.pt"
            save_checkpoint(bc_model, bc_path)
            with self.assertRaises(ValueError):
                load_bc_checkpoint_into_ac(ac, bc_path)


if __name__ == "__main__":
    unittest.main()
