"""Focused tests for Stage 30 differential-report.v1."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "src" / "projects" / "cmre-porting"))

from vibe.differential_validation import (  # noqa: E402
    COMPARISON_SCOPE,
    OBSERVATION_SCHEMA_VERSION,
    REPORT_SCHEMA_VERSION,
    NormalizedObservation,
    build_stage30_fixture_report,
    compare_observations,
    write_stage30_fixture_report,
)


def _observation(source: str, evidence_type: str = "simulator") -> NormalizedObservation:
    values = {
        scope: {
            "value": {"scope": scope, "value": 1},
            "fidelity": "EXACT",
        }
        for scope in COMPARISON_SCOPE
    }
    return NormalizedObservation(
        fixture_id="fixture-test-30",
        source=source,
        evidence_type=evidence_type,
        values=values,
    )


class Stage30DifferentialValidationTests(unittest.TestCase):
    def test_exact_runtime_observations_match_all_scopes(self):
        report = compare_observations(_observation("simulator"), _observation("native", "runtime"))

        self.assertEqual(report["contract_schema_version"], REPORT_SCHEMA_VERSION)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["native_claim"])
        self.assertTrue(report["summary"]["all_scopes_runtime_matched"])
        self.assertEqual(
            {item["status"] for item in report["comparisons"]},
            {"MATCH"},
        )

    def test_missing_native_observation_is_blocked_not_pass(self):
        report = compare_observations(_observation("simulator"), None)

        self.assertEqual(report["status"], "BLOCKED")
        self.assertFalse(report["summary"]["native_runtime_present"])
        self.assertEqual(
            {item["status"] for item in report["comparisons"]},
            {"NATIVE_MISSING"},
        )
        self.assertFalse(report["native_claim"])

    def test_inference_native_observation_cannot_be_promoted(self):
        report = compare_observations(_observation("simulator"), _observation("native", "inference"))

        self.assertEqual(report["status"], "PARTIAL")
        self.assertEqual(
            {item["status"] for item in report["comparisons"]},
            {"INFERENCE"},
        )
        self.assertFalse(report["summary"]["native_runtime_present"])

    def test_value_mismatch_is_failure(self):
        native = _observation("native", "runtime")
        native.values["cost"]["value"] = {"scope": "cost", "value": 2}

        report = compare_observations(_observation("simulator"), native)

        self.assertEqual(report["status"], "FAIL")
        by_scope = {item["scope"]: item for item in report["comparisons"]}
        self.assertEqual(by_scope["cost"]["status"], "MISMATCH")
        self.assertEqual(by_scope["entity_creation"]["status"], "MATCH")

    def test_stage30_fixture_artifact_is_truthful_and_schema_valid(self):
        report = build_stage30_fixture_report(seed=29, max_loops=900)

        self.assertEqual(report["contract_schema_version"], REPORT_SCHEMA_VERSION)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertFalse(report["native_claim"])
        self.assertEqual(report["stage29_contract"]["status"], "PASS")
        self.assertEqual(report["stage29_contract"]["schema_version"], "normal-start-contract.v1")
        self.assertEqual(len(report["fixture_coverage"]), 3)
        self.assertEqual(
            set(item["scope"] for item in report["comparisons"]),
            set(COMPARISON_SCOPE),
        )

    def test_stage30_fixture_writes_json_artifact(self):
        with tempfile.TemporaryDirectory(prefix="stage30-differential-") as directory:
            output_path = Path(directory) / "differential-report.json"
            report = write_stage30_fixture_report(output_path)
            written = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(written["status"], report["status"])
        self.assertEqual(written["contract_schema_version"], REPORT_SCHEMA_VERSION)
        self.assertEqual(OBSERVATION_SCHEMA_VERSION, "differential-observation.v1")
        self.assertFalse(written["native_claim"])


if __name__ == "__main__":
    unittest.main()
