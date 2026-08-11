"""`--commander-enforce` must be capable of failing.

The Stage 6 gate requires "commander max-level gate passes". The original
implementation resolved it with::

    report.get("commander", {}).get("commander_max_level_gate_passed", True)

so a report that never populated ``report["commander"]`` - which is exactly
what happens when the rollout ends early, e.g. the 05:02 run that lost its
socket at game loop 24112 - resolved to ``True``. Enforcement then reported
success for a gate that was never evaluated.

Each assertion here has a matching negative control; a gate test that only ever
checks the passing case reproduces the very defect it is meant to catch.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "tools" / "run_live_rl.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_live_rl_commander_gate", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_live_rl = _load_module()


class CommanderGateFailClosedTests(unittest.TestCase):
    @staticmethod
    def _write_launch_profile_bank(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        mastery_keys = "\n".join(
            f'    <Key name="Player|1|Mastery|{slot}|Value"><Value int="30" /></Key>'
            for slot in range(1, 7)
        )
        path.write_text(
            f"""<?xml version="1.0" encoding="utf-8"?>
<Bank version="1">
  <Section name="CMUI|LaunchProfile">
    <Key name="Player|1|Commander"><Value string="TerranRaynor" /></Key>
    <Key name="Player|1|CommanderLevel"><Value int="15" /></Key>
    <Key name="Player|1|MasteryCount"><Value int="6" /></Key>
    <Key name="Player|1|MasteryLevel"><Value int="180" /></Key>
{mastery_keys}
  </Section>
</Bank>
""",
            encoding="utf-8",
        )

    def test_full_mastery_layout_gate_accepts_default_all_thirty(self):
        gate = run_live_rl.mastery_layout_gate("30,30,30,30,30,30")
        self.assertTrue(gate["full"])
        self.assertEqual(gate["values"], [30, 30, 30, 30, 30, 30])

    def test_full_mastery_layout_gate_rejects_partial_or_malformed_layout(self):
        for layout in ("30,0,30,30,30,30", "30,30,30", "30,30,30,30,30,31"):
            with self.subTest(layout=layout):
                gate = run_live_rl.mastery_layout_gate(layout)
                self.assertFalse(gate["full"])
                self.assertTrue(gate["reasons"])

    def test_missing_commander_block_is_not_a_pass(self):
        evaluated, passed = run_live_rl.commander_gate_state({})
        self.assertFalse(evaluated, "an absent commander block was never evaluated")
        self.assertFalse(passed, "an unevaluated gate must not report success")

    def test_commander_block_without_the_verdict_is_not_a_pass(self):
        """A partially written block is still an unevaluated gate."""

        evaluated, passed = run_live_rl.commander_gate_state(
            {"commander": {"commander_id": "TerranRaynor", "commander_level": 15}}
        )
        self.assertFalse(evaluated)
        self.assertFalse(passed)

    def test_explicit_failure_is_reported_as_evaluated_and_failed(self):
        evaluated, passed = run_live_rl.commander_gate_state(
            {"commander": {"commander_max_level_gate_passed": False}}
        )
        self.assertTrue(evaluated, "an explicit verdict means the gate did run")
        self.assertFalse(passed)

    def test_explicit_pass_still_passes(self):
        """Positive control: fail-closed must not become fail-always."""

        evaluated, passed = run_live_rl.commander_gate_state(
            {"commander": {"commander_max_level_gate_passed": True}}
        )
        self.assertTrue(evaluated)
        self.assertTrue(passed)

    def test_non_dict_commander_field_is_not_a_pass(self):
        for junk in (None, "TerranRaynor", 1, []):
            with self.subTest(junk=junk):
                evaluated, passed = run_live_rl.commander_gate_state({"commander": junk})
                self.assertFalse(evaluated)
                self.assertFalse(passed)

    def test_underleveled_profile_is_blocked_before_launcher_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "live-rl-report.json"
            args = run_live_rl.build_parser().parse_args([
                "--commander-level", "7",
                "--output", str(report_path),
            ])
            report = run_live_rl.run_live(args)
            persisted = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["launcher_started"])
        self.assertEqual(report["blocked_reason"], "commander_max_level_gate_failed")
        self.assertEqual(persisted["status"], "blocked")

    def test_partial_mastery_layout_is_blocked_before_launcher_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "live-rl-report.json"
            args = run_live_rl.build_parser().parse_args([
                "--mastery-layout", "30,0,30,30,30,30",
                "--output", str(report_path),
            ])
            report = run_live_rl.run_live(args)
            persisted = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["launcher_started"])
        self.assertEqual(report["blocked_reason"], "commander_max_level_gate_failed")
        self.assertFalse(report["commander"]["commander_full_mastery_layout_passed"])
        self.assertEqual(persisted["status"], "blocked")

    def test_launch_profile_snapshot_ignores_stale_bank(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Banks"
            output = Path(tmp) / "run"
            bank = root / "CMCoopLaunchProfile.SC2Bank"
            self._write_launch_profile_bank(bank)
            os.utime(bank, (10.0, 10.0))

            stale = run_live_rl.snapshot_commander_launch_profile(
                output,
                banks_root=root,
                fresh_since=20.0,
            )
            self.assertFalse(stale["fresh_selected"])
            self.assertNotIn("selected", stale)

            os.utime(bank, (30.0, 30.0))
            fresh = run_live_rl.snapshot_commander_launch_profile(
                output,
                banks_root=root,
                fresh_since=20.0,
            )
        self.assertTrue(fresh["fresh_selected"])
        self.assertEqual(fresh["selected"]["level"], 15)
        self.assertEqual(fresh["selected"]["mastery"], "full")

    def test_launcher_shell_prefers_pwsh(self):
        with mock.patch.object(
            run_live_rl.shutil,
            "which",
            side_effect=lambda name: {"pwsh": "C:/Program Files/PowerShell/7/pwsh.exe", "powershell": "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"}[name],
        ):
            self.assertEqual(
                run_live_rl.resolve_powershell_executable(),
                "C:/Program Files/PowerShell/7/pwsh.exe",
            )

    def test_launcher_shell_falls_back_to_windows_powershell(self):
        with mock.patch.object(
            run_live_rl.shutil,
            "which",
            side_effect=lambda name: None if name == "pwsh" else "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
        ):
            self.assertEqual(
                run_live_rl.resolve_powershell_executable(),
                "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
            )


if __name__ == "__main__":
    unittest.main()
