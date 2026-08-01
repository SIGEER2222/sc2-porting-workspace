from __future__ import annotations

import unittest

from cmre_neuro_adapter.neuro.action_queue import ActionQueue
from cmre_neuro_adapter.neuro.actions import ActionCommand


def command(action_id: str, name: str = "move") -> ActionCommand:
    return ActionCommand(action_id, name, None, float(len(action_id)))


class ActionQueueTests(unittest.TestCase):
    def test_capacity_and_fifo_eviction(self) -> None:
        queue = ActionQueue(capacity=2)
        queue.enqueue(command("one"))
        queue.enqueue(command("two"))

        offer = queue.enqueue(command("three"))

        self.assertTrue(offer.accepted)
        self.assertIsNotNone(offer.evicted)
        self.assertEqual(offer.evicted.command.action_id, "one")
        self.assertEqual(queue.queued_action_ids, ("two", "three"))
        self.assertEqual(queue.pop().action_id, "two")
        self.assertEqual(queue.pop().action_id, "three")
        self.assertIsNone(queue.pop())

    def test_duplicate_action_id_is_not_enqueued(self) -> None:
        queue = ActionQueue()
        queue.enqueue(command("same"))

        offer = queue.enqueue(command("same", "attack"))

        self.assertFalse(offer.accepted)
        self.assertTrue(offer.duplicate)
        self.assertEqual(tuple(item.name for item in queue), ("move",))

    def test_clear_by_action_and_clear_all(self) -> None:
        queue = ActionQueue(capacity=4)
        queue.enqueue(command("move-1", "move"))
        queue.enqueue(command("attack-1", "attack"))
        queue.enqueue(command("move-2", "move"))

        removed = queue.clear_action("move")

        self.assertEqual(tuple(item.action_id for item in removed), ("move-1", "move-2"))
        self.assertEqual(queue.queued_action_ids, ("attack-1",))
        self.assertEqual(queue.clear_all()[0].action_id, "attack-1")
        self.assertEqual(len(queue), 0)

    def test_capacity_must_be_positive_integer(self) -> None:
        for capacity in (0, -1, True, 1.5):
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                ActionQueue(capacity)


if __name__ == "__main__":
    unittest.main()
