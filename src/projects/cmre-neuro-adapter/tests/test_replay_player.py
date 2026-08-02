from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cmre_neuro_adapter.macro_replay import build_macro_replay
from cmre_neuro_adapter.replay_player import load_records, render_player_html


class ReplayPlayerTests(unittest.TestCase):
    def test_load_records_reads_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.jsonl"
            path.write_text('{"record_type":"header"}\n{"record_type":"summary"}\n', encoding="utf-8")
            self.assertEqual(load_records(path)[0]["record_type"], "header")

    def test_render_player_embeds_data_and_controls(self) -> None:
        records = [
            {"record_type": "header", "replay_id": "test"},
            {
                "record_type": "frame",
                "label": "initial",
                "loop": 0,
                "state_version": 0,
                "context": {
                    "context_version": 1,
                    "resources": {"minerals": 50, "supply_used": 1, "supply_cap": 10},
                    "own_units": [
                        {
                            "entity_id": 7,
                            "unit_type_id": "Barracks",
                            "owner": 1,
                            "x": 5.0,
                            "y": 0.0,
                            "health": 1024000,
                            "shields": 0,
                            "energy": 0,
                            "state": "idle",
                        }
                    ],
                    "visible_enemies": [
                        {
                            "entity_id": 8,
                            "unit_type_id": "Zergling",
                            "owner": 2,
                            "x": 9.0,
                            "y": 4.0,
                            "health": 35840,
                            "shields": 0,
                            "energy": 0,
                            "state": "moving",
                        }
                    ],
                    "mission": {},
                },
                "events": [],
                "command_results": [],
            },
            {"record_type": "summary", "actions_successful": 0, "actions_total": 0, "event_count": 0},
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "player.html"
            render_player_html(records, output)
            html = output.read_text(encoding="utf-8")
            self.assertIn("id=\"map\"", html)
            self.assertIn("id=\"seek\"", html)
            self.assertIn("data-speed=\"16\"", html)
            self.assertIn("id=\"entities\"", html)
            self.assertIn("id=\"rawContext\"", html)
            self.assertIn('"unit_type_id":"Zergling"', html)
            self.assertIn('"health":1024000', html)
            self.assertIn('"record_type":"header"', html)
            self.assertNotIn("__REPLAY_DATA__", html)
            json.loads(html.split("const RECORDS = ", 1)[1].split(";", 1)[0])

    def test_render_player_keeps_legacy_map_entity_frames(self) -> None:
        records = [
            {"record_type": "header", "replay_id": "legacy-map"},
            {
                "loop": 0,
                "entities_by_player": {
                    "0": [{"id": 10, "t": "MineralField", "p": 0, "x": 4, "y": 5, "hp": 1500, "alive": True}],
                    "1": [{"id": 11, "t": "Marine", "p": 1, "x": 6, "y": 7, "hp": 45, "alive": True}],
                },
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "legacy-player.html"
            render_player_html(records, output)
            html = output.read_text(encoding="utf-8")
            self.assertIn('r.record_type === "frame" || r.entities_by_player', html)
            self.assertIn('"entities_by_player"', html)
            self.assertIn('"MineralField"', html)
            self.assertIn('"Marine"', html)

    def test_macro_replay_is_state_driven_and_starts_without_army(self) -> None:
        replay = build_macro_replay(max_loops=1_400)
        frames = [record for record in replay if record.get("record_type") == "frame"]
        actions = [record for record in replay if record.get("record_type") == "action"]
        summary = replay[-1]
        self.assertEqual(summary["status"], "PASS")
        initial_types = {entity["t"] for entity in frames[0]["entities_by_player"]["1"]}
        self.assertEqual(initial_types, {"CommandCenter", "SCV"})
        self.assertEqual(frames[0]["p1_resources"]["minerals"], 50)
        self.assertTrue(any(frame["economy"]["estimated_minerals_collected"] > 0 for frame in frames))
        self.assertGreater(summary["final_resources"]["vespene"], 0)
        self.assertGreaterEqual(summary["final_units_by_type"]["SCV"], 10)
        self.assertGreaterEqual(summary["final_units_by_type"]["Marine"], 2)
        for unit_type in ("SupplyDepot", "Barracks", "Refinery", "Marine"):
            self.assertTrue(
                any(
                    action.get("arguments", {}).get("unit_type_id") == unit_type
                    and action.get("completed")
                    and action.get("started")
                    for action in actions
                ),
                unit_type,
            )
        for action in actions:
            lifecycle = [
                name
                for name in ("accepted", "started", "completed", "failed")
                if action.get(name) is not None
            ]
            self.assertIn("accepted", lifecycle)
            if action["failed"] is None:
                self.assertEqual(lifecycle[:3], ["accepted", "started", "completed"])


if __name__ == "__main__":
    unittest.main()
