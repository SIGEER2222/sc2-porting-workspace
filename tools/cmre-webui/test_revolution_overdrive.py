#!/usr/bin/env python3
"""MVP coverage for the owned Revolution Overdrive WebUI route."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEBUI_DIR = ROOT / "tools" / "cmre-webui"
EVIDENCE = (
    ROOT
    / "artifacts"
    / "projects"
    / "revolution-overdrive-porting"
    / "stage03-commander-package"
    / "launcher"
    / "last-run.json"
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class RevolutionOverdriveWebUiMvpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        env = dict(os.environ)
        env["CMRE_WEBUI_DRY_RUN"] = "1"
        cls.server = subprocess.Popen(
            [sys.executable, "server.py", "--port", str(cls.port), "--no-browser"],
            cwd=WEBUI_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(f"{cls.base}/api/factors", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        stdout, stderr = cls.server.communicate(timeout=5)
        raise RuntimeError(f"WebUI did not start\nstdout={stdout}\nstderr={stderr}")

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()

    def get_json(self, path: str) -> dict:
        with urllib.request.urlopen(f"{self.base}{path}", timeout=10) as response:
            return json.loads(response.read())

    def post_json(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read())

    def test_registry_exposes_factions_and_maps_without_changing_cmre_lists(self):
        factors = self.get_json("/api/factors")
        maps = self.get_json("/api/maps")

        self.assertEqual(len(factors["revolutionCommanders"]), 5)
        self.assertEqual(
            {entry["faction"] for entry in factors["revolutionCommanders"]},
            {"Iron", "Madness", "Pirate", "Coverts", "Umojan"},
        )
        self.assertEqual(len(maps["revolutionMaps"]), 31)
        self.assertTrue(all(entry["packageId"] == "revolution-overdrive" for entry in maps["revolutionMaps"]))
        self.assertTrue(all(entry.get("packageId") != "revolution-overdrive" for entry in maps["maps"]))

    def test_webui_dry_run_reaches_owned_launcher_and_stages_map(self):
        result = self.post_json("/api/launch", {
            "packageId": "revolution-overdrive",
            "commander": "RevolutionOverdriveIron",
            "faction": "Iron",
            "mapName": "traynor01.SC2Map",
        })

        self.assertTrue(result["success"], result)
        self.assertEqual(result["packageId"], "revolution-overdrive")
        self.assertEqual(result["faction"], "Iron")
        self.assertTrue(any("launch-revolution-overdrive.ps1" in arg for arg in result["debug_args"]))
        evidence = json.loads(EVIDENCE.read_text(encoding="utf-8-sig"))
        self.assertEqual(evidence["status"], "staged")
        self.assertTrue(evidence["noLaunch"])
        self.assertEqual(evidence["map"], "traynor01.SC2Map")
        self.assertEqual(evidence["faction"], "Iron")
        self.assertTrue(Path(evidence["stagedMap"]).is_dir())
        self.assertTrue((Path(evidence["stagedMap"]) / "MapScript.galaxy").is_file())

    def test_webui_dry_run_stages_cross_category_runtime_patch(self):
        result = self.post_json("/api/launch", {
            "packageId": "revolution-overdrive",
            "mapPackage": "revolution-overdrive",
            "commander": "TerranAlenger3",
            "commanderPackage": "cmre",
            "mapName": "thanson01.SC2Map",
        })

        self.assertTrue(result["success"], result)
        self.assertEqual(result["commander"], "TerranAlenger3")
        self.assertTrue(any("launch-revolution-overdrive.ps1" in arg for arg in result["debug_args"]))
        self.assertEqual(result["debug_args"][result["debug_args"].index("-Commander") + 1], "TerranAlenger3")
        evidence = json.loads(EVIDENCE.read_text(encoding="utf-8-sig"))
        self.assertEqual(evidence["status"], "staged")
        self.assertEqual(evidence["commander"], "TerranAlenger3")
        self.assertEqual(evidence["patchMode"], "runtime_galaxy_overlay")
        self.assertTrue(any(item["name"] == "EmpireAlenger.SC2Mod" for item in evidence["stagedPatchDependencies"]))
        self.assertTrue(all(item["status"] == "found" for item in evidence["patchCatalogContracts"]))
        self.assertEqual(
            evidence["sourceMapManifestBefore"]["manifestSha256"],
            evidence["sourceMapManifestAfter"]["manifestSha256"],
        )
        staged_script = (Path(evidence["stagedMap"]) / "MapScript.galaxy").read_text(encoding="utf-8-sig")
        self.assertIn("RO_PATCH_RUNTIME_OVERLAY_V1 ro-patch-TerranAlenger3", staged_script)


if __name__ == "__main__":
    unittest.main()
