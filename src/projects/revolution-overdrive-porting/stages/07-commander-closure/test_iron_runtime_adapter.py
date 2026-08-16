import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = PROJECT_ROOT.parents[2] / "tools" / "launchers" / "launch-revolution-overdrive.ps1"
CONFIG = PROJECT_ROOT / "vibe" / "map_commander_adapters.json"
MAP_SCRIPT = PROJECT_ROOT / "packages" / "Maps" / "thanson01.SC2Map" / "MapScript.galaxy"


class IronRuntimeAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher_text = LAUNCHER.read_text(encoding="utf-8")
        cls.map_text = MAP_SCRIPT.read_text(encoding="utf-8")
        cls.config = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_opening_creation_remains_map_owned(self):
        self.assertIn(
            'libNtve_gf_UnitCreateFacingPoint(1, "SCV", 0, 1, PointFromId(1940147643), PointFromId(1940147643));',
            self.map_text,
        )
        self.assertNotIn(
            'libNtve_gf_UnitCreateFacingPoint(1, "1gangtiegongchengche", 0, 1, PointFromId(1940147643), PointFromId(1940147643));',
            self.map_text,
        )

    def test_launcher_declares_runtime_replacement_without_static_rewrite(self):
        self.assertIn('status = "runtime_bootstrap_declared"', self.launcher_text)
        self.assertNotIn('$needle = \'libNtve_gf_UnitCreateFacingPoint(1, "SCV"', self.launcher_text)
        self.assertNotIn('status = "applied_to_staged_map"', self.launcher_text)

    def test_runtime_bootstrap_registers_unit_lifecycle_events(self):
        for event in (
            "TriggerAddEventUnitCreated",
            "TriggerAddEventUnitChangeOwner",
            "TriggerAddEventTimePeriodic",
        ):
            self.assertIn(event, self.launcher_text)
        self.assertIn("$replacementBody", self.launcher_text)
        self.assertIn("$runtimeReplacements", self.launcher_text)
        self.assertIn("$runtimeReplacementList = @($runtimeReplacements)", self.launcher_text)
        self.assertIn("__RO_REPLACEMENT_BODY__", self.launcher_text)

    def test_iron_rule_covers_all_ro_maps_and_valid_catalog_targets(self):
        rules = [
            rule
            for rule in self.config["map_commander_rules"]
            if rule["id"] == "revolution-overdrive-iron-runtime"
        ]
        self.assertEqual(len(rules), 1)
        rule = rules[0]
        self.assertEqual(rule["map_pattern"], r"^(?!tarcade\.SC2Map$).+\.SC2Map$")
        replacements = {item["from"]: item["to"] for item in rule["runtime_replacements"]}
        self.assertEqual(
            replacements,
            {
                "SCV": "1gangtiegongchengche",
                "CommandCenter": "1gangtieyaosai",
                "OrbitalCommand": "1gangtieyaosai",
                "OrbitalCommandACGluescreenDummy": "1gangtieyaosai",
                "PlanetaryFortress": "1gangtieyaosai",
                "Nexus": "1gangtieyaosai",
                "Hatchery": "1gangtieyaosai",
                "Lair": "1gangtieyaosai",
                "Hive": "1gangtieyaosai",
                "Factory": "1zhuzaochejian",
                "FactoryFlying": "1zhuzaochejianFlying",
                "Starport": "1xingkongchuanwu",
                "StarportFlying": "1xingkongchuanwuFlying",
                "PerditionTurret": "1moripaotai",
                "PerditionTurretUnderground": "1moripaotai2",
                "PlasmaTurret": "1guidaopaotai",
                "LightArray": "1fangkongta",
                "RefineryRich": "1zidonghuajinglianchang",
                "AutomatedRefinery": "1zidonghuajinglianchang",
                "SupplyDepot": "1ranliaozhan",
                "Armory": "1gangtiegongchang",
                "FusionCore": "1jubianhexin",
                "IronWarrior": "1wuzhuangjiqiren",
                "HERC": "1xiulijiqiren",
                "ShockTrooper": "1gangtiezhanlang",
                "Saboteur": "1jixiehete",
                "Desecrator": "1huochexia",
                "Radbat": "1huochexia",
                "SpartanCompany": "1jurenjijia",
                "MengskGoliath": "1jurenjijia",
                "Phantom": "1gangtiezhiyi",
                "BileTank": "1zhongxinggongchengtanke",
                "Titan": "1gangtiebaolei",
                "Hercules": "1zhongxingwuzhuangdenglujian",
                "VoidConduit": "1zhongxingzhanliexunhangjian1",
                "SpecOpsRaven": "1kexuechuan",
                "Liberator": "1zhongxingwuzhuangpaojian",
            },
        )

    def test_non_iron_rules_use_runtime_trigger_bridges_without_chat(self):
        expected = {
            "Coverts": (
                "lib6B3CCD85_gt_E789B9E68898E9989FE58D95E4BD8DE69BBFE68DA2",
                "SCVC",
            ),
            "Umojan": (
                "lib6B3CCD85_gt_ymyE58D95E4BD8DE69BBFE68DA2",
                "SCVU",
            ),
            "Pirate": (
                "lib6B3CCD85_gt_E6B5B7E79B97E58D95E4BD8DE69BBFE68DA2",
                None,
            ),
            "Madness": (
                "lib6B3CCD85_gt_E8BF9CE5BE81E5869BE58D95E4BD8DE69BBFE68DA2",
                None,
            ),
        }
        rules = {
            rule["commander_pattern"].removeprefix("^RevolutionOverdrive").removesuffix("$"): rule
            for rule in self.config["map_commander_rules"]
        }
        for faction, (trigger, worker) in expected.items():
            rule = rules[faction]
            self.assertEqual(rule["selection"]["mode"], "runtime_galaxy_bootstrap")
            self.assertFalse(rule["selection"]["manualChatRequired"])
            bridge = rule["runtime_trigger_bridge"]
            self.assertEqual(bridge["replacementTrigger"], trigger)
            self.assertEqual(bridge["header"], "Lib6B3CCD85_h.galaxy")
            self.assertEqual(rule["runtime_replacements"][0]["to"], worker) if worker else self.assertEqual(rule.get("runtime_replacements"), None)

        self.assertIn("TriggerExecute(", self.launcher_text)
        self.assertIn("runtime_trigger_bridge", self.launcher_text)
        self.assertIn('selectionMode -eq "runtime_galaxy_bootstrap"', self.launcher_text)

    def test_realtime_probe_has_expected_catalog_targets_for_each_faction(self):
        probe = (
            PROJECT_ROOT / "stages" / "07-commander-closure" / "iron_opening_runtime_probe.py"
        ).read_text(encoding="utf-8")
        for faction, target in {
            "Iron": "1gangtiegongchengche",
            "Coverts": "SCVC",
            "Umojan": "SCVU",
            "Pirate": "9shougezhe",
            "Madness": "3diguozhijian",
        }.items():
            self.assertIn(f'"{faction}"', probe)
            self.assertIn(f'"{target}"', probe)
        self.assertIn("--faction", probe)
        self.assertIn("passed_realtime_{options.faction.lower()}_replacement_observed", probe)

    def test_reference_only_targets_are_fail_closed_when_catalog_is_missing(self):
        rule = next(
            rule
            for rule in self.config["map_commander_rules"]
            if rule["id"] == "revolution-overdrive-iron-runtime"
        )
        unsupported = {item["from"]: item["to"] for item in rule["unsupported_reference_replacements"]}
        self.assertEqual(unsupported["Barracks"], "1jixiezuzhuanggongchang")
        self.assertEqual(unsupported["BarracksFlying"], "1jixiezuzhuanggongchangFlying")
        self.assertNotIn("1jixiezuzhuanggongchang", self.launcher_text)

    def test_api_runs_use_unique_packed_map_when_previous_run_exists(self):
        self.assertIn("$ListenPort -gt 0 -and (Test-Path -LiteralPath $packedMapBase", self.launcher_text)
        self.assertIn(".stage07.\" + $ListenPort + \".packed.SC2Map", self.launcher_text)


if __name__ == "__main__":
    unittest.main()
