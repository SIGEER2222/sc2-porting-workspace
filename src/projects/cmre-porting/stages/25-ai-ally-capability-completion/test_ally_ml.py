import json
import tempfile
import unittest
from pathlib import Path

from vibe.consumers.ally_ai import AllyPolicy
from vibe.contracts import Observation
from vibe.ml_policy import (
    MLPModeModel,
    encode_observation,
    make_public_expert_dataset,
    samples_from_records,
)


class AllyMachineLearningTests(unittest.TestCase):
    def test_training_loss_decreases_and_checkpoint_round_trips(self):
        records = make_public_expert_dataset((42, 7), samples_per_seed=48)
        samples = samples_from_records(records)
        model = MLPModeModel(hidden_dim=16, seed=7)
        metrics = model.fit(samples, epochs=35, learning_rate=0.08, seed=7)
        self.assertTrue(metrics["loss_decreased"])
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = model.save(Path(directory) / "model.json")
            loaded = MLPModeModel.load(checkpoint)
            expected = model.predict_features(samples[0][0])
            actual = loaded.predict_features(samples[0][0])
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
        self.assertEqual(expected.label, actual.label)
        self.assertAlmostEqual(expected.confidence, actual.confidence, places=12)
        self.assertEqual(payload["schema"], "cmre-ally-mlp.v1")
        payload["bias_o"][0] += 0.001
        with self.assertRaisesRegex(ValueError, "model_weights_hash_mismatch"):
            MLPModeModel.from_dict(payload)

    def test_structure_health_is_not_tactical_health(self):
        observation = Observation(
            loop=0,
            player_id=2,
            own_units=[
                {"entity_id": 1, "unit_type_id": "CommandCenter", "owner": 2, "x": 85, "y": 94, "health": 100, "max_health": 100},
                {"entity_id": 2, "unit_type_id": "FactoryTechLab", "owner": 2, "x": 80, "y": 94, "health": 1, "max_health": 100},
                {"entity_id": 3, "unit_type_id": "Marine", "owner": 2, "x": 82, "y": 94, "health": 45, "max_health": 45},
            ],
            visible_enemies=[],
            visible_allies=[{"entity_id": 9, "unit_type_id": "Marine", "owner": 1, "x": 86, "y": 94, "health": 45, "max_health": 45}],
            resources={"minerals": 500, "vespene": 100, "supply_cap": 20, "supply_used": 2},
            mission={},
        )
        features = encode_observation(observation, "follow", (85, 94, 14), 14)
        self.assertAlmostEqual(features[2], 1.0 / 40.0)
        self.assertAlmostEqual(features[5], 1.0)

    def test_loaded_model_decision_is_p2_owned(self):
        records = make_public_expert_dataset((42, 7), samples_per_seed=24)
        model = MLPModeModel(hidden_dim=16, seed=7)
        model.fit(samples_from_records(records), epochs=20, learning_rate=0.08, seed=7)
        observation = Observation(
            loop=0,
            player_id=2,
            own_units=[
                {"entity_id": 2, "unit_type_id": "CommandCenter", "owner": 2, "x": 85, "y": 94, "health": 100, "max_health": 100},
                {"entity_id": 3, "unit_type_id": "Marine", "owner": 2, "x": 86, "y": 94, "health": 45, "max_health": 45},
            ],
            visible_enemies=[],
            visible_allies=[{"entity_id": 1, "unit_type_id": "Marine", "owner": 1, "x": 85, "y": 94, "health": 45, "max_health": 45}],
            resources={"minerals": 0, "vespene": 0, "supply_cap": 20, "supply_used": 2},
            mission={},
        )
        policy = AllyPolicy(
            player_id=2,
            leader_entity_id=1,
            leader_player_id=1,
            base_region=(85, 94, 14),
            mode_model=model,
        )
        actions = policy.decide(observation, loop=1)
        self.assertGreater(policy.ml_decision_count, 0)
        self.assertTrue(policy.last_ml_prediction["label"])
        self.assertTrue(all(action.entity_id in {2, 3} for action in actions))


if __name__ == "__main__":
    unittest.main()
