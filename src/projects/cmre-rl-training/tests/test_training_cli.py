"""Stage 07 tests for the user-facing training command."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cmre_rl_training.training_cli import main, parse_map_names


class TrainingCliTests(unittest.TestCase):
    def test_map_argument_validation(self) -> None:
        self.assertEqual(parse_map_names("Dead of Night,void-launch"), ("Dead of Night", "void-launch"))
        with self.assertRaises(ValueError):
            parse_map_names("dead-of-night,dead-of-night")

    def test_fake_backend_writes_report_and_checkpoint(self) -> None:
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "fake"
            status = main([
                "--backend", "fake",
                "--maps", "dead-of-night,void-launch",
                "--iterations", "1",
                "--rollout-steps", "2",
                "--max-episode-steps", "2",
                "--hidden-dim", "8",
                "--ppo-epochs", "1",
                "--batch-size", "2",
                "--ent-coef", "0.05",
                "--ent-floor", "0.5",
                "--step-loops", "16",
                "--start-minerals", "200",
                "--start-vespene", "25",
                "--output-dir", str(output),
            ])
            self.assertEqual(status, 0)
            report = json.loads((output / "training-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["total_steps"], 4)
            self.assertEqual(report["config"]["ent_coef"], 0.05)
            self.assertEqual(report["config"]["ent_floor"], 0.5)
            self.assertEqual(report["config"]["step_loops"], 16)
            self.assertEqual(report["config"]["start_minerals"], 200)
            self.assertEqual(report["config"]["start_vespene"], 25)
            self.assertTrue(report["commander"]["commander_max_level_gate_passed"])
            self.assertEqual(report["commander"]["commander_level"], 15)
            self.assertEqual(report["commander"]["commander_mastery"], "full")
            self.assertIn("action_metrics", report)
            self.assertTrue((output / "map-aware-policy.pt").exists())

    def test_underleveled_commander_is_blocked_before_training(self) -> None:
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "blocked"
            status = main([
                "--backend", "fake",
                "--maps", "dead-of-night",
                "--iterations", "1",
                "--rollout-steps", "2",
                "--max-episode-steps", "2",
                "--commander-level", "7",
                "--output-dir", str(output),
            ])
            self.assertEqual(status, 1)
            report = json.loads((output / "training-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["total_steps"], 0)
            self.assertFalse(report["commander"]["commander_max_level_gate_passed"])
            self.assertFalse((output / "map-aware-policy.pt").exists())

    def test_simulator_backend_runs_actual_session_path(self) -> None:
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "simulator"
            status = main([
                "--backend", "simulator",
                "--maps", "dead-of-night,void-launch",
                "--iterations", "1",
                "--rollout-steps", "2",
                "--max-episode-steps", "2",
                "--hidden-dim", "8",
                "--ppo-epochs", "1",
                "--batch-size", "2",
                "--output-dir", str(output),
            ])
            self.assertEqual(status, 0)
            report = json.loads((output / "training-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["backend"], "simulator")
            self.assertEqual(report["total_steps"], 4)

    def test_resume_loads_previous_map_aware_checkpoint(self) -> None:
        with TemporaryDirectory() as tmp:
            first = Path(tmp) / "first"
            second = Path(tmp) / "second"
            common = [
                "--backend", "fake",
                "--maps", "dead-of-night,void-launch",
                "--iterations", "1",
                "--rollout-steps", "2",
                "--max-episode-steps", "2",
                "--hidden-dim", "8",
                "--ppo-epochs", "1",
                "--batch-size", "2",
            ]
            self.assertEqual(main([*common, "--output-dir", str(first)]), 0)
            checkpoint = first / "map-aware-policy.pt"
            self.assertTrue(checkpoint.exists())
            self.assertEqual(
                main([*common, "--resume", str(checkpoint), "--output-dir", str(second)]),
                0,
            )
            report = json.loads((second / "training-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["config"]["resumed_from"], str(checkpoint.resolve()))


if __name__ == "__main__":
    unittest.main()
