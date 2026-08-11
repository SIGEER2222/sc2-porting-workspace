"""A cutoff must never be reported as terminal evidence.

Stage 6's rule is "do not convert timeout/cutoff into victory". On 2026-08-10 a
192,000-game-loop rollout exhausted its 6000-step budget with
``terminal_observed=false`` and was still written out as ``status="passed"``,
because the runtime gate accepted ``steps_collected == max_steps`` OR
``terminal_observed`` as interchangeable. ``--stop-on-terminal`` only permits an
early exit; nothing ever asserted one happened.

These tests pin the demanding half of that contract.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from run_live_rl import build_runtime_census, terminal_gate_failures  # noqa: E402


class TerminalGateFailClosedTests(unittest.TestCase):
    def test_budget_exhaustion_without_terminal_is_a_gate_failure(self) -> None:
        report = {"terminal_observed": False, "steps_collected": 6000}
        self.assertEqual(
            terminal_gate_failures(report, require_terminal=True),
            ["terminal_not_observed"],
        )

    def test_observed_terminal_is_not_a_failure(self) -> None:
        """Positive control: the demand must be satisfiable."""

        report = {"terminal_observed": True, "terminal_results": [{"result": "Victory"}]}
        self.assertEqual(terminal_gate_failures(report, require_terminal=True), [])

    def test_runs_that_never_asked_for_terminal_evidence_are_untouched(self) -> None:
        """Negative control: this must not turn every Stage-5 run red."""

        report = {"terminal_observed": False, "steps_collected": 2048}
        self.assertEqual(terminal_gate_failures(report, require_terminal=False), [])

    def test_unreachable_evidence_names_the_structural_cause(self) -> None:
        report = {
            "terminal_observed": False,
            "runtime_census": {
                "terminal_evidence_reachable": False,
                "verdict": "player_faction_uninitialised:launcher_map_never_entered_gameplay",
            },
        }
        failures = terminal_gate_failures(report, require_terminal=True)
        self.assertEqual(len(failures), 1)
        self.assertTrue(failures[0].startswith("terminal_not_observed:evidence_unreachable:"))
        self.assertIn("player_faction_uninitialised", failures[0])

    def test_collapsed_economy_is_distinguished_from_unreachable_evidence(self) -> None:
        report = {
            "terminal_observed": False,
            "runtime_census": {
                "terminal_evidence_reachable": True,
                "economy_collapsed": True,
                "verdict": "economy_lost:commander_economy_came_online_then_collapsed",
            },
        }
        self.assertEqual(
            terminal_gate_failures(report, require_terminal=True),
            ["terminal_not_observed:commander_economy_collapsed"],
        )


class CensusPeakVerdictTests(unittest.TestCase):
    """Two-point sampling cannot tell "never online" from "online then lost"."""

    @staticmethod
    def _observation(loop: int, *, supply_cap: int, units: int, minerals: int = 0):
        return {
            "loop": loop,
            "own_units": [{"unit_type_id": 48} for _ in range(units)],
            "resources": {"minerals": minerals, "vespene": 0, "supply_used": 0, "supply_cap": supply_cap},
        }

    def test_economy_that_came_online_and_died_is_not_called_uninitialised(self) -> None:
        initial = self._observation(0, supply_cap=0, units=0)
        final = self._observation(192000, supply_cap=0, units=2, minerals=2472)
        census = build_runtime_census(
            initial, final, peak={"max_supply_cap": 15, "loop_at_max_supply_cap": 4000, "samples": 6000}
        )
        self.assertFalse(census["commander_economy_online"])
        self.assertTrue(census["commander_economy_ever_online"])
        self.assertTrue(census["economy_collapsed"])
        self.assertEqual(
            census["verdict"], "economy_lost:commander_economy_came_online_then_collapsed"
        )
        # The artifact was not broken: a player_result was structurally reachable.
        self.assertTrue(census["terminal_evidence_reachable"])

    def test_economy_that_never_appeared_still_reports_partial_faction(self) -> None:
        """Negative control: the new state must not swallow the old one."""

        initial = self._observation(0, supply_cap=0, units=0)
        final = self._observation(192000, supply_cap=0, units=2, minerals=2472)
        census = build_runtime_census(initial, final, peak={"max_supply_cap": 0, "samples": 6000})
        self.assertFalse(census["commander_economy_ever_online"])
        self.assertFalse(census["economy_collapsed"])
        self.assertEqual(census["verdict"], "partial_faction:units_without_commander_economy")
        self.assertFalse(census["terminal_evidence_reachable"])

    def test_live_economy_still_reports_faction_initialised(self) -> None:
        initial = self._observation(0, supply_cap=0, units=0)
        final = self._observation(20000, supply_cap=15, units=16, minerals=300)
        census = build_runtime_census(initial, final, peak={"max_supply_cap": 15, "samples": 600})
        self.assertEqual(census["verdict"], "faction_initialised")
        self.assertFalse(census["economy_collapsed"])
        self.assertTrue(census["terminal_evidence_reachable"])

    def test_missing_peak_keeps_the_legacy_two_point_behaviour(self) -> None:
        initial = self._observation(0, supply_cap=0, units=0)
        final = self._observation(192000, supply_cap=0, units=2, minerals=2472)
        census = build_runtime_census(initial, final)
        self.assertEqual(census["verdict"], "partial_faction:units_without_commander_economy")
        self.assertNotIn("peak", census)


if __name__ == "__main__":
    unittest.main()
