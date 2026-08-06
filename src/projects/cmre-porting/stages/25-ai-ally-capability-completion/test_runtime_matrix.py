"""Regression tests for the serial CMRE runtime matrix harness."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "src" / "projects" / "cmre-porting"))

from vibe import run_cmre_runtime_matrix as matrix  # noqa: E402


class RuntimeMatrixTests(unittest.TestCase):
    def test_commander_then_map_order_frontloads_both_focus_slices(self):
        commanders = [
            {"id": "C1", "group": "official", "race": "Terran"},
            {"id": "C2", "group": "official", "race": "Protoss"},
            {"id": "C3", "group": "alenger", "race": "Zerg"},
        ]
        with patch.object(matrix, "load_commanders", return_value=commanders):
            with patch.object(matrix, "load_maps", return_value=["M1.SC2Map", "M2.SC2Map"]):
                pairs = matrix.build_pairs(
                    order="commander-then-map",
                    focus_commander="C1",
                    focus_map="M1.SC2Map",
                )

        self.assertEqual(
            [(pair["commander_id"], pair["map_name"]) for pair in pairs],
            [
                ("C1", "M1.SC2Map"),
                ("C1", "M2.SC2Map"),
                ("C2", "M1.SC2Map"),
                ("C3", "M1.SC2Map"),
                ("C2", "M2.SC2Map"),
                ("C3", "M2.SC2Map"),
            ],
        )

    def test_reborn_map_set_filters_to_campaign_port_maps_and_explicit_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in [
                "zchar01_reborn_port.SC2Map",
                "zstorychar.SC2Map",
                "Zerg_Assault.SC2Map",
            ]:
                (root / name).mkdir()
            with patch.object(matrix, "load_commanders", return_value=[{"id": "TerranAlenger3", "group": "alenger", "race": "Terran"}]):
                pairs = matrix.build_pairs(
                    map_root=root,
                    map_set="reborn",
                    commander_id="TerranAlenger3",
                )
        self.assertEqual([pair["map_name"] for pair in pairs], ["zchar01_reborn_port.SC2Map", "zstorychar.SC2Map"])
        self.assertTrue(all(pair["enable_reborn"] for pair in pairs))
        self.assertTrue(all(pair["map_source"].endswith(pair["map_name"]) for pair in pairs))

    def test_only_explicit_launcher_busy_is_retryable(self):
        self.assertTrue(matrix.is_runtime_busy({"stderr_tail": "SC2_RUNTIME_BUSY"}))
        self.assertFalse(matrix.is_runtime_busy({"stderr_tail": "LaunchError"}))

    def test_subprocess_environment_exposes_project_vibe_package(self):
        with patch.object(matrix.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = ""
            run.return_value.stderr = ""
            matrix.run_process(["python", "-c", "pass"], 5)

        environment = run.call_args.kwargs["env"]
        self.assertIn("src\\projects\\cmre-porting", environment["PYTHONPATH"])

    def test_launcher_file_command_is_normalized_with_quoted_values(self):
        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            r"E:\maps\launch-cmre-alenger.ps1",
            "-MapName",
            "营救矿工.SC2Map",
            "-LegacyRootOverride",
            r"E:\CMRE's runtime",
            "-NoLaunch",
        ]
        normalized = matrix.powershell_command(command)
        self.assertEqual(normalized[4], "-Command")
        self.assertIn("-MapName '营救矿工.SC2Map'", normalized[5])
        self.assertIn("-LegacyRootOverride 'E:\\CMRE''s runtime'", normalized[5])
        self.assertTrue(normalized[5].endswith("-NoLaunch"))

    def test_run_process_captures_normalized_launcher_command(self):
        command = ["powershell", "-File", r"E:\launcher.ps1", "-NoLaunch"]
        with patch.object(matrix.subprocess, "run") as run:
            run.return_value.returncode = 4294967295
            run.return_value.stdout = "launcher output"
            run.return_value.stderr = "launcher error"
            result = matrix.run_process(command, 5)

        actual = run.call_args.args[0]
        self.assertEqual(actual[4], "-Command")
        self.assertEqual(result["returncode"], 4294967295)
        self.assertEqual(result["stdout_tail"], "launcher output")
        self.assertEqual(result["stderr_tail"], "launcher error")

    def test_live_command_uses_pair_map_source_for_external_map_sets(self):
        pair = {
            "map_name": "zchar01_reborn_port.SC2Map",
            "commander_id": "TerranAlenger3",
            "map_source": r"E:\external\zchar01_reborn_port.SC2Map",
            "enable_reborn": True,
        }
        command = matrix.launcher_command(pair, "reborn-smoke", 5901, stage=False)
        self.assertIn(r"E:\external\zchar01_reborn_port.SC2Map", command)

    def test_reborn_packed_map_is_staged_inside_sc2_install_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packed = root / "artifact.SC2Map"
            packed.write_bytes(b"packed-map")
            with patch.object(matrix, "SC2_ROOT", root / "sc2"):
                runtime_map = matrix.stage_packed_map_for_sc2(packed, "cmre-runtime-001")

            self.assertEqual(
                runtime_map,
                root / "sc2" / "Maps" / "cmre-runtime-001-api.SC2Map",
            )
            self.assertEqual(runtime_map.read_bytes(), b"packed-map")

    def test_busy_stage_retries_then_returns_latest_success(self):
        pair = {
            "map_name": "亡者之夜.SC2Map",
            "commander_id": "ProtossAlarak",
        }
        busy = {
            "returncode": 1,
            "stdout_tail": "",
            "stderr_tail": "SC2_RUNTIME_BUSY",
        }
        passed = {
            "returncode": 0,
            "stdout_tail": "staged",
            "stderr_tail": "",
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(matrix, "run_process", side_effect=[busy, passed]) as run:
                with patch.object(matrix.time, "sleep") as sleep:
                    result = matrix.run_stage_with_retry(
                        pair,
                        "cmre-runtime-001",
                        5901,
                        Path(directory),
                        30,
                    )

        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(matrix.STAGE_BUSY_RETRY_DELAY_SEC)


if __name__ == "__main__":
    unittest.main()
