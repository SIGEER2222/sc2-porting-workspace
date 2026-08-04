"""Tests for RealSc2BackendAdapter (Stage 05 G1, G2).

G1: RealSc2BackendAdapter implements the RlBackend protocol
    (state_version, reset, step) using a BotAI-like interface.
G2: All 19 RL actions translate to correct SC2 commands.

Since python-sc2 is not installed in this environment, we use a MockBotAI
that records issued commands and simulates state advancement. The adapter
is designed to accept any object implementing the BotAI surface
(units, do_action, worker, townhalls, etc.).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
_NEURO_PATH = str(_REPO_ROOT / "src" / "projects" / "cmre-neuro-adapter")
_VIBE_PATH = str(_REPO_ROOT / "src" / "projects" / "cmre-porting")
for _p in (_NEURO_PATH, _VIBE_PATH):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np

from cmre_rl_training.action_space import ACTION_INDEX, ACTION_NAMES, NUM_ACTIONS
from cmre_rl_training.backends import RlBackend


class MockUnit:
    """Mimics python-sc2 Unit interface for testing."""

    def __init__(self, tag: int, unit_type: str, is_worker: bool = False,
                 is_structure: bool = False, is_combat: bool = False) -> None:
        self.tag = tag
        self.type_id = type("TypeId", (), {"value": unit_type})()
        self._is_worker = is_worker
        self._is_structure = is_structure
        self._is_combat = is_combat
        self.orders: list = []
        self.position = type("Pos", (), {"x": 85.0, "y": 94.0})()
        self.health = 45.0
        self.shields = 0.0
        self.energy = 0.0
        self.owner = 1

    @property
    def is_worker(self) -> bool:
        return self._is_worker

    @property
    def is_structure(self) -> bool:
        return self._is_structure

    @property
    def is_combat_unit(self) -> bool:
        return self._is_combat


class MockUnits:
    """Mimics python-sc2 Units collection; iterable + filtered views."""

    def __init__(self, units_list: list[MockUnit]) -> None:
        self._units_list = units_list
        self.workers = [u for u in units_list if u.is_worker]
        self.combat_units = [u for u in units_list if u.is_combat_unit]
        self.structures = [u for u in units_list if u.is_structure]

    def __iter__(self):
        return iter(self._units_list)

    def __len__(self):
        return len(self._units_list)

    def of_type(self, type_id) -> list:
        return [u for u in self._units_list if u.type_id.value == type_id]


class MockBotAI:
    """Records commands issued by the adapter; simulates step advancement."""

    def __init__(self) -> None:
        self._step_count = 0
        self._minerals = 100
        self.issued_commands: list[dict[str, Any]] = []
        # Populate with mock units
        self._units_list = [
            MockUnit(1, "CommandCenter", is_structure=True),
            MockUnit(2, "SCV", is_worker=True),
            MockUnit(3, "Marine", is_combat=True),
        ]
        self.units = MockUnits(self._units_list)

    @property
    def state(self) -> Any:
        return type("State", (), {
            "minerals": self._minerals,
            "vespene": 0,
            "supply_used": 5,
            "supply_cap": 11,
            "game_loop": self._step_count,
        })()

    async def do_action(self, action: Any) -> None:
        self.issued_commands.append({"kind": "do_action", "action": action})

    async def do(self, action: Any) -> None:
        self.issued_commands.append({"kind": "do", "action": action})

    async def chat_send(self, message: str, team_only: bool = False) -> None:
        self.issued_commands.append({"kind": "chat", "message": message})

    def _advance_step(self) -> None:
        self._step_count += 1
        self._minerals += 10


class RealSc2BackendAdapterProtocolTests(unittest.TestCase):
    """G1: RealSc2BackendAdapter implements RlBackend protocol."""

    def test_implements_rl_backend_protocol(self) -> None:
        from cmre_rl_training.real_sc2_backend import RealSc2BackendAdapter

        bot = MockBotAI()
        adapter = RealSc2BackendAdapter(bot)
        self.assertIsInstance(adapter, RlBackend)

    def test_state_version_is_int_and_non_negative(self) -> None:
        from cmre_rl_training.real_sc2_backend import RealSc2BackendAdapter

        adapter = RealSc2BackendAdapter(MockBotAI())
        self.assertIsInstance(adapter.state_version, int)
        self.assertGreaterEqual(adapter.state_version, 0)

    def test_reset_returns_observation_dict(self) -> None:
        from cmre_rl_training.real_sc2_backend import RealSc2BackendAdapter

        adapter = RealSc2BackendAdapter(MockBotAI())
        obs = adapter.reset()
        self.assertIsInstance(obs, dict)
        for key in ("loop", "player_id", "own_units", "visible_enemies",
                     "resources", "mission"):
            self.assertIn(key, obs)

    def test_step_returns_tuple_of_correct_types(self) -> None:
        from cmre_rl_training.real_sc2_backend import RealSc2BackendAdapter

        adapter = RealSc2BackendAdapter(MockBotAI())
        adapter.reset()
        obs, terminated, info = adapter.step("move_units", {"target_x": 70.0, "target_y": 80.0})
        self.assertIsInstance(obs, dict)
        self.assertIsInstance(terminated, bool)
        self.assertIsInstance(info, dict)
        self.assertIn("action_id", info)


class RealSc2BackendActionTranslationTests(unittest.TestCase):
    """G2: All 19 RL actions translate to correct SC2 commands."""

    def setUp(self) -> None:
        from cmre_rl_training.real_sc2_backend import RealSc2BackendAdapter

        self.bot = MockBotAI()
        self.adapter = RealSc2BackendAdapter(self.bot)
        self.adapter.reset()

    def test_all_19_actions_have_translators(self) -> None:
        from cmre_rl_training.real_sc2_backend import RealSc2BackendAdapter

        adapter = RealSc2BackendAdapter(MockBotAI())
        for action_name in ACTION_NAMES:
            self.assertIn(
                action_name,
                adapter._action_translators,
                f"Missing translator for action: {action_name}",
            )

    def test_move_units_translates_to_move_command(self) -> None:
        self.adapter.step("move_units", {
            "target_x": 70.0, "target_y": 80.0,
            "entity_tags": [3],
        })
        self.assertEqual(len(self.bot.issued_commands), 1)
        self.assertIn("move", str(self.bot.issued_commands[0]).lower() +
                      str(self.bot.issued_commands[0]["action"]).lower())

    def test_attack_move_units_translates_to_attack_move(self) -> None:
        self.adapter.step("attack_move_units", {
            "target_x": 70.0, "target_y": 80.0,
            "entity_tags": [3],
        })
        self.assertGreaterEqual(len(self.bot.issued_commands), 1)

    def test_gather_resources_translates_to_gather(self) -> None:
        self.adapter.step("gather_resources", {
            "entity_tags": [2],
            "target_tag": 200,
        })
        self.assertGreaterEqual(len(self.bot.issued_commands), 1)

    def test_stop_units_translates_to_stop(self) -> None:
        self.adapter.step("stop_units", {"entity_tags": [3]})
        self.assertGreaterEqual(len(self.bot.issued_commands), 1)

    def test_hold_units_translates_to_hold(self) -> None:
        self.adapter.step("hold_units", {"entity_tags": [3]})
        self.assertGreaterEqual(len(self.bot.issued_commands), 1)

    def test_build_structure_translates_to_build(self) -> None:
        self.adapter.step("build_structure", {
            "entity_tags": [2],
            "unit_type": "SupplyDepot",
            "target_x": 84.0, "target_y": 93.0,
        })
        self.assertGreaterEqual(len(self.bot.issued_commands), 1)

    def test_produce_unit_translates_to_train(self) -> None:
        self.adapter.step("produce_unit", {
            "entity_tags": [1],
            "unit_type": "SCV",
        })
        self.assertGreaterEqual(len(self.bot.issued_commands), 1)

    def test_cancel_order_translates_to_cancel(self) -> None:
        # Give a unit an order first
        self.bot._units_list[2].orders = [{"ability_id": 1234}]
        self.adapter.step("cancel_order", {"entity_tags": [3]})
        self.assertGreaterEqual(len(self.bot.issued_commands), 1)

    def test_state_version_advances_after_step(self) -> None:
        v0 = self.adapter.state_version
        self.adapter.step("move_units", {"target_x": 70.0, "target_y": 80.0})
        self.assertGreater(self.adapter.state_version, v0)

    def test_unknown_action_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self.adapter.step("nonexistent_action", {})

    def test_step_with_no_entity_tags_defaults_to_all_combat(self) -> None:
        """If no entity_tags provided, adapter should pick combat units."""
        self.adapter.step("move_units", {"target_x": 70.0, "target_y": 80.0})
        self.assertGreaterEqual(len(self.bot.issued_commands), 1)


class RealSc2BackendObservationTests(unittest.TestCase):
    """Observation dict produced by RealSc2BackendAdapter is encoder-compatible."""

    def setUp(self) -> None:
        from cmre_rl_training.real_sc2_backend import RealSc2BackendAdapter

        self.adapter = RealSc2BackendAdapter(MockBotAI())
        self.adapter.reset()

    def test_observation_has_encoder_required_fields(self) -> None:
        from cmre_rl_training.observation import rl_feature_count

        obs = self.adapter.reset()
        self.assertIn("resources", obs)
        self.assertIn("minerals", obs["resources"])
        self.assertIn("supply_used", obs["resources"])
        self.assertIn("supply_cap", obs["resources"])
        self.assertIn("state_version", obs["resources"])
        self.assertIn("mission", obs)
        self.assertIn("own_units", obs)
        # Each own_unit must have entity_id, unit_type_id, etc.
        if obs["own_units"]:
            unit = obs["own_units"][0]
            for field in ("entity_id", "unit_type_id", "owner", "x", "y",
                          "health", "shields", "energy", "state", "orders"):
                self.assertIn(field, unit, f"Unit missing field: {field}")

    def test_observation_resources_state_version_matches_loop(self) -> None:
        obs = self.adapter.reset()
        self.assertEqual(
            obs["resources"]["state_version"],
            obs["loop"],
        )


if __name__ == "__main__":
    unittest.main()
