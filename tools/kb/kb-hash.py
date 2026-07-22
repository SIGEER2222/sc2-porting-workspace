#!/usr/bin/env python3
"""Print the current source tree hash without building the index.

Useful for diagnosing manifest mismatches:

    python tools/kb/kb-hash.py
"""
from __future__ import annotations

import sys

from kb_common import (
    REPO_ROOT,
    compute_source_hash_from_index,
    iter_all_source_files,
    load_config,
)


def main() -> int:
    config = load_config()
    index = iter_all_source_files(config)
    current_hash = compute_source_hash_from_index(index)

    # Per-root counts for diagnostic. Topic field is `<segment>` for primary
    # root files and `<alias>:<segment>` for extra root files.
    primary_count = sum(1 for _, _, topic in index if ":" not in topic)
    extra_count = len(index) - primary_count

    print(f"repo_root: {REPO_ROOT}")
    print(f"sources_root: {REPO_ROOT / config['sourcesRoot']}")
    print(f"files (primary): {primary_count}")
    print(f"files (extra roots): {extra_count}")
    print(f"files (total): {len(index)}")
    print(f"hash: {current_hash}")
    if config.get("extraScanRoots"):
        print("extra scan roots:")
        for r in config["extraScanRoots"]:
            print(f"  - path={r['path']} alias={r.get('alias', r['path'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
