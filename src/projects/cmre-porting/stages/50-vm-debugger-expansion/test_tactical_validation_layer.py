"""Stage 50 tactical validation layer focused tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "src" / "projects" / "cmre-porting"))

from vibe.consumers.tactical import (  # noqa: E402
    AB_COMPARE_RULE,
    AggressiveTimingPushStrategy,
    DelayedDefensiveBaselineStrategy,
    FocusFireStrategy,
    TACTICAL_REPORT_SCHEMA_VERSION,
    run_tactical_ab,
    run_tactical_batch,
    run_tactical_scenario,
    scenario_identity,
    sweep_tactical_ab,
    verify_tactical_determinism,
)


def _timing_push_scenario() -> dict:
    return {
        "schema_version": "m7",
        "name": "Stage50 timing push setback",
        "players": [
            {"id": 1, "name": "Terran", "race": "terran", "allies": [], "is_ai": True},
            {"id": 2, "name": "Zerg", "race": "zerg", "allies": [], "is_ai": True},
        ],
        "spawns": [
            {"unit_type_id": "Marine", "owner_player_id": 1, "x": 0.0, "y": 0.0},
            {"unit_type_id": "Marine", "owner_player_id": 1, "x": 1.0, "y": 0.0},
            {"unit_type_id": "Marine", "owner_player_id": 1, "x": 2.0, "y": 0.0},
            {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 6.0, "y": 0.0},
            {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 7.0, "y": 0.0},
            {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 8.0, "y": 0.0},
        ],
        "commands": [],
        "max_loops": 360,
        "seed": 42,
        "strict": True,
        "win_condition": "annihilation",
    }


class Stage50TacticalValidationLayerTests(unittest.TestCase):
    def test_tactical_report_v1_has_seed_batch_identity_and_reliability(self) -> None:
        scenario = _timing_push_scenario()
        seeds = [42, 43, 44]

        report = run_tactical_ab(
            scenario,
            AggressiveTimingPushStrategy(attack_loop=0),
            DelayedDefensiveBaselineStrategy(defend_until_loop=16),
            seeds=seeds,
            max_loops=260,
        )
        payload = report.to_dict()

        self.assertEqual(payload["schema_version"], TACTICAL_REPORT_SCHEMA_VERSION)
        self.assertEqual(payload["run_mode"], "seed_batch")
        self.assertEqual(payload["scenario_id"], scenario_identity(scenario)["scenario_id"])
        self.assertEqual(payload["scenario_version"], scenario_identity(scenario)["scenario_version"])
        self.assertEqual(payload["seed_batch"]["seeds"], seeds)
        self.assertEqual(payload["seed_batch"]["n_runs"], len(seeds))
        self.assertIn("success_rate", payload["seed_batch"]["strategy_a"])
        self.assertIn("completion_time", payload["seed_batch"]["strategy_a"])
        self.assertEqual(payload["ab_comparison"]["compare_rule"], AB_COMPARE_RULE)
        self.assertIn(payload["result_reliability"], {"usable", "degraded", "not_reliable"})
        self.assertIn("unit_fidelity", payload["capability_coverage"])
        self.assertTrue(payload["architecture_gates"]["policy_uses_observation_action"])

    def test_runner_surfaces_are_deterministic_and_batchable(self) -> None:
        scenario = _timing_push_scenario()
        seed = 42

        single = run_tactical_scenario(scenario, FocusFireStrategy(), seed=seed, max_loops=240)
        batch = run_tactical_batch(scenario, FocusFireStrategy(), seeds=[seed, 43], max_loops=240)
        determinism = verify_tactical_determinism(scenario, FocusFireStrategy(), seed=seed, max_loops=240)

        self.assertTrue(single.trace_hash)
        self.assertEqual(batch.seed_count, 2)
        self.assertTrue(determinism["deterministic"])
        self.assertTrue(determinism["same_trace_hash"])
        self.assertTrue(determinism["same_end_loop"])

    def test_sweep_runs_each_parameter_point_as_seed_batch(self) -> None:
        scenario = _timing_push_scenario()

        reports = sweep_tactical_ab(
            scenario,
            AggressiveTimingPushStrategy(),
            DelayedDefensiveBaselineStrategy(),
            seeds=[42, 43],
            param_grid={"max_loops": [240, 260]},
            max_loops=240,
        )

        self.assertEqual(len(reports), 2)
        self.assertEqual([r.ab_comparison["sweep_params"]["max_loops"] for r in reports], [240, 260])
        self.assertTrue(all(r.seed_batch["n_runs"] == 2 for r in reports))


if __name__ == "__main__":
    unittest.main()
