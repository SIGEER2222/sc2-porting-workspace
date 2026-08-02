from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
