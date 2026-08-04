"""Tests for RL action space and action masking (G1)."""

from __future__ import annotations

import unittest

import numpy as np

from cmre_rl_training.action_space import (
    ACTION_INDEX,
    ACTION_NAMES,
    NUM_ACTIONS,
    compute_action_mask,
)


def _unit(uid: str, **kwargs) -> dict:
    base = {
        "entity_id": 1,
        "unit_type_id": uid,
        "owner": 1,
        "x": 85, "y": 94,
        "health": 100, "shields": 0, "energy": 0,
        "state": "idle", "orders": [],
    }
    base.update(kwargs)
    return base


class ActionSpaceTests(unittest.TestCase):
    def test_action_count_matches_basic_routes(self) -> None:
        # BASIC_ACTION_ROUTES has 19 entries (verified from basic_actions.py)
        self.assertEqual(NUM_ACTIONS, 19)

    def test_action_index_is_bijective(self) -> None:
        for i, name in enumerate(ACTION_NAMES):
            self.assertEqual(ACTION_INDEX[name], i)
        self.assertEqual(len(ACTION_INDEX), NUM_ACTIONS)

    def test_mask_all_false_when_no_units(self) -> None:
        obs = {"own_units": [], "resources": {"minerals": 1000}}
        mask = compute_action_mask(obs)
        self.assertEqual(len(mask), NUM_ACTIONS)
        self.assertFalse(mask.any())

    def test_mask_movement_with_combat_unit(self) -> None:
        obs = {"own_units": [_unit("Marine")], "resources": {}}
        mask = compute_action_mask(obs)
        self.assertTrue(mask[ACTION_INDEX["move_units"]])
        self.assertTrue(mask[ACTION_INDEX["attack_move_units"]])
        self.assertTrue(mask[ACTION_INDEX["attack_units"]])
        self.assertFalse(mask[ACTION_INDEX["gather_resources"]])

    def test_mask_gather_with_worker(self) -> None:
        obs = {"own_units": [_unit("SCV")], "resources": {}}
        mask = compute_action_mask(obs)
        self.assertTrue(mask[ACTION_INDEX["gather_resources"]])
        self.assertTrue(mask[ACTION_INDEX["repair_units"]])
        self.assertFalse(mask[ACTION_INDEX["move_units"]])

    def test_mask_build_requires_worker_and_minerals(self) -> None:
        # Worker but no minerals
        obs = {"own_units": [_unit("SCV")], "resources": {"minerals": 0}}
        mask = compute_action_mask(obs)
        self.assertFalse(mask[ACTION_INDEX["build_structure"]])

        # Worker with minerals
        obs = {"own_units": [_unit("SCV")], "resources": {"minerals": 100}}
        mask = compute_action_mask(obs)
        self.assertTrue(mask[ACTION_INDEX["build_structure"]])

    def test_mask_produce_requires_producer_and_minerals(self) -> None:
        obs = {"own_units": [_unit("Barracks")], "resources": {"minerals": 0}}
        mask = compute_action_mask(obs)
        self.assertFalse(mask[ACTION_INDEX["produce_unit"]])

        obs = {"own_units": [_unit("Barracks")], "resources": {"minerals": 150}}
        mask = compute_action_mask(obs)
        self.assertTrue(mask[ACTION_INDEX["produce_unit"]])

    def test_mask_research_requires_tech_and_minerals(self) -> None:
        obs = {"own_units": [_unit("EngineeringBay")], "resources": {"minerals": 0}}
        mask = compute_action_mask(obs)
        self.assertFalse(mask[ACTION_INDEX["research_upgrade"]])

        obs = {"own_units": [_unit("EngineeringBay")], "resources": {"minerals": 100}}
        mask = compute_action_mask(obs)
        self.assertTrue(mask[ACTION_INDEX["research_upgrade"]])

    def test_mask_rally_with_producer(self) -> None:
        obs = {"own_units": [_unit("Factory")], "resources": {}}
        mask = compute_action_mask(obs)
        self.assertTrue(mask[ACTION_INDEX["rally_producer"]])

    def test_mask_cancel_with_orders(self) -> None:
        obs = {
            "own_units": [_unit("Barracks", orders=[{"kind": "train"}])],
            "resources": {},
        }
        mask = compute_action_mask(obs)
        self.assertTrue(mask[ACTION_INDEX["cancel_order"]])

    def test_mask_cancel_false_without_orders(self) -> None:
        obs = {"own_units": [_unit("Marine")], "resources": {}}
        mask = compute_action_mask(obs)
        self.assertFalse(mask[ACTION_INDEX["cancel_order"]])

    def test_mask_transport_with_medivac(self) -> None:
        obs = {"own_units": [_unit("Medivac")], "resources": {}}
        mask = compute_action_mask(obs)
        self.assertTrue(mask[ACTION_INDEX["load_units"]])
        self.assertTrue(mask[ACTION_INDEX["unload_units"]])

    def test_mask_morph_with_any_unit(self) -> None:
        obs = {"own_units": [_unit("SiegeTank")], "resources": {}}
        mask = compute_action_mask(obs)
        self.assertTrue(mask[ACTION_INDEX["morph_unit"]])

    def test_mask_dtype_is_bool(self) -> None:
        obs = {"own_units": [_unit("Marine")], "resources": {}}
        mask = compute_action_mask(obs)
        self.assertEqual(mask.dtype, np.bool_)


if __name__ == "__main__":
    unittest.main()
