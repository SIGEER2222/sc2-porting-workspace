from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cmre_neuro_adapter.macro_replay import build_macro_replay
from cmre_neuro_adapter.real_map_replay import build_map_record
from cmre_neuro_adapter.replay_player import _with_map_record, load_records, render_player_html


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
            self.assertIn("id=\"endReason\"", html)
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

    def test_render_player_marks_single_frame_static_preview(self) -> None:
        records = [
            {"record_type": "header", "replay_id": "static-preview", "evidence_type": "static"},
            {"record_type": "frame", "loop": 0, "entities_by_player": {}},
            {"record_type": "summary", "evidence_type": "static", "status": "STATIC_PREVIEW"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "static-player.html"
            render_player_html(records, output)
            html = output.read_text(encoding="utf-8")
            self.assertIn("IS_STATIC_PREVIEW", html)
            self.assertIn("replayStatus", html)
            self.assertIn("无动态回放帧", html)
            self.assertIn("control.disabled=true", html)

    def test_render_player_embeds_real_map_layer_metadata(self) -> None:
        records = [
            {"record_type": "header", "replay_id": "real-map"},
            {
                "record_type": "map",
                "map_name": "亡者之夜.SC2Map",
                "minimap_data_url": "data:image/png;base64,AAAA",
                "world_bounds": {"min_x": 16, "max_x": 176, "min_y": 16, "max_y": 176},
                "static_objects": [{"id": "map-1", "unit_type_id": "MineralField", "owner": 0, "x": 85, "y": 94}],
                "friendly_players": [1, 2],
            },
            {
                "record_type": "frame",
                "loop": 0,
                "entities_by_player": {"2": [{"entity_id": 7, "unit_type_id": "SCV", "owner": 2, "x": 85, "y": 94, "health": 46080}]},
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "real-map-player.html"
            render_player_html(records, output)
            html = output.read_text(encoding="utf-8")
            self.assertIn("const MAP_META", html)
            self.assertIn("minimap_data_url", html)
            self.assertIn("staticLayer", html)
            self.assertIn("world_bounds", html)
            self.assertIn("亡者之夜.SC2Map", html)

    def test_with_map_record_adds_display_only_simulator_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            map_records = root / "map.jsonl"
            map_records.write_text(
                '{"record_type":"header"}\n'
                '{"record_type":"map","map_name":"亡者之夜.SC2Map","static_objects":[]}\n',
                encoding="utf-8",
            )
            replay = [{"record_type": "header"}, {"record_type": "summary"}]
            merged = _with_map_record(replay, map_records, project_simulator=True)
            self.assertEqual(merged[1]["record_type"], "map")
            self.assertEqual(merged[1]["dynamic_coordinate_projection"]["kind"], "display-only")
            self.assertEqual(merged[1]["display_note"], "真实地图静态层 + simulator 动态层（坐标为显示投影）")

    def test_build_map_record_preserves_original_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            map_path = root / "亡者之夜.SC2Map"
            source = root / "source"
            source.mkdir()
            map_path.write_bytes(b"packed-map")
            (source / "minimap.png").write_bytes(b"png")
            (source / "t3Terrain.xml").write_text(
                '<terrain><heightMap dim="193 193 "/></terrain>', encoding="utf-8"
            )
            (source / "Objects").write_text(
                '<root><ObjectUnit Id="7" UnitType="MineralField" Player="0" Position="85,94,0"/>'
                '<ObjectUnit Id="8" UnitType="Barracks" Player="1" Position="80,90,0"/></root>',
                encoding="utf-8",
            )
            record = build_map_record(map_path, source)
            self.assertEqual(record["map_name"], "亡者之夜.SC2Map")
            self.assertEqual(record["terrain_height_map_dim"], [193, 193])
            self.assertEqual(len(record["static_objects"]), 2)
            self.assertEqual(record["static_objects"][1]["unit_type_id"], "Barracks")
            self.assertEqual(record["static_objects"][1]["id"], "map-8")
            self.assertEqual(record["static_objects"][1]["source_object_id"], 8)

    def test_real_map_geometry_and_spawn_markers_are_source_aligned(self) -> None:
        source = Path(__file__).parents[1] / "artifacts" / "real-map-source-20260802"
        if not (source / "Objects").is_file():
            self.skipTest("real map extraction artifact is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            map_path = Path(directory) / "dead-of-night.SC2Map"
            map_path.write_bytes(b"packed-map")
            record = build_map_record(map_path, source)
        self.assertEqual(record["map_size"], {"width": 192, "height": 192})
        self.assertEqual(record["terrain_height_map_dim"], [193, 193])
        self.assertEqual(record["image_rect_px"], {"x": 48, "y": 48, "w": 160, "h": 160})
        self.assertEqual(record["world_bounds"], {"min_x": 16.0, "max_x": 176.0, "min_y": 16.0, "max_y": 176.0})
        self.assertEqual(len(record["static_objects"]), 1319)
        self.assertEqual(len({item["source_object_id"] for item in record["static_objects"]}), 1319)
        markers = {item["owner"]: item for item in record["placement_markers"]}
        self.assertEqual((markers[1]["x"], markers[1]["y"]), (85.0, 94.0))
        self.assertEqual((markers[2]["x"], markers[2]["y"]), (76.0, 103.0))

    def test_player_contains_source_destroyed_state_projection(self) -> None:
        records = [
            {"record_type": "header", "replay_id": "alignment"},
            {
                "record_type": "map",
                "map_name": "亡者之夜.SC2Map",
                "minimap_data_url": "data:image/png;base64,AAAA",
                "world_bounds": {"min_x": 16, "max_x": 176, "min_y": 16, "max_y": 176},
                "static_objects": [
                    {
                        "id": "map-42",
                        "source_object_id": 42,
                        "source_unit_type_id": "Bunker",
                        "unit_type_id": "Bunker",
                        "owner": 3,
                        "x": 101.5,
                        "y": 149.5,
                    }
                ],
                "friendly_players": [1, 2],
            },
            {"record_type": "frame", "loop": 0, "entities_by_player": {}, "events": []},
            {
                "record_type": "frame",
                "loop": 112,
                "entities_by_player": {},
                "events": [{"kind": "infested_structure_destroyed", "source_object_id": 42}],
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "alignment-player.html"
            render_player_html(records, output)
            html = output.read_text(encoding="utf-8")
        self.assertIn("destroyedSourceObjectIds", html)
        self.assertIn("source_object_id", html)
        self.assertIn("drawStaticObject(object,destroyedIds)", html)

    def test_static_preview_without_frames_has_safe_empty_frame(self) -> None:
        records = [
            {"record_type": "header", "replay_id": "empty-static"},
            {
                "record_type": "map",
                "map_name": "亡者之夜.SC2Map",
                "static_objects": [],
            },
            {"record_type": "summary", "status": "STATIC_PREVIEW", "evidence_type": "static"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "empty-static.html"
            render_player_html(records, output)
            html = output.read_text(encoding="utf-8")
        self.assertIn("const EMPTY_FRAME", html)
        self.assertIn("FRAMES[0] || EMPTY_FRAME", html)

    def test_macro_replay_is_state_driven_and_starts_without_army(self) -> None:
        replay = build_macro_replay(max_loops=10_400)
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
        self.assertTrue(summary["macro_acceptance"])
        self.assertTrue(summary["victory"])
        self.assertEqual(summary["actions_failed"], 0)
        self.assertEqual(summary["end_reason"], "all_objectives_success")
        self.assertGreaterEqual(summary["nights_survived"], 1)
        self.assertGreaterEqual(summary["first_night_target_loop"], 10_000)
        self.assertTrue(any(frame["context"]["mission"]["night"] == 1 for frame in frames))
        self.assertTrue(any(event["kind"] == "map_script_wave_spawned" for frame in frames for event in frame["events"]))
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
