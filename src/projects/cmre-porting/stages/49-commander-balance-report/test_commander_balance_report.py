"""Stage 49 commander balance report focused tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "src" / "projects" / "cmre-porting"))

from vibe.simulation_first_progression import (  # noqa: E402
    COMMANDER_UNIT_SLICE,
    PROGRESSION_SCHEMA_VERSION,
    build_progress_dashboard,
    build_stage_report,
    write_progress_dashboard,
    write_stage_report,
)


class Stage49CommanderBalanceReportTests(unittest.TestCase):
    def test_balance_report_has_rows_without_native_claim(self) -> None:
        report = build_stage_report(49)
        unit_ids = {row["unit_id"] for row in report["balance_rows"]}

        self.assertEqual(report["contract_schema_version"], "stage49-commander-balance-report.v1")
        self.assertEqual(report["progression_schema_version"], PROGRESSION_SCHEMA_VERSION)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["native_claim"])
        self.assertFalse(report["balance_basis"]["native_balance_claim"])
        self.assertEqual(report["native_differential"], "BLOCKED")
        self.assertTrue({"Marine", "Marauder", "SiegeTank"}.issubset(unit_ids))
        self.assertTrue(report["checks"]["rows_present"])
        self.assertTrue(report["checks"]["all_rows_label_fidelity"])
        self.assertTrue(all(row["fidelity"] == "APPROXIMATE" for row in report["balance_rows"]))

    def test_unit_slice_source_is_visible_and_not_native_certification(self) -> None:
        report = build_stage_report(48)
        slice_data = report["commander_unit_slice"]

        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["native_claim"])
        self.assertEqual(report["native_differential"], "BLOCKED")
        self.assertEqual(slice_data["requested_units"], list(COMMANDER_UNIT_SLICE))
        self.assertIn("not CMRE native commander import", slice_data["commander_scope"])
        self.assertIn("slice_hash", slice_data)

    def test_dashboard_truthfully_closes_stage49_and_opens_stage50(self) -> None:
        dashboard = build_progress_dashboard()

        self.assertEqual(dashboard["stage_count"], 17)
        self.assertEqual(dashboard["next_stage"], "50-vm-debugger-expansion")
        self.assertEqual(dashboard["summary"]["completed_stage_count"], 17)
        self.assertEqual(dashboard["summary"]["native_claim_count"], 0)
        self.assertEqual(dashboard["summary"]["native_differential_blocked_count"], 17)
        self.assertEqual(dashboard["summary"]["report_status_counts"].get("BLOCKED"), 3)
        self.assertEqual(dashboard["summary"]["report_status_counts"].get("PASS"), 14)
        self.assertEqual(dashboard["stages"][-1]["stage"], "49-commander-balance-report")
        self.assertEqual(dashboard["stages"][-1]["stage_status"], "COMPLETE")

    def test_write_report_and_dashboard_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage49-balance-") as directory:
            output = Path(directory) / "stage49.json"
            dashboard_output = Path(directory) / "dashboard.json"
            report = write_stage_report(49, output)
            dashboard = write_progress_dashboard(dashboard_output)
            written_report = json.loads(output.read_text(encoding="utf-8"))
            written_dashboard = json.loads(dashboard_output.read_text(encoding="utf-8"))

        self.assertEqual(written_report["status"], report["status"])
        self.assertEqual(written_dashboard["stage_count"], dashboard["stage_count"])
        self.assertFalse(written_report["native_claim"])
        self.assertEqual(written_dashboard["next_stage"], "50-vm-debugger-expansion")


if __name__ == "__main__":
    unittest.main()
