from __future__ import annotations

import json
import unittest

from cmre_neuro_adapter.neuro.mission_projection import MissionContextProjector


class MappingBackend:
    @staticmethod
    def observation() -> dict:
        return {
            "player_id": 1,
            "loop": 42,
            "mission": {
                "phase": "night",
                "night": 2,
                "wave": 4,
                "objectives": [
                    {"id": "hold", "name": "hold", "status": "active"},
                    {"id": "rescue", "name": "rescue", "status": "success"},
                ],
            },
            "resources": {
                "minerals": 800,
                "vespene": 200,
                "supply_used": 12,
                "supply_cap": 31,
                "hidden_bank_balance": 999999,
            },
            "own_units": [
                {
                    "entity_id": 2,
                    "unit_type_id": "Marine",
                    "owner": 1,
                    "x": 10.0,
                    "y": 11.0,
                    "health": 46080,
                    "shields": 0,
                    "energy": 0,
                    "state": "alive",
                    "max_health": 46080,
                    "hidden_debug": "omit",
                }
            ],
            "visible_enemies": [
                {
                    "entity_id": 5,
                    "unit_type_id": "Zergling",
                    "owner": 2,
                    "x": 16.0,
                    "y": 11.0,
                    "health": 35000,
                    "shields": 0,
                    "energy": 0,
                    "state": "alive",
                }
            ],
            "hidden_world_snapshot": {"entities": "must not leak"},
        }


class MissionProjectionTests(unittest.TestCase):
    def test_public_context_is_versioned_and_excludes_hidden_state(self) -> None:
        projector = MissionContextProjector(map_name="dead-of-night")

        first = projector.project(MappingBackend.observation(), state_version=7)
        second = projector.project(MappingBackend.observation(), state_version=7)
        payload = json.loads(first.to_json())

        self.assertEqual(first.context_version, 1)
        self.assertEqual(second.context_version, 2)
        self.assertEqual(first.state_version, 7)
        self.assertEqual(first.source_loop, 42)
        self.assertEqual(first.to_envelope().loop, 42)
        self.assertEqual(payload["map"], "dead-of-night")
        self.assertEqual(payload["mission"]["night"], 2)
        self.assertEqual(
            [item["name"] for item in payload["mission"]["objectives"]],
            ["hold", "rescue"],
        )
        self.assertEqual(
            [item["entity_id"] for item in payload["own_units"]],
            [2],
        )
        self.assertEqual(payload["mission"]["resources"]["minerals"], 800)
        self.assertNotIn("hidden_world_snapshot", first.to_json())
        self.assertNotIn("hidden_debug", first.to_json())
        self.assertNotIn("hidden_bank_balance", first.to_json())

    def test_map_and_source_version_mismatches_are_rejected(self) -> None:
        projector = MissionContextProjector(map_name="dead-of-night")
        projector.project(MappingBackend.observation(), state_version=7)
        with self.assertRaisesRegex(ValueError, "older"):
            projector.project(MappingBackend.observation(), state_version=6)

        with self.assertRaisesRegex(ValueError, "mission objectives"):
            projector.project(
                {"player_id": 1, "loop": 42, "mission": {"objectives": "hidden"}},
                state_version=8,
            )


if __name__ == "__main__":
    unittest.main()
