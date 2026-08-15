from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "src" / "projects" / "cmre-porting"))

from vibe.dou_ququ_behavior import (  # noqa: E402
    DouQuquVm,
    DouQuquVmBridge,
    load_config,
    load_function_metadata,
)


class FixedRandom:
    def __init__(self, value: int):
        self.value = value

    def randint(self, _lower: int, _upper: int) -> int:
        return self.value


class DouQuquBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()
        self.bridge = DouQuquVmBridge(config=self.config, seed=7)

    def call(self, function_id: str, **args):
        response = self.bridge.call(function_id, args)
        self.assertEqual(response["error_code"], "OK", response)
        return response["payload"]

    def spawn(self, unit_type: str, owner: int = 1, x: float = 0.0, y: float = 0.0):
        return self.call("douququ.unit.spawn", unit_type=unit_type, owner=owner, x=x, y=y)["tag"]

    @staticmethod
    def units(snapshot, unit_type: str, *, alive: bool | None = None):
        return [
            unit for unit in snapshot["units"]
            if unit["unit_type"] == unit_type and (alive is None or unit["alive"] == alive)
        ]

    def test_reaver_ordinary_and_fatal_probabilities_and_impact_point(self):
        rule = self.config["rules"]["reaverAttack"]
        self.assertEqual(rule["ordinaryChancePercent"], 20)
        self.assertEqual(rule["killChancePercent"], 30)
        reaver = self.spawn("Reaver", x=1.0, y=1.0)
        target = self.spawn("Marine", owner=2, x=9.0, y=11.0)
        self.bridge.world.rng = FixedRandom(20)
        ordinary = self.call("douququ.attack", attacker_tag=reaver, target_tag=target)
        self.assertTrue(ordinary["triggered"])
        self.assertEqual(ordinary["impactPoint"], {"x": 9.0, "y": 11.0})
        zealot = self.units(self.call("douququ.snapshot"), "Zealot")[0]
        self.assertEqual(zealot["position"], {"x": 9.0, "y": 11.0})

        fatal_target = self.spawn("Marine", owner=2, x=20.0, y=21.0)
        self.bridge.world.rng = FixedRandom(30)
        fatal = self.call("douququ.kill", killer_tag=reaver, victim_tag=fatal_target)
        self.assertTrue(fatal["scarabImpact"]["triggered"])
        self.assertEqual(fatal["scarabImpact"]["impactPoint"], {"x": 20.0, "y": 21.0})

    def test_reaver_has_three_active_generated_zealots_and_releases_slot(self):
        self.config["rules"]["reaverAttack"]["ordinaryChancePercent"] = 100
        bridge = DouQuquVmBridge(config=self.config, seed=1)
        reaver = bridge.call("douququ.unit.spawn", {"unit_type": "Reaver", "owner": 1, "x": 2.0, "y": 3.0})["payload"]["tag"]
        target = bridge.call("douququ.unit.spawn", {"unit_type": "Marine", "owner": 2, "x": 4.0, "y": 5.0})["payload"]["tag"]
        results = [bridge.call("douququ.attack", {"attacker_tag": reaver, "target_tag": target})["payload"] for _ in range(4)]
        self.assertEqual([item["triggered"] for item in results], [True, True, True, False])
        self.assertEqual(results[-1]["blocked"], "max_active_generated")
        self.assertEqual(bridge.world.snapshot()["activeGeneratedZealots"], {reaver: 3})
        zealot = next(unit["tag"] for unit in bridge.world.snapshot()["units"] if unit["unit_type"] == "Zealot")
        bridge.call("douququ.kill", {"killer_tag": target, "victim_tag": zealot})
        self.assertEqual(bridge.world.snapshot()["activeGeneratedZealots"], {reaver: 2})
        replacement = bridge.call("douququ.attack", {"attacker_tag": reaver, "target_tag": target})["payload"]
        self.assertTrue(replacement["triggered"])

    def test_vulture_storage_refill_is_fifty_and_death_drops_owned_mines(self):
        vulture = self.spawn("Vulture", x=6.0, y=7.0)
        initial = next(unit for unit in self.call("douququ.snapshot")["units"] if unit["tag"] == vulture)
        self.assertEqual((initial["storage_max"], initial["stored_mines"]), (5, 5))
        self.call("douququ.vulture.consume", unit_tag=vulture, count=2)
        self.call("douququ.player.set_minerals", owner=1, minerals=50)
        refill = self.call("douququ.vulture.refill", unit_tag=vulture)
        self.assertEqual((refill["status"], refill["storedMines"], refill["minerals"]), ("refilled", 5, 0))
        full = self.call("douququ.vulture.refill", unit_tag=vulture)
        self.assertEqual(full["status"], "already_full")

        victim = self.spawn("Vulture", owner=2, x=12.0, y=13.0)
        death = self.call("douququ.kill", killer_tag=vulture, victim_tag=victim)
        mines = self.units(self.call("douququ.snapshot"), "SpiderMine")
        self.assertEqual(len(death["spawned"]), 3)
        self.assertEqual([(mine["owner"], mine["position"]) for mine in mines], [(2, {"x": 12.0, "y": 13.0})] * 3)

    def test_banshee_hatch_consumes_twenty_energy_and_ticks_spawn_marines(self):
        banshee = self.spawn("InfestedBanshee", x=10.0, y=11.0)
        self.call("douququ.unit.set_energy", unit_tag=banshee, energy=100.0)
        for energy, count in ((20, 1), (40, 2), (60, 3), (80, 4)):
            self.call("douququ.unit.set_energy", unit_tag=banshee, energy=100.0)
            result = self.call("douququ.banshee.hatch", unit_tag=banshee, requested_energy=energy)
            self.assertEqual((result["status"], len(result["spawned"]), result["cost"]), ("hatched", count, energy))
        self.call("douququ.unit.set_energy", unit_tag=banshee, energy=20.0)
        ticked = self.call("douququ.tick", seconds=10.0)
        self.assertEqual(len(ticked["spawned"]), 1)
        self.assertEqual(len(self.units(self.call("douququ.snapshot"), "Marine")), 1 + 2 + 3 + 4 + 1)
        self.call("douququ.unit.set_energy", unit_tag=banshee, energy=19.0)
        insufficient = self.call("douququ.banshee.hatch", unit_tag=banshee, requested_energy=20)
        self.assertEqual((insufficient["status"], insufficient["energy"], insufficient["spawned"]), ("insufficient_energy", 19.0, []))

    def test_brood_lord_proc_is_real_projectile_metadata_not_unit_spawn(self):
        self.assertEqual(self.config["rules"]["broodLordAttack"]["chancePercent"], 15)
        lord = self.spawn("BroodLord")
        target = self.spawn("Marine", owner=2, x=30.0, y=31.0)
        self.bridge.world.rng = FixedRandom(15)
        result = self.call("douququ.attack", attacker_tag=lord, target_tag=target)
        self.assertTrue(result["triggered"])
        self.assertEqual(result["projectile"]["launchEffect"], "CRV_BroodLord_BanelingLaunch")
        self.assertEqual(result["projectile"]["target"], {"x": 30.0, "y": 31.0})
        self.assertEqual(self.units(self.call("douququ.snapshot"), "Baneling"), [])

    def test_hydralisk_heals_only_after_kill_by_twenty_five(self):
        hydra = self.spawn("Hydralisk")
        target = self.spawn("Marine", owner=2)
        self.call("douququ.unit.set_life", unit_tag=hydra, life=50.0)
        self.call("douququ.attack", attacker_tag=hydra, target_tag=target)
        state = next(unit for unit in self.call("douququ.snapshot")["units"] if unit["tag"] == hydra)
        self.assertEqual(state["life"], 50.0)
        victim = self.spawn("Marine", owner=2)
        result = self.call("douququ.kill", killer_tag=hydra, victim_tag=victim)
        self.assertEqual(result["healed"], 25.0)
        state = next(unit for unit in self.call("douququ.snapshot")["units"] if unit["tag"] == hydra)
        self.assertEqual(state["life"], 75.0)

    def test_kerrigan_whitelist_spawns_two_at_victim_position_and_broodlings_do_not_recurse(self):
        for killer_type in ("K5Kerrigan", "K5KerriganBurrowed"):
            killer = self.spawn(killer_type, owner=1)
            victim = self.spawn("Marine", owner=2, x=40.0, y=41.0)
            result = self.call("douququ.kill", killer_tag=killer, victim_tag=victim)
            self.assertEqual(len(result["kerriganBroodlings"]), 2, killer_type)
            broodling = next(unit for unit in self.units(self.call("douququ.snapshot"), "KerriganInfestBroodling") if unit["tag"] == result["kerriganBroodlings"][0])
            self.assertEqual((broodling["owner"], broodling["position"]), (1, {"x": 40.0, "y": 41.0}))
            recursive_victim = self.spawn("Marine", owner=2)
            recursive = self.call("douququ.kill", killer_tag=broodling["tag"], victim_tag=recursive_victim)
            self.assertEqual(recursive["spawned"], [])

    def test_debug_vm_executes_real_plugin_side_effects(self):
        config = copy.deepcopy(self.config)
        config["rules"]["reaverAttack"]["ordinaryChancePercent"] = 100
        vm = DouQuquVm(config=config, seed=3)
        result = vm.run_sync({
            "vm": "vibe-debug/1",
            "steps": [
                {"op": "call", "fn": "douququ.reset", "args": {"seed": 3}},
                {"op": "call", "fn": "douququ.unit.spawn", "args": {"unit_type": "Reaver", "owner": 1}, "save": "reaver"},
                {"op": "call", "fn": "douququ.unit.spawn", "args": {"unit_type": "Marine", "owner": 2, "x": 8.0, "y": 9.0}, "save": "target"},
                {"op": "call", "fn": "douququ.attack", "args": {"attacker_tag": "$vars.reaver.tag", "target_tag": "$vars.target.tag"}},
                {"op": "assert", "source": "$last", "path": "triggered", "equals": True},
                {"op": "assert", "source": "$last", "path": "impactPoint.x", "equals": 8.0},
                {"op": "call", "fn": "douququ.snapshot", "args": {}, "save": "snapshot"},
                {"op": "assert", "source": "$vars.snapshot", "path": "units.2.unit_type", "equals": "Zealot"},
            ],
        })
        self.assertEqual(result["status"], "passed", result)

    def test_config_and_dispatch_are_explicit(self):
        metadata = load_function_metadata()
        expected = {
            "douququ.reset", "douququ.unit.set_energy", "douququ.unit.set_life", "douququ.player.set_minerals",
            "douququ.attack", "douququ.reaver.scarab_impact", "douququ.kill", "douququ.banshee.hatch",
            "douququ.tick", "douququ.vulture.refill", "douququ.vulture.consume", "douququ.snapshot",
            "douququ.unit.spawn",
        }
        self.assertEqual(expected, set(metadata))
        self.assertEqual(set(DouQuquVmBridge()._dispatch), set(metadata))


if __name__ == "__main__":
    unittest.main()
