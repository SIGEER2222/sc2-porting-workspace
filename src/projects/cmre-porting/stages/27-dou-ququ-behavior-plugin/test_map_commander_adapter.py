from pathlib import Path
import sys

VIBE_ROOT = Path(__file__).resolve().parents[2] / "vibe"
sys.path.insert(0, str(VIBE_ROOT))

from map_commander_adapter import load_adapter_config, resolve_adapter  # noqa: E402


CONFIG = Path(__file__).resolve().parents[2] / "vibe" / "map_commander_adapters.json"


def test_map_rule_and_commander_rule_are_combined():
    config = load_adapter_config(CONFIG)
    result = resolve_adapter(
        config,
        map_name="zzerus03_reborn_port.SC2Map",
        commander_id="TerranAlenger3",
        commander_profile={
            "startingStructure": "3diguoqianshaojidi",
            "startingWorker": "3diguolaogong",
            "workerCount": 12,
            "vanillaRemovals": ["CommandCenter", "SCV"],
        },
    )

    assert result["map_id"] == "reborn-zerg-campaign"
    assert result["startup"]["startingStructure"] == "3diguoqianshaojidi"
    assert result["startup"]["startingWorker"] == "3diguolaogong"
    assert result["startup"]["workerCount"] == 12
    assert "Hatchery" in result["startup"]["vanillaRemovals"]
    assert "SCV" in result["startup"]["vanillaRemovals"]
    assert result["event_unit_replacements"]["native_zerg_worker"] == "3diguolaogong"
    assert result["event_unit_replacements"]["native_zerg_townhall"] == "3diguoqianshaojidi"


def test_native_opening_is_preserved_for_dead_of_night():
    config = load_adapter_config(CONFIG)
    result = resolve_adapter(
        config,
        map_name="亡者之夜.SC2Map",
        commander_id="ZergKerrigan",
    )

    assert result["map_id"] == "dead-of-night-native-opening"
    assert result["map_unit_policy"]["mode"] == "preserve_native"
    assert result["startup"]["startingStructure"] == "Hatchery"
    assert result["startup"]["startingWorker"] == "Drone"
