"""Audit-focused regression tests for the Stage 20 simulator controller."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "src" / "projects" / "cmre-porting"))

from vibe.map_extractor import ExtractionStats, MapData  # noqa: E402
from vibe.run_dead_of_night import run_dead_of_night  # noqa: E402
from vibe.simulator_session import SimulatorSession  # noqa: E402


def _synthetic_map(spawns, start_loop=1000, end_loop=1200):
    scenario = {
        "schema_version": "m7",
        "name": "stage20-synthetic-dead-of-night",
        "players": [
            {"id": 1, "name": "Ally", "race": "terran", "allies": [], "is_ai": True},
            {"id": 3, "name": "Enemy", "race": "zerg", "allies": [], "is_ai": True},
            {"id": 4, "name": "WaveEnemy", "race": "zerg", "allies": [], "is_ai": True},
            {"id": 5, "name": "Infected", "race": "zerg", "allies": [], "is_ai": True},
        ],
        "spawns": list(spawns),
        "commands": [],
        "max_loops": 3000,
        "seed": 42,
        "strict": False,
        "win_condition": "custom",
    }
    return MapData(
        scenario=scenario,
        regions=[],
        stats=ExtractionStats(),
        map_bounds={"min_x": 0, "min_y": 0, "max_x": 200, "max_y": 200},
        wave_timing={
            "total_nights": 1,
            "nights": [
                {
                    "night_number": 1,
                    "start_loop": start_loop,
                    "end_loop": end_loop,
                    "difficulty": "light",
                }
            ],
        },
    )


class AdversarialHardeningTests(unittest.TestCase):
    def _run(self, data, **kwargs):
        with tempfile.TemporaryDirectory(prefix="stage20-sim-") as temp_dir:
            replay_path = Path(temp_dir) / "replay.jsonl"
            defaults = {
                "include_preset_enemies": False,
                "enable_enemy_ai": False,
                "enable_player_ai": False,
                "verbose": False,
                "clear_enemy_structures": True,
                "replay_log_path": str(replay_path),
                "wave_strength_scale": 0.25,
                "push_army_size": 1,
                "push_unit_type": "Battlecruiser",
            }
            defaults.update(kwargs)
            with patch("vibe.run_dead_of_night.extract_dead_of_night", return_value=data):
                report = run_dead_of_night(**defaults)
            replay = [
                json.loads(line)
                for line in replay_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            return report, replay

    def test_target_summary_records_stale_target_reallocation(self):
        report, _ = self._run(
            _synthetic_map(
                [
                    {"unit_type_id": "MissileTurret", "owner_player_id": 3, "x": 85.0, "y": 94.0},
                    {"unit_type_id": "MissileTurret", "owner_player_id": 3, "x": 86.0, "y": 94.0},
                ]
            ),
            max_loops=100,
            time_scale=0.02,
        )

        summary = report.target_allocation_summary
        self.assertEqual(report.verdict, "victory")
        self.assertEqual(report.remaining_enemy_structures, 0)
        self.assertGreaterEqual(summary["allocations"], 2)
        self.assertGreaterEqual(summary["reallocations"], 1)
        self.assertEqual(summary["reallocation_reasons"], {"target_destroyed": 1})
        self.assertEqual(summary["unique_targets_assigned"], 2)

    def test_controlled_push_loss_is_visible_in_event_and_target_summaries(self):
        data = _synthetic_map(
            [
                {"unit_type_id": "MissileTurret", "owner_player_id": 3, "x": 85.0, "y": 94.0},
                {"unit_type_id": "MissileTurret", "owner_player_id": 3, "x": 100.0, "y": 94.0},
            ]
        )
        original_step = SimulatorSession.scenario_step
        step_calls = 0

        def kill_one_push_unit(session, loops=1, snapshot=True):
            nonlocal step_calls
            result = original_step(session, loops, snapshot)
            step_calls += 1
            if step_calls == 2:
                push_units = [
                    entity
                    for entity in session.world.entities.values()
                    if entity.owner_player_id == 1 and entity.is_alive
                ]
                push_units[0].health = push_units[0].health.__class__.zero()
                from sc2_simulator.world.entity import UnitState

                push_units[0].state = UnitState.DEAD
            return result

        with patch.object(SimulatorSession, "scenario_step", new=kill_one_push_unit):
            report, _ = self._run(data, max_loops=70, time_scale=1.0, push_army_size=2)

        self.assertEqual(report.player1_survivors, 1)
        self.assertGreaterEqual(report.event_summary["counts"].get("death", 0), 1)
        self.assertEqual(report.target_allocation_summary["push_units_dead_filtered"], 1)

    def test_event_summary_separates_event_count_from_payload_total(self):
        report, _ = self._run(
            _synthetic_map(
                [{"unit_type_id": "MissileTurret", "owner_player_id": 3, "x": 85.0, "y": 94.0}],
                start_loop=2,
                end_loop=6,
            ),
            max_loops=8,
            time_scale=1.0,
        )

        summary = report.event_summary
        self.assertGreater(summary["counts"].get("infected_spawned", 0), 0)
        self.assertEqual(
            summary["payload_totals"]["infected_cleared_day"],
            report.infected_cleared_in_day,
        )
        self.assertEqual(
            summary["payload_totals"]["building_reinforcements"],
            report.building_reinforcements_spawned,
        )

    def test_three_seed_reports_keep_clearance_and_audit_contract(self):
        report_dir = (
            REPO_ROOT
            / "artifacts"
            / "projects"
            / "cmre-porting"
            / "stage20-simulator-ai-ally-adversarial-hardening"
        )
        for seed in (42, 7, 99):
            with self.subTest(seed=seed):
                report = json.loads(
                    (report_dir / f"clear-seed-{seed}.json").read_text(encoding="utf-8")
                )
                self.assertEqual(report["verdict"], "victory")
                self.assertEqual(report["end_reason"], "all_objectives_success")
                self.assertEqual(report["initial_enemy_structures"], 344)
                self.assertEqual(report["remaining_enemy_structures"], 0)
                self.assertGreater(report["event_summary"]["counts"]["death"], 0)
                self.assertEqual(
                    report["event_summary"]["payload_totals"]["infected_cleared_day"],
                    report["infected_cleared_in_day"],
                )
                self.assertEqual(
                    report["event_summary"]["payload_totals"]["building_reinforcements"],
                    report["building_reinforcements_spawned"],
                )
                target_summary = report["target_allocation_summary"]
                self.assertGreater(target_summary["reallocations"], 0)
                self.assertEqual(
                    target_summary["reallocation_reasons"]["target_destroyed"],
                    target_summary["reallocations"],
                )
                self.assertEqual(report["cmd_fail_stats"], {})


if __name__ == "__main__":
    unittest.main()
