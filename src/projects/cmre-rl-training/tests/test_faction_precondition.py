"""Fail-closed precondition: never evaluate a terminal run on an empty faction.

Background (Stage 6, 20260810). Attempt 3 ran 192,000 game loops and produced
no ``player_result``. The Galaxy-side initialization markers were all green:

    initialization_gate_started      = 1
    initialization_complete          = 1
    initialization_building_ready_p1 = 1
    initialization_units_ready_p1    = 1

while the SC2 API's own observation of ``player_id=1`` reported
``own_unit_count=0``, ``minerals=0``, ``supply_cap=0`` at rollout start.

Both cannot be true about the same player. The markers are written in one
unconditional block (``initialization-gate.galaxy:111-115``) the moment
``gf_CmreOnDemandInitializationReady()`` returns true, and that helper skips
every P1 ownership check when the launch profile omits
``CreateStartingUnitsP1`` / ``EnsurePreventDefeatP1`` - which the RL harness
never sets. So four "ready" markers are four restatements of one boolean that
asserted nothing.

These tests pin the host-side replacement, which uses the API observation as an
independent witness.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MODULE_PATH = _PROJECT_ROOT / "tools" / "run_live_rl.py"

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_spec = importlib.util.spec_from_file_location("_run_live_rl_faction", _MODULE_PATH)
assert _spec and _spec.loader
run_live_rl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_live_rl)

faction_precondition_failures = run_live_rl.faction_precondition_failures


def _observation(*, units: int, supply_cap: int, minerals: int = 0) -> dict:
    return {
        "loop": 0,
        "own_units": [
            {"unit_type_id": "4051", "tag": str(i)} for i in range(units)
        ],
        "resources": {
            "minerals": minerals,
            "vespene": 0,
            "supply_used": 0,
            "supply_cap": supply_cap,
        },
    }


class FactionPreconditionTests(unittest.TestCase):
    def test_empty_faction_is_refused(self) -> None:
        """The exact Stage 6 attempt-3 start state must not be evaluated."""

        failures = faction_precondition_failures(
            _observation(units=0, supply_cap=0), require_faction=True
        )
        self.assertTrue(failures, "an empty faction must fail the precondition")
        joined = " ".join(failures)
        self.assertIn("supply_cap=0", joined)
        self.assertIn("own_unit_count=0", joined)

    def test_live_faction_passes(self) -> None:
        """Positive control: a real commander economy must not be blocked."""

        failures = faction_precondition_failures(
            _observation(units=6, supply_cap=15, minerals=50), require_faction=True
        )
        self.assertEqual(failures, [])

    def test_flag_off_never_blocks(self) -> None:
        """Negative control: stages that do not demand a faction are untouched.

        ``train_eval_loop.py`` and the short smoke stages legitimately run on
        thin artifacts. Turning this into an unconditional check would break
        them, so the guard must be inert unless explicitly demanded.
        """

        failures = faction_precondition_failures(
            _observation(units=0, supply_cap=0), require_faction=False
        )
        self.assertEqual(failures, [])

    def test_units_without_supply_still_refused(self) -> None:
        """The 512-step accepted run's end state is *not* a valid Stage 6 start.

        ``{4051 placeholder, Marine}`` with ``supply_cap=0`` has controllable
        surface but no production, so it can neither win nor lose. Owning a
        couple of units is not evidence of an initialised faction.
        """

        failures = faction_precondition_failures(
            _observation(units=2, supply_cap=0, minerals=50), require_faction=True
        )
        self.assertEqual(len(failures), 1)
        self.assertIn("supply_cap=0", failures[0])

    def test_missing_observation_is_refused_not_crashed(self) -> None:
        """A missing observation is an absence of evidence, not a pass."""

        for empty in (None, {}):
            with self.subTest(empty=empty):
                failures = faction_precondition_failures(empty, require_faction=True)
                self.assertTrue(failures)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
