from __future__ import annotations

import sys
from pathlib import Path

import yaml
from sc2.ids.unit_typeid import UnitTypeId


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[2]
ARES_ROOT = WORKSPACE_ROOT / "reference" / "ares-sc2"
sys.path.insert(0, str(ARES_ROOT / "src"))
sys.path.insert(0, str(ARES_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from ares import AresBot
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.macro import (
    AutoSupply,
    BuildWorkers,
    ExpansionController,
    GasBuildingController,
    MacroPlan,
    ProductionController,
    SpawnController,
)

from vibe.ares_bot import CmreEnhancedBot
from vibe.macro_plan import DeadOfNightMacroPlan, MacroConfig


def test_project_config_and_build_order_are_valid_yaml() -> None:
    config = yaml.safe_load((PROJECT_ROOT / "config.yml").read_text(encoding="utf-8"))
    builds = yaml.safe_load(
        (PROJECT_ROOT / "terran_builds.yml").read_text(encoding="utf-8")
    )

    assert config["GameStep"] == 2
    assert builds["Builds"]["dead_of_night_macro"]["OpeningBuildOrder"]


def test_macro_plan_uses_expansion_and_production_behaviors() -> None:
    bot = AresBot()
    plan = DeadOfNightMacroPlan(bot, MacroConfig()).build(bot.start_location)

    assert isinstance(plan, MacroPlan)
    assert [type(behavior) for behavior in plan.macros] == [
        AutoSupply,
        BuildWorkers,
        GasBuildingController,
        ExpansionController,
        SpawnController,
        ProductionController,
    ]
    assert UnitTypeId.SIEGETANK in MacroConfig().army_composition


def test_bot_entrypoint_uses_native_ares_lifecycle() -> None:
    bot = CmreEnhancedBot()

    assert isinstance(bot, AresBot)
    assert bot.policy.macro.config.max_bases == 3


def test_combat_maneuver_is_an_ares_behavior() -> None:
    assert issubclass(CombatManeuver, object)
