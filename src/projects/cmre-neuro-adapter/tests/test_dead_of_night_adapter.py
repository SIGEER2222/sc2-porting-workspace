from __future__ import annotations

import asyncio
import json
import unittest

from cmre_neuro_adapter.mission.dead_of_night_adapter import DeadOfNightAdapter
from cmre_neuro_adapter.neuro.actions import ActionDefinition
from cmre_neuro_adapter.neuro.mission_projection import project_observation
from cmre_neuro_adapter.neuro.runtime import NeuroRuntime
from cmre_neuro_adapter.neuro.sender import MemorySender
from cmre_neuro_adapter.neuro.session import NeuroSessionIdentity


def context(
    *,
    context_version: int,
    state_version: int,
    loop: int,
    wave: int = 1,
    status: str = "active",
    phase: str = "night",
    terminated: bool = False,
    own_units: list[dict] | None = None,
    visible_enemies: list[dict] | None = None,
):
    return project_observation(
        {
            "player_id": 1,
            "loop": loop,
            "mission": {
                "phase": phase,
                "night": 1,
                "wave": wave,
                "terminated": terminated,
                "end_reason": "all_objectives_success" if terminated else "",
                "objectives": [
                    {"id": "hold", "name": "Hold", "status": status}
                ],
            },
            "resources": {"minerals": 500, "vespene": 100},
            "own_units": own_units or [unit(1, "Marine", 1)],
            "visible_enemies": visible_enemies or [],
        },
        map_name="dead-of-night",
        context_version=context_version,
        state_version=state_version,
    )


def unit(entity_id: int, unit_type_id: str, owner: int, state: str = "alive") -> dict:
    return {
        "entity_id": entity_id,
        "unit_type_id": unit_type_id,
        "owner": owner,
        "x": float(entity_id),
        "y": 10.0,
        "health": 100,
        "shields": 0,
        "energy": 0,
        "state": state,
    }


class DeadOfNightAdapterTests(unittest.TestCase):
    def test_context_is_semantically_deduplicated_and_forced_refresh_works(self) -> None:
        adapter = DeadOfNightAdapter()
        first = adapter.ingest(context(context_version=1, state_version=1, loop=1))
        repeated = adapter.ingest(context(context_version=2, state_version=2, loop=2))
        forced = adapter.ingest(
            context(context_version=3, state_version=3, loop=3), force=True
        )

        self.assertTrue(first.emitted)
        self.assertFalse(repeated.emitted)
        self.assertEqual(repeated.reason, "deduplicated")
        self.assertIsNone(repeated.envelope)
        self.assertTrue(forced.emitted)
        self.assertEqual(forced.reason, "forced")

    def test_public_event_order_is_deterministic(self) -> None:
        adapter = DeadOfNightAdapter(building_types={"Barracks"})
        adapter.ingest(
            context(
                context_version=1,
                state_version=1,
                loop=1,
                wave=1,
                own_units=[unit(1, "Marine", 1)],
                visible_enemies=[unit(9, "Zergling", 2)],
            )
        )
        update = adapter.ingest(
            context(
                context_version=2,
                state_version=2,
                loop=2,
                wave=2,
                status="success",
                own_units=[unit(1, "Marine", 1), unit(10, "Barracks", 1)],
                visible_enemies=[],
            )
        )

        self.assertEqual(
            [event.kind for event in update.events],
            [
                "objective_changed",
                "wave_spawned",
                "building_completed",
                "unit_died",
            ],
        )
        self.assertEqual(
            [event.payload["sequence"] for event in update.events], [1, 2, 3, 4]
        )
        self.assertEqual(update.events[-1].payload["entity_id"], 9)

    def test_action_policy_handles_no_build_pause_block_and_terminal_state(self) -> None:
        sender = MemorySender()
        runtime = NeuroRuntime(sender)
        identity = NeuroSessionIdentity("session", "character", "Neuro")
        actions = {
            name: ActionDefinition(name, f"Use {name}")
            for name in ("attack_unit", "produce_unit", "research_upgrade", "set_rally")
        }
        adapter = DeadOfNightAdapter(runtime=runtime, actions=actions)
        asyncio.run(runtime.connect())
        asyncio.run(runtime.identify(identity))

        active = asyncio.run(
            adapter.sync(context(context_version=1, state_version=1, loop=1))
        )
        no_build = asyncio.run(
            adapter.sync(
                context(context_version=2, state_version=2, loop=2), no_build=True
            )
        )
        paused = asyncio.run(
            adapter.sync(
                context(context_version=3, state_version=3, loop=3), paused=True
            )
        )
        victory = asyncio.run(
            adapter.sync(
                context(
                    context_version=4,
                    state_version=4,
                    loop=4,
                    phase="victory",
                    terminated=True,
                    status="success",
                )
            )
        )

        self.assertEqual(
            active.snapshot.runtime.active_action_names,
            ("attack_unit", "produce_unit", "research_upgrade", "set_rally"),
        )
        self.assertEqual(no_build.snapshot.runtime.active_action_names, ("attack_unit",))
        self.assertEqual(paused.snapshot.runtime.active_action_names, ())
        self.assertEqual(victory.snapshot.runtime.active_action_names, ())
        self.assertFalse(runtime.state.in_mission)
        self.assertEqual(runtime.state.active_actions, ())

    def test_replayed_context_event_trace_is_identical(self) -> None:
        def run_trace() -> str:
            adapter = DeadOfNightAdapter(building_types={"Barracks"})
            updates = [
                adapter.ingest(
                    context(context_version=1, state_version=1, loop=1)
                ),
                adapter.ingest(
                    context(
                        context_version=2,
                        state_version=2,
                        loop=2,
                        wave=2,
                        own_units=[unit(1, "Marine", 1), unit(2, "Barracks", 1)],
                    )
                ),
            ]
            return json.dumps(
                [update.to_dict() for update in updates],
                sort_keys=True,
                separators=(",", ":"),
            )

        self.assertEqual(run_trace(), run_trace())


if __name__ == "__main__":
    unittest.main()
