from __future__ import annotations

import sys
import unittest
import asyncio
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
VIBE_ROOT = REPO_ROOT / "src" / "projects" / "cmre-porting"
if str(VIBE_ROOT) not in sys.path:
    sys.path.insert(0, str(VIBE_ROOT))

from cmre_neuro_adapter.neuro.actions import ActionCommand  # noqa: E402
from cmre_neuro_adapter.neuro.basic_actions import (  # noqa: E402
    BASIC_ACTION_ROUTES,
    basic_action_definitions,
    basic_action_operations,
    route_basic_action,
)
from cmre_neuro_adapter.neuro.schemas import (  # noqa: E402
    SchemaValidationError,
    validate_action_arguments,
)
from cmre_neuro_adapter.neuro.simulator_transport import (  # noqa: E402
    SimulatorSessionBackend,
    SimulatorTransport,
)
from cmre_neuro_adapter.neuro.runtime import NeuroRuntime  # noqa: E402
from cmre_neuro_adapter.neuro.sender import MemorySender  # noqa: E402
from cmre_neuro_adapter.neuro.session import NeuroSessionIdentity  # noqa: E402


MOVE_SCENARIO = (
    REPO_ROOT
    / "reference"
    / "sc2-ally-bot"
    / "scenarios"
    / "sc2-simulator"
    / "marine_move_only.json"
)
BARRACKS_SCENARIO = (
    REPO_ROOT
    / "reference"
    / "sc2-ally-bot"
    / "scenarios"
    / "sc2-simulator"
    / "barracks_and_marine.json"
)


class BasicActionCatalogTests(unittest.TestCase):
    def test_catalog_covers_command_surface_with_fixed_routes(self) -> None:
        expected = {
            "move_units",
            "stop_units",
            "hold_units",
            "patrol_units",
            "attack_move_units",
            "attack_units",
            "gather_resources",
            "build_structure",
            "produce_unit",
            "research_upgrade",
            "cast_point_ability",
            "cast_unit_ability",
            "cast_no_target_ability",
            "repair_units",
            "morph_unit",
            "cancel_order",
            "load_units",
            "unload_units",
            "rally_producer",
        }
        self.assertEqual(set(BASIC_ACTION_ROUTES), expected)
        self.assertEqual(set(basic_action_operations()), expected)
        self.assertEqual(
            tuple(action.name for action in basic_action_definitions()),
            tuple(BASIC_ACTION_ROUTES),
        )

    def test_route_is_typed_and_maps_research_name_without_reflection(self) -> None:
        command = ActionCommand(
            "research-1",
            "research_upgrade",
            {
                "entity_ids": [4],
                "issuer_player_id": 1,
                "upgrade_id": "TerranInfantryWeaponsLevel1",
            },
            0.0,
        )
        operation, args = route_basic_action(command)
        self.assertEqual(operation, "unit.order")
        self.assertEqual(args["kind"], "research")
        self.assertEqual(args["unit_type_id"], "TerranInfantryWeaponsLevel1")
        self.assertNotIn("upgrade_id", args)

    def test_array_schema_rejects_invalid_group_without_side_effect(self) -> None:
        schema = BASIC_ACTION_ROUTES["move_units"].schema
        with self.assertRaises(SchemaValidationError):
            validate_action_arguments(
                {
                    "entity_ids": [],
                    "issuer_player_id": 1,
                    "target_x": 1.0,
                    "target_y": 0.0,
                },
                schema,
            )
        with self.assertRaises(SchemaValidationError):
            validate_action_arguments(
                {
                    "entity_ids": [True],
                    "issuer_player_id": 1,
                    "target_x": 1.0,
                    "target_y": 0.0,
                },
                schema,
            )


class BasicActionSimulatorTests(unittest.TestCase):
    @staticmethod
    def _session(path: Path):
        from cmre_neuro_adapter.neuro.simulator_transport import SimulatorSessionBackend
        from vibe.simulator_session import SimulatorSession

        session = SimulatorSession()
        session.scenario_load(scenario_path=str(path), catalog="m7")
        session.scenario_reset()
        backend = SimulatorSessionBackend(
            session,
            action_operations=basic_action_operations(),
        )
        return session, SimulatorTransport(
            backend,
            action_operations=basic_action_operations(),
        )

    def test_move_command_changes_real_simulator_position(self) -> None:
        session, transport = self._session(MOVE_SCENARIO)
        result = transport.dispatch(
            ActionCommand(
                "move-1",
                "move_units",
                {
                    "entity_ids": [1],
                    "issuer_player_id": 1,
                    "target_x": 5.0,
                    "target_y": 0.0,
                },
                0.0,
            ),
            expected_state_version=0,
        )
        self.assertTrue(result.success, result.message)
        session.scenario_step(200)
        unit = session.query_unit(1)
        self.assertAlmostEqual(unit["x"], 5.0, delta=0.2)

    def test_build_and_produce_commands_change_real_simulator_state(self) -> None:
        session, transport = self._session(BARRACKS_SCENARIO)
        build = transport.dispatch(
            ActionCommand(
                "build-1",
                "build_structure",
                {
                    "entity_ids": [3],
                    "issuer_player_id": 1,
                    "unit_type_id": "Barracks",
                    "target_x": 5.0,
                    "target_y": 0.0,
                },
                0.0,
            ),
            expected_state_version=0,
        )
        self.assertTrue(build.success, build.message)
        session.scenario_step(70)
        structures = session.query_structures(1, "Barracks")
        self.assertEqual(structures["live_count"], 1)
        producer = structures["structures"][0]["unit_tag"]
        train = transport.dispatch(
            ActionCommand(
                "train-1",
                "produce_unit",
                {
                    "entity_ids": [producer],
                    "issuer_player_id": 1,
                    "unit_type_id": "Marine",
                },
                0.0,
            ),
            expected_state_version=70,
        )
        self.assertTrue(train.success, train.message)
        session.scenario_step(25)
        marines = [
            unit
            for unit in session.query_units(1)["units"]
            if unit["unit_type_id"] == "Marine" and unit["state"] != "dead"
        ]
        self.assertGreaterEqual(len(marines), 1)

    def test_runtime_registers_queues_dispatches_and_returns_basic_action(self) -> None:
        _session, transport = self._session(MOVE_SCENARIO)
        sender = MemorySender()
        runtime = NeuroRuntime(sender, dispatcher=transport.dispatch)

        async def run() -> object:
            await runtime.connect()
            await runtime.update_actions(basic_action_definitions())
            await runtime.identify(NeuroSessionIdentity("session", "character", "Neuro"))
            await runtime.start_mission()
            accepted = await runtime.receive_action(
                {
                    "id": "runtime-move-1",
                    "name": "move_units",
                    "arguments": {
                        "entity_ids": [1],
                        "issuer_player_id": 1,
                        "target_x": 5.0,
                        "target_y": 0.0,
                        "expected_state_version": 0,
                    },
                }
            )
            dispatched = await runtime.dispatch_next()
            return accepted, dispatched

        accepted, dispatched = asyncio.run(run())
        self.assertTrue(accepted.success)
        self.assertIsNotNone(dispatched)
        assert dispatched is not None
        self.assertTrue(dispatched.success, dispatched.message)
        self.assertEqual(dispatched.action_id, "runtime-move-1")
        self.assertEqual(dispatched.operation, "unit.order")
        self.assertEqual(sender.messages[-1]["command"], "action/result")


if __name__ == "__main__":
    unittest.main()
