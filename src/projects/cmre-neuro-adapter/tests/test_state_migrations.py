from __future__ import annotations

import tempfile
import unittest

from cmre_neuro_adapter.persistence.migrations import (
    StateValidationError,
    UnsupportedSchemaError,
    canonical_json,
    checksum_for,
    make_envelope,
)
from cmre_neuro_adapter.persistence.state_store import StateStore
from cmre_neuro_adapter.mission.mission_state import CampaignState, RuntimeState
from test_state_store import make_snapshot
from cmre_neuro_adapter.persistence.campaign_state import encode_campaign_state
from cmre_neuro_adapter.persistence.mission_state import encode_mission_state
from cmre_neuro_adapter.persistence.runtime_state import encode_runtime_state


class StateMigrationTests(unittest.TestCase):
    def test_campaign_v0_alias_migrates_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(directory)
            envelope = make_envelope(
                "campaign",
                {"campaign_id": "cmre", "version": 8},
                schema_version=0,
            )
            store.path_for("campaign").write_text(
                canonical_json(envelope.to_dict()), encoding="utf-8"
            )

            self.assertEqual(store.load_campaign(), CampaignState("cmre", 8))

    def test_mission_and_runtime_v0_aliases_migrate_without_state_loss(self) -> None:
        snapshot = make_snapshot()
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(directory)
            mission_payload = encode_mission_state(snapshot.mission)
            mission_payload["map_name"] = mission_payload.pop("map")
            runtime_payload = encode_runtime_state(snapshot.runtime)
            runtime_payload["active_actions"] = runtime_payload.pop(
                "active_action_names"
            )
            runtime_payload["queued_ids"] = runtime_payload.pop("queued_action_ids")
            store.path_for("mission").write_text(
                canonical_json(
                    make_envelope("mission", mission_payload, schema_version=0).to_dict()
                ),
                encoding="utf-8",
            )
            store.path_for("runtime").write_text(
                canonical_json(
                    make_envelope("runtime", runtime_payload, schema_version=0).to_dict()
                ),
                encoding="utf-8",
            )

            self.assertEqual(store.load_mission(), snapshot.mission)
            self.assertEqual(store.load_runtime(), snapshot.runtime)

    def test_future_schema_is_rejected_before_state_is_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(directory)
            payload = encode_campaign_state(CampaignState("cmre", 1))
            future = make_envelope("campaign", payload).to_dict()
            future["schema_version"] = 2
            future["checksum"] = checksum_for("campaign", 2, payload)
            store.path_for("campaign").write_text(
                canonical_json(future), encoding="utf-8"
            )

            with self.assertRaises(UnsupportedSchemaError):
                store.load_campaign()

    def test_missing_required_payload_field_is_not_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(directory)
            payload = encode_campaign_state(CampaignState("cmre", 1))
            del payload["id"]
            store.path_for("campaign").write_text(
                canonical_json(make_envelope("campaign", payload).to_dict()),
                encoding="utf-8",
            )

            with self.assertRaises(StateValidationError):
                store.load_campaign()


if __name__ == "__main__":
    unittest.main()
