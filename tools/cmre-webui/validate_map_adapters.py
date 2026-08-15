"""Validate the project-owned map/commander adapter matrix.

The command consumes map directory names and commander profiles, then emits a
static resolution report. It does not modify maps, mods, or runtime banks.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
VIBE_ROOT = REPO_ROOT / "src" / "projects" / "cmre-porting" / "vibe"
if str(VIBE_ROOT) not in sys.path:
    sys.path.insert(0, str(VIBE_ROOT))

from map_commander_adapter import load_adapter_config, resolve_adapter  # noqa: E402
from map_event_extractor import discover_map_dirs  # noqa: E402


COMMANDER_ID_RE = re.compile(r"^(?:Terran|Zerg|Protoss)?(Alenger\d+)$")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _profile_for(commander_id: str, commander_config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    match = COMMANDER_ID_RE.fullmatch(commander_id)
    if match is None:
        return "", {}
    profile_id = str(commander_config.get("alengerIdToName", {}).get(match.group(1), ""))
    profiles = commander_config.get("commanderProfiles", {})
    profile = profiles.get(profile_id, {})
    if not isinstance(profile, dict):
        raise ValueError(f"commander profile is not an object: {profile_id}")
    return profile_id, profile


def validate_matrix(
    *,
    maps_root: Path,
    adapter_config_path: Path,
    commander_config_path: Path,
    commander_ids: list[str],
) -> dict[str, Any]:
    adapter_config = load_adapter_config(adapter_config_path)
    commander_config = _load_json(commander_config_path)
    map_names = [path.name for path in discover_map_dirs(maps_root)]
    if not map_names:
        raise ValueError(f"no unpacked .SC2Map directories found under {maps_root}")

    resolutions = []
    for map_name in map_names:
        for commander_id in commander_ids:
            profile_id, profile = _profile_for(commander_id, commander_config)
            resolved = resolve_adapter(
                adapter_config,
                map_name=map_name,
                commander_id=commander_id,
                commander_profile=profile,
            )
            startup = resolved["startup"]
            if not startup["startingStructure"] or not startup["startingWorker"]:
                raise ValueError(f"empty startup catalog id: {map_name}/{commander_id}")
            resolutions.append(
                {
                    "map": map_name,
                    "commander": commander_id,
                    "profile": profile_id or None,
                    "mapAdapterId": resolved["map_id"],
                    "mapAdapterMode": resolved["map_unit_policy"]["mode"],
                    "startingStructure": startup["startingStructure"],
                    "startingWorker": startup["startingWorker"],
                    "workerCount": startup["workerCount"],
                    "vanillaRemovalCount": len(startup["vanillaRemovals"]),
                    "eventUnitReplacements": resolved["event_unit_replacements"],
                    "evidence_type": "static",
                }
            )

    custom_profiles = sum(1 for item in resolutions if item["profile"])
    return {
        "schema_version": "cmre-map-commander-adapter-matrix.v1",
        "evidence_type": "static",
        "runtime_claim": "none; this matrix validates static adapter resolution",
        "maps_root": maps_root.name,
        "map_count": len(map_names),
        "commander_count": len(commander_ids),
        "resolution_count": len(resolutions),
        "custom_profile_resolution_count": custom_profiles,
        "maps": map_names,
        "commanders": commander_ids,
        "resolutions": resolutions,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maps-root", required=True, type=Path)
    parser.add_argument(
        "--adapter-config",
        type=Path,
        default=VIBE_ROOT / "map_commander_adapters.json",
    )
    parser.add_argument(
        "--commander-config",
        type=Path,
        default=REPO_ROOT / "src" / "config" / "alenger-mods.json",
    )
    parser.add_argument(
        "--commander",
        dest="commanders",
        action="append",
        help="runtime commander id; repeat for matrix columns",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    commander_config = _load_json(args.commander_config)
    commanders = args.commanders or [
        f"Terran{key}" for key in commander_config.get("alengerIdToName", {})
    ]
    result = validate_matrix(
        maps_root=args.maps_root,
        adapter_config_path=args.adapter_config,
        commander_config_path=args.commander_config,
        commander_ids=commanders,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        key: result[key]
        for key in ("map_count", "commander_count", "resolution_count", "custom_profile_resolution_count")
    }
    summary["output"] = args.output.as_posix()
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
