#!/usr/bin/env python3
"""Shared helpers for kb-build.py and kb-query.py.

Kept separate from the executable scripts because their filenames contain
dashes and cannot be imported as Python modules directly.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
CONFIG_PATH = SCRIPT_DIR / "kb-config.json"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _iter_files_under(root: Path, extensions: tuple, exclude_prefixes: list[str]) -> list[Path]:
    """Walk a directory recursively and return files matching extensions, skipping
    any whose relative path starts with one of `exclude_prefixes`."""
    files: list[Path] = []
    if not root.is_dir():
        return files
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if not path.name.endswith(extensions):
            continue
        rel = path.relative_to(root).as_posix()
        if any(rel.startswith(p) for p in exclude_prefixes):
            continue
        files.append(path)
    return files


def iter_all_source_files(config: dict) -> list[tuple[Path, str, str]]:
    """Return (absolute_path, source_alias, topic) for every file to be indexed.

    Walks the primary `sourcesRoot` plus every `extraScanRoots` entry. The
    `source` field stored in each chunk is `<alias>/<relative-path>` so the
    origin can be traced back from query results.
    """
    sources_root = REPO_ROOT / config["sourcesRoot"]
    primary_ext = tuple(config.get("fileExtensions", [".md"]))
    primary_exclude = config.get("excludePaths", []) or []
    if not config.get("includeLegacy", False):
        primary_exclude = list(primary_exclude) + ["legacy/"]
    else:
        primary_exclude = list(primary_exclude)

    results: list[tuple[Path, str, str]] = []

    # Primary sources root: alias is empty, source path is relative to sources_root.
    for path in _iter_files_under(sources_root, primary_ext, primary_exclude):
        rel = path.relative_to(sources_root).as_posix()
        topic = rel.split("/", 1)[0] if "/" in rel else rel
        results.append((path, rel, topic))

    # Extra scan roots (e.g. sc2-data-trigger official mirror).
    for root_entry in config.get("extraScanRoots", []):
        root_path = REPO_ROOT / root_entry["path"]
        alias = root_entry.get("alias", root_entry["path"])
        ext = tuple(root_entry.get("fileExtensions", primary_ext))
        excludes = root_entry.get("excludeSubpaths", []) or []
        if not root_path.is_dir():
            print(f"WARNING: extra scan root missing, skipping: {root_path}")
            continue
        for path in _iter_files_under(root_path, ext, excludes):
            rel = path.relative_to(root_path).as_posix()
            source = f"{alias}/{rel}"
            topic = f"{alias}:{rel.split('/', 1)[0] if '/' in rel else rel}"
            results.append((path, source, topic))

    return results


def compute_source_hash_from_index(index: list[tuple[Path, str, str]]) -> str:
    """SHA-256 over (source_alias, content) for every file in the index."""
    h = hashlib.sha256()
    for path, source_alias, _ in index:
        h.update(source_alias.encode("utf-8"))
        h.update(b"\0")
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        h.update(b"\0")
    return h.hexdigest()
