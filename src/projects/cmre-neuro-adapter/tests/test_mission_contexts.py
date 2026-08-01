from __future__ import annotations

import json
import unittest

from cmre_neuro_adapter.mission.mission_state import MissionState
from cmre_neuro_adapter.neuro.mission_projection import project_observation


def make_context(*, loop: int = 10, state_version: int = 4):
    return project_observation(
        {
            "player_id": 1,
            "loop": loop,
            "mission": {
                "phase": "night",
                "night": 1,
                "wave": 2,
                "objectives": [
                    {"id": "hold", "name": "Hold the base", "status": "active"}
                ],
            },
            "resources": {"minerals": 400, "vespene": 75},
            "own_units": [
                {
                    "entity_id": 1,
                    "unit_type_id": "Marine",
                    "owner": 1,
                    "x": 10.0,
                    "y": 10.0,
                    "health": 46080,
                    "shields": 0,
                    "energy": 0,
                    "state": "alive",
                },
                {
                    "entity_id": 2,
                    "unit_type_id": "CommandCenter",
                    "owner": 1,
                    "x": 8.0,
                    "y": 8.0,
                    "health": 1500,
                    "shields": 0,
                    "energy": 0,
                    "state": "alive",
                },
            ],
            "visible_enemies": [],
        },
        map_name="dead-of-night",
        context_version=loop,
        state_version=state_version,
    )


class MissionContextTests(unittest.TestCase):
    def test_state_separates_versions_and_public_summaries(self) -> None:
        context = make_context()
        state = MissionState.from_context(
            context,
            version=3,
            no_build=True,
            paused=False,
            blocking=True,
        )

        self.assertEqual(state.version, 3)
        self.assertEqual(state.source_state_version, 4)
        self.assertEqual(state.source_loop, 10)
        self.assertTrue(state.no_build)
        self.assertTrue(state.blocking)
        self.assertEqual(state.economy.resources[0], ("minerals", 400))
        self.assertEqual(
            state.production.own_unit_counts,
            (("CommandCenter", 1), ("Marine", 1)),
        )
        self.assertEqual(state.production.base_count, 1)
        self.assertEqual(state.production.base_unit_types, ("CommandCenter",))
        self.assertEqual(state.tactical.own_unit_count, 2)
        payload = state.to_dict()
        self.assertEqual(payload["economy"]["resources"]["vespene"], 75)
        self.assertNotIn("world", json.dumps(payload))

    def test_state_does_not_mutate_when_source_context_is_changed(self) -> None:
        context = make_context()
        state = MissionState.from_context(
            context,
            version=1,
            no_build=False,
            paused=False,
            blocking=False,
        )
        changed = dict(context.resources)
        changed["minerals"] = 1
        self.assertEqual(state.economy.resources[0], ("minerals", 400))
        self.assertNotEqual(changed["minerals"], state.economy.resources[0][1])


if __name__ == "__main__":
    unittest.main()
