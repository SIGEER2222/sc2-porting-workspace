from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cmre_neuro_adapter.mission.mission_state import (
    CampaignState,
    MissionSnapshot,
    MissionState,
    RuntimeState,
)
from cmre_neuro_adapter.neuro.mission_projection import project_observation
from cmre_neuro_adapter.persistence.migrations import (
    StateCorruptionError,
    canonical_json,
    make_envelope,
)
from cmre_neuro_adapter.persistence.state_store import (
    AtomicWriteError,
    StateStore,
)


def make_snapshot(*, minerals: int = 500, loop: int = 12) -> MissionSnapshot:
    context = project_observation(
        {
            "player_id": 1,
            "loop": loop,
            "mission": {
                "phase": "night",
                "night": 1,
                "wave": 2,
                "objectives": [
                    {"id": "hold", "name": "Hold", "status": "active"}
                ],
            },
            "resources": {"minerals": minerals, "vespene": 75},
            "own_units": [
                {
                    "entity_id": 1,
                    "unit_type_id": "Marine",
                    "owner": 1,
                    "x": 10.0,
                    "y": 10.0,
                    "health": 100,
                    "shields": 0,
                    "energy": 0,
                    "state": "alive",
                }
            ],
            "visible_enemies": [],
        },
        map_name="dead-of-night",
        context_version=loop,
        state_version=loop,
    )
    return MissionSnapshot(
        campaign=CampaignState("cmre", 7),
        mission=MissionState.from_context(
            context,
            version=4,
            no_build=False,
            paused=False,
            blocking=False,
        ),
        runtime=RuntimeState(
            version=3,
            context_version=context.context_version,
            active_action_names=("attack_unit",),
            queued_action_ids=("action-1",),
            ready=True,
        ),
    )


class StateStoreTests(unittest.TestCase):
    def test_snapshot_round_trip_is_domain_separated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(directory)
            snapshot = make_snapshot()
            store.save_snapshot(snapshot)

            self.assertEqual(store.load_snapshot().to_dict(), snapshot.to_dict())
            self.assertFalse(store.last_load_recovered)
            self.assertEqual(
                sorted(path.name for path in Path(directory).glob("*.json")),
                ["campaign.json", "mission.json", "runtime.json"],
            )
            self.assertNotIn("world", Path(directory, "mission.json").read_text())

    def test_corrupt_primary_recovers_the_last_good_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(directory)
            store.save_campaign(CampaignState("cmre", 1))
            store.save_campaign(CampaignState("cmre", 2))
            path = store.path_for("campaign")
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["payload"]["version"] = 999
            path.write_text(canonical_json(raw), encoding="utf-8")

            self.assertEqual(store.load_campaign(), CampaignState("cmre", 2))
            self.assertTrue(store.last_load_recovered)

    def test_interrupted_replacement_leaves_old_primary_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(directory)
            store.save_campaign(CampaignState("cmre", 1))
            with patch(
                "cmre_neuro_adapter.persistence.state_store.os.replace",
                side_effect=OSError("simulated interruption"),
            ):
                with self.assertRaises(AtomicWriteError):
                    store.save_campaign(CampaignState("cmre", 2))

            self.assertEqual(store.load_campaign(), CampaignState("cmre", 1))
            self.assertFalse(store.last_load_recovered)

    def test_cross_domain_file_cannot_be_exposed_as_campaign_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(directory)
            snapshot = make_snapshot()
            store.save_snapshot(snapshot)
            mission_envelope = make_envelope(
                "mission", {"unexpected": "domain"}
            )
            store.path_for("campaign").write_text(
                canonical_json(mission_envelope.to_dict()), encoding="utf-8"
            )

            self.assertEqual(store.load_campaign(), snapshot.campaign)
            self.assertTrue(store.last_load_recovered)

    def test_both_corrupt_copies_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(directory)
            store.save_campaign(CampaignState("cmre", 1))
            store.path_for("campaign").write_text("{}", encoding="utf-8")
            store.backup_path_for("campaign").write_text("{}", encoding="utf-8")

            with self.assertRaises(StateCorruptionError):
                store.load_campaign()

    def test_save_load_replay_trace_is_deterministic(self) -> None:
        def run(directory: str) -> tuple[str, tuple[str, ...]]:
            store = StateStore(directory)
            store.save_snapshot(make_snapshot())
            restored = store.load_snapshot()
            trace = canonical_json(restored.to_dict())
            files = tuple(
                Path(directory, name).read_text(encoding="utf-8")
                for name in ("campaign.json", "mission.json", "runtime.json")
            )
            return trace, files

        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            self.assertEqual(run(first), run(second))


if __name__ == "__main__":
    unittest.main()
