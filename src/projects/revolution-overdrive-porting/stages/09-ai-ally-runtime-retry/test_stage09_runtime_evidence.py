"""Deterministic guard over the Stage 09 native runtime evidence artifact.

Stage 09's objective was never a new adapter feature: it was to obtain one stable, approved,
debug-free native window for ``thorner03`` and run the *unchanged* Stage 08 escort probe.
That window was obtained on 2026-08-09 and the probe returned
``passed_native_p2_handover_observed``.

This test needs no SC2 instance. It locks the *shape and integrity* of that evidence so the
runtime claim cannot silently rot: if the artifact is regenerated with debug APIs, map edits,
adapter-created P2 units, or without the observed owner transition, the claim fails here.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
EVIDENCE = (
    ROOT
    / "artifacts"
    / "projects"
    / "revolution-overdrive-porting"
    / "stage09-ai-ally-runtime-retry"
    / "p2-handover-probe.json"
)

# SC2 API Alliance enum as seen from the observing player (player 1 here).
ALLIANCE_SELF = 1
ALLIANCE_ALLY = 2
ALLIANCE_NEUTRAL = 3

P2_PLAYER_ID = 2


class Stage09RuntimeEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not EVIDENCE.is_file():
            raise unittest.SkipTest(f"Stage 09 runtime evidence not present: {EVIDENCE}")
        cls.data = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_probe_reached_a_real_gameplay_window(self):
        lifecycle = self.data["lifecycle"]
        self.assertEqual(lifecycle["create_game"]["status_name"], "init_game")
        self.assertEqual(lifecycle["create_game"]["nested_error"], 0)
        self.assertEqual(lifecycle["create_game"]["errors"], [])
        self.assertEqual(lifecycle["join_game"]["status_name"], "in_game")
        self.assertEqual(lifecycle["join_game"]["errors"], [])
        self.assertEqual(lifecycle["join_game"]["player_id"], 1)
        self.assertGreater(lifecycle["catalog"]["abilities"], 0)

    def test_claim_is_not_manufactured(self):
        """No map edit, no adapter-spawned P2 unit, no injected melee AI, no debug API."""

        self.assertFalse(self.data["map_edits"])
        self.assertFalse(self.data["adapter_created_p2_units"])
        self.assertFalse(self.data["generic_melee_ai_injected"])
        self.assertEqual(self.data["debug_apis_used"], [])

    def test_baseline_starts_with_zero_p2_ownership(self):
        baseline = self.data["baseline"]
        self.assertEqual(baseline["p2_owned_count"], 0)
        self.assertEqual(baseline["p2_owned_units"], [])

    def test_gate_precedes_handover_in_game_loops(self):
        """Region 24 entry must be observed strictly before P2 ownership appears."""

        self.assertTrue(self.data["gate_reached"])
        self.assertEqual(self.data["gate_method"], "escort_native_tychus")
        gate_loops = [
            entry["game_loop"]
            for entry in self.data["timeline"]
            if entry.get("phase") == "handover_watch"
        ]
        self.assertTrue(gate_loops, "timeline has no handover_watch samples")
        self.assertLess(min(gate_loops), self.data["handover_census"]["game_loop"])
        self.assertGreater(self.data["handover_census"]["game_loop"], self.data["baseline"]["game_loop"])

    def test_handover_transfers_odin_ownership_to_player_two(self):
        census = self.data["handover_census"]
        self.assertTrue(self.data["handover_observed"])
        self.assertEqual(census["p2_owned_count"], 1)
        owned = census["p2_owned_units"]
        self.assertEqual(len(owned), 1)
        odin = owned[0]
        self.assertEqual(odin["type"], "Odin")
        self.assertEqual(odin["owner"], P2_PLAYER_ID)
        self.assertEqual(
            odin["alliance"],
            ALLIANCE_ALLY,
            "the handed-over Odin must read as an ALLY from player 1's own observation",
        )

    def test_odin_owner_transitions_from_rescuable_to_player_two(self):
        """The same unit tag must be observed changing hands, not merely appearing."""

        odin_tag = self.data["handover_census"]["p2_owned_units"][0]["tag"]
        owners: list[tuple[int, int]] = []
        for entry in self.data["timeline"]:
            for unit in entry.get("odin_units", []) or []:
                if unit.get("tag") == odin_tag:
                    owners.append((entry["game_loop"], unit["owner"]))
        self.assertTrue(owners, "handed-over Odin tag never appears in the timeline")
        pre = [owner for _, owner in owners if owner != P2_PLAYER_ID]
        post = [owner for _, owner in owners if owner == P2_PLAYER_ID]
        self.assertTrue(pre, "no pre-handover owner observed for the Odin tag")
        self.assertTrue(post, "Odin tag never observed under player 2")
        self.assertNotEqual(pre[0], P2_PLAYER_ID)
        first_p2_loop = min(loop for loop, owner in owners if owner == P2_PLAYER_ID)
        last_pre_loop = max(loop for loop, owner in owners if owner != P2_PLAYER_ID)
        self.assertLess(last_pre_loop, first_p2_loop, "ownership must move forward in time")

    def test_handover_is_stable_after_the_transfer(self):
        for label in ("post_handover_census", "final"):
            census = self.data[label]
            self.assertEqual(census["p2_owned_count"], 1, f"{label} lost P2 ownership")
            self.assertEqual(census["p2_owned_units"][0]["owner"], P2_PLAYER_ID)

    def test_gate_matches_the_map_owned_rescue_lifecycle(self):
        gate = self.data["gate"]
        self.assertIn("RegionFromId(24)", gate["event"])
        self.assertIn("TychusCommando", gate["condition"])
        self.assertIn("libNtve_gf_RescueUnit", gate["handover_call"])

    def test_verdict_is_the_native_pass(self):
        self.assertEqual(self.data["verdict"], "passed_native_p2_handover_observed")
        self.assertEqual(self.data["classification"], "runtime")
        self.assertEqual(self.data["map"], "thorner03.stage07.packed.SC2Map")


if __name__ == "__main__":
    unittest.main()
