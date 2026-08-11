"""Offline contract tests for the Stage 10 live policy evaluator."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "evaluate_live_policy.py"
SPEC = importlib.util.spec_from_file_location("evaluate_live_policy", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
EVALUATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVALUATOR)


class LivePolicyEvalTests(unittest.TestCase):
    def test_parse_map_spec_requires_launcher_and_packed_path(self) -> None:
        parsed = EVALUATOR.parse_map_spec("void-launch|虚空降临.SC2Map|maps/void.SC2Map")
        self.assertEqual(parsed["map_id"], "void-launch")
        self.assertEqual(parsed["launcher_map_name"], "虚空降临.SC2Map")
        self.assertTrue(parsed["map_path"].endswith("maps\\void.SC2Map") or parsed["map_path"].endswith("maps/void.SC2Map"))
        with self.assertRaises(ValueError):
            EVALUATOR.parse_map_spec("void-launch|missing")

    def test_command_has_terminal_replay_and_variant_contract(self) -> None:
        command = EVALUATOR.build_run_command(
            checkpoint=Path("checkpoint.pt"),
            map_spec={
                "map_id": "dead-of-night",
                "launcher_map_name": "亡者之夜.SC2Map",
                "map_path": "dead.SC2Map",
            },
            variant="deterministic-baseline",
            port=5960,
            max_steps=64,
            step_mul=8,
            output=Path("report.json"),
            launcher_suffix="stage10-test",
            python_executable="python",
        )
        self.assertIn("--stop-on-terminal", command)
        self.assertIn("--save-replay", command)
        self.assertIn("--commander-enforce", command)
        self.assertEqual(command[command.index("--commander-level") + 1], "15")
        self.assertEqual(command[command.index("--commander-mastery") + 1], "full")
        self.assertIn("--deterministic", command)
        self.assertEqual(command[command.index("--variant") + 1], "deterministic-baseline")

    def test_summary_is_blocked_without_terminal_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "policy.pt"
            checkpoint.write_bytes(b"policy")
            summary = EVALUATOR.summarize_reports(
                [{
                    "status": "passed",
                    "runtime_gate": True,
                    "terminal_observed": False,
                    "script_error_verdict": {"has_new_errors": False},
                    "commander": {"commander_max_level_gate_passed": True},
                }],
                checkpoint=checkpoint,
                maps=[{"map_id": "dead-of-night"}],
                variants=["frozen-stochastic"],
            )
        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["terminal_count"], 0)
        self.assertIsNone(summary["win_rate"])

    def test_summary_counts_terminal_victory_and_clean_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "policy.pt"
            checkpoint.write_bytes(b"policy")
            summary = EVALUATOR.summarize_reports(
                [{
                    "status": "passed",
                    "runtime_gate": True,
                    "terminal_observed": True,
                    "terminal_results": [{"player_id": 1, "result_name": "victory"}],
                    "script_error_verdict": {"has_new_errors": False},
                    "commander": {"commander_max_level_gate_passed": True},
                }],
                checkpoint=checkpoint,
                maps=[{"map_id": "dead-of-night"}],
                variants=["frozen-stochastic"],
            )
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["victory_count"], 1)
        self.assertEqual(summary["win_rate"], 1.0)
