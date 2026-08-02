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
                                "behavior": "StimpackBehavior",
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


if __name__ == "__main__":
    unittest.main()
