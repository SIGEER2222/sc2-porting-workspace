"""Tests for commander max-level / full-mastery validation (plan Stage 2)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cmre_rl_training.commander_profile import (
    build_commander_profile,
    commander_report_fields,
    get_commander_spec,
    read_commander_evidence,
    read_launch_profile_bank,
    validate_commander_profile,
)


class CommanderSpecTests(unittest.TestCase):
    def test_known_raynor_is_max_level_15(self) -> None:
        spec = get_commander_spec("TerranRaynor")
        self.assertEqual(spec.max_level, 15)
        self.assertTrue(spec.known)

    def test_unknown_commander_defaults_to_max_level(self) -> None:
        spec = get_commander_spec("SomeFutureCommander")
        self.assertEqual(spec.max_level, 15)
        self.assertFalse(spec.known)


class CommanderValidationTests(unittest.TestCase):
    def test_max_level_full_mastery_passes(self) -> None:
        profile = build_commander_profile("TerranRaynor", level=15, mastery="full")
        validation = validate_commander_profile(profile)
        self.assertTrue(validation["passed"])
        self.assertTrue(validation["level_ok"])
        self.assertTrue(validation["mastery_ok"])
        self.assertEqual(validation["effective_level"], 15)
        self.assertEqual(validation["evidence_source"], "config")

    def test_default_declared_level_is_max_level(self) -> None:
        # Omitting --commander-level defaults the declared level to the max.
        profile = build_commander_profile("TerranRaynor", mastery="full")
        validation = validate_commander_profile(profile)
        self.assertTrue(validation["passed"])
        self.assertEqual(validation["effective_level"], 15)

    def test_underleveled_commander_fails(self) -> None:
        profile = build_commander_profile("TerranRaynor", level=7, mastery="full")
        validation = validate_commander_profile(profile)
        self.assertFalse(validation["passed"])
        self.assertFalse(validation["level_ok"])
        self.assertIn("below max level", " ".join(validation["reasons"]))

    def test_missing_level_and_mastery_fails(self) -> None:
        profile = build_commander_profile("TerranRaynor")
        profile.declared_mastery = None
        profile.declared_level = None
        validation = validate_commander_profile(profile)
        self.assertFalse(validation["passed"])
        self.assertIsNone(validation["evidence_source"])
        self.assertTrue(any("no commander" in r for r in validation["reasons"]))

    def test_partial_mastery_fails_when_full_required(self) -> None:
        profile = build_commander_profile("TerranRaynor", level=15, mastery="partial")
        validation = validate_commander_profile(profile)
        self.assertFalse(validation["passed"])
        self.assertTrue(validation["level_ok"])
        self.assertFalse(validation["mastery_ok"])

    def test_observed_evidence_overrides_declared(self) -> None:
        profile = build_commander_profile("TerranRaynor", level=15, mastery="full")
        profile.observed_level = 7
        profile.evidence_source = "bank"
        validation = validate_commander_profile(profile)
        self.assertFalse(validation["passed"])
        self.assertEqual(validation["effective_level"], 7)
        self.assertTrue(validation["runtime_proven"])


class CommanderEvidenceTests(unittest.TestCase):
    @staticmethod
    def _write_launch_profile_bank(
        path: Path,
        *,
        commander_id: str = "TerranRaynor",
        level: int = 15,
        mastery_values=None,
    ) -> None:
        if mastery_values is None:
            mastery_values = [30, 30, 30, 30, 30, 30]
        mastery_keys = "\n".join(
            f'    <Key name="Player|1|Mastery|{slot}|Value"><Value int="{value}" /></Key>'
            for slot, value in enumerate(mastery_values, start=1)
        )
        path.write_text(
            f"""<?xml version="1.0" encoding="utf-8"?>
<Bank version="1">
  <Section name="CMUI|LaunchProfile">
    <Key name="Player|1|Commander"><Value string="{commander_id}" /></Key>
    <Key name="Player|1|CommanderLevel"><Value int="{level}" /></Key>
    <Key name="Player|1|MasteryCount"><Value int="6" /></Key>
    <Key name="Player|1|MasteryLevel"><Value int="180" /></Key>
{mastery_keys}
  </Section>
</Bank>
""",
            encoding="utf-8",
        )

    def test_read_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.json"
            path.write_text(json.dumps({
                "commander_id": "TerranRaynor",
                "level": 15,
                "mastery": "full",
                "source": "bank",
            }), encoding="utf-8")
            evidence = read_commander_evidence(path)
        self.assertEqual(evidence["level"], 15)
        self.assertEqual(evidence["mastery"], "full")
        self.assertEqual(evidence["source"], "bank")

    def test_build_profile_from_evidence_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.json"
            path.write_text(json.dumps({"level": 15, "mastery": "full"}), encoding="utf-8")
            profile = build_commander_profile("TerranRaynor", evidence_path=path)
        validation = validate_commander_profile(profile)
        self.assertTrue(validation["passed"])
        self.assertTrue(validation["runtime_proven"])
        self.assertEqual(validation["evidence_source"], "bank")

    def test_missing_evidence_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            read_commander_evidence("does-not-exist.json")

    def test_read_launch_profile_bank_as_runtime_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "CMCoopLaunchProfile.SC2Bank"
            self._write_launch_profile_bank(path)
            evidence = read_launch_profile_bank(path)
            profile = build_commander_profile("TerranRaynor", evidence_path=path)
        validation = validate_commander_profile(profile)
        self.assertEqual(evidence["level"], 15)
        self.assertEqual(evidence["mastery"], "full")
        self.assertEqual(evidence["mastery_values"], [30, 30, 30, 30, 30, 30])
        self.assertTrue(validation["passed"])
        self.assertTrue(validation["runtime_proven"])
        self.assertEqual(validation["evidence_source"], "bank")

    def test_launch_profile_bank_overrides_underleveled_saved_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "CMCoopLaunchProfile.SC2Bank"
            self._write_launch_profile_bank(path, level=7)
            profile = build_commander_profile("TerranRaynor", level=15, mastery="full", evidence_path=path)
        validation = validate_commander_profile(profile)
        self.assertFalse(validation["passed"])
        self.assertEqual(validation["effective_level"], 7)

    def test_launch_profile_bank_requires_all_mastery_slots_full(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "CMCoopLaunchProfile.SC2Bank"
            self._write_launch_profile_bank(path, mastery_values=[30, 0, 30, 30, 30, 30])
            profile = build_commander_profile("TerranRaynor", level=15, mastery="full", evidence_path=path)
        validation = validate_commander_profile(profile)
        self.assertFalse(validation["passed"])
        self.assertEqual(validation["effective_mastery"], "partial")

    def test_launch_profile_bank_rejects_a_different_maxed_commander(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "CMCoopLaunchProfile.SC2Bank"
            self._write_launch_profile_bank(path, commander_id="TerranAlenger3")
            profile = build_commander_profile(
                "TerranRaynor", level=15, mastery="full", evidence_path=path
            )
        validation = validate_commander_profile(profile)
        self.assertFalse(validation["passed"])
        self.assertFalse(validation["identity_ok"])
        self.assertEqual(validation["commander_id"], "TerranRaynor")
        self.assertEqual(validation["observed_commander_id"], "TerranAlenger3")
        self.assertIn("identity mismatch", " ".join(validation["reasons"]))


class CommanderReportFieldsTests(unittest.TestCase):
    def test_report_fields_roundtrip(self) -> None:
        profile = build_commander_profile("TerranRaynor", level=15, mastery="full")
        validation = validate_commander_profile(profile)
        fields = commander_report_fields(profile, validation)
        self.assertEqual(fields["commander_id"], "TerranRaynor")
        self.assertEqual(fields["commander_level"], 15)
        self.assertEqual(fields["commander_max_level"], 15)
        self.assertTrue(fields["commander_max_level_gate_passed"])
        self.assertFalse(fields["commander_runtime_proven"])
        self.assertEqual(fields["commander_evidence_source"], "config")
        self.assertIn("commander_gate_reasons", fields)


if __name__ == "__main__":
    unittest.main()
