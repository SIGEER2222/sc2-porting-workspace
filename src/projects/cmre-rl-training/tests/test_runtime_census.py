"""Tests for the live-run runtime census.

The census exists to make one specific failure legible: a CMRE launcher map can
create/join a game and advance loops while the campaign trigger stack never hands
the player a real faction. Frames move, observations answer, and every order comes
back NotSupported/Error. Without a census that shows "1 placeholder unit, 0
minerals, 0 supply cap", the run only reports "0 successful actions", which is
indistinguishable from a policy that simply chose badly.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "tools" / "run_live_rl.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_live_rl_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_live_rl = _load_module()


def _observation(*, loop, units, minerals=0, vespene=0, supply_used=0, supply_cap=0):
    return {
        "loop": loop,
        "own_units": [{"unit_type_id": name} for name in units],
        "visible_enemies": [],
        "visible_allies": [],
        "resources": {
            "minerals": minerals,
            "vespene": vespene,
            "supply_used": supply_used,
            "supply_cap": supply_cap,
        },
    }


class RuntimeCensusTests(unittest.TestCase):
    def test_uninitialised_faction_is_detected(self):
        """One placeholder unit, no economy => the mission never started."""

        initial = _observation(loop=0, units=["4051"])
        final = _observation(loop=4096, units=["4051"])
        census = run_live_rl.build_runtime_census(initial, final)

        self.assertFalse(census["mission_actually_started"])
        self.assertEqual(
            census["verdict"],
            "player_faction_uninitialised:launcher_map_never_entered_gameplay",
        )
        self.assertEqual(census["final"]["own_unit_count"], 1)
        self.assertEqual(census["final"]["supply_cap"], 0)
        self.assertEqual(census["final"]["minerals"], 0)

    def test_real_faction_is_detected(self):
        initial = _observation(
            loop=0,
            units=["CommandCenter", "SCV", "SCV"],
            minerals=50,
            supply_used=12,
            supply_cap=15,
        )
        final = _observation(
            loop=4096,
            units=["CommandCenter", "SCV", "SCV", "Marine"],
            minerals=310,
            supply_used=14,
            supply_cap=23,
        )
        census = run_live_rl.build_runtime_census(initial, final)

        self.assertTrue(census["mission_actually_started"])
        self.assertEqual(census["verdict"], "faction_initialised")
        self.assertEqual(census["final"]["own_unit_count"], 4)
        self.assertEqual(census["final"]["own_unit_types"]["SCV"], 2)

    def test_supply_cap_alone_proves_a_started_mission(self):
        """A single unit is fine if the player actually owns supply."""

        observation = _observation(loop=10, units=["CommandCenter"], supply_cap=15)
        census = run_live_rl.build_runtime_census(observation, observation)
        self.assertTrue(census["mission_actually_started"])
        self.assertEqual(census["verdict"], "faction_initialised")
        self.assertTrue(census["terminal_evidence_reachable"])

    def test_minerals_alone_proves_a_started_mission(self):
        observation = _observation(loop=10, units=["4051"], minerals=50)
        census = run_live_rl.build_runtime_census(observation, observation)
        self.assertTrue(census["mission_actually_started"])

    def test_units_without_supply_cap_are_only_a_partial_faction(self):
        """The observed GAMEPLAY_OK artifact state: orders work, economy never does.

        Loop 16384 of the 2048-step acceptance run still reported 2 own units,
        50 minerals and supply_cap 0 — identical to loop 1024. Actions succeed,
        so this is valid Stage-5 evidence, but no mission player_result can ever
        arrive, so Stage 6 must not be attempted here.
        """

        observation = _observation(
            loop=16384,
            units=["4051", "Marine"],
            minerals=50,
            supply_used=1,
            supply_cap=0,
        )
        census = run_live_rl.build_runtime_census(observation, observation)

        self.assertTrue(census["mission_actually_started"])
        self.assertEqual(census["verdict"], "partial_faction:units_without_commander_economy")
        self.assertFalse(census["commander_economy_online"])
        self.assertFalse(census["terminal_evidence_reachable"])

    def test_uninitialised_faction_is_not_terminal_reachable(self):
        observation = _observation(loop=1024, units=["4051"])
        census = run_live_rl.build_runtime_census(observation, observation)
        self.assertFalse(census["terminal_evidence_reachable"])
        self.assertFalse(census["commander_economy_online"])

    def test_unit_types_are_sorted_by_descending_count(self):
        observation = _observation(loop=1, units=["SCV", "Marine", "SCV", "SCV", "Marine"])
        census = run_live_rl.build_runtime_census(observation, observation)
        self.assertEqual(list(census["final"]["own_unit_types"]), ["SCV", "Marine"])

    def test_empty_observations_do_not_raise(self):
        census = run_live_rl.build_runtime_census({}, {})
        self.assertFalse(census["mission_actually_started"])
        self.assertEqual(census["final"]["own_unit_count"], 0)


class ApiReadinessProbeTests(unittest.TestCase):
    def test_probe_reports_failure_on_a_dead_port(self):
        """The probe must never report ready when nothing answers."""

        # Port 1 is reserved and never serves an SC2 API.
        ready, detail = run_live_rl.probe_sc2_api(1, timeout_seconds=1.0)
        self.assertFalse(ready)
        self.assertTrue(detail)


if __name__ == "__main__":
    unittest.main()
