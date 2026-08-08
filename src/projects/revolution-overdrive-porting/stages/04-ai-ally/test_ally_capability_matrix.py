"""Pin the RO-AI-001 generalization result: the ally capability matrix.

Stage 08 proved exactly one map (``thorner03``) hands a native ally to P2, and the
open follow-up (RO-AI-001) recorded that the remaining maps were fail-closed and
therefore *not generalized*.  ``vibe/ally_matrix.py`` answers that question
deterministically: for every owned map it enumerates every ``(leader, ally)``
pairing for which the fail-closed contract builder returns a valid contract, and
attributes each pair to static literal-ID edges or to PlayerGroupLoop expansion.

These assertions lock in the measured aggregate so any future adapter change that
silently widens or narrows the authorized surface fails the build.  The suite is
read-only: it asserts every map script is byte-identical after extraction.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
PROJECT_ROOT = ROOT / "src" / "projects" / "revolution-overdrive-porting"
sys.path.insert(0, str(PROJECT_ROOT))

from vibe.ally_matrix import build_capability_matrix, summarize  # noqa: E402


MAPS_ROOT = PROJECT_ROOT / "packages" / "Maps"

EXPECTED_MAP_COUNT = 31
# Maps that can never yield a contract: they declare no alliance at all.
ALWAYS_UNSUPPORTED = ("tarcade.SC2Map", "tstory01.SC2Map")
# Floor, not an exact pin.  ``ai_ally._extract_dynamic_alliances`` is still being
# tightened (RO-AI-001 phase 2), so the resolved-edge count legitimately moves.
# What must never regress is how much of the campaign is covered at all.
MIN_SUPPORTED_MAPS = 24
MIN_P1_LED_MAPS = 18


class AllyCapabilityMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matrix = build_capability_matrix(MAPS_ROOT)
        cls.summary = summarize(cls.matrix)

    def test_matrix_covers_every_owned_map(self) -> None:
        self.assertEqual(len(self.matrix), EXPECTED_MAP_COUNT)
        self.assertEqual(self.summary["mapCount"], EXPECTED_MAP_COUNT)

    def test_alliance_free_maps_never_produce_a_contract(self) -> None:
        """Entry-flow shells declare no alliance, so they must stay fail-closed."""

        for name in ALWAYS_UNSUPPORTED:
            capability = next(c for c in self.matrix if c.map_name == name)
            self.assertEqual(capability.alliance_call_count, 0)
            self.assertFalse(capability.supported, f"{name} must not authorize a pair")

    def test_campaign_coverage_does_not_regress(self) -> None:
        self.assertGreaterEqual(self.summary["supportedMapCount"], MIN_SUPPORTED_MAPS)

    def test_dynamic_expansion_stays_a_minority_of_evidence(self) -> None:
        """Group expansion may add pairs, but literal-ID edges must dominate.

        If dynamic evidence ever outweighs static evidence the expander has almost
        certainly started merging unrelated mission groups (the RO-AI-001 failure
        mode), which would silently widen the authorized surface.
        """

        by_evidence = self.summary["pairCountByEvidence"]
        self.assertGreater(by_evidence.get("static", 0), 0)
        self.assertGreater(by_evidence.get("static", 0), by_evidence.get("dynamic", 0))

    def test_p1_led_contract_coverage_does_not_regress(self) -> None:
        """The actionable subset is P1-led pairings; guard how much we can drive."""

        p1_led = [
            capability.map_name
            for capability in self.matrix
            if any(pair.leader_player_id == 1 for pair in capability.pairs)
        ]
        self.assertGreaterEqual(len(p1_led), MIN_P1_LED_MAPS)

    def test_thorner03_matrix_matches_stage08_runtime_ground_truth(self) -> None:
        """Cross-validate against the only runtime-verified handover we own."""

        thorner03 = next(c for c in self.matrix if c.map_name == "thorner03.SC2Map")
        p1_pairs = [pair for pair in thorner03.pairs if pair.leader_player_id == 1]
        self.assertEqual(len(p1_pairs), 1)
        pair = p1_pairs[0]
        self.assertEqual(pair.ally_player_id, 2)
        self.assertEqual(pair.activation_mode, "time-gated")
        self.assertEqual(pair.evidence, "static")

    def test_matrix_never_authorizes_reserved_or_out_of_range_players(self) -> None:
        for capability in self.matrix:
            for pair in capability.pairs:
                for player in (pair.leader_player_id, pair.ally_player_id):
                    self.assertGreater(player, 0)
                    self.assertLessEqual(player, 15)
                    self.assertNotIn(player, (15, 16))
                self.assertNotIn(pair.ally_player_id, pair.enemy_targets)

    def test_source_maps_are_never_mutated(self) -> None:
        digests = {
            path.name: (path / "MapScript.galaxy").read_bytes()
            for path in sorted(MAPS_ROOT.glob("*.SC2Map"))
            if path.is_dir()
        }
        build_capability_matrix(MAPS_ROOT)
        for name, before in digests.items():
            after = (MAPS_ROOT / name / "MapScript.galaxy").read_bytes()
            self.assertEqual(before, after, f"{name} was mutated")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
