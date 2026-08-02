import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "src" / "projects" / "cmre-porting"))

from vibe.map_extractor import ExtractionStats, MapData  # noqa: E402
from vibe.run_dead_of_night import (  # noqa: E402
    CLEAR_PUSH_COMMAND_INTERVAL,
    build_night_waves,
    run_dead_of_night,
)
from vibe.simulator_session import SimulatorSession  # noqa: E402


STAGE_DIR = Path(__file__).resolve().parent


def _synthetic_map(spawns, start_loop=1000, end_loop=1200):
    players = [
        {"id": 1, "name": "Ally", "race": "terran", "allies": [], "is_ai": True},
        {"id": 3, "name": "Enemy", "race": "zerg", "allies": [], "is_ai": True},
        {"id": 4, "name": "WaveEnemy", "race": "zerg", "allies": [], "is_ai": True},
        {"id": 5, "name": "Infected", "race": "zerg", "allies": [], "is_ai": True},
    ]
    scenario = {
        "schema_version": "m7",
        "name": "stage19-synthetic-dead-of-night",
        "players": players,
        "spawns": list(spawns),
        "commands": [],
        "max_loops": 3000,
        "seed": 42,
        "strict": False,
        "win_condition": "custom",
    }
    wave_timing = {
        "total_nights": 1,
        "nights": [
            {
                "night_number": 1,
                "start_loop": start_loop,
                "end_loop": end_loop,
                "difficulty": "light",
            }
        ],
    }
    return MapData(
        scenario=scenario,
        regions=[],
        stats=ExtractionStats(),
        map_bounds={"min_x": 0, "min_y": 0, "max_x": 200, "max_y": 200},
        wave_timing=wave_timing,
    )


class TestSimulatorAiAllyClearance(unittest.TestCase):
    def _run(self, data, **kwargs):
        with tempfile.TemporaryDirectory(prefix="stage19-sim-") as temp_dir:
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
            frames = [
                json.loads(line)
                for line in replay_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            return report, frames

    def test_night_infection_day_cleanup_and_building_reinforcement(self):
        data = _synthetic_map(
            [
                {
                    "unit_type_id": "MissileTurret",
                    "owner_player_id": 3,
                    "x": 85.0,
                    "y": 94.0,
                }
            ],
            start_loop=2,
            end_loop=6,
        )
        report, _ = self._run(
            data,
            max_loops=8,
            time_scale=1.0,
        )

        self.assertGreater(report.infected_spawned, 0)
        self.assertEqual(report.infected_cleared_in_day, report.infected_spawned)
        self.assertGreater(report.building_reinforcements_spawned, 0)
        self.assertEqual(report.victory_mode, "clear_enemy_structures")
        self.assertEqual(report.end_reason, "max_loops_reached")

    def test_destroyed_target_is_reallocated_after_stale_target(self):
        data = _synthetic_map(
            [
                {
                    "unit_type_id": "MissileTurret",
                    "owner_player_id": 3,
                    "x": 85.0,
                    "y": 94.0,
                },
                {
                    "unit_type_id": "MissileTurret",
                    "owner_player_id": 3,
                    "x": 86.0,
                    "y": 94.0,
                },
            ]
        )
        report, _ = self._run(
            data,
            max_loops=100,
            time_scale=0.02,
        )

        self.assertEqual(report.verdict, "victory")
        self.assertEqual(report.end_reason, "all_objectives_success")
        self.assertEqual(report.initial_enemy_structures, 2)
        self.assertEqual(report.remaining_enemy_structures, 0)
        self.assertGreaterEqual(report.end_loop, CLEAR_PUSH_COMMAND_INTERVAL)
        self.assertGreaterEqual(report.cmd_ok_stats.get("push", 0), 2)
        self.assertEqual(report.cmd_fail_stats, {})
        self.assertGreater(report.event_summary.get("total", 0), 0)
        self.assertIn("payload_totals", report.event_summary)
        allocation = report.target_allocation_summary
        self.assertEqual(allocation.get("push_units_spawned"), 1)
        self.assertGreaterEqual(allocation.get("allocations", 0), 2)
        self.assertGreaterEqual(allocation.get("reallocations", 0), 1)
        self.assertEqual(
            allocation.get("reallocation_reasons", {}).get("target_destroyed"),
            allocation.get("reallocations"),
        )

    def test_dead_push_unit_is_ignored_by_later_dispatch(self):
        data = _synthetic_map(
            [
                {
                    "unit_type_id": "MissileTurret",
                    "owner_player_id": 3,
                    "x": 85.0,
                    "y": 94.0,
                },
                {
                    "unit_type_id": "MissileTurret",
                    "owner_player_id": 3,
                    "x": 100.0,
                    "y": 94.0,
                },
            ]
        )
        original_step = SimulatorSession.scenario_step
        step_calls = 0

        def kill_one_push_unit_after_first_dispatch(session, loops=1, snapshot=True):
            nonlocal step_calls
            result = original_step(session, loops, snapshot)
            step_calls += 1
            if step_calls == 2:
                push_units = [
                    entity
                    for entity in session.world.entities.values()
                    if entity.owner_player_id == 1 and entity.is_alive
                ]
                self.assertEqual(len(push_units), 2)
                push_units[0].health = push_units[0].health.__class__.zero()
                from sc2_simulator.world.entity import UnitState

                push_units[0].state = UnitState.DEAD
            return result

        with patch.object(
            SimulatorSession,
            "scenario_step",
            new=kill_one_push_unit_after_first_dispatch,
        ):
            report, _ = self._run(
                data,
                max_loops=70,
                time_scale=1.0,
                push_army_size=2,
            )

        self.assertEqual(report.end_reason, "max_loops_reached")
        self.assertEqual(report.player1_survivors, 1)
        self.assertEqual(report.total_commands_issued, 3)
        self.assertEqual(report.cmd_fail_stats, {})
        self.assertEqual(
            report.target_allocation_summary.get("push_units_spawned"), 2
        )
        self.assertEqual(report.target_allocation_summary.get("push_units_dead_filtered"), 1)

    def test_wall_clock_exhaustion_is_inconclusive_with_live_structures(self):
        data = _synthetic_map(
            [
                {
                    "unit_type_id": "MissileTurret",
                    "owner_player_id": 3,
                    "x": 85.0,
                    "y": 94.0,
                }
            ]
        )
        report, _ = self._run(
            data,
            max_loops=200,
            time_scale=0.02,
            wall_time_budget_sec=0.0,
        )

        self.assertEqual(report.verdict, "inconclusive")
        self.assertEqual(report.end_reason, "time_budget_exceeded")
        self.assertEqual(report.remaining_enemy_structures, 1)
        self.assertEqual(report.objectives[0]["status"], "active")

    def test_wave_seed_is_deterministic(self):
        data = _synthetic_map([])
        first = build_night_waves(data.wave_timing, time_scale=0.02, strength_scale=0.25, seed=7)
        second = build_night_waves(data.wave_timing, time_scale=0.02, strength_scale=0.25, seed=7)
        other = build_night_waves(data.wave_timing, time_scale=0.02, strength_scale=0.25, seed=8)

        self.assertEqual(
            [(wave.name, wave.at_loop, wave.spawns) for wave in first],
            [(wave.name, wave.at_loop, wave.spawns) for wave in second],
        )
        self.assertNotEqual(
            [(wave.name, wave.at_loop, wave.spawns) for wave in first],
            [(wave.name, wave.at_loop, wave.spawns) for wave in other],
        )


if __name__ == "__main__":
    unittest.main()
