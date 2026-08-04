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
from vibe.ml.encoder import FEATURE_NAMES, FEATURE_SCHEMA, feature_schema_hash
from vibe.ml.model import MODEL_SCHEMA, P2AllyPolicyNet, load_checkpoint, save_checkpoint


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

    def test_pytorch_checkpoint_round_trip_emits_complete_p2_intent(self):
        observation = Observation(
            loop=128,
            player_id=2,
            own_units=[
                {"entity_id": 2, "unit_type_id": "CommandCenter", "owner": 2,
                 "x": 85, "y": 94, "health": 1400 * 1024,
                 "max_health": 1400 * 1024, "orders": []},
                {"entity_id": 3, "unit_type_id": "Marine", "owner": 2,
                 "x": 86, "y": 94, "health": 45 * 1024,
                 "max_health": 45 * 1024, "orders": []},
            ],
            visible_enemies=[],
            visible_allies=[
                {"entity_id": 1, "unit_type_id": "Marine", "owner": 1,
                 "x": 84, "y": 94, "health": 45 * 1024,
                 "max_health": 45 * 1024, "orders": []},
            ],
            resources={
                "minerals": 500, "vespene": 100, "supply_cap": 20,
                "supply_used": 2, "state_version": 128,
            },
            mission={"progress": 0.25},
        )
        model = P2AllyPolicyNet(hidden_dim=24, seed=7)
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = save_checkpoint(model, Path(directory) / "ally-intent.pt")
            loaded = load_checkpoint(checkpoint)
            intent = loaded.predict_intent(
                observation,
                requested_mode="follow",
                decision_id="p2-ml-test-128",
                issuer_player_id=2,
            )

        payload = intent.to_dict()
        self.assertEqual(MODEL_SCHEMA, "cmre-ally-intent-pytorch.v2")
        self.assertEqual(FEATURE_SCHEMA, "cmre-ally-observation.v2")
        self.assertEqual(len(FEATURE_NAMES), 49)
        self.assertEqual(feature_schema_hash(), "38e40cb49fb9e80e565af79d2b474d4c77d3eeb9a15f05e9ce941f60a9ddd7b1")
        self.assertEqual(payload["schema"], MODEL_SCHEMA)
        self.assertEqual(payload["issuer_player_id"], 2)
        self.assertEqual(payload["observation_version"], 128)
        self.assertEqual(
            set(payload["probabilities"]),
            {"economy", "production", "tactical", "command"},
        )
        self.assertTrue(all(payload["probabilities"][head] for head in payload["probabilities"]))

    def test_pytorch_loader_rejects_legacy_json_mlp_checkpoint(self):
        model = MLPModeModel(hidden_dim=8, seed=7)
        with tempfile.TemporaryDirectory() as directory:
            legacy_checkpoint = model.save(Path(directory) / "legacy.json")
            with self.assertRaisesRegex(ValueError, "p2_model_schema_mismatch"):
                load_checkpoint(legacy_checkpoint)

    def test_ally_policy_trace_preserves_full_pytorch_intent(self):
        observation = Observation(
            loop=1,
            player_id=2,
            own_units=[
                {"entity_id": 2, "unit_type_id": "CommandCenter", "owner": 2,
                 "x": 85, "y": 94, "health": 100, "max_health": 100},
                {"entity_id": 3, "unit_type_id": "Marine", "owner": 2,
                 "x": 86, "y": 94, "health": 45, "max_health": 45},
            ],
            visible_enemies=[],
            visible_allies=[
                {"entity_id": 1, "unit_type_id": "Marine", "owner": 1,
                 "x": 85, "y": 94, "health": 45, "max_health": 45},
            ],
            resources={"minerals": 0, "vespene": 0, "supply_cap": 20,
                       "supply_used": 2, "state_version": 1},
            mission={},
        )
        policy = AllyPolicy(
            player_id=2,
            leader_entity_id=1,
            leader_player_id=1,
            base_region=(85, 94, 14),
            mode_model=P2AllyPolicyNet(hidden_dim=24, seed=7),
        )

        policy.decide(observation, loop=1)

        trace = policy.last_ml_prediction
        self.assertEqual(trace["schema"], MODEL_SCHEMA)
        self.assertEqual(trace["issuer_player_id"], 2)
        self.assertEqual(trace["observation_version"], 1)
        self.assertEqual(set(trace["probabilities"]), {"economy", "production", "tactical", "command"})


if __name__ == "__main__":
    unittest.main()
