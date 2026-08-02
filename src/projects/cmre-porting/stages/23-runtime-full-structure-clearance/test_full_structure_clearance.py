"""Stage 23 deterministic controller contract tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

STAGE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(STAGE_ROOT))

from run_runtime_full_structure_clearance import (  # noqa: E402
    ClearanceAllocator,
    _declared_targets_in_census,
    _declared_targets_in_observation,
    _objective_targets,
    _project_final_targets,
)


class FullStructureClearanceTests(unittest.TestCase):
    def test_objective_projection_rejects_ally_neutral_and_non_objective_structures(self):
        observation = {
            "units": [
                {"tag": 1, "owner": 1, "alliance": 1, "health": 400},
                {"tag": 2, "owner": 2, "alliance": 2, "health": 400},
                {"tag": 3, "owner": 3, "alliance": 4, "health": 400},
                {"tag": 4, "owner": 4, "alliance": 4, "health": 400},
                {"tag": 5, "owner": 5, "alliance": 4, "health": 400},
                {"tag": 6, "owner": 6, "alliance": 2, "health": 400},
                {"tag": 9, "owner": 9, "alliance": 3, "health": 400},
            ]
        }
        census = {"structures": [
            {"owner": 1, "unit_type": "CommandCenter", "unit_tag": 1},
            {"owner": 2, "unit_type": "CommandCenter", "unit_tag": 2},
            {"owner": 3, "unit_type": "Bunker", "unit_tag": 3},
            {"owner": 4, "unit_type": "Bunker", "unit_tag": 4},
            {"owner": 5, "unit_type": "ColonistHut", "unit_tag": 5},
            {"owner": 6, "unit_type": "SensorTower", "unit_tag": 6},
            {"owner": 9, "unit_type": "Debris", "unit_tag": 9},
        ]}
        targets = _objective_targets(census, observation)
        self.assertEqual(set(targets), {3, 4, 5})
        self.assertEqual({item["owner"] for item in targets.values()}, {3, 4, 5})

    def test_objective_projection_rejects_stale_and_dead_observation_tags(self):
        observation = {
            "units": [
                {"tag": 10, "owner": 3, "alliance": 4, "health": 0},
                {"tag": 11, "owner": 3, "alliance": 4, "health": 100},
            ]
        }
        census = {"structures": [
            {"owner": 3, "unit_type": "Bunker", "unit_tag": 10},
            {"owner": 3, "unit_type": "Hatchery", "unit_tag": 11},
            {"owner": 3, "unit_type": "Nexus", "unit_tag": 99},
        ]}
        targets = _objective_targets(census, observation)
        self.assertEqual(set(targets), {11})

    def test_reconcile_reallocates_destroyed_target_and_dead_attacker(self):
        allocator = ClearanceAllocator()
        allocator.assign(10, 100)
        allocator.assign(11, 101)
        allocator.reconcile({10}, {101, 102})
        self.assertEqual(allocator.assignments, {})
        self.assertEqual(allocator.stats["attacker_lost"], 1)
        self.assertEqual(allocator.stats["target_destroyed"], 1)
        self.assertEqual(allocator.idle_attackers({10, 12}), [10, 12])
        self.assertEqual(allocator.available_targets({101, 102}), [101, 102])

    def test_reinforcement_can_be_allocated_after_initial_targets(self):
        allocator = ClearanceAllocator()
        allocator.assign(10, 100)
        allocator.reconcile({10, 11}, {100, 101})
        idle = allocator.idle_attackers({10, 11})
        available = allocator.available_targets({100, 101})
        self.assertEqual(idle, [11])
        self.assertEqual(available, [101])
        allocator.assign(idle[0], available[0])
        self.assertEqual(allocator.assignments, {10: 100, 11: 101})

    def test_stale_tag_is_retried_then_bounded(self):
        allocator = ClearanceAllocator(max_retries=2)
        allocator.assign(10, 100)
        allocator.record_attack_result(10, 100, False, "INVALID_ARGS")
        self.assertEqual(allocator.target_attempts[100], 1)
        self.assertNotIn(100, allocator.blocked_targets)
        allocator.assign(11, 100)
        allocator.record_attack_result(11, 100, False, "INVALID_ARGS")
        self.assertIn(100, allocator.blocked_targets)
        self.assertEqual(allocator.stats["bounded_retry_exhausted"], 1)
        self.assertEqual(allocator.available_targets({100, 101}), [101])

    def test_successful_attack_has_no_retry_or_block_side_effect(self):
        allocator = ClearanceAllocator()
        allocator.assign(10, 100)
        allocator.record_attack_result(10, 100, True, "OK")
        self.assertEqual(allocator.stats["attack_ok"], 1)
        self.assertEqual(allocator.target_attempts, {})
        self.assertEqual(allocator.blocked_targets, set())

    def test_final_census_failure_preserves_last_known_targets(self):
        last_known = {101: {"owner": 5, "unit_type": "ColonistHut", "unit_tag": 101}}
        targets, verified = _project_final_targets(None, {"units": []}, last_known)
        self.assertFalse(verified)
        self.assertEqual(targets, last_known)

    def test_final_census_success_reprojects_live_targets(self):
        census = {"structures": [{"owner": 3, "unit_type": "Bunker", "unit_tag": 202}]}
        observation = {
            "units": [{"tag": 202, "owner": 3, "alliance": 4, "health": 100}]
        }
        targets, verified = _project_final_targets(census, observation, {})
        self.assertTrue(verified)
        self.assertEqual(set(targets), {202})

    def test_live_assigned_target_remains_eligible_for_bounded_retry(self):
        allocator = ClearanceAllocator(max_retries=2)
        allocator.assign(10, 100)
        allocator.reconcile({10, 11}, {100})
        self.assertEqual(allocator.available_targets({100}), [])
        self.assertEqual(allocator.retryable_targets({100}), [100])
        allocator.assign(11, 100)
        self.assertEqual(allocator.assignments, {10: 100, 11: 100})
        allocator.record_attack_result(11, 100, False, "INVALID_ARGS")
        self.assertNotIn(100, allocator.blocked_targets)

    def test_terminal_observation_confirms_last_declared_target_is_gone(self):
        declared = {100: {"owner": 5, "unit_type": "ColonistHut", "unit_tag": 100}}
        terminal = {
            "units": [
                {"canonical_tag": 101, "owner": 5, "alliance": 4, "health": 500},
            ],
            "player_results": [1],
        }
        self.assertEqual(_declared_targets_in_observation(declared, terminal), {})

    def test_terminal_observation_keeps_live_declared_target_unresolved(self):
        declared = {100: {"owner": 5, "unit_type": "ColonistHut", "unit_tag": 100}}
        terminal = {
            "units": [
                {"canonical_tag": 100, "owner": 5, "alliance": 4, "health": 1},
            ],
        }
        self.assertEqual(set(_declared_targets_in_observation(declared, terminal)), {100})

    def test_typed_census_keeps_declared_target_when_raw_visibility_disappears(self):
        declared = {100: {"owner": 5, "unit_type": "ColonistHut", "unit_tag": 100}}
        census = {
            "structures": [
                {"owner": 5, "unit_type": "ColonistHut", "unit_tag": 100},
            ]
        }
        self.assertEqual(_declared_targets_in_census(declared, census), declared)

    def test_typed_census_allows_zero_when_declared_tags_are_absent(self):
        declared = {100: {"owner": 5, "unit_type": "ColonistHut", "unit_tag": 100}}
        census = {"structures": [{"owner": 5, "unit_type": "CreepTumorUsed", "unit_tag": 200}]}
        self.assertEqual(_declared_targets_in_census(declared, census), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
