from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
LAUNCHER = ROOT / "tools" / "launchers" / "launch-cmre-alenger.ps1"
CONFIG = ROOT / "src" / "projects" / "cmre-porting" / "vibe" / "map_commander_adapters.json"


def test_launcher_resolves_map_adapter_before_writing_launch_profile():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    assert "map_commander_adapters.json" in source
    assert "Select-CmreMapAdapterRule" in source
    assert "MapAdapterId = @(" in source
    assert "MapAdapterMode = @(" in source
    assert "MapAdapterEventReplacementCount = @(" in source
    assert "MapAdapter|Anchor|" in source
    assert "MapAdapter|EventReplacement|" in source
    assert "commander.startingStructure" in source
    assert "commander.startingWorker" in source


def test_adapter_config_is_inside_project_and_has_a_generic_fallback():
    assert CONFIG.is_file()
    text = CONFIG.read_text(encoding="utf-8")
    assert '"schema_version": 1' in text
    assert '"id": "generic-cmre"' in text
    assert '"id": "reborn-zerg-campaign"' in text
