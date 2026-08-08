"""Pin RO-AI-001: PlayerGroupLoop (auto<hex>_var) SetAlliance resolution.

Before this fix, the 24 dynamic-owner maps expressed alliance/enemy edges through a
generated loop iterator (``auto<hex>_var`` bound to group ``auto<hex>_g``). Those
calls were invisible to the static adapter (owner is a loop variable), so the edges
sat in ``unresolved_alliance_calls`` and never reached the contract -> fail-closed.

The deterministic resolver pairs each iterator with its group, expands the group to
concrete players, and re-resolves the call. Across the 24 maps: 200 unresolved
calls -> 182 deterministically resolved into contract edges, 18 stay fail-closed
(library-init-empty groups populated at runtime, e.g.
``libA9E65AFF_gv_enemyPlayers = PlayerGroupEmpty()``). No runtime, no map mutation,
no generic AI.
"""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
PROJECT_ROOT = ROOT / "src" / "projects" / "revolution-overdrive-porting"
sys.path.insert(0, str(PROJECT_ROOT))

from vibe.ai_ally import extract_all_map_rosters  # noqa: E402


MAPS_ROOT = PROJECT_ROOT / "packages" / "Maps"

# RO-AI-001 deterministic aggregate (matches ai_ally_dynamic.py prototype dry-run).
EXPECTED_DYNAMIC_OWNER_MAPS = 24
EXPECTED_RESOLVED = 182
EXPECTED_UNRESOLVED = 18
ENTRY_FLOW_MAPS = ("tarcade.SC2Map", "tstory01.SC2Map")


class RoAi001DynamicAllianceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rosters = {r.map_name: r for r in extract_all_map_rosters(MAPS_ROOT)}

    def test_extracts_all_31_owned_maps_without_mutating_scripts(self):
        self.assertEqual(len(self.rosters), 31)
        for roster in self.rosters.values():
            self.assertTrue(roster.map_script_preserved)
            self.assertFalse(roster.generic_ai_start_calls)
            self.assertFalse(roster.generic_ai_melee_start_calls)

    def test_entry_flow_maps_stay_entry_flow_and_fail_closed(self):
        for name in ENTRY_FLOW_MAPS:
            roster = self.rosters[name]
            self.assertEqual(roster.classification, "entry-flow")
            self.assertEqual(roster.dynamic_resolved_call_count, 0)
            self.assertEqual(len(roster.dynamic_unresolved_alliance_calls), 0)

    def test_aggregate_dynamic_resolution_matches_ro_ai_001_baseline(self):
        dynamic_owner = [
            r for r in self.rosters.values()
            if r.dynamic_resolved_call_count + len(r.dynamic_unresolved_alliance_calls) > 0
        ]
        self.assertEqual(len(dynamic_owner), EXPECTED_DYNAMIC_OWNER_MAPS)

        total_resolved = sum(r.dynamic_resolved_call_count for r in self.rosters.values())
        total_unresolved = sum(len(r.dynamic_unresolved_alliance_calls) for r in self.rosters.values())
        self.assertEqual(total_resolved, EXPECTED_RESOLVED)
        self.assertEqual(total_unresolved, EXPECTED_UNRESOLVED)

        # The 24 dynamic-owner maps already carried explicit (resolved) edges, so the
        # adapter classifies them as missions and now folds the 138 dynamic edges in.
        self.assertTrue(all(r.classification == "mission" for r in dynamic_owner))

    def test_every_resolved_dynamic_edge_is_a_concrete_alliance_call(self):
        for roster in self.rosters.values():
            for call in roster.dynamic_alliance_calls:
                self.assertIsNotNone(call.source_player)
                self.assertIsNotNone(call.target_player)
                self.assertIn(call.relation, ("ally", "enemy", "neutral"))
                self.assertGreater(call.source_player, 0)
                self.assertGreater(call.target_player, 0)

    def test_unresolved_dynamic_edges_remain_visible_for_fail_closed_audit(self):
        for roster in self.rosters.values():
            for call in roster.dynamic_unresolved_alliance_calls:
                self.assertEqual(call.name, "libNtve_gf_SetAlliance")

    def test_unresolved_dynamic_edges_trace_to_runtime_leader_identity(self):
        """RO-AI-001 closure: every fail-closed dynamic edge hinges on a runtime
        leader identity (``libA9E65AFF_gv_player01``), not an analysable opaque
        group. This is irreducible under static-only analysis -> correctly
        fail-closed, and provably so.
        """

        reasons: dict[str, int] = {}
        for roster in self.rosters.values():
            for call in roster.dynamic_unresolved_alliance_calls:
                reasons[call.reason or "unknown"] = reasons.get(call.reason or "unknown", 0) + 1
        self.assertEqual(reasons, {"runtime_leader_identity": EXPECTED_UNRESOLVED})
        self.assertEqual(sum(reasons.values()), EXPECTED_UNRESOLVED)


if __name__ == "__main__":
    unittest.main()
