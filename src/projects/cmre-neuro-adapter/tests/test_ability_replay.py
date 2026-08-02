from __future__ import annotations

import json
import tempfile
import unittest

from cmre_neuro_adapter.abilities import AbilityExecutor, AbilityState
from cmre_neuro_adapter.mission.mission_state import (
    CampaignState,
    MissionSnapshot,
    MissionState,
    RuntimeState,
)
from cmre_neuro_adapter.neuro.mission_projection import project_observation
from cmre_neuro_adapter.persistence.state_store import StateStore


def make_snapshot(abilities: AbilityState) -> MissionSnapshot:
    context = project_observation(
        {
            "player_id": 1,
            "loop": 10,
            "mission": {"phase": "night", "night": 1, "wave": 2},
            "resources": {"minerals": 500, "vespene": 100},
            "own_units": [],
            "visible_enemies": [
                {
                    "entity_id": 9,
                    "unit_type_id": "Zergling",
                    "owner": 2,
                    "x": 20.0,
                    "y": 20.0,
                    "health": 35,
                    "shields": 0,
                    "energy": 0,
                    "state": "alive",
                }
            ],
        },
        map_name="dead-of-night",
        context_version=10,
        state_version=10,
    )
    return MissionSnapshot(
        campaign=CampaignState("cmre", 1),
        mission=MissionState.from_context(
            context, version=1, no_build=False, paused=False, blocking=False
        ),
        runtime=RuntimeState(1, 10, (), (), False),
        abilities=abilities,
    )


class AbilityReplayTests(unittest.TestCase):
    def test_ability_state_survives_snapshot_load(self) -> None:
        state = AbilityState.initial(energy=200)
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(directory)
            store.save_snapshot(make_snapshot(state))
            restored = store.load_snapshot()

            self.assertEqual(restored.abilities, state)
            self.assertTrue(store.path_for("abilities").exists())
            payload = store.path_for("mission").read_text(encoding="utf-8")
            self.assertNotIn("world", payload)

    def test_repeated_and_restored_ability_traces_are_identical(self) -> None:
        def run(state: AbilityState) -> tuple[str, AbilityState]:
            executor = AbilityExecutor()
            context = make_snapshot(state).mission.context
            traces = []
            first = executor.execute(
                "nuke_visible_target",
                {"target_entity_id": 9},
                context=context,
                state=state,
            )
            traces.append(first.to_dict())
            restored = make_snapshot(first.state).abilities
            assert restored is not None
            second = executor.execute(
                "heal_allies", {}, context=context, state=restored, loop=40
            )
            traces.append(second.to_dict())
            return json.dumps(traces, sort_keys=True, separators=(",", ":")), second.state

        first_trace, first_state = run(AbilityState.initial(energy=200))
        second_trace, second_state = run(AbilityState.initial(energy=200))
        self.assertEqual(first_trace, second_trace)
        self.assertEqual(first_state, second_state)


if __name__ == "__main__":
    unittest.main()
