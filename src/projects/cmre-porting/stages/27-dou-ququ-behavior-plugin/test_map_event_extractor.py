import json
import sys
from pathlib import Path

VIBE_ROOT = Path(__file__).resolve().parents[2] / "vibe"
sys.path.insert(0, str(VIBE_ROOT))

from map_event_extractor import MapEventExtractor, extract_map_tree  # noqa: E402


def _write_map(path):
    (path / "Base.SC2Data" / "GameData").mkdir(parents=True)
    (path / "Objects").write_text(
        '<PlacedObjects><ObjectUnit Id="1" UnitType="Lair" Player="1" Position="10,20,0"/>'
        '<ObjectUnit Id="2" UnitType="Hydralisk" Player="4" Position="12,20,0"/></PlacedObjects>',
        encoding="utf-8",
    )
    (path / "MapScript.galaxy").write_text(
        """void gf_DropWave () {\n"
        "    libNtve_gf_CreateUnitsWithDefaultFacing(3, \"Hydralisk\", 0, 4, Point(1.0, 2.0));\n"
        "    gf_AttackwithZergDropPod(2, \"Zergling\", 1, \"Roach\", 0, \"\", Point(3.0, 4.0));\n"
        "}\n""",
        encoding="utf-8",
    )
    (path / "Base.SC2Data" / "GameData" / "EffectData.xml").write_text(
        '<Catalog><CEffectCreateUnit id="DropMarine"><Unit value="Marine"/></CEffectCreateUnit></Catalog>',
        encoding="utf-8",
    )


def test_extracts_preplaced_script_and_gamedata_sources(tmp_path):
    map_dir = tmp_path / "demo.SC2Map"
    _write_map(map_dir)
    result = MapEventExtractor(map_dir, source_root=tmp_path).extract()

    assert result["evidence_type"] == "static"
    assert result["summary"]["preplaced_unit_counts"] == {"Hydralisk": 1, "Lair": 1}
    assert result["summary"]["event_counts"]["airdrop"] >= 1
    units = {unit for event in result["events"] for unit in event["unit_types"]}
    assert {"Hydralisk", "Zergling", "Roach", "Marine"} <= units
    assert all(not item["source_file"].startswith("/") for item in result["events"])


def test_tree_inventory_is_json_serializable(tmp_path):
    _write_map(tmp_path / "one.SC2Map")
    payload = extract_map_tree(tmp_path)
    json.dumps(payload, ensure_ascii=False)
    assert payload["map_count"] == 1
    assert payload["maps"][0]["map_path"] == "one.SC2Map"
