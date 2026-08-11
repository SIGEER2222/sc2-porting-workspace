"""Tests for train_eval_loop plan building (plan Stage 4, --dry-run)."""

from __future__ import annotations

import tempfile
import unittest
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from tools.train_eval_loop import TrainEvalConfig, build_eval_plan, run_train_eval


def _config_with_checkpoint(checkpoint: Path) -> TrainEvalConfig:
    return TrainEvalConfig(
        maps=("dead-of-night", "void-launch"),
        variants=("frozen-stochastic", "live-update", "deterministic-baseline"),
        live_port_start=5960,
        live_max_steps=512,
        live_step_mul=8,
        stop_on_terminal=True,
        save_replay=True,
        commander="TerranRaynor",
        commander_level=15,
        commander_mastery="full",
        dry_run=True,
        report_root=Path("artifacts/train-eval-loop/live"),
        train_output_dir=Path("artifacts/train-eval-loop/training"),
        checkpoint_path=checkpoint,
    )


class BuildEvalPlanTests(unittest.TestCase):
    def test_plan_has_one_command_per_map_variant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "map-aware-policy.pt"
            checkpoint.write_bytes(b"dummy-checkpoint-bytes")
            config = _config_with_checkpoint(checkpoint)
            plan = build_eval_plan(config)
        self.assertEqual(plan["total_runs"], 2 * 3)
        self.assertEqual(len(plan["commands"]), 6)

    def test_ports_are_unique_and_sequential(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "map-aware-policy.pt"
            checkpoint.write_bytes(b"x")
            plan = build_eval_plan(_config_with_checkpoint(checkpoint))
        ports = [cmd["port"] for cmd in plan["commands"]]
        self.assertEqual(len(ports), len(set(ports)))
        self.assertEqual(ports, list(range(5960, 5960 + 6)))

    def test_command_invokes_run_live_rl_with_expected_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "map-aware-policy.pt"
            checkpoint.write_bytes(b"x")
            plan = build_eval_plan(_config_with_checkpoint(checkpoint))
        first = plan["commands"][0]
        self.assertTrue(first["command"][1].replace("\\", "/").endswith("tools/run_live_rl.py"))
        self.assertIn("--stop-on-terminal", first["command"])
        self.assertIn("--save-replay", first["command"])
        self.assertIn("--commander-level", first["command"])
        self.assertIn("15", first["command"])
        self.assertIn("--commander-mastery", first["command"])
        self.assertIn("full", first["command"])
        self.assertTrue(first["command"][first["command"].index("--port") + 1].isdigit())

    def test_checkpoint_hash_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "map-aware-policy.pt"
            checkpoint.write_bytes(b"stable-content")
            plan = build_eval_plan(_config_with_checkpoint(checkpoint))
        self.assertEqual(len(plan["checkpoint_sha256"]), 64)

    def test_missing_checkpoint_records_pending_hash(self) -> None:
        config = _config_with_checkpoint(Path("artifacts/does-not-exist.pt"))
        plan = build_eval_plan(config)
        self.assertEqual(plan["checkpoint_sha256"], "pending")

    def test_each_run_has_distinct_report_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "c.pt"
            checkpoint.write_bytes(b"x")
            plan = build_eval_plan(_config_with_checkpoint(checkpoint))
        report_paths = {cmd["report_path"] for cmd in plan["commands"]}
        self.assertEqual(len(report_paths), 6)

    def test_underleveled_commander_blocks_the_plan_before_any_live_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "c.pt"
            checkpoint.write_bytes(b"x")
            config = _config_with_checkpoint(checkpoint)
            config.commander_level = 7
            plan = build_eval_plan(config)
        self.assertEqual(plan["status"], "blocked")
        self.assertFalse(plan["commander_gate_passed"])
        self.assertEqual(plan["total_runs"], 0)
        self.assertEqual(plan["commands"], [])


class TrainEvalExecutionTests(unittest.TestCase):
    def test_training_uses_configured_simulator_loop_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = TrainEvalConfig(
                train_output_dir=Path(tmp) / "training",
                checkpoint_path=Path(tmp) / "training" / "policy.pt",
                report_root=Path(tmp) / "reports",
                train_step_loops=16,
            )
            captured: dict[str, object] = {}

            def fake_run_training(args):
                captured["step_loops"] = args.step_loops
                captured["start_minerals"] = args.start_minerals
                captured["start_vespene"] = args.start_vespene
                return {"status": "passed", "total_steps": 1, "total_mean_reward": 0.0}

            with patch("cmre_rl_training.training_cli.run_training", side_effect=fake_run_training):
                from tools.train_eval_loop import _run_training

                _run_training(config)

        self.assertEqual(captured["step_loops"], 16)
        self.assertIsNone(captured["start_minerals"])
        self.assertIsNone(captured["start_vespene"])

    def test_post_training_plan_records_checkpoint_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "training" / "policy.pt"
            config = TrainEvalConfig(
                train_output_dir=checkpoint.parent,
                checkpoint_path=checkpoint,
                report_root=Path(tmp) / "reports",
                skip_live=True,
            )

            def fake_training(_config):
                checkpoint.parent.mkdir(parents=True, exist_ok=True)
                checkpoint.write_bytes(b"trained-checkpoint")
                return {
                    "status": "passed",
                    "total_steps": 64,
                    "total_mean_reward": 0.25,
                    "commander": {},
                }

            with patch("tools.train_eval_loop._run_training", side_effect=fake_training):
                report = run_train_eval(config)

            expected_hash = hashlib.sha256(b"trained-checkpoint").hexdigest()
            saved_plan = json.loads(
                (config.report_root / "train-eval-plan.json").read_text(encoding="utf-8")
            )
            saved_report = json.loads(
                (config.report_root / "train-eval-report.json").read_text(encoding="utf-8")
            )

        self.assertEqual(saved_plan["checkpoint_sha256"], expected_hash)
        self.assertEqual(report["plan_checkpoint_sha256"], expected_hash)
        self.assertEqual(saved_report["status"], "trained_only")
        self.assertEqual(saved_report["report_path"], str(config.report_root / "train-eval-report.json"))


if __name__ == "__main__":
    unittest.main()
