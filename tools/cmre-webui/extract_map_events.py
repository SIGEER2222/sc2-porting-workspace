"""CLI wrapper for the project-owned static map event extractor."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VIBE_ROOT = REPO_ROOT / "src" / "projects" / "cmre-porting" / "vibe"
if str(VIBE_ROOT) not in sys.path:
    sys.path.insert(0, str(VIBE_ROOT))

from map_event_extractor import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
