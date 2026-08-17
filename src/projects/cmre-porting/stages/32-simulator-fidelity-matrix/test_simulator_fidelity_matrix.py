"""Stage 32 simulator fidelity matrix contract tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "src" / "projects" / "cmre-porting"))

from vibe.simulator_fidelity_matrix import (  # noqa: E402
    NATIVE_DIFFERENTIAL_STATUS,
    REPORT_SCHEMA_VERSION,
    build_fidelity_matrix,
    write_fidelity_matrix,
)


class Stage32SimulatorFidelityMatrixTests(unittest.TestCase):
    def test_matrix_contains_all_roadmap_rows_and_domains(self):
        report = build_fidelity_matrix()
        rows = report["matrix"]
        expected = {
            ("Unit", "HP/Shield"), ("Unit", "Armor"),
            ("Weapon", "Damage"), ("Weapon", "Period"),
            ("Weapon", "Range"), ("Weapon", "Target Filter"),
            ("Movement", "Speed"), ("Movement", "Acceleration"),
            ("Movement", "Collision"), ("Combat", "Damage"),
            ("Combat", "Splash"), ("Combat", "Search"),
            ("Economy", "Gather"), ("Economy", "Deposit"),
            ("Production", "Train"), ("Upgrade", "Modifier"),
            ("Ability", "Cost"), ("Ability", "Cooldown"),
            ("Ability", "Effect"), ("Vision", "Sight"),
            ("Terrain", "Walkable"), ("Terrain", "Height"),
            ("Pathing", "Path"), ("Trigger", "Event"),
            ("Trigger", "Condition"), ("Trigger", "Action"),
            ("Mission", "Objective"),
        }
        self.assertEqual(len(rows), 27)
        self.assertEqual({(row["domain"], row["feature"]) for row in rows}, expected)
        self.assertEqual(report["summary"]["row_count"], 27)
        self.assertEqual(report["status"], "PASS")

    def test_matrix_is_truthful_about_native_differential_and_unsupported_scope(self):
        report = build_fidelity_matrix()
        self.assertFalse(report["native_claim"])
        self.assertEqual(report["evidence_type"], "simulator")
        self.assertEqual(report["runtime_claim"].split(";")[0], "none")
        self.assertTrue(all(row["tested"] for row in report["matrix"]))
        self.assertTrue(all(row["native_differential"] == NATIVE_DIFFERENTIAL_STATUS for row in report["matrix"]))
        acceleration = next(row for row in report["matrix"] if row["feature"] == "Acceleration")
        self.assertFalse(acceleration["supported"])
        self.assertEqual(acceleration["fidelity"], "UNSUPPORTED")
        self.assertGreater(report["summary"]["unsupported_count"], 0)
        self.assertTrue(report["checks"]["native_differential_truthful"])

    def test_matrix_has_source_provenance_and_passed_inputs(self):
        report = build_fidelity_matrix()
        self.assertTrue(report["checks"]["all_rows_have_provenance"])
        self.assertTrue(report["checks"]["catalog_baseline_pass"])
        self.assertTrue(report["checks"]["normal_start_baseline_pass"])
        self.assertTrue(report["source_policy"]["reference_source_read_only"])
        self.assertTrue(report["source_policy"]["native_observation_required_for_differential"])
        for row in report["matrix"]:
            self.assertTrue(row["source"], row)
            self.assertTrue(row["test_id"], row)
            self.assertEqual(row["native_differential_reason"], report["matrix"][0]["native_differential_reason"])

    def test_matrix_writes_schema_valid_artifact(self):
        with tempfile.TemporaryDirectory(prefix="stage32-fidelity-") as directory:
            output = Path(directory) / "fidelity-matrix.json"
            report = write_fidelity_matrix(output)
            self.assertTrue(output.is_file())
            written = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(written["contract_schema_version"], REPORT_SCHEMA_VERSION)
        self.assertEqual(written["status"], report["status"])
        self.assertEqual(written["summary"]["row_count"], 27)
        self.assertFalse(written["native_claim"])


if __name__ == "__main__":
    unittest.main()
