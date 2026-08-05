"""Stage 06 G5: shared PPO self-training over two map profiles."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cmre_rl_training.backends import FakeBackend
from cmre_rl_training.env import CmreRLEnv
from cmre_rl_training.map_aware import load_map_aware_checkpoint
from cmre_rl_training.self_training import MultiMapSelfTrainer, MultiMapTrainingConfig


class MultiMapSelfTrainingTests(unittest.TestCase):
    def test_one_policy_trains_on_two_maps_and_emits_checkpoint_metadata(self) -> None:
        factories = {
            "Dead of Night": lambda: CmreRLEnv(
                FakeBackend(max_steps=3), normalize_reward=False
            ),
            "Void Launch": lambda: CmreRLEnv(
                FakeBackend(max_steps=3), normalize_reward=False
            ),
        }
        with TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "shared-policy.pt"
            trainer = MultiMapSelfTrainer(
                factories,
                config=MultiMapTrainingConfig(
                    iterations=1,
                    rollout_steps=4,
                    hidden_dim=16,
                    ppo_epochs=1,
                    batch_size=4,
                    checkpoint_path=checkpoint,
                ),
            )
            report = trainer.train()

            self.assertEqual(report["map_order"], ["Dead of Night", "Void Launch"])
            self.assertEqual(set(report["maps"]), set(factories))
            self.assertEqual(report["total_steps"], 8)
            self.assertTrue(checkpoint.exists())
            self.assertEqual(report["checkpoint_path"], str(checkpoint))
            self.assertEqual(report["maps"]["Dead of Night"]["steps"], 4)
            self.assertEqual(report["maps"]["Void Launch"]["steps"], 4)

            loaded = load_map_aware_checkpoint(checkpoint)
            self.assertEqual(loaded.context_dim, 8)
            self.assertEqual(loaded.num_actions, 19)


if __name__ == "__main__":
    unittest.main()
