"""Stage 22 simulator contract tests for typed combat and structure census."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "src" / "projects" / "cmre-porting"))

from vibe import protocol  # noqa: E402
from vibe.simulator_transport import SimulatorTransport  # noqa: E402


SCENARIO = {
    "schema_version": "m7.v1",
    "name": "Stage 22 typed combat census",
    "players": [
        {"id": 1, "name": "Ally", "race": "terran", "allies": [3]},
        {"id": 2, "name": "Enemy", "race": "zerg", "allies": []},
        {"id": 3, "name": "Friendly ally", "race": "terran", "allies": [1]},
    ],
    "spawns": [
        {"unit_type_id": "CommandCenter", "owner_player_id": 1, "x": 0.0, "y": 10.0},
        {"unit_type_id": "SupplyDepot", "owner_player_id": 1, "x": 6.0, "y": 10.0},
        {"unit_type_id": "CommandCenter", "owner_player_id": 2, "x": 12.0, "y": 10.0},
        {"unit_type_id": "Barracks", "owner_player_id": 3, "x": 18.0, "y": 10.0},
        {"unit_type_id": "Marine", "owner_player_id": 1, "x": 0.0, "y": 0.0},
        {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 4.0, "y": 0.0},
        {"unit_type_id": "Marine", "owner_player_id": 3, "x": 0.0, "y": 4.0},
        {"unit_type_id": "MineralField", "owner_player_id": 0, "x": 24.0, "y": 10.0},
    ],
    "max_loops": 200,
    "seed": 22,
    "strict": True,
    "win_condition": "survival",
}
COMBAT_SCENARIO = dict(SCENARIO)
COMBAT_SCENARIO["spawns"] = [
    spawn for spawn in SCENARIO["spawns"] if spawn["owner_player_id"] != 0
]


class TypedCombatCensusTests(unittest.TestCase):
    def _boot(self, suffix: str, scenario: dict = SCENARIO) -> SimulatorTransport:
        transport = SimulatorTransport()
        transport.open_session(f"stage22-{suffix}")
        session_id = transport.registry._sessions  # noqa: SLF001
        self.assertTrue(session_id)
        loaded = transport.send(protocol.make_request(
            list(session_id)[0], f"{suffix}-load", 1, "scenario.load",
            {"scenario_dict": scenario},
        ))
        self.assertEqual(loaded.error_code, 0)
        reset = transport.send(protocol.make_request(
            list(session_id)[0], f"{suffix}-reset", 2, "scenario.reset",
        ))
        self.assertEqual(reset.error_code, 0)
        return transport

    def _invoke(self, transport: SimulatorTransport, request_id: str, sequence: int,
                function_id: str, args: dict):
        session_id = next(iter(transport.registry._sessions))  # noqa: SLF001
        return transport.send(protocol.make_request(
            session_id, request_id, sequence, "function.invoke",
            {"function_id": function_id, "args": args},
        ))

    def test_structure_census_is_typed_and_read_only(self):
        transport = self._boot("census")
        world = transport.session.world
        self.assertIsNotNone(world)
        before = world.snapshot()

        all_structures = self._invoke(
            transport, "census-all", 3, "vibe.query.structures", {},
        )
        self.assertEqual(all_structures.error_code, 0)
        self.assertEqual(all_structures.payload["live_count"], 4)
        self.assertEqual(
            {(item["owner"], item["unit_type"]) for item in all_structures.payload["structures"]},
            {(1, "CommandCenter"), (1, "SupplyDepot"), (2, "CommandCenter"), (3, "Barracks")},
        )
        self.assertNotIn((0, "MineralField"), {
            (item["owner"], item["unit_type"])
            for item in all_structures.payload["structures"]
        })

        owner_one = self._invoke(
            transport, "census-owner", 4, "vibe.query.structures",
            {"owner_player": 1},
        )
        self.assertEqual(owner_one.error_code, 0)
        self.assertEqual(owner_one.payload["live_count"], 2)
        command_centers = self._invoke(
            transport, "census-type", 5, "vibe.query.structures",
            {"unit_type": "CommandCenter"},
        )
        self.assertEqual(command_centers.error_code, 0)
        self.assertEqual(command_centers.payload["live_count"], 2)
        self.assertEqual(world.snapshot(), before)

    def test_invalid_targets_are_rejected_without_state_side_effects(self):
        for label, target_tag in (("missing", 9999), ("neutral", 8), ("ally", 7)):
            with self.subTest(target=label):
                transport = self._boot(f"invalid-{label}")
                world = transport.session.world
                before = world.snapshot()
                response = self._invoke(
                    transport, f"attack-{label}", 3, "vibe.unit.attack",
                    {"attacker_tag": 5, "target_tag": target_tag},
                )
                self.assertEqual(response.error_code, int(protocol.ErrorCode.INVALID_ARGS))
                self.assertEqual(world.snapshot(), before)

        transport = self._boot("invalid-stale")
        killed = self._invoke(
            transport, "kill-target", 3, "vibe.unit.kill", {"unit_tag": 6},
        )
        self.assertEqual(killed.error_code, 0)
        world = transport.session.world
        before = world.snapshot()
        stale = self._invoke(
            transport, "attack-stale", 4, "vibe.unit.attack",
            {"attacker_tag": 5, "target_tag": 6},
        )
        self.assertEqual(stale.error_code, int(protocol.ErrorCode.INVALID_ARGS))
        self.assertEqual(world.snapshot(), before)

    def test_valid_enemy_attack_advances_and_changes_target_health(self):
        transport = self._boot("valid-attack", COMBAT_SCENARIO)
        world = transport.session.world
        target_before = world.get_entity(6).health.raw
        response = self._invoke(
            transport, "attack-valid", 3, "vibe.unit.attack",
            {"attacker_tag": 5, "target_tag": 6},
        )
        self.assertEqual(response.error_code, 0)
        self.assertTrue(response.payload["issued"])
        self.assertEqual(world.get_entity(5).attack_target_id, 6)

        stepped = transport.send(protocol.make_request(
            next(iter(transport.registry._sessions)), "step-after-attack", 4,
            "scenario.step", {"loops": 30},
        ))
        self.assertEqual(stepped.error_code, 0)
        self.assertEqual(stepped.payload["loop"], 30)
        self.assertLess(world.get_entity(6).health.raw, target_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
