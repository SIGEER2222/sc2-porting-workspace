"""The economy high-water mark must survive whatever the observation stream is.

It is sampled from inside the grounding hook, i.e. from data the run does not
control, so a malformed observation must degrade the measurement rather than
abort the rollout.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from run_live_rl import CensusPeakTracker  # noqa: E402


class CensusPeakTrackerTests(unittest.TestCase):
    def test_it_remembers_the_highest_supply_cap_and_where_it_happened(self) -> None:
        tracker = CensusPeakTracker()
        tracker.observe({"loop": 0, "resources": {"supply_cap": 0}, "own_units": []})
        tracker.observe({"loop": 4000, "resources": {"supply_cap": 15}, "own_units": [1] * 16})
        tracker.observe({"loop": 9000, "resources": {"supply_cap": 31}, "own_units": [1] * 40})
        tracker.observe({"loop": 192000, "resources": {"supply_cap": 0}, "own_units": [1, 2]})
        fields = tracker.as_dict()
        self.assertEqual(fields["max_supply_cap"], 31)
        self.assertEqual(fields["loop_at_max_supply_cap"], 9000)
        self.assertEqual(fields["max_own_unit_count"], 40)
        self.assertEqual(fields["samples"], 4)

    def test_a_run_that_never_had_supply_reports_zero_not_none(self) -> None:
        tracker = CensusPeakTracker()
        tracker.observe({"loop": 0, "resources": {"supply_cap": 0}, "own_units": []})
        fields = tracker.as_dict()
        self.assertEqual(fields["max_supply_cap"], 0)
        self.assertIsNone(fields["loop_at_max_supply_cap"])

    def test_junk_observations_are_ignored_instead_of_raising(self) -> None:
        tracker = CensusPeakTracker()
        for junk in (None, "not-a-mapping", 42, {}, {"resources": None}, {"resources": {"supply_cap": "x"}}):
            tracker.observe(junk)  # type: ignore[arg-type]
        self.assertEqual(tracker.as_dict()["max_supply_cap"], 0)

    def test_a_valid_sample_after_junk_is_still_recorded(self) -> None:
        """Positive control: the defensive path must not swallow real data."""

        tracker = CensusPeakTracker()
        tracker.observe(None)  # type: ignore[arg-type]
        tracker.observe({"loop": 77, "resources": {"supply_cap": 23}, "own_units": [1, 2, 3]})
        fields = tracker.as_dict()
        self.assertEqual(fields["max_supply_cap"], 23)
        self.assertEqual(fields["loop_at_max_supply_cap"], 77)


if __name__ == "__main__":
    unittest.main()
