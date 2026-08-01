from __future__ import annotations

import asyncio
import unittest

from cmre_neuro_adapter.neuro.action_queue import ActionQueue
from cmre_neuro_adapter.neuro.action_registry import ActionRegistry
from cmre_neuro_adapter.neuro.actions import ActionCommand, ActionDefinition
from cmre_neuro_adapter.neuro.sender import MemorySender


def action(name: str, description: str = "Do one thing") -> ActionDefinition:
    return ActionDefinition(name, description, {"type": "object"})


def queued(action_id: str, name: str) -> ActionCommand:
    return ActionCommand(action_id, name, None, 1.0)


class ActionRegistryTests(unittest.TestCase):
    def test_new_actions_are_registered_in_one_batch(self) -> None:
        sender = MemorySender()
        registry = ActionRegistry(sender)

        change = asyncio.run(registry.sync([action("attack"), action("move")]))

        self.assertEqual(change.registered, ("attack", "move"))
        self.assertEqual(change.unregistered, ())
        self.assertEqual(sender.messages[0]["command"], "actions/register")
        self.assertEqual(
            [item["name"] for item in sender.messages[0]["data"]["actions"]],
            ["attack", "move"],
        )

    def test_unchanged_actions_are_not_re_registered(self) -> None:
        sender = MemorySender()
        registry = ActionRegistry(sender)
        asyncio.run(registry.sync([action("move")]))
        sender.clear()

        change = asyncio.run(registry.sync([action("move")]))

        self.assertEqual(change.unchanged, ("move",))
        self.assertEqual(sender.messages, [])

    def test_changed_and_missing_actions_unregister_before_register(self) -> None:
        sender = MemorySender()
        queue = ActionQueue()
        queue.enqueue(queued("old-1", "move"))
        queue.enqueue(queued("old-2", "remove"))
        registry = ActionRegistry(sender, queue=queue)
        asyncio.run(registry.sync([action("move"), action("remove")]))
        sender.clear()

        change = asyncio.run(registry.sync([action("move", "Changed" )]))

        self.assertEqual(change.unregistered, ("move", "remove"))
        self.assertEqual(change.registered, ("move",))
        self.assertEqual([message["command"] for message in sender.messages], [
            "actions/unregister",
            "actions/register",
        ])
        self.assertEqual(sender.messages[0]["data"]["action_names"], ["move", "remove"])
        self.assertEqual(queue.queued_action_ids, ())

    def test_reregister_all_sends_complete_active_set(self) -> None:
        sender = MemorySender()
        registry = ActionRegistry(sender)
        asyncio.run(registry.sync([action("move"), action("attack")]))
        sender.clear()

        asyncio.run(registry.reregister_all())

        self.assertEqual(sender.messages[0]["command"], "actions/register")
        self.assertEqual(
            [item["name"] for item in sender.messages[0]["data"]["actions"]],
            ["attack", "move"],
        )


if __name__ == "__main__":
    unittest.main()
