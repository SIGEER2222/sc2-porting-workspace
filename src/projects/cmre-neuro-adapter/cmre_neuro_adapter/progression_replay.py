"""Compatibility CLI for the state-driven macro replay.

The old implementation merged a fixed action schedule into legacy frames. That
made production appear complete without a simulator command, resource income,
or completion observation. This module keeps the old command shape for callers
but always runs the clean macro fixture instead.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .macro_replay import DEFAULT_REPLAY_MAX_LOOPS, build_macro_replay


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load JSONL only to validate the compatibility input is well formed."""

    records: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("replay records must be objects")
            records.append(record)
    return records


def build_progression_replay(
    records: list[dict[str, Any]] | None = None,
    *,
    source_replay: str = "clean-macro-fixture",
    max_loops: int = DEFAULT_REPLAY_MAX_LOOPS,
) -> list[dict[str, Any]]:
    """Run a clean simulator fixture; never synthesize entities into ``records``.

    ``records`` remains accepted for API compatibility. Its entity frames are not
    used as world state because a legacy snapshot cannot prove an opening economy.
    """

    return build_macro_replay(source_replay=source_replay, max_loops=max_loops)


def write_progression_replay(source_path: Path, output_path: Path, *, max_loops: int = DEFAULT_REPLAY_MAX_LOOPS) -> None:
    # Parse the source so malformed compatibility inputs still fail loudly, but
    # deliberately do not copy its entities, resources, or action schedule.
    load_jsonl(source_path)
    data = build_progression_replay(
        source_replay=Path(source_path).name,
        max_loops=max_loops,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in data) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?", help="legacy replay identity; never used as world state")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-loops", type=int, default=DEFAULT_REPLAY_MAX_LOOPS)
    args = parser.parse_args()
    if args.source is None:
        raise SystemExit("source replay is required for compatibility; use the clean fixture CLI for a source-free run")
    write_progression_replay(args.source, args.output, max_loops=args.max_loops)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "build_progression_replay",
    "load_jsonl",
    "write_progression_replay",
]
