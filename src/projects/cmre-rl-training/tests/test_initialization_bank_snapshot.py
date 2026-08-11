"""The CMRE init-chain acceptance signal must survive the next launch.

`initialization_gate_started` is the one marker that separates "the mission
actually started" from "the API answered and nothing happened" (EVAL-009). The
approved launcher zeroes `CMRERebornDebug.SC2Bank` on every launch, so the file
only ever describes the run that just finished. On 2026-08-10 the first
non-zero reading was destroyed by the following launch minutes later, which is
exactly the failure mode this snapshot exists to prevent.

Every assertion below has a matching negative control: a zeroed bank must not
report the chain as fired, or the check is a tautology.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "tools" / "run_live_rl.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_live_rl_bank_snapshot", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_live_rl = _load_module()


def _bank(**values: int) -> str:
    keys = "".join(
        f'    <Key name="{name}">\n      <Value int="{value}"/>\n    </Key>\n'
        for name, value in values.items()
    )
    return f'<?xml version="1.0" encoding="utf-8"?>\n<Bank version="1">\n  <Section name="debug">\n{keys}  </Section>\n</Bank>\n'


def _write_bank(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class InitializationBankSnapshotTests(unittest.TestCase):
    def test_fired_chain_is_reported_and_copied(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            banks = tmp_path / "Banks"
            output = tmp_path / "run"
            output.mkdir()
            _write_bank(
                banks,
                "CMRERebornDebug.SC2Bank",
                _bank(
                    map_init_entered=1,
                    initialization_gate_started=1,
                    initialization_complete=1,
                    preselected_commander_startup=1,
                ),
            )

            result = run_live_rl.snapshot_initialization_banks(output, banks_root=banks)

            self.assertTrue(result["commander_init_chain_fired"])
            self.assertEqual(result["initialization_gate_started"], 1)
            self.assertEqual(result["initialization_complete"], 1)
            self.assertEqual(len(result["snapshots"]), 1)
            copied = output / "banks" / "CMRERebornDebug.SC2Bank"
            self.assertTrue(copied.is_file(), "the bank must be copied, not merely parsed")

    def test_zeroed_bank_is_a_negative_control(self):
        """A launcher-reset bank must NOT report the chain as fired."""

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            banks = tmp_path / "Banks"
            output = tmp_path / "run"
            output.mkdir()
            _write_bank(
                banks,
                "CMRERebornDebug.SC2Bank",
                _bank(map_init_entered=0, initialization_gate_started=0, initialization_complete=0),
            )

            result = run_live_rl.snapshot_initialization_banks(output, banks_root=banks)

            self.assertFalse(result["commander_init_chain_fired"])
            self.assertEqual(result["initialization_gate_started"], 0)

    def test_account_scoped_zero_copies_do_not_mask_a_root_write(self):
        """Banks/<account>/ copies stay zeroed; merging must not average them away."""

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            banks = tmp_path / "Banks"
            output = tmp_path / "run"
            output.mkdir()
            _write_bank(banks, "CMRERebornDebug.SC2Bank", _bank(initialization_gate_started=1))
            _write_bank(banks, "1/CMRERebornDebug.SC2Bank", _bank(initialization_gate_started=0))
            _write_bank(banks, "2/CMRERebornDebug.SC2Bank", _bank(initialization_gate_started=0))

            result = run_live_rl.snapshot_initialization_banks(output, banks_root=banks)

            self.assertTrue(result["commander_init_chain_fired"])
            self.assertEqual(len(result["snapshots"]), 3, "every copy must be preserved")
            self.assertEqual(result["by_source"]["1/CMRERebornDebug.SC2Bank"]["initialization_gate_started"], "0")

    def test_self_nested_backup_directory_cannot_break_the_snapshot(self):
        """Regression: the cursed ``.runtime-lab-backup-*`` chain killed a snapshot.

        The real ``Documents/StarCraft II/Banks`` holds
        ``.runtime-lab-backup-1786206967`` nested inside itself over and over.
        ``Path.glob("**/CMRERebornDebug.SC2Bank")`` walked into it, ran past
        MAX_PATH and raised ``FileNotFoundError: [WinError 3]``, so the Stage 6
        terminal run reported ``initialization_bank: {"error": ...}`` and lost
        its acceptance signal even though the run itself was healthy. The scan
        must prune those directories and still find the root bank.
        """

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            banks = tmp_path / "Banks"
            output = tmp_path / "run"
            output.mkdir()
            _write_bank(banks, "CMRERebornDebug.SC2Bank", _bank(initialization_gate_started=1))
            # 4 levels only: 6 already overruns MAX_PATH when *creating* the
            # fixture, which is the same wall the production glob hit. The
            # prune triggers on the first level, so depth beyond that adds
            # nothing but flakiness.
            cursed = "/".join([".runtime-lab-backup-1786206967"] * 4)
            _write_bank(
                banks,
                f"{cursed}/CMRERebornDebug.SC2Bank",
                _bank(initialization_gate_started=0),
            )

            result = run_live_rl.snapshot_initialization_banks(output, banks_root=banks)

            self.assertNotIn("error", result, "the cursed directory must not fail the snapshot")
            self.assertTrue(result["commander_init_chain_fired"])
            self.assertEqual(
                len(result["snapshots"]),
                1,
                "only the root bank is real; the backup chain must be pruned",
            )
            self.assertNotIn(
                ".runtime-lab-backup-1786206967",
                " ".join(result["by_source"]),
            )

    def test_pruning_is_by_prefix_not_by_being_nested(self):
        """Negative control: an ordinary nested bank must still be collected.

        Without this, "prune the cursed directory" could degenerate into "only
        ever look at the root", which would silently drop the account-scoped
        copies the merge relies on.
        """

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            banks = tmp_path / "Banks"
            output = tmp_path / "run"
            output.mkdir()
            _write_bank(banks, "14/CMRERebornDebug.SC2Bank", _bank(initialization_gate_started=1))

            result = run_live_rl.snapshot_initialization_banks(output, banks_root=banks)

            self.assertEqual(len(result["snapshots"]), 1)
            self.assertTrue(result["commander_init_chain_fired"])

    def test_missing_bank_root_is_not_a_crash_and_not_a_pass(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output = tmp_path / "run"
            output.mkdir()

            result = run_live_rl.snapshot_initialization_banks(output, banks_root=tmp_path / "nope")

            self.assertEqual(result["snapshots"], [])
            self.assertFalse(result["commander_init_chain_fired"])


if __name__ == "__main__":
    unittest.main()
