from __future__ import annotations

import asyncio
import unittest

from cmre_neuro_adapter.neuro.actions import ActionCommand, ActionDefinition
from cmre_neuro_adapter.neuro.mission_projection import MissionContextProjector
from cmre_neuro_adapter.neuro.runtime import NeuroRuntime
from cmre_neuro_adapter.neuro.sender import MemorySender
from cmre_neuro_adapter.neuro.simulator_transport import SimulatorTransport
from cmre_neuro_adapter.neuro.session import NeuroSessionIdentity


MOVE_SCHEMA = {
    "type": "object",
    "properties": {
        "target": {"type": "string"},
        "expected_state_version": {"type": "integer", "minimum": 0},
    },
    "required": ["target"],
    "additionalProperties": False,
}


class DeterministicBackend:
    def __init__(self) -> None:
        self.state_version = 0
        self.loop = 0
        self.calls: list[tuple[str, dict]] = []
        self.supported_actions = ("move", "broken")

    def observe(self, player_id: int) -> dict:
        return {
            "player_id": player_id,
            "loop": self.loop,
            "mission": {
                "phase": "night",
                "night": 1,
                "wave": self.loop // 2,
                "objectives": [
                    {"name": "defend_base", "status": "active"}
                ],
            },
            "resources": {"minerals": 500, "vespene": 100},
            "own_units": [],
            "visible_enemies": [],
        }

    def execute(self, operation: str, args: dict) -> dict:
        self.calls.append((operation, dict(args)))
        if operation == "fail.operation":
            raise RuntimeError("backend unavailable")
        self.state_version += 1
        self.loop += 1
        return {"loop": self.loop, "message": "applied"}


def move_command(action_id: str, expected_version: int | None = None) -> ActionCommand:
    args = {"target": "base"}
    if expected_version is not None:
        args["expected_state_version"] = expected_version
    return ActionCommand(action_id, "move", args, 1.0)


class SimulatorTransportTests(unittest.TestCase):
    def test_action_is_translated_and_duplicate_is_idempotent(self) -> None:
        backend = DeterministicBackend()
        transport = SimulatorTransport(
            backend, action_operations={"move": "unit.move"}
        )

        first = transport.dispatch(
            move_command("move-1"), expected_state_version=0
        )
        duplicate = transport.dispatch(
            move_command("move-1"), expected_state_version=0
        )

        self.assertTrue(first.success)
        self.assertEqual(first.action_id, "move-1")
        self.assertEqual(first.operation, "unit.move")
        self.assertEqual(first.loop, 1)
        self.assertEqual(first.action_id, duplicate.action_id)
        self.assertEqual(first.state_version, duplicate.state_version)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(backend.calls, [("unit.move", {"target": "base"})])

    def test_stale_unsupported_and_backend_failures_do_not_mutate_state(self) -> None:
        backend = DeterministicBackend()
        transport = SimulatorTransport(
            backend,
            action_operations={"move": "unit.move", "broken": "fail.operation"},
        )
        transport.dispatch(move_command("move-1"), expected_state_version=0)

        stale = transport.dispatch(
            move_command("move-2"), expected_state_version=0
        )
        unsupported = transport.dispatch(
            ActionCommand("attack-1", "attack", {}, 1.0)
        )
        failed = transport.dispatch(ActionCommand("broken-1", "broken", {}, 1.0))

        self.assertFalse(stale.success)
        self.assertEqual(stale.operation, "stale_state")
        self.assertIn("expected 0, current 1", stale.message)
        self.assertFalse(unsupported.success)
        self.assertEqual(unsupported.operation, "unsupported_action")
        self.assertFalse(failed.success)
        self.assertEqual(failed.operation, "dispatch")
        self.assertIn("backend unavailable", failed.message)
        self.assertEqual(backend.state_version, 1)
        self.assertEqual(backend.loop, 1)
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(backend.calls[-1], ("fail.operation", {}))

    def test_runtime_dispatch_preserves_action_correlation(self) -> None:
        backend = DeterministicBackend()
        transport = SimulatorTransport(
            backend, action_operations={"move": "unit.move"}
        )
        sender = MemorySender()
        runtime = NeuroRuntime(sender, dispatcher=transport.dispatch)
        identity = NeuroSessionIdentity("session", "character", "Neuro")

        asyncio.run(runtime.connect())
        asyncio.run(runtime.update_actions([ActionDefinition("move", "Move", MOVE_SCHEMA)]))
        asyncio.run(runtime.identify(identity))
        asyncio.run(runtime.start_mission())
        accepted = asyncio.run(
            runtime.receive_action(
                {
                    "id": "move-1",
                    "name": "move",
                    "arguments": {"target": "base", "expected_state_version": 0},
                }
            )
        )
        result = asyncio.run(runtime.dispatch_next())

        self.assertTrue(accepted.success)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.success)
        self.assertEqual(result.action_id, "move-1")
        self.assertEqual(result.operation, "unit.move")
        self.assertEqual(backend.calls, [("unit.move", {"target": "base"})])
        self.assertEqual(sender.messages[-1]["command"], "action/result")
        self.assertEqual(sender.messages[-1]["data"]["id"], "move-1")
        self.assertTrue(sender.messages[-1]["data"]["success"])

    def test_repeated_input_trace_is_deterministic(self) -> None:
        def run_trace() -> list[tuple[str, str, int | None]]:
            backend = DeterministicBackend()
            transport = SimulatorTransport(
                backend, action_operations={"move": "unit.move"}
            )
            trace = [(transport.observe().to_json(), "context", None)]
            for index, expected_version in enumerate((0, 1), start=1):
                result = transport.dispatch(
                    move_command(f"move-{index}"),
                    expected_state_version=expected_version,
                )
                context = transport.observe()
                trace.append((context.to_json(), result.message, result.loop))
            return trace

        self.assertEqual(run_trace(), run_trace())


if __name__ == "__main__":
    unittest.main()
