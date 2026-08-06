from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
PROJECT_ROOT = ROOT / "src" / "projects" / "revolution-overdrive-porting"
sys.path.insert(0, str(PROJECT_ROOT))

from vibe.ai_ally import (  # noqa: E402
    build_ally_contract,
    extract_all_map_rosters,
    extract_map_roster,
)


MAPS_ROOT = PROJECT_ROOT / "packages" / "Maps"


class RevolutionOverdriveAiAllyAdapterTests(unittest.TestCase):
    def test_extracts_all_owned_maps_without_mutating_map_scripts(self):
        before = {
            path.relative_to(MAPS_ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in MAPS_ROOT.glob("*.SC2Map/MapScript.galaxy")
        }

        rosters = extract_all_map_rosters(MAPS_ROOT)

        after = {
            path.relative_to(MAPS_ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in MAPS_ROOT.glob("*.SC2Map/MapScript.galaxy")
        }
        self.assertEqual(len(rosters), 31)
        self.assertEqual(before, after)
        self.assertTrue(all(roster.map_script_preserved for roster in rosters))
        self.assertTrue(all(not roster.generic_ai_start_calls for roster in rosters))

    def test_thanson01_roster_preserves_explicit_colonist_ally_and_enemy_set(self):
        roster = extract_map_roster(MAPS_ROOT / "thanson01.SC2Map")

        self.assertEqual(roster.classification, "mission")
        self.assertIn(4, roster.direct_allies_by_player[1])
        self.assertTrue({2, 3, 5, 6}.issubset(roster.direct_enemies_by_player[1]))
        contract = build_ally_contract(roster, leader_player_id=1, ally_player_id=4)
        self.assertTrue(contract.valid)
        self.assertEqual(contract.authorized_command_sources, (1,))
        self.assertTrue(contract.is_safe_target(2))
        self.assertFalse(contract.is_safe_target(4))
        self.assertFalse(contract.is_safe_target(0))

    def test_tzeratul04_explicit_ally_contract_rejects_neutral_and_unknown_targets(self):
        roster = extract_map_roster(MAPS_ROOT / "tzeratul04.SC2Map")

        self.assertEqual(roster.classification, "mission")
        self.assertIn(2, roster.direct_allies_by_player[1])
        self.assertIn(7, roster.direct_enemies_by_player[1])
        contract = build_ally_contract(roster, leader_player_id=1, ally_player_id=2)
        self.assertTrue(contract.valid)
        self.assertTrue(contract.is_safe_target(7))
        self.assertFalse(contract.is_safe_target(8))
        self.assertFalse(contract.is_safe_target(999))
        self.assertFalse(contract.accepts_command_from(2))
        self.assertTrue(contract.accepts_command_from(1))

    def test_static_audit_keeps_low_level_alliance_and_player_group_evidence(self):
        roster = extract_map_roster(MAPS_ROOT / "thanson01.SC2Map")

        self.assertTrue(roster.player_set_alliance_calls)
        self.assertTrue(roster.player_group_add_calls)
        self.assertTrue(any(4 in players for players in roster.player_groups.values()))
        self.assertTrue(any(
            call.source_player == 1
            and call.target_player == 4
            and call.relation == "ally"
            for call in roster.alliance_calls
        ))

    def test_entry_maps_are_explicitly_not_available_for_generic_ally_adapter(self):
        for map_name in ("tarcade.SC2Map", "tstory01.SC2Map"):
            roster = extract_map_roster(MAPS_ROOT / map_name)
            self.assertEqual(roster.classification, "entry-flow")
            contract = build_ally_contract(roster, leader_player_id=1, ally_player_id=2)
            self.assertFalse(contract.valid)
            self.assertIn("no_explicit_leader_ally_edge", contract.issues)


if __name__ == "__main__":
    unittest.main()
