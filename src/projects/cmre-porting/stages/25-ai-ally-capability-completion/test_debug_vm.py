"""Focused tests for the hot-loaded runtime debug VM."""

from __future__ import annotations

import asyncio
import json
import unittest

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "src" / "projects" / "cmre-porting"))

from vibe.debug_vm import DebugVm, load_function_metadata  # noqa: E402
from vibe import protocol  # noqa: E402
from vibe.simulator_transport import SimulatorTransport  # noqa: E402


class FakeBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.loop = 0

    async def call(self, function_id: str, args: dict):
        self.calls.append((function_id, args))
        if function_id == "vibe.test.ping":
            return {"kind": "result", "error_code": "OK", "state_version": self.loop, "payload": {"message": "pong", **args}}
        return {"kind": "error", "error_code": "FUNCTION_NOT_FOUND", "state_version": self.loop, "payload": {"reason": function_id}}

    async def step(self, loops: int):
        self.loop += loops
        return {"kind": "result", "error_code": "OK", "state_version": self.loop, "payload": {"loop": self.loop}}


class UnitBridge(FakeBridge):
    async def call(self, function_id: str, args: dict):
        self.calls.append((function_id, args))
        if function_id == "vibe.unit.spawn_group":
            return {
                "kind": "result",
                "error_code": "OK",
                "state_version": self.loop,
                "payload": {"function_id": function_id, "created": 3, "unit_tags": [101, 102, 103]},
            }
        if function_id == "vibe.unit.add_behavior":
            return {
                "kind": "result",
                "error_code": "OK",
                "state_version": self.loop,
                "payload": {
                    "function_id": function_id,
                    "unit_tag": args["unit_tag"],
                    "behavior": args["behavior"],
                    "stacks": args["stacks"],
                    "count": args["stacks"],
                },
            }
        if function_id == "vibe.unit.add_ability":
            return {
                "kind": "result",
                "error_code": "OK",
                "state_version": self.loop,
                "payload": {
                    "function_id": function_id,
                    "unit_tag": args["unit_tag"],
                    "ability": args["ability"],
                    "has_ability": True,
                },
            }
        if function_id == "vibe.unit.query_ability":
            return {
                "kind": "result",
                "error_code": "OK",
                "state_version": self.loop,
                "payload": {
                    "function_id": function_id,
                    "unit_tag": args["unit_tag"],
                    "ability": args["ability"],
                    "has_ability": True,
                },
            }
        return await super().call(function_id, args)


class DebugVmTests(unittest.TestCase):
    def run_vm(self, program, *, metadata=None, catalog=None):
        return asyncio.run(DebugVm(
            FakeBridge(),
            function_metadata=metadata or load_function_metadata(),
            catalog=catalog or [],
        ).run(program))

    def test_call_step_assert_repeat_without_game_restart(self):
        result = self.run_vm({
            "vm": "vibe-debug/1",
            "steps": [
                {"op": "call", "fn": "vibe.test.ping", "args": {"nonce": "hot"}, "save": "ping"},
                {"op": "assert", "source": "$vars.ping", "path": "message", "equals": "pong"},
                {"op": "repeat", "count": 2, "steps": [{"op": "step", "loops": 3}]},
                {"op": "assert", "source": "$last", "path": "loop", "equals": 6},
            ],
        })
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["instructions_executed"], 6)

    def test_unregistered_function_fails_before_transport(self):
        result = self.run_vm({
            "vm": "vibe-debug/1",
            "steps": [
                {"op": "call", "fn": "vibe.test.unknown", "args": {}, "allow_error": True},
            ],
        })
        self.assertEqual(result["status"], "failed")
        self.assertIn("not registered", result["error"])

    def test_inventory_only_catalog_entry_is_not_callable(self):
        catalog_path = ROOT / "artifacts" / "projects" / "cmre-porting" / "stage25-ai-ally-capability-completion" / "discovery" / "function-catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        inventory_entry = next(
            entry for entry in catalog["functions"]
            if entry["disposition"] == "inventory-only"
        )
        bridge = FakeBridge()
        result = asyncio.run(DebugVm(
            bridge,
            function_metadata=load_function_metadata(),
            catalog=catalog["functions"],
        ).run({
            "vm": "vibe-debug/1",
            "steps": [{"op": "call", "fn": inventory_entry["name"], "args": {}}],
        }))
        self.assertEqual(result["status"], "failed")
        self.assertIn("not registered", result["error"])
        self.assertEqual(bridge.calls, [])

    def test_strategy_rejects_debug_only_function(self):
        result = self.run_vm({
            "vm": "vibe-debug/1",
            "mode": "strategy",
            "steps": [{"op": "call", "fn": "vibe.test.ping", "args": {}}],
        }, metadata={"vibe.test.ping": {"debug_only": True}})
        self.assertEqual(result["status"], "failed")
        self.assertIn("debug-only", result["error"])

    def test_catalog_search_is_local_and_bounded(self):
        result = self.run_vm({
            "vm": "vibe-debug/1",
            "steps": [{"op": "catalog.search", "name": "hex", "limit": 1, "save": "matches"}],
        }, catalog=[{"name": "libHexTalents", "kind": "library-function"}, {"name": "other", "kind": "helper"}])
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["vars"]["matches"]["count"], 1)

    def test_typed_args_are_rejected_before_bridge(self):
        bridge = FakeBridge()
        result = asyncio.run(DebugVm(
            bridge,
            function_metadata=load_function_metadata(),
        ).run({
            "vm": "vibe-debug/1",
            "steps": [{
                "op": "call",
                "fn": "vibe.test.ping",
                "args": {"nonce": "bad;wire"},
            }],
        }))
        self.assertEqual(result["status"], "failed")
        self.assertIn("INVALID_ARGS", result["error"])
        self.assertEqual(bridge.calls, [])

    def test_catalog_artifact_is_complete_and_registry_aligned(self):
        catalog_path = ROOT / "artifacts" / "projects" / "cmre-porting" / "stage25-ai-ally-capability-completion" / "discovery" / "function-catalog.json"
        registry = load_function_metadata()
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        self.assertEqual(catalog["summary"]["functions"], len(catalog["functions"]))
        self.assertEqual(sum(catalog["summary"]["by_disposition"].values()), len(catalog["functions"]))
        self.assertTrue(all(source["parse_errors"] == 0 for source in catalog["sources"]))
        callable_names = {entry["name"] for entry in catalog["functions"] if entry["registered_handler"]}
        registry_handlers = {entry["handler"] for entry in registry.values()}
        catalog_names = {entry["name"] for entry in catalog["functions"]}
        self.assertTrue(registry_handlers)
        self.assertTrue(registry_handlers <= callable_names)
        self.assertTrue(catalog_names)
        self.assertTrue(all(
            entry["disposition"] == "inventory-only" or entry["registered_handler"]
            for entry in catalog["functions"]
        ))

    def test_instruction_budget_fails_closed(self):
        vm = DebugVm(FakeBridge(), function_metadata={"vibe.test.ping": {}} , max_instructions=2)
        result = asyncio.run(vm.run({
            "vm": "vibe-debug/1",
            "steps": [{"op": "repeat", "count": 3, "steps": [{"op": "set", "name": "x", "value": 1}]}],
        }))
        self.assertEqual(result["status"], "failed")
        self.assertIn("budget", result["error"])

    def test_foreach_applies_behavior_to_every_returned_unit_tag(self):
        bridge = UnitBridge()
        result = asyncio.run(DebugVm(
            bridge,
            function_metadata=load_function_metadata(),
        ).run({
            "vm": "vibe-debug/1",
            "steps": [
                {
                    "op": "call",
                    "fn": "vibe.unit.spawn_group",
                    "args": {"unit_type": "Marine", "count": 3, "player": 1},
                    "save": "squad",
                },
                {
                    "op": "foreach",
                    "source": "$vars.squad.unit_tags",
                    "item": "unit_tag",
                    "steps": [
                        {
                            "op": "call",
                            "fn": "vibe.unit.add_behavior",
                            "args": {
                                "unit_tag": "$vars.unit_tag",
                                "behavior": "Stimpack",
                                "stacks": 1,
                            },
                        },
                        {"op": "assert", "source": "$last", "path": "count", "equals": 1},
                    ],
                },
            ],
        }))
        self.assertEqual(result["status"], "passed")
        behavior_calls = [call for call in bridge.calls if call[0] == "vibe.unit.add_behavior"]
        self.assertEqual([args["unit_tag"] for _, args in behavior_calls], [101, 102, 103])

    def test_foreach_adds_ability_to_every_returned_unit_tag(self):
        bridge = UnitBridge()
        result = asyncio.run(DebugVm(
            bridge,
            function_metadata=load_function_metadata(),
        ).run({
            "vm": "vibe-debug/1",
            "steps": [
                {
                    "op": "call",
                    "fn": "vibe.unit.spawn_group",
                    "args": {"unit_type": "Marine", "count": 3, "player": 1},
                    "save": "squad",
                },
                {
                    "op": "foreach",
                    "source": "$vars.squad.unit_tags",
                    "item": "unit_tag",
                    "steps": [
                        {
                            "op": "call",
                            "fn": "vibe.unit.add_ability",
                            "args": {
                                "unit_tag": "$vars.unit_tag",
                                "ability": "Stimpack",
                            },
                        },
                        {"op": "assert", "source": "$last", "path": "has_ability", "equals": True},
                        {
                            "op": "call",
                            "fn": "vibe.unit.query_ability",
                            "args": {
                                "unit_tag": "$vars.unit_tag",
                                "ability": "Stimpack",
                            },
                        },
                        {"op": "assert", "source": "$last", "path": "has_ability", "equals": True},
                    ],
                },
            ],
        }))
        self.assertEqual(result["status"], "passed")
        ability_calls = [call for call in bridge.calls if call[0] == "vibe.unit.add_ability"]
        self.assertEqual([args["unit_tag"] for _, args in ability_calls], [101, 102, 103])
        query_calls = [call for call in bridge.calls if call[0] == "vibe.unit.query_ability"]
        self.assertEqual([args["unit_tag"] for _, args in query_calls], [101, 102, 103])

    def test_cross_unit_ability_program_is_hot_loadable(self):
        program_path = Path(__file__).with_name("debug-vm-runtime-cross-unit-ability.json")
        program = json.loads(program_path.read_text(encoding="utf-8"))
        self.assertEqual(program["steps"][3]["fn"], "vibe.unit.query_ability")
        self.assertEqual(program["steps"][3]["args"]["ability"], "MedivacHeal")
        self.assertEqual(program["steps"][5]["fn"], "vibe.unit.add_ability")
        self.assertEqual(program["steps"][5]["args"]["ability"], "MedivacHeal")
        self.assertEqual(program["steps"][7]["args"]["ability"], "MedivacHeal")

    def test_comprehensive_capability_program_runs_against_simulator_transport(self):
        program_path = Path(__file__).with_name("debug-vm-runtime-capability.json")
        program = json.loads(program_path.read_text(encoding="utf-8"))
        transport = SimulatorTransport()
        session_id = "stage25-debug-vm-capability"
        transport.open_session(session_id)
        scenario = {
            "schema_version": "m7.v1",
            "name": "Stage 25 Debug VM capability probe",
            "players": [{"id": 1, "name": "Debugger", "race": "terran", "allies": []}],
            "spawns": [],
            "max_loops": 20,
            "seed": 25,
            "strict": True,
            "win_condition": "survival",
        }
        loaded = transport.send(protocol.make_request(
            session_id, "cap-load", 1, "scenario.load", {"scenario_dict": scenario},
        ))
        self.assertEqual(loaded.error_code, 0, loaded.payload)
        reset = transport.send(protocol.make_request(
            session_id, "cap-reset", 2, "scenario.reset",
        ))
        self.assertEqual(reset.error_code, 0, reset.payload)

        class TransportBridge:
            async def call(self, function_id, args):
                response = transport.send(protocol.make_request(
                    session_id,
                    f"vm-call-{transport.executed + 1}",
                    transport.executed + 3,
                    "function.invoke",
                    {"function_id": function_id, "args": args},
                ))
                return response

            async def step(self, loops):
                return transport.send(protocol.make_request(
                    session_id,
                    f"vm-step-{transport.executed + 1}",
                    transport.executed + 3,
                    "scenario.step",
                    {"loops": loops},
                ))

        catalog_path = ROOT / "artifacts" / "projects" / "cmre-porting" / "stage25-ai-ally-capability-completion" / "discovery" / "function-catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))["functions"]
        result = asyncio.run(DebugVm(
            TransportBridge(),
            function_metadata=load_function_metadata(),
            catalog=catalog,
            max_instructions=256,
        ).run(program))
        self.assertEqual(result["status"], "passed", result["error"])
        self.assertGreaterEqual(result["instructions_executed"], 40)
        self.assertEqual(transport.session.world.get_entity(1).health.to_float(), 12.5)
        self.assertEqual(transport.session._catalog_overrides[("unit", "Marine", "LifeMax", 1)], "60.5")
        self.assertEqual(transport.session._catalog_overrides[("unit", "Marine", "CostResource[0]", 1)], "25")
        self.assertEqual(transport.session._catalog_overrides[("unit", "Marine", "CostResource[1]", 1)], "10")
        self.assertEqual(transport.session._catalog_overrides[("abil", "BarracksTrainNova", "InfoArray[0].Unit", 1)], "Marauder")
        self.assertEqual(
            transport.session._visual_overrides[1],
            {
                "model": {"model": "Marine", "variation": 2},
                "scale": 1.5,
                "color": "{1,0.1,0.1,1}",
                "opacity": 0.5,
            },
        )


if __name__ == "__main__":
    unittest.main()
