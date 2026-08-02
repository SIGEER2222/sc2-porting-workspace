from __future__ import annotations

import asyncio
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from cmre_neuro_adapter.neuro.actions import ActionCommand, ExecutionResult
from cmre_neuro_adapter.neuro.context import ContextEnvelope
from cmre_neuro_adapter.neuro.mission_projection import PublicMissionContext
from cmre_neuro_adapter.transports import (
    BankTransport,
    InputBinding,
    InputTransport,
    Sc2ApiTransport,
    TransportError,
    XmlBankStore,
)


def observation(loop: int = 4) -> dict:
    return {
        "player_id": 1,
        "loop": loop,
        "state_version": loop,
        "mission": {"phase": "night", "night": 1, "wave": 2},
        "resources": {"minerals": 500, "vespene": 100},
        "own_units": [],
        "visible_enemies": [],
    }


def command(action_id: str = "a-1", name: str = "move") -> ActionCommand:
    return ActionCommand(action_id, name, {"expected_state_version": 4}, 1.0)


class FakeSc2Api:
    def __init__(self) -> None:
        self.connected = False
        self.calls: list[str] = []
        self.commands: list[str] = []

    async def connect(self) -> None:
        self.calls.append("connect")
        self.connected = True

    async def close(self) -> None:
        self.calls.append("close")
        self.connected = False

    async def observe(self, player_id: int) -> dict:
        self.calls.append(f"observe:{player_id}")
        return observation()

    async def dispatch(self, action: ActionCommand) -> dict:
        self.commands.append(action.action_id)
        return {"success": True, "message": "SC2 accepted", "state_version": 5}


class SlowSc2Api(FakeSc2Api):
    async def dispatch(self, action: ActionCommand) -> dict:
        await asyncio.sleep(0.05)
        return await super().dispatch(action)


class Sc2ApiTransportTests(unittest.TestCase):
    def test_observation_dispatch_duplicate_and_reconnect(self) -> None:
        client = FakeSc2Api()
        transport = Sc2ApiTransport(client)
        asyncio.run(transport.connect())
        context = asyncio.run(transport.observe())
        result = asyncio.run(transport.dispatch(command()))
        duplicate = asyncio.run(transport.dispatch(command()))

        self.assertIsInstance(context, PublicMissionContext)
        self.assertTrue(result.success)
        self.assertEqual(result.state_version, 5)
        follow_up = asyncio.run(
            transport.dispatch(
                ActionCommand("a-2", "move", {"expected_state_version": 5}, 1.0)
            )
        )
        self.assertTrue(follow_up.success)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(client.commands, ["a-1", "a-2"])
        asyncio.run(transport.reconnect())
        self.assertEqual(transport.status.reconnects, 1)
        self.assertEqual(client.calls.count("connect"), 2)

    def test_stale_and_timeout_fail_as_typed_results(self) -> None:
        client = FakeSc2Api()
        transport = Sc2ApiTransport(client)
        asyncio.run(transport.connect())
        asyncio.run(transport.observe())
        stale = asyncio.run(
            transport.dispatch(
                ActionCommand("stale", "move", {"expected_state_version": 3}, 1.0)
            )
        )
        self.assertFalse(stale.success)
        self.assertEqual(stale.operation, "stale_state")

        slow = Sc2ApiTransport(SlowSc2Api(), timeout=0.001)
        asyncio.run(slow.connect())
        timed_out = asyncio.run(slow.dispatch(ActionCommand("slow", "move", {}, 1.0)))
        self.assertFalse(timed_out.success)
        self.assertEqual(timed_out.operation, "timeout")


class MemoryBank:
    def __init__(self) -> None:
        self.data: dict[str, dict] = {"meta": {"ready": True}}
        self.writes: list[dict] = []

    def read(self) -> dict:
        return {section: dict(values) for section, values in self.data.items()}

    def write(self, updates: dict) -> None:
        self.writes.append(updates)
        for section, values in updates.items():
            self.data.setdefault(section, {}).update(values)


class BankTransportTests(unittest.TestCase):
    def test_bank_stages_actions_and_context_with_correlation(self) -> None:
        bank = MemoryBank()
        transport = BankTransport(bank)
        transport.connect()
        transport.publish_context(ContextEnvelope("mission", "Night 1"))
        result = transport.dispatch(ActionCommand("bank-1", "move", {"x": 1}, 1.0))

        self.assertTrue(result.success)
        self.assertEqual(bank.data["do_action"]["action_id"], "bank-1")
        self.assertEqual(bank.data["do_action"]["action_name"], "move")
        self.assertTrue(bank.data["game_context"]["mission_new"])
        self.assertIsNone(transport.poll_result("missing"))

    def test_xml_bank_store_round_trips_reference_value_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "NeuroIntegration.SC2Bank")
            root = ET.Element("Bank")
            ET.SubElement(root, "Section", {"name": "meta"})
            ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
            store = XmlBankStore(path)
            store.write({"meta": {"ready": True, "count": 3, "name": "cmre"}})
            self.assertEqual(
                store.read(), {"meta": {"ready": True, "count": 3, "name": "cmre"}}
            )


class RecordingInput:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def send(self, binding: InputBinding, action: ActionCommand) -> ExecutionResult:
        self.calls.append((binding.kind, binding.value))
        return ExecutionResult(action.action_id, True, "sent", "input.key")


class InputTransportTests(unittest.TestCase):
    def test_bound_action_is_idempotent_and_unbound_action_fails(self) -> None:
        sink = RecordingInput()
        transport = InputTransport(sink, {"move": InputBinding("key", "M")})
        transport.connect()
        first = transport.dispatch(ActionCommand("input-1", "move", {}, 1.0))
        duplicate = transport.dispatch(ActionCommand("input-1", "move", {}, 1.0))
        unsupported = transport.dispatch(ActionCommand("input-2", "attack", {}, 1.0))

        self.assertTrue(first.success)
        self.assertTrue(duplicate.duplicate)
        self.assertFalse(unsupported.success)
        self.assertEqual(unsupported.operation, "unsupported_action")
        self.assertEqual(sink.calls, [("key", "M")])

    def test_input_transport_rejects_observation_and_context(self) -> None:
        transport = InputTransport(RecordingInput(), {"move": "M"})
        transport.connect()
        with self.assertRaises(TransportError) as observation_error:
            transport.observe()
        with self.assertRaises(TransportError) as context_error:
            transport.publish_context({})
        self.assertEqual(observation_error.exception.code, "observation_unsupported")
        self.assertEqual(context_error.exception.code, "context_unsupported")


if __name__ == "__main__":
    unittest.main()
