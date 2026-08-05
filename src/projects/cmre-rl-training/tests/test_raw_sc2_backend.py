"""Stage 06 tests for the injected raw SC2 session contract."""

from __future__ import annotations

import unittest
from typing import Any, Mapping

from cmre_rl_training.action_grounding import ActionGrounder
from cmre_rl_training.map_profiles import MapProfileRegistry
from cmre_rl_training.raw_sc2_backend import RawSc2Backend


class FakeRawSession:
    def __init__(self) -> None:
        self.loop = 0
        self.dispatches: list[tuple[str, dict[str, Any]]] = []
        self.left = False
        self.terminated = False

    def reset(self, map_name: str, player_id: int) -> Mapping[str, Any]:
        self.loop = 0
        return self._observation(map_name, player_id)

    def observe(self) -> Mapping[str, Any]:
        return self._observation("Void Launch", 1)

    def dispatch(self, action_id: str, args: Mapping[str, Any]) -> Mapping[str, Any]:
        self.dispatches.append((action_id, dict(args)))
        return {"success": True, "result": 1}

    def step(self, step_mul: int) -> Mapping[str, Any]:
        self.loop += step_mul
        if self.loop >= 16:
            self.terminated = True
        return self._observation("Void Launch", 1)

    def leave(self) -> None:
        self.left = True

    def _observation(self, map_name: str, player_id: int) -> dict[str, Any]:
        return {
            "loop": self.loop,
            "map_name": map_name,
            "player_id": player_id,
            "own_units": [{"entity_id": 3, "unit_type_id": "Marine", "x": 1, "y": 1}],
            "visible_enemies": [{"entity_id": 9, "unit_type_id": "Zergling", "x": 20, "y": 20}],
            "resources": {"minerals": 100},
            "mission": {"terminated": self.terminated},
            "action_errors": [],
        }


class RawSc2BackendTests(unittest.TestCase):
    def test_loop_enemy_action_result_and_termination_are_preserved(self) -> None:
        session = FakeRawSession()
        backend = RawSc2Backend(
            session,
            map_name="Void Launch",
            grounder=ActionGrounder(MapProfileRegistry().resolve("Void Launch")),
        )
        initial = backend.reset()
        self.assertEqual(initial["loop"], 0)
        self.assertEqual(len(initial["visible_enemies"]), 1)

        observation, terminated, info = backend.step("attack_units", {})
        self.assertEqual(observation["loop"], 8)
        self.assertFalse(terminated)
        self.assertTrue(info["success"])
        self.assertEqual(session.dispatches[0][1]["target_entity_id"], 9)

        _, terminated, _ = backend.step("hold_units", {})
        self.assertTrue(terminated)
        self.assertEqual(backend.state_version, 16)
        backend.close()
        self.assertTrue(session.left)


if __name__ == "__main__":
    unittest.main()
