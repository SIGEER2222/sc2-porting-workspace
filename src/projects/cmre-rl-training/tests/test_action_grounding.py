"""Stage 06 tests for transport-neutral legal action grounding."""

from __future__ import annotations

import unittest

from cmre_rl_training.action_grounding import ActionGrounder, ActionGroundingError
from cmre_rl_training.map_profiles import MapProfileRegistry


def _observation() -> dict:
    return {
        "own_units": [
            {"entity_id": 1, "unit_type_id": "CommandCenter", "x": 85, "y": 94},
            {"entity_id": 2, "unit_type_id": "SCV", "x": 86, "y": 93},
            {"entity_id": 3, "unit_type_id": "Marine", "x": 87, "y": 92},
            {"entity_id": 4, "unit_type_id": "Medivac", "x": 88, "y": 91},
        ],
        "visible_enemies": [{"entity_id": 100, "unit_type_id": "Zergling", "x": 70, "y": 80}],
        "mineral_fields": [{"entity_id": 200, "x": 80, "y": 90}],
    }


class ActionGroundingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.grounder = ActionGrounder(MapProfileRegistry().resolve("Dead of Night"))
        self.observation = _observation()

    def test_attack_and_gather_use_observation_entities(self) -> None:
        attack = self.grounder.ground("attack_units", self.observation)
        gather = self.grounder.ground("gather_resources", self.observation)

        self.assertEqual(attack["entity_ids"], [3])
        self.assertEqual(attack["target_entity_id"], 100)
        self.assertEqual(gather["entity_ids"], [2])
        self.assertEqual(gather["target_entity_id"], 200)

    def test_point_actions_follow_live_context_and_load_avoids_transport_self_target(self) -> None:
        attack_move = self.grounder.ground("attack_move_units", self.observation)
        load = self.grounder.ground("load_units", self.observation)

        self.assertEqual((attack_move["target_x"], attack_move["target_y"]), (70.0, 80.0))
        self.assertEqual(load["entity_ids"], [4])
        self.assertEqual(load["target_entity_id"], 1)

    def test_missing_target_is_reported(self) -> None:
        empty = {"own_units": [{"entity_id": 3, "unit_type_id": "Marine"}]}
        with self.assertRaisesRegex(ActionGroundingError, "no_visible_enemy"):
            self.grounder.ground("attack_units", empty)
        with self.assertRaisesRegex(ActionGroundingError, "unknown_action"):
            self.grounder.ground("not_an_action", self.observation)


if __name__ == "__main__":
    unittest.main()
