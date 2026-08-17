"""Stage 33 world-state observability focused tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "src" / "projects" / "cmre-porting"))

from vibe.world_state_observability import (  # noqa: E402
    CONTRACT_SCHEMA_VERSION,
    DOMAIN_NAMES,
    build_observability_contract,
    write_observability_contract,
)


class Stage33WorldStateObservabilityTests(unittest.TestCase):
    def test_contract_covers_required_domains_without_native_claim(self) -> None:
        report = build_observability_contract(max_loops=180)
        domains = {domain["name"]: domain for domain in report["domains"]}

        self.assertEqual(report["contract_schema_version"], CONTRACT_SCHEMA_VERSION)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["native_claim"])
        self.assertEqual(report["native_differential"], "BLOCKED")
        self.assertEqual(set(DOMAIN_NAMES), set(domains))
        self.assertTrue(report["checks"]["all_required_domains_present"])
        self.assertTrue(report["checks"]["no_hidden_state_omission"])
        self.assertTrue(report["source_policy"]["reference_simulator_read_only"])

    def test_hashes_and_trace_are_deterministic(self) -> None:
        report = build_observability_contract(max_loops=180)

        self.assertTrue(report["snapshot_identity"]["state_hash_consistent"])
        self.assertTrue(report["snapshot_identity"]["deterministic_across_runs"])
        self.assertTrue(report["trace_identity"]["trace_hash_consistent"])
        self.assertTrue(report["checks"]["deterministic_across_runs"])
        self.assertGreaterEqual(report["trace_identity"]["event_count"], 1)

    def test_write_contract_artifact_and_trace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage33-observability-") as directory:
            output = Path(directory) / "observability.json"
            trace_output = Path(directory) / "observability.trace.jsonl"
            report = write_observability_contract(output, trace_output=trace_output, max_loops=180)
            written = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(written["status"], report["status"])
        self.assertEqual(written["contract_schema_version"], CONTRACT_SCHEMA_VERSION)
        self.assertIn("trace_artifact_sha256", written["trace_identity"])
        self.assertTrue(written["checks"]["native_claim_false"])


if __name__ == "__main__":
    unittest.main()
