import json
import tempfile
import unittest
from pathlib import Path

from vibe.p1_ml import (
    ACTION_LABELS,
    MODEL_SCHEMA,
    P1ActionPolicyNet,
    build_manual_dataset,
    load_checkpoint,
    save_checkpoint,
    train_p1_model,
)


ROOT = Path(__file__).resolve().parents[5]
MANUAL = ROOT / "artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/manual-p1-20260804"


class P1MachineLearningTests(unittest.TestCase):
    def test_real_manual_replay_keeps_unknown_out_of_training(self):
        # This gate is intentionally evidence-bound: it may only pass on real
        # runtime capture, never on synthesised data. `artifacts/` is
        # git-ignored, so the capture can disappear from a clean checkout.
        # Fail loudly with the exact regeneration command instead of dying on
        # an opaque FileNotFoundError deep inside pathlib (that opacity has
        # already caused this gap to be mis-attributed once).
        observations = MANUAL / "manual-runtime-observations.jsonl"
        actions = MANUAL / "manual-p1-actions.jsonl"
        missing = [path.name for path in (observations, actions) if not path.exists()]
        if missing:
            self.fail(
                "Stage25 runtime evidence missing: "
                + ", ".join(missing)
                + f"\n  expected under: {MANUAL}"
                + "\n  regenerate with a LIVE SC2 in API mode plus a human playing P1:"
                + "\n    python -m vibe.manual_replay_capture --port 5000 \\"
                + "\n      --map src/projects/cmre-porting/packages/Maps/亡者之夜.SC2Map \\"
                + f"\n      --out {MANUAL}"
                + "\n  (the capture sends no actions; P1 behaviour must come from the UI)"
                + "\n  NOTE: this gate cannot be satisfied offline and must not be"
                + " relaxed to a skip -- a red bar here is an honest evidence gap."
            )
        dataset = build_manual_dataset(observations, actions)
        self.assertEqual(dataset["evidence_type"], "runtime")
        self.assertGreater(dataset["action_count"], len(dataset["examples"]))
        self.assertGreater(dataset["label_audit"].get("unknown", 0), 0)
        self.assertTrue(all(item["label"] != "unknown" for item in dataset["examples"]))
        self.assertGreaterEqual(len(dataset["examples"]), 2)

    def test_torch_training_and_checkpoint_round_trip(self):
        examples = [
            {"features": [0.1] * 20, "label": "move"},
            {"features": [0.9] * 20, "label": "move"},
            {"features": [0.2] * 20, "label": "move"},
            {"features": [0.8] * 20, "label": "move"},
        ]
        model, metrics = train_p1_model(examples[:3], examples[3:], epochs=8)
        self.assertTrue(metrics["loss_decreased"])
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = save_checkpoint(model, Path(directory) / "p1-action.pt", training=metrics)
            loaded = load_checkpoint(checkpoint)
            first = loaded.predict_action({"loop": 1, "own_units": [], "visible_enemies": [], "visible_allies": [], "resources": {}}, player_id=1)
            payload = json.loads(json.dumps(first.to_dict()))
        self.assertEqual(payload["issuer_player_id"], 1)
        self.assertIn(payload["label"], ACTION_LABELS)
        self.assertEqual(MODEL_SCHEMA, "cmre-p1-action-pytorch.v1")

    def test_live_model_can_be_constructed_without_hidden_world_state(self):
        model = P1ActionPolicyNet(seed=7)
        prediction = model.predict_action(
            {"loop": 22, "own_units": [{"entity_id": 1, "unit_type_id": "SCV", "x": 85, "y": 94, "health": 45, "max_health": 45}],
             "visible_enemies": [], "visible_allies": [], "resources": {"minerals": 50, "supply_cap": 15, "supply_used": 1}},
            decision_id="p1-test", player_id=1,
        )
        self.assertEqual(prediction.decision_id, "p1-test")
        self.assertEqual(prediction.issuer_player_id, 1)


if __name__ == "__main__":
    unittest.main()
