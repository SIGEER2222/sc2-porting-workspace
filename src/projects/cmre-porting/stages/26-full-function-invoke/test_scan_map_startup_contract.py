import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[6]
SCRIPT = Path(__file__).with_name("scan_map_startup_contract.py")
SOURCE_ROOT = ROOT / "cmre-runtime" / "Maps" / "CMRE"
REBORN = ROOT / "cmre-runtime" / "Mods" / "reborn" / "crys_the_swarm_reborn.SC2Mod" / "Base.SC2Data" / "Lib48DF4533.galaxy"


def run_scan(tmp_path, source_root=SOURCE_ROOT, dependency=None):
    output = tmp_path / "contract.json"
    command = [sys.executable, str(SCRIPT), "--source-root", str(source_root), "--out", str(output)]
    if dependency:
        command.extend(["--dependency-file", str(dependency)])
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    return json.loads(output.read_text(encoding="utf-8"))


def test_scan_covers_all_cmre_maps_and_preserves_source_hashes(tmp_path):
    contract = run_scan(tmp_path)
    assert contract["mapCount"] == 15
    maps = {item["map"]: item for item in contract["maps"]}
    assert "亡者之夜.SC2Map" in maps
    dead = maps["亡者之夜.SC2Map"]
    assert dead["sourceFiles"]["Objects"]["sha256"]
    assert dead["sourceFiles"]["MapScript.galaxy"]["sha256"]
    assert dead["sourceFiles"]["Triggers"]["sha256"]
    assert dead["staticPlayerUnitSummary"]["P1"]["ACHeroSpawnPlacement"] == 1
    assert dead["staticPlayerUnitSummary"]["P2"]["ACHeroSpawnPlacement"] == 1
    assert dead["adaptation"]["preplacedPlayerObjects"] == "preserve_exactly"
    assert dead["triggers"]["status"] == "complete"
    assert dead["initialization"]["startingGameQ"]["id"] == "00000032"
    assert "gt_Init01LoadData" in dead["startupCallGraph"]["mapInitTriggers"]
    assert dead["startupCallGraph"]["reachableFunctions"]


def test_scan_distinguishes_death_cradle_mission_structures(tmp_path):
    contract = run_scan(tmp_path)
    record = next(item for item in contract["maps"] if item["map"] == "死亡摇篮.SC2Map")
    assert record["staticPlayerUnitSummary"]["P1"]["CODResearchFacility"] == 1
    assert record["staticPlayerUnitSummary"]["P2"]["CODResearchFacility"] == 1
    assert record["adaptation"]["missionStartStructures"] == ["CODResearchFacility"]


def test_scan_records_dynamic_creation_and_k5_replacement_dependency(tmp_path):
    contract = run_scan(tmp_path, dependency=REBORN)
    dead = next(item for item in contract["maps"] if item["map"] == "亡者之夜.SC2Map")
    assert any(item["unitType"] == "ACVirophage" for item in dead["dynamicCreationSites"])
    replacement = dead["adaptation"]["rebornReplacementSource"]
    assert replacement["enabled"] is True
    assert replacement["sourceUnitTypes"] == ["K5Kerrigan", "K5KerriganBurrowed"]
    assert replacement["sourceProvision"] == "launcher_adapter_before_commander_start"
    assert replacement["requiredFunction"]["name"] == "lib48DF4533_gt_CommanderStart_Func"
    assert "HunterKiller" in replacement["targetUnitTypes"]
    assert replacement["referenceCount"] >= 10
    assert "dynamicPlayerUnitTypes" in dead["adaptation"]


def test_launcher_contract_is_compact_and_preserves_map_owned_objects(tmp_path):
    output = tmp_path / "full.json"
    launcher = tmp_path / "launcher.json"
    command = [
        sys.executable,
        str(SCRIPT),
        "--source-root",
        str(SOURCE_ROOT),
        "--dependency-file",
        str(REBORN),
        "--out",
        str(output),
        "--launcher-out",
        str(launcher),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    compact = json.loads(launcher.read_text(encoding="utf-8"))
    assert compact["schemaVersion"] == 1
    assert len(compact["maps"]) == 15
    dead = next(item for item in compact["maps"] if item["map"] == "亡者之夜.SC2Map")
    assert dead["adaptation"]["protectedPlayerUnitTypes"] == ["ACHeroSpawnPlacement"]
    assert "dynamicPlayerUnitTypes" in dead["adaptation"]
    assert dead["sourceFiles"]["Objects"]["sha256"]
    assert dead["sourceFiles"]["Triggers"]["sha256"]
    assert dead["analysis"]["triggerStatus"] == "complete"


def test_scanner_does_not_guess_dynamic_owner_or_type(tmp_path):
    fixture = tmp_path / "fixture.SC2Map"
    fixture.mkdir()
    (fixture / "Objects").write_text(
        '<?xml version="1.0"?><PlacedObjects><ObjectUnit Id="1" UnitType="ACHeroSpawnPlacement" Player="1" Position="1,2,0"/></PlacedObjects>',
        encoding="utf-8",
    )
    (fixture / "MapScript.galaxy").write_text(
        'void gt_Init_Func() { UnitCreate(1, lv_type, 0, EventPlayer(), Point(1.0, 2.0)); }\n'
        'void gt_Init() { TriggerAddEventMapInit(gt_Init); }\n',
        encoding="utf-8",
    )
    (fixture / "Triggers").write_text(
        '<?xml version="1.0"?><TriggerData><Root/></TriggerData>',
        encoding="utf-8",
    )
    contract = run_scan(tmp_path, fixture)
    site = contract["maps"][0]["dynamicCreationSites"][0]
    assert site["unitType"] == "unknown"
    assert site["ownerScope"] == "unknown"
    assert contract["maps"][0]["status"] == "static_complete_with_unknowns"


def test_scanner_fails_closed_when_triggers_are_missing(tmp_path):
    fixture = tmp_path / "missing-triggers.SC2Map"
    fixture.mkdir()
    (fixture / "Objects").write_text(
        '<?xml version="1.0"?><PlacedObjects/>', encoding="utf-8"
    )
    (fixture / "MapScript.galaxy").write_text("void InitMap() {}\n", encoding="utf-8")
    output = tmp_path / "contract.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--source-root", str(fixture), "--out", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "Triggers" in completed.stderr
