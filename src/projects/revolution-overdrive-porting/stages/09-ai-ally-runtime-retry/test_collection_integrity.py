"""Meta-guard: no test module in this project may be silently hidden or unimportable.

Rationale (2026-08-09): Stage 09's original ``test_runtime_observed_contract.py`` referenced
adapter symbols that a history reset had removed. It was quarantined via
``conftest.collect_ignore_glob`` to keep the suite green, which made every later gate report
"32 passed" while that guard never ran at all. A hidden test is worse than a red test.

This module enforces two invariants that would have caught it:

1. ``collect_ignore_glob`` is empty -- exclusions require a deliberate, visible edit here.
2. Every ``test_*.py`` under the project imports cleanly, so a dangling symbol fails loudly
   at collection rather than disappearing from the count.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFTEST = PROJECT_ROOT / "conftest.py"


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(f"_integrity_{path.stem}_{abs(hash(path))}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot build import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CollectionIntegrityTests(unittest.TestCase):
    def test_no_silent_test_exclusion(self):
        """conftest must not hide any test module from collection."""

        self.assertTrue(CONFTEST.is_file(), "project conftest.py is missing")
        conftest = _load_module(CONFTEST)
        ignored = list(getattr(conftest, "collect_ignore_glob", []))
        ignored += list(getattr(conftest, "collect_ignore", []))
        self.assertEqual(
            ignored,
            [],
            "Tests are being hidden from collection: "
            f"{ignored}. Hidden tests report as green forever. Fix or delete the test instead.",
        )

    def test_every_project_test_module_is_importable(self):
        """A dangling import must fail loudly, not shrink the collected test count."""

        sys.path.insert(0, str(PROJECT_ROOT))
        try:
            failures: list[str] = []
            modules = sorted(PROJECT_ROOT.rglob("test_*.py"))
            self.assertGreater(len(modules), 5, "test discovery found suspiciously few modules")
            for path in modules:
                if "__pycache__" in path.parts or path == Path(__file__):
                    continue
                try:
                    _load_module(path)
                except Exception as exc:  # noqa: BLE001 - report every broken module
                    failures.append(f"{path.relative_to(PROJECT_ROOT)}: {type(exc).__name__}: {exc}")
            self.assertEqual(failures, [], "Unimportable test modules:\n" + "\n".join(failures))
        finally:
            if sys.path and sys.path[0] == str(PROJECT_ROOT):
                sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
