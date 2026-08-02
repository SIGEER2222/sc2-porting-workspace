from __future__ import annotations

import unittest

from cmre_neuro_adapter.abilities import AbilityExecutor, AbilityRegistry, AbilityState
from cmre_neuro_adapter.neuro.mission_projection import PublicMissionContext, project_observation


def context(*, loop: int = 10, visible_enemies: list[dict] | None = None) -> PublicMissionContext:
    return project_observation(
        {
            "player_id": 1,
            "loop": loop,
            "mission": {"phase": "night", "night": 1, "wave": 2},
            "resources": {"minerals": 500, "vespene": 100},
            "own_units": [
                {
                    "entity_id": 1,
                    "unit_type_id": "Marine",
                    "owner": 1,
                    "x": 10.0,
                    "y": 10.0,
                    "health": 80,
                    "shields": 0,
                    "energy": 0,
                    "state": "alive",
                }
            ],
            "visible_enemies": visible_enemies or [],
        },
        map_name="dead-of-night",
        context_version=loop,
        state_version=loop,
    )


def enemy(entity_id: int = 9, state: str = "alive") -> dict:
    return {
        "entity_id": entity_id,
        "unit_type_id": "Zergling",
        "owner": 2,
        "x": 20.0,
        "y": 20.0,
        "health": 35,
        "shields": 0,
        "energy": 0,
        "state": state,
    }


class AbilityTests(unittest.TestCase):
    def test_registry_exposes_only_the_four_stable_abilities(self) -> None:
        registry = AbilityRegistry()
        self.assertEqual(
            registry.names,
            ("call_backup", "heal_allies", "nuke_visible_target", "temporary_shields"),
        )
        self.assertEqual(
            tuple(action.name for action in registry.action_definitions()),
            registry.names,
        )

    def test_success_creates_one_effect_and_updates_state_once(self) -> None:
        state = AbilityState.initial(energy=100)
        result = AbilityExecutor().execute("heal_allies", {}, context= context(), state=state)

        self.assertTrue(result.success)
        self.assertEqual(result.code, "accepted")
        self.assertIsNotNone(result.effect)
        assert result.effect is not None
        self.assertEqual(result.effect.operation, "ability.heal_allies")
        self.assertEqual(result.effect.sequence, 1)
        self.assertEqual(result.state.energy, 75)
        self.assertEqual(result.state.cooldown_until("heal_allies"), 40)
        self.assertEqual(state.energy, 100)

    def test_failures_are_side_effect_free(self) -> None:
        executor = AbilityExecutor()
        low_energy = AbilityState.initial(energy=1)
        result = executor.execute("heal_allies", {}, context=context(), state=low_energy)
        self.assertFalse(result.success)
        self.assertEqual(result.code, "insufficient_energy")
        self.assertIs(result.state, low_energy)
        self.assertIsNone(result.effect)

        visible = context(loop=20, visible_enemies=[enemy()])
        nuke = executor.execute(
            "nuke_visible_target",
            {"target_entity_id": 9},
            context=visible,
            state=AbilityState.initial(energy=200),
        )
        cooldown = executor.execute(
            "nuke_visible_target",
            {"target_entity_id": 9},
            context=visible,
            state=nuke.state,
        )
        self.assertTrue(nuke.success)
        self.assertFalse(cooldown.success)
        self.assertEqual(cooldown.code, "cooldown_active")
        self.assertIs(cooldown.state, nuke.state)
        self.assertIsNone(cooldown.effect)

    def test_invalid_and_invisible_targets_do_not_consume_energy(self) -> None:
        state = AbilityState.initial(energy=200)
        executor = AbilityExecutor()
        invalid = executor.execute(
            "nuke_visible_target", {}, context=context(), state=state
        )
        invisible = executor.execute(
            "nuke_visible_target",
            {"target_entity_id": 99},
            context=context(),
            state=state,
        )
        self.assertEqual(invalid.code, "invalid_arguments")
        self.assertEqual(invisible.code, "target_not_visible")
        self.assertIs(invalid.state, state)
        self.assertIs(invisible.state, state)
        self.assertEqual(state.to_dict(), {"version": 1, "energy": 200, "cooldowns": {}, "use_sequence": 0})

    def test_public_context_contains_readiness_but_not_hidden_state(self) -> None:
        projected = AbilityRegistry().to_context(AbilityState.initial(energy=100), loop=10)
        self.assertEqual(projected["energy"], 100)
        self.assertTrue(any(item["name"] == "heal_allies" and item["available"] for item in projected["abilities"]))
        self.assertNotIn("world", projected)


if __name__ == "__main__":
    unittest.main()
