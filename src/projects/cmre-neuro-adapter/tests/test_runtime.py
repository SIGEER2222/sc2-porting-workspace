from __future__ import annotations

import asyncio
import unittest

from cmre_neuro_adapter.neuro.actions import ActionCommand, ActionDefinition, ExecutionResult
from cmre_neuro_adapter.neuro.context import ContextEnvelope
from cmre_neuro_adapter.neuro.runtime import NeuroRuntime
from cmre_neuro_adapter.neuro.sender import MemorySender
from cmre_neuro_adapter.neuro.session import NeuroSessionIdentity


SCHEMA = {
    "type": "object",
    "properties": {"target": {"type": "string", "enum": ["base", "north"]}},
    "required": ["target"],
    "additionalProperties": False,
}


def action(name: str = "move") -> ActionDefinition:
    return ActionDefinition(name, "Move the army.", SCHEMA)


IDENTITY = NeuroSessionIdentity("session-1", "character-1", "Neuro")


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sender = MemorySender()
        self.dispatched: list[ActionCommand] = []

        def dispatcher(command: ActionCommand) -> ExecutionResult:
            self.dispatched.append(command)
            return ExecutionResult(command.action_id, True, "applied", "dispatch")

        self.runtime = NeuroRuntime(self.sender, dispatcher=dispatcher)

    def ready_runtime(self) -> None:
        asyncio.run(self.runtime.connect())
        asyncio.run(self.runtime.update_actions([action()]))
        asyncio.run(self.runtime.identify(IDENTITY))

    def test_registration_and_context_wait_for_identity(self) -> None:
        asyncio.run(self.runtime.connect())
        asyncio.run(self.runtime.update_actions([action()]))
        self.assertEqual([item["command"] for item in self.sender.messages], ["startup"])
        self.assertFalse(
            asyncio.run(
                self.runtime.publish_context(ContextEnvelope("mission", "Night 1"))
            )
        )

        asyncio.run(self.runtime.identify(IDENTITY))

        self.assertEqual(
            [item["command"] for item in self.sender.messages],
            ["startup", "actions/register"],
        )
        self.assertTrue(self.runtime.state.identified)
        self.assertEqual(self.runtime.state.active_actions, ("move",))

    def test_wire_messages_drive_startup_and_action_result(self) -> None:
        asyncio.run(self.runtime.connect())
        asyncio.run(self.runtime.update_actions([action()]))

        identity = asyncio.run(
            self.runtime.handle_message(
                {
                    "command": "startup",
                    "data": {
                        "session": {
                            "sessionId": "session-1",
                            "characterId": "character-1",
                            "displayName": "Neuro",
                        }
                    },
                }
            )
        )
        result = asyncio.run(
            self.runtime.handle_message(
                {
                    "command": "action",
                    "data": {
                        "id": "move-1",
                        "name": "move",
                        "arguments": {"target": "base"},
                    },
                }
            )
        )

        self.assertEqual(identity, IDENTITY)
        self.assertTrue(result.success)
        self.assertEqual(self.runtime.state.queued_action_ids, ("move-1",))

    def test_invalid_unknown_and_duplicate_actions_are_rejected(self) -> None:
        self.ready_runtime()
        self.sender.clear()

        unknown = asyncio.run(
            self.runtime.receive_action({"id": "unknown-1", "name": "attack", "arguments": {}})
        )
        invalid = asyncio.run(
            self.runtime.receive_action({"id": "invalid-1", "name": "move", "arguments": {}})
        )
        accepted = asyncio.run(
            self.runtime.receive_action(
                {"id": "move-1", "name": "move", "arguments": {"target": "base"}}
            )
        )
        duplicate = asyncio.run(
            self.runtime.receive_action(
                {"id": "move-1", "name": "move", "arguments": {"target": "north"}}
            )
        )

        self.assertFalse(unknown.success)
        self.assertFalse(invalid.success)
        self.assertTrue(accepted.success)
        self.assertFalse(duplicate.success)
        self.assertEqual(len(self.runtime.queue), 1)
        self.assertEqual(
            [item["data"]["success"] for item in self.sender.messages],
            [False, False, True, False],
        )

    def test_paused_blocking_and_update_windows_do_not_dispatch(self) -> None:
        self.ready_runtime()
        asyncio.run(self.runtime.start_mission())
        asyncio.run(
            self.runtime.receive_action(
                {"id": "move-1", "name": "move", "arguments": {"target": "base"}}
            )
        )

        for setter in (
            self.runtime.set_paused,
            self.runtime.set_blocking,
            self.runtime.set_update_in_progress,
        ):
            setter(True)
            self.assertIsNone(asyncio.run(self.runtime.dispatch_next()))
            setter(False)

        result = asyncio.run(self.runtime.dispatch_next())
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual([item.action_id for item in self.dispatched], ["move-1"])

    def test_reconnect_reregisters_and_preserves_queue(self) -> None:
        self.ready_runtime()
        asyncio.run(
            self.runtime.receive_action(
                {"id": "move-1", "name": "move", "arguments": {"target": "base"}}
            )
        )
        self.sender.clear()

        asyncio.run(self.runtime.disconnect())
        asyncio.run(self.runtime.connect())
        self.assertEqual([item["command"] for item in self.sender.messages], ["startup"])
        asyncio.run(self.runtime.identify(IDENTITY))

        self.assertEqual(
            [item["command"] for item in self.sender.messages],
            ["startup", "actions/register"],
        )
        self.assertEqual(self.runtime.state.queued_action_ids, ("move-1",))

    def test_end_mission_unregisters_actions_and_clears_queue(self) -> None:
        self.ready_runtime()
        asyncio.run(self.runtime.start_mission())
        asyncio.run(
            self.runtime.receive_action(
                {"id": "move-1", "name": "move", "arguments": {"target": "base"}}
            )
        )
        self.sender.clear()

        asyncio.run(self.runtime.end_mission())

        self.assertEqual([item["command"] for item in self.sender.messages], ["actions/unregister"])
        self.assertEqual(self.runtime.state.active_actions, ())
        self.assertEqual(self.runtime.state.queued_action_ids, ())
        self.assertFalse(self.runtime.state.in_mission)

    def test_dispatch_failure_becomes_failed_result(self) -> None:
        async def failing(_: ActionCommand) -> ExecutionResult:
            raise RuntimeError("transport unavailable")

        runtime = NeuroRuntime(self.sender, dispatcher=failing)
        asyncio.run(runtime.connect())
        asyncio.run(runtime.update_actions([action()]))
        asyncio.run(runtime.identify(IDENTITY))
        asyncio.run(runtime.start_mission())
        asyncio.run(
            runtime.receive_action(
                {"id": "move-1", "name": "move", "arguments": {"target": "base"}}
            )
        )

        result = asyncio.run(runtime.dispatch_next())

        self.assertIsNotNone(result)
        self.assertFalse(result.success)
        self.assertIn("transport unavailable", result.message)


if __name__ == "__main__":
    unittest.main()
