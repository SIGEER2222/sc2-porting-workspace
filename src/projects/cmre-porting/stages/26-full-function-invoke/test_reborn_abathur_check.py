from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path

import pytest


HERE = Path(__file__).parent


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = load_module("generate_reborn_abathur_baseline")
checker = load_module("reborn_abathur_check")


@pytest.fixture
def source_root(tmp_path: Path) -> Path:
    data = tmp_path / "crys_the_swarm_reborn.SC2Mod" / "Base.SC2Data"
    game_data = data / "GameData"
    game_data.mkdir(parents=True)
    (game_data / "UnitData.xml").write_text(
        "<Catalog><CUnit id=\"Larva\"><CardLayouts>"
        "<LayoutButtons Face=\"One\" Type=\"AbilCmd\" AbilCmd=\"LarvaTrainSwarm2,Train2\" Row=\"1\" Column=\"2\"/>"
        "<LayoutButtons Face=\"Two\" Type=\"AbilCmd\" AbilCmd=\"LarvaTrain,Train19\"/>"
        "</CardLayouts></CUnit><CUnit id=\"ExpectedUnit\"/><CUnit id=\"SecondUnit\"/></Catalog>",
        encoding="utf-8",
    )
    (game_data / "AbilData.xml").write_text(
        "<Catalog><CAbilTrain id=\"LarvaTrainSwarm2\"><InfoArray index=\"Train2\" Time=\"27\">"
        "<Button Requirements=\"HavePool\"/><Unit value=\"ExpectedUnit\"/></InfoArray></CAbilTrain>"
        "<CAbilTrain id=\"LarvaTrain\"><InfoArray index=\"Train19\">"
        "<Unit value=\"SecondUnit\"/><Unit value=\"SecondUnit\"/></InfoArray></CAbilTrain></Catalog>",
        encoding="utf-8",
    )
    (data / "Lib48DF4533.galaxy").write_text(
        "bool lib48DF4533_gt_UnitUnlocks_Func (bool a, bool b) { TechTreeUnitAllow(1, \"ExpectedUnit\", true); return true; }\n"
        "bool lib48DF4533_gt_Abathur_Func (bool a, bool b) { if (UnitGetType(x) == \"ExpectedUnit\") { } return true; }\n"
        "bool lib48DF4533_gt_AbathurAbilities_Func (bool a, bool b) { if (UnitGetType(x) == \"SecondUnit\") { } return true; }\n",
        encoding="utf-8",
    )
    return tmp_path


def baseline_from_fixture(source_root: Path) -> dict:
    return generator.build_baseline(source_root)


def passing_runtime(baseline: dict) -> dict:
    commands = baseline["larva"]["card_exposed_commands"]
    return {
        "larva_count": 2,
        "available_commands": [
            {"ability": command["ability"], "command_index": command["command_index"]} for command in commands
        ],
        "command_results": [
            {
                "ability": command["ability"],
                "command_index": command["command_index"],
                "produced_delta": dict(Counter(command["products"])),
            }
            for command in commands
        ],
        "census": {"p1": {"Larva": 1, "ExpectedUnit": 1}, "p2": {}},
    }


def test_original_card_command_resolves_product_and_quantity(source_root: Path):
    baseline = baseline_from_fixture(source_root)
    commands = baseline["larva"]["card_exposed_commands"]
    assert [(item["ability"], item["command"], item["products"], item["quantity"]) for item in commands] == [
        ("LarvaTrain", "Train19", ["SecondUnit", "SecondUnit"], 2),
        ("LarvaTrainSwarm2", "Train2", ["ExpectedUnit"], 1),
    ]
    assert baseline["source"]["root"] == "reborn"
    assert all("\\" not in entry["path"] for entry in baseline["source"]["files"].values())


def test_inherited_larva_command_is_preserved(source_root: Path):
    inherited = source_root / "inherited.xml"
    inherited.write_text(
        "<Catalog><CAbilTrain id=\"LarvaTrainSwarm\"><InfoArray index=\"Train4\">"
        "<Unit value=\"InheritedUnit\"/></InfoArray></CAbilTrain></Catalog>",
        encoding="utf-8",
    )
    train = generator.parse_train_abilities(
        source_root / "crys_the_swarm_reborn.SC2Mod/Base.SC2Data/GameData/AbilData.xml", inherited
    )
    assert train["LarvaTrainSwarm"]["Train4"]["products"] == ["InheritedUnit"]
    assert train["LarvaTrainSwarm"]["Train4"]["source"] == "swarm_campaign_inherited"


def test_exact_runtime_comparison_passes(source_root: Path):
    baseline = baseline_from_fixture(source_root)
    assert checker.compare_runtime(baseline, passing_runtime(baseline))["verdict"] == "PASS"


def test_wrong_product_for_same_command_fails(source_root: Path):
    baseline = baseline_from_fixture(source_root)
    runtime = passing_runtime(baseline)
    runtime["command_results"][0]["produced_delta"] = {"ExpectedUnit": 2}
    result = checker.compare_runtime(baseline, runtime)
    assert result["verdict"] == "FAIL"
    assert any(item["code"] == "WRONG_OUTPUT" for item in result["failures"])


def test_expected_ability_missing_fails(source_root: Path):
    baseline = baseline_from_fixture(source_root)
    runtime = passing_runtime(baseline)
    runtime["available_commands"] = runtime["available_commands"][1:]
    result = checker.compare_runtime(baseline, runtime)
    assert any(item["code"] == "EXPECTED_ABILITY_MISSING" for item in result["failures"])


def test_no_larva_empty_runtime_and_unknown_unit_are_explicit(source_root: Path):
    baseline = baseline_from_fixture(source_root)
    runtime = passing_runtime(baseline)
    runtime["larva_count"] = 0
    runtime["census"] = {"p1": {"SyntheticUnknown": 1}, "p2": {}}
    result = checker.compare_runtime(baseline, runtime)
    codes = {item["code"] for item in result["failures"]}
    assert "NO_LARVA" in codes
    assert result["observed_external_census_units"]["p1"] == ["SyntheticUnknown"]
    empty = checker.compare_runtime(baseline, {"larva_count": 0})
    assert any(item["code"] == "EMPTY_RUNTIME_CENSUS" for item in empty["failures"])
    partial = checker.compare_runtime(baseline, {"larva_count": 0, "census": {"p1": {"Larva": 1}}})
    assert any(item["code"] == "EMPTY_RUNTIME_CENSUS" for item in partial["failures"])
    assert partial["observed_external_census_units"] == {}


def test_census_separates_original_roster_from_map_units(source_root: Path):
    baseline = baseline_from_fixture(source_root)
    runtime = passing_runtime(baseline)
    runtime["census"] = {"p1": {"ExpectedUnit": 1, "Hatchery": 1, "MapMarker": 1}, "p2": {"Drone": 1}}
    result = checker.compare_runtime(baseline, runtime)
    p1 = result["census_roster_comparison"]["p1"]
    assert "ExpectedUnit" in p1["observed_original_units"]
    assert "Hatchery" in p1["observed_original_buildings"]
    assert p1["non_roster_units"] == ["MapMarker"]
    assert result["census_roster_comparison"]["p2"]["observed_original_units"] == ["Drone"]


def test_baseline_includes_inherited_core_zerg_buildings(source_root: Path):
    baseline = baseline_from_fixture(source_root)
    buildings = baseline["roster"]["original_roster"]["buildings"]
    assert {"Hatchery", "SpawningPool", "LurkerDen"} <= set(buildings)


def test_missing_and_extra_controlled_output_fail_closed():
    assert checker.classify_command_output(["ExpectedUnit"], {})["status"] == "MISSING_OUTPUT"
    assert checker.classify_command_output(["ExpectedUnit"], {"ExpectedUnit": 1, "WrongUnit": 1})["status"] == "UNEXPECTED_OUTPUT"
