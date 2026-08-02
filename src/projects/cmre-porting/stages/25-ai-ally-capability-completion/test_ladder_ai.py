"""Stage 25 full-game ladder AI simulator acceptance."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "src" / "projects" / "cmre-porting"))

from vibe.ladder_ai import (  # noqa: E402
    build_ladder_game_scenario,
    run_ladder_batch,
    run_ladder_game,
)


class LadderAiFullGameTests(unittest.TestCase):
    def test_scenario_declares_normal_cooperative_ladder_roster(self):
        scenario = build_ladder_game_scenario(seed=42, max_loops=5000)
        players = {int(player["id"]): player for player in scenario["players"]}
        self.assertEqual(players[1]["allies"], [2])
        self.assertEqual(players[2]["allies"], [1])
        self.assertTrue(players[2]["is_ai"])
        self.assertEqual(scenario["win_condition"], "enemy_elimination")
        self.assertEqual(
            scenario["win_condition_params"]["enemy_player_ids"],
            [3],
        )

    def test_full_game_reaches_victory_with_macro_and_tactics(self):
        report = run_ladder_game(seed=42, max_loops=5000)
        self.assertEqual(report.status, "PASS")
        self.assertTrue(report.victory)
        self.assertEqual(report.end_reason, "enemy_elimination")
        self.assertEqual(report.final_enemy_units_by_type, {})
        self.assertGreaterEqual(report.final_units_by_type.get("CommandCenter", 0), 2)
        self.assertGreaterEqual(report.final_units_by_type.get("Barracks", 0), 2)
        self.assertGreaterEqual(report.action_kind_counts.get("attack", 0), 1)
        self.assertEqual(report.error_breakdown, {})
        self.assertTrue(all(report.checks.values()))

    def test_full_game_is_deterministic_across_seeds(self):
        batch = run_ladder_batch(seeds=(7, 99), max_loops=5000)
        self.assertEqual(batch["status"], "PASS")
        self.assertEqual(len(batch["runs"]), 2)
        self.assertTrue(all(run["victory"] for run in batch["runs"]))
        self.assertTrue(all(run["checks"]["research"] for run in batch["runs"]))
        self.assertTrue(all(run["checks"]["pressure_response"] for run in batch["runs"]))

    def test_tool_exports_default_style_jsonl_and_single_file_player(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_ladder_game(
                seed=42,
                max_loops=5000,
                replay_dir=Path(directory),
            )
            replay_path = Path(report.replay_path)
            player_path = Path(report.replay_html_path)
            self.assertTrue(replay_path.is_file())
            self.assertTrue(player_path.is_file())
            self.assertEqual(replay_path.name, "replay.jsonl")
            self.assertEqual(player_path.name, "state-driven-player.html")
            self.assertGreater(report.replay_frame_count, 100)
            html = player_path.read_text(encoding="utf-8")
            self.assertIn("CMRE 梯队 AI 完整局回放", html)
            self.assertIn(">VICTORY<", html)
            self.assertIn('"end_reason":"enemy_elimination"', html)
            self.assertIn('"runtime_claim":"none; simulator evidence only"', html)


if __name__ == "__main__":
    unittest.main()
