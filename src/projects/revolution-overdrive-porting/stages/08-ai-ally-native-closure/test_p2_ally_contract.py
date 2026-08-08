"""Guard the thorner03 P2 AI ally contract discovered in Stage 08.

Stage 07 left P2 as an open ``blocked`` item on the reasoning that an ally with no units must be
broken. These tests pin the opposite, evidence-backed reading: P2 is a *time-gated* ally, and the
absence of P2-owned units before the gate is the map's intended behavior.

If any of these assertions ever fail, the runtime expectation encoded in the RO AI ally adapter
and in the Stage 08 verdict is no longer valid and must be re-derived.
"""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path


STAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = STAGE_DIR.parents[1]
sys.path.insert(0, str(STAGE_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from p2_contract_trace import MAPS_ROOT, trace_p2_contract  # noqa: E402
from vibe.ai_ally import build_ally_contract, extract_map_roster  # noqa: E402


class Thorner03P2AllyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.map_dir = MAPS_ROOT / "thorner03.SC2Map"
        cls.script = cls.map_dir / "MapScript.galaxy"
        cls.before = hashlib.sha256(cls.script.read_bytes()).hexdigest()
        cls.trace = trace_p2_contract(cls.map_dir)

    def test_trace_is_read_only_against_the_owned_map_script(self):
        after = hashlib.sha256(self.script.read_bytes()).hexdigest()
        self.assertEqual(self.before, after)
        self.assertEqual(self.trace.map_script_sha256, after)

    def test_p2_is_an_ally_of_p1_from_initialization(self):
        self.assertEqual(self.trace.leader_player_id, 1)
        self.assertEqual(self.trace.ally_player_id, 2)
        self.assertEqual(self.trace.ally_symbol, "gv_p02_TYCHUS")
        self.assertEqual(len(self.trace.alliance_setup), 1)
        self.assertIn("AllyWithSharedVision", self.trace.alliance_setup[0].text)

    def test_p2_is_hostile_to_the_mission_enemy_players(self):
        # A decorative slot would have no enemy relationships at all.
        self.assertGreaterEqual(len(self.trace.ally_enemy_setup), 8)

    def test_p2_receives_its_unit_only_through_a_single_rescue_handover(self):
        self.assertEqual(len(self.trace.unit_handover), 1)
        self.assertEqual(self.trace.handover_unit_ref, "UnitFromId(2)")
        self.assertFalse(self.trace.owns_units_at_start)

    def test_handover_is_gated_on_a_specific_unit_type_entering_a_specific_region(self):
        self.assertEqual(self.trace.gate_region_id, 24)
        self.assertEqual(self.trace.gate_unit_type, "TychusCommando")
        self.assertTrue(self.trace.is_time_gated_ally)

    def test_handover_chain_runs_through_midq_into_midcleanup(self):
        chain = " | ".join(c.text for c in self.trace.handover_trigger_chain)
        self.assertIn("gt_MidQ", chain)
        self.assertIn("gt_MidCleanup", chain)

    def test_p2_behavior_is_map_owned_ai_waves_and_never_generic_melee_ai(self):
        self.assertTrue(self.trace.is_script_driven_ai)
        self.assertEqual(self.trace.generic_ai_start, [])
        wave_calls = {c.text.split("(")[0].strip() for c in self.trace.ai_wave_control}
        self.assertIn("AIAttackWaveUseUnit", wave_calls)
        self.assertIn("AIAttackWaveSend", wave_calls)

    def test_stage07_observation_is_consistent_with_this_contract(self):
        """Stage 07 saw zero P2 units at loop 48 and read it as a defect.

        Under the traced contract that observation is *required*: the handover only runs after
        the gate, which Stage 07 never reached. The two facts must not both be treated as open
        problems.
        """
        self.assertFalse(self.trace.owns_units_at_start)
        self.assertTrue(self.trace.is_time_gated_ally)

    def test_odin_is_prebound_hidden_then_revealed_immediately_before_rescue(self):
        """Stage 08 discovery: the Odin is pre-bound to ``gv_odin`` (L616), hidden at map start
        (L620/L4800), and revealed (L5388) on the line immediately before the RescueUnit handover
        (L5389). That lifecycle is what makes the runtime owner-16 -> owner-2 transition a true
        handover of an existing unit, not a spawn created by the adapter.
        """
        self.assertEqual(self.trace.handover_unit_alias, "gv_odin")
        self.assertEqual(self.trace.handover_unit_ref, "UnitFromId(2)")
        self.assertTrue(self.trace.hidden_before_handover)
        reveal_lines = sorted(c.line for c in self.trace.handover_unit_revealed)
        handover_line = self.trace.unit_handover[0].line
        self.assertIn(handover_line - 1, reveal_lines)

    def test_native_probe_contains_no_debug_injection_path(self):
        """The probe must remain admissible under the repository's no-cheat runtime gate."""
        probe = (STAGE_DIR / "p2_handover_probe.py").read_text(encoding="utf-8")
        for forbidden in ("RequestDebug", "DebugGameState", "create_unit", "game_state.god"):
            self.assertNotIn(forbidden, probe)

    def test_adapter_exposes_thorner03_time_gate_and_blocks_pre_handover_dispatch(self):
        roster = extract_map_roster(self.map_dir)
        contract = build_ally_contract(roster, leader_player_id=1, ally_player_id=2)

        self.assertTrue(contract.valid)
        self.assertEqual(contract.activation.mode, "time-gated")
        self.assertEqual(contract.activation.gate_unit_type, "TychusCommando")
        self.assertEqual(contract.activation.gate_region_id, 24)
        self.assertEqual(contract.activation.handover_unit_ref, "UnitFromId(2)")
        self.assertFalse(contract.ally_observation_ready(0))
        self.assertFalse(contract.can_dispatch_ally_action(1, 0))
        self.assertTrue(contract.ally_observation_ready(1))
        self.assertTrue(contract.can_dispatch_ally_action(1, 1))

    def test_adapter_rejects_unknown_activation_without_native_ownership(self):
        roster = extract_map_roster(MAPS_ROOT / "thanson01.SC2Map")
        contract = build_ally_contract(roster, leader_player_id=1, ally_player_id=4)

        self.assertTrue(contract.valid)
        self.assertFalse(contract.can_dispatch_ally_action(1, 0))
        self.assertFalse(contract.can_dispatch_ally_action(4, 1))

if __name__ == "__main__":
    unittest.main()
