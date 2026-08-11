"""Pin the live-run default packed map to the artifact that actually starts the mission.

Background (three-way A/B evidence, 2026-08-10):

Three packed `亡者之夜` artifacts all pass every transport-level check — the SC2 API
answers, `CreateGame` and `JoinGame` succeed, and frames advance — yet they differ
sharply in how much of the mission actually comes up. The map was the only variable;
code, checkpoint and parameters were identical in every arm.

    亡者之夜_live_packed_OVERLAY_20260810.SC2Map (md5 ccc74e2c..., 3328542 B)
        census verdict=faction_initialised, commander_economy_online=TRUE,
        supply 15/15, 15 SCV + CommandCenter, 535 minerals, 9 visible enemies,
        terminal_evidence_reachable=true, reward_sum=+2577.95,
        debug bank initialization_gate_started=1 / initialization_complete=1

    亡者之夜_live_packed_GAMEPLAY_OK_20260731.SC2Map (md5 fa20e497..., 3280916 B)
        census verdict=faction_initialised but commander_economy_online=FALSE:
        supply_cap=0, Marine + placeholder 4051 only, reward_sum=-587.65.
        Predates the 2026-08-09 observer/init-gate overlay, so the CMRE
        commander-init trigger chain never fires.

    亡者之夜_live_packed.SC2Map (20260809-23:33 repack, md5 5f122326..., 5756487 B)
        census verdict=player_faction_uninitialised, own=1 (placeholder 4051),
        0 minerals, 0 visible enemies, 0/512 successful actions.

`faction_initialised` alone was NOT a sufficient pin: the 20260731 artifact satisfies
it while leaving the commander economy permanently offline, which makes a real
mission terminal (`player_result`) unreachable. The pin therefore keys on the overlay
artifact specifically, and the source comment must carry the economy evidence — not
just the faction verdict — so a future repack cannot quietly regress to a map that
"has units" but can never finish a match.
"""

from __future__ import annotations

import hashlib
import importlib.util
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "tools" / "run_live_rl.py"

KNOWN_GOOD_RELATIVE = "artifacts/live-maps/亡者之夜_live_packed_OVERLAY_20260810.SC2Map"
KNOWN_GOOD_MD5 = "ccc74e2c6fff5b1914d196b5867705c5"
KNOWN_GOOD_SIZE = 3328542

# Artifacts proven unable to bring the mission up. Never make any of these the
# default again without re-running the faction-census A/B *and* the debug-bank
# initialization snapshot.
#
#   - the 20260809 repack never hands the player a faction at all
#   - the 20260731 artifact hands a faction but never a commander economy
#     (supply_cap stays 0), so no mission terminal is reachable
SUPERSEDED_RELATIVE = {
    "artifacts/live-maps/亡者之夜_live_packed.SC2Map": "20260809 repack: player_faction_uninitialised",
    "artifacts/live-maps/亡者之夜_live_packed_GAMEPLAY_OK_20260731.SC2Map": "pre-overlay: supply_cap=0, commander economy offline",
    "artifacts/live-maps/亡者之夜_live_packed_PREOVERLAY_20260809.SC2Map": "pre-overlay snapshot, kept for A/B only",
    "artifacts/live-maps/亡者之夜_live_packed_OLD_stale_20260809.SC2Map": "stale copy, kept for A/B only",
}


def _load_module():
    spec = importlib.util.spec_from_file_location("run_live_rl_map_pin", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_live_rl = _load_module()


def _default_map_path() -> str:
    parser = run_live_rl.build_parser()
    args = parser.parse_args([])
    return str(args.map_path).replace("\\", "/")


class LiveMapPinTests(unittest.TestCase):
    def test_default_map_path_is_the_overlay_artifact(self):
        self.assertEqual(_default_map_path(), KNOWN_GOOD_RELATIVE)

    def test_default_map_path_is_none_of_the_superseded_artifacts(self):
        default = _default_map_path()
        for relative, reason in SUPERSEDED_RELATIVE.items():
            self.assertNotEqual(default, relative, msg=f"{relative} is superseded: {reason}")

    def test_overlay_artifact_exists_with_the_expected_bytes(self):
        path = run_live_rl.REPO_ROOT / KNOWN_GOOD_RELATIVE
        if not path.is_file():
            self.skipTest(f"packed map artifact not present in this checkout: {path}")
        self.assertEqual(path.stat().st_size, KNOWN_GOOD_SIZE)
        digest = hashlib.md5(path.read_bytes()).hexdigest()
        self.assertEqual(digest, KNOWN_GOOD_MD5)

    def test_the_pin_is_documented_in_source(self):
        """The default must carry its A/B justification, not just a path.

        `faction_initialised` on its own was the insufficient criterion that let the
        supply_cap=0 artifact hold the default for a week, so the source is required
        to document the *economy* evidence as well.
        """

        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn(KNOWN_GOOD_MD5, source)
        self.assertIn("faction_initialised", source)
        self.assertIn("commander_economy_online", source)

    def test_superseded_artifacts_are_still_on_disk_for_reverse_control(self):
        """A pin with no losing arm on disk cannot be re-falsified later."""

        present = [
            relative
            for relative in SUPERSEDED_RELATIVE
            if (run_live_rl.REPO_ROOT / relative).is_file()
        ]
        if not present:
            self.skipTest("no superseded artifacts in this checkout")
        self.assertNotIn(_default_map_path(), present)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
