"""Stage 29 normal-start macro-bootstrap contract tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "src" / "projects" / "cmre-porting"))

from vibe.normal_start_contract import (  # noqa: E402
    CONTRACT_SCHEMA_VERSION,
    REQUIRED_CHECKS,
    build_normal_start_scenario,
    run_normal_start_contract,
)


class Stage29NormalStartContractTests(unittest.TestCase):
    def test_scenario_declares_fair_no_enemy_normal_start(self):
        scenario = build_normal_start_scenario(seed=29, max_loops=900)
        players = {int(player["id"]): player for player in scenario["players"]}
        self.assertEqual(players[1]["race"], "terran")
        self.assertEqual(players[2]["race"], "terran")
        self.assertEqual(players[1]["allies"], [2])
        self.assertEqual(players[2]["allies"], [1])
        self.assertEqual(scenario["initial_minerals"], 50)
        self.assertEqual(scenario["initial_vespene"], 0)
        self.assertEqual(scenario["_cooperative_enemy_player_ids"], [])

        p1_units = [
            spawn["unit_type_id"] for spawn in scenario["spawns"]
            if int(spawn["owner_player_id"]) == 1
        ]
        p2_units = [
            spawn["unit_type_id"] for spawn in scenario["spawns"]
            if int(spawn["owner_player_id"]) == 2
        ]
        self.assertEqual(p1_units, p2_units)
        self.assertEqual(p1_units.count("CommandCenter"), 1)
        self.assertEqual(p1_units.count("SCV"), 12)
        self.assertEqual(set(p1_units), {"CommandCenter", "SCV"})

    def test_contract_passes_required_macro_bootstrap_checks(self):
        report = run_normal_start_contract(seed=29, max_loops=900)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["contract_schema_version"], CONTRACT_SCHEMA_VERSION)
        self.assertEqual(report["result_category"], "macro_bootstrap")
        self.assertFalse(report["native_claim"])
        self.assertEqual(
            report["runtime_claim"],
            "none; deterministic simulator macro-bootstrap only",
        )
        for check_name in REQUIRED_CHECKS:
            self.assertTrue(report["checks"][check_name], check_name)
        self.assertTrue(report["checks"]["initial_state_fair"])
        self.assertTrue(report["checks"]["no_initial_adapter_advantage"])
        self.assertTrue(report["checks"]["enemy_none"])
        self.assertEqual(report["summary"]["error_breakdown"], {})
        self.assertGreaterEqual(report["summary"]["final_units_by_type"].get("Marine", 0), 1)
        self.assertGreater(report["check_details"]["earned_minerals_lower_bound"], 0)

    def test_contract_writes_report_artifact(self):
        with tempfile.TemporaryDirectory(prefix="stage29-normal-start-") as directory:
            output_path = Path(directory) / "normal-start-contract.json"
            report = run_normal_start_contract(output_path=output_path)
            self.assertTrue(output_path.is_file())
            written = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(written["status"], report["status"])
            self.assertEqual(written["contract_schema_version"], CONTRACT_SCHEMA_VERSION)
            self.assertFalse(written["native_claim"])


if __name__ == "__main__":
    unittest.main()
