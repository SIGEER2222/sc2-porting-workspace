#!/usr/bin/env python3
"""Build the Git-managed Revolution Overdrive runtime patch registry."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[4]
PROJECT_ROOT = WORKSPACE / "src" / "projects" / "revolution-overdrive-porting"
VIBE_ROOT = PROJECT_ROOT / "vibe"
PATCH_MANIFEST = VIBE_ROOT / "commander_map_patches.json"
MATRIX_DEFAULT = (
    WORKSPACE
    / "artifacts"
    / "projects"
    / "revolution-overdrive-porting"
    / "stage10-all-commander-adaptation"
    / "commander-map-matrix.json"
)
RUNTIME_EVIDENCE_INDEX = (
    WORKSPACE
    / "artifacts"
    / "projects"
    / "revolution-overdrive-porting"
    / "stage10-all-commander-adaptation"
    / "runtime-evidence-index.json"
)
ALENGER_CONFIG = WORKSPACE / "src" / "config" / "alenger-mods.json"
REBORN_CONFIG = WORKSPACE / "src" / "config" / "reborn-commanders.json"

RACE_DEFAULTS = {
    "Terran": {"startingStructure": "CommandCenter", "startingWorker": "SCV"},
    "Zerg": {"startingStructure": "Hatchery", "startingWorker": "Drone"},
    "Protoss": {"startingStructure": "Nexus", "startingWorker": "Probe"},
}
NATIVE_STRUCTURE_TYPES = [
    "CommandCenter",
    "OrbitalCommand",
    "PlanetaryFortress",
    "Hatchery",
    "Lair",
    "Hive",
    "Nexus",
]
NATIVE_WORKER_TYPES = ["SCV", "Drone", "Probe"]

# Each source is rooted at a registered workspace source. The launcher resolves
# these IDs locally and only writes the selected directories into SC2 staging.
DEPENDENCY_SOURCES = {
    "ro-owned": {
        "sourceId": "revolution-overdrive-owned-package",
        "root": "src/projects/revolution-overdrive-porting/packages/Commander/Mods",
    },
    "cmre-core": {
        "sourceId": "cmre-owned-project",
        "root": "src/projects/cmre-porting/packages/Mods/CMRE",
    },
    "cmre-commanders": {
        "sourceId": "cmre-owned-project",
        "root": "src/projects/cmre-porting/packages/Mods/Commanders",
    },
    "cmre-runtime": {
        "sourceId": "cmre-runtime",
        "root": "Mods",
    },
}

OFFICIAL_OVERRIDES = {
    "TerranSwann": {"startingStructure": "CommandCenterSwann", "startingWorker": "SCVSwann", "hero": "Swann"},
    "TerranHorner": {"startingStructure": "HHCommandCenter", "startingWorker": "HHSCV", "hero": "HHReaper"},
    "TerranMengsk": {"startingStructure": "CommandCenterMengsk", "startingWorker": "SCVMengsk", "hero": "MarauderMengsk"},
    "TerranRaynor": {"hero": "RaynorCommando"},
    "TerranTychus": {"hero": "TychusCommando"},
    "TerranNova": {"hero": "NovaCoop"},
    "ZergKerrigan": {"hero": "Kerrigan"},
    "ZergDehaka": {"startingStructure": "DehakaHatchery", "startingWorker": "DehakaDrone", "hero": "DehakaCoop"},
    "ZergZagara": {"hero": "ZaGara"},
    "ZergStetmann": {"startingStructure": "HatcheryStetmann", "startingWorker": "DroneStetmann", "hero": "GaryStetmann"},
    "ZergStukov": {"hero": "InfestedStukovCoop"},
    "ZergAbathur": {"hero": "CoopCasterAbathur"},
    "ProtossKarax": {"hero": "KaraxChampion"},
    "ProtossVorazun": {"hero": "VorazunChampion"},
    "ProtossZeratul": {"hero": "Zeratul"},
    "ProtossFenix": {"hero": "FenixChampion"},
    "ProtossArtanis": {"hero": "Artanis"},
    "ProtossAlarak": {"hero": "AlarakChampion"},
}

# Native factions keep their Stage 07 bridge. Their start units still appear in
# this contract so all WebUI choices are represented by one manifest.
RO_FACTION_PROFILES = {
    "RevolutionOverdriveIron": {"race": "Terran", "startingStructure": "1gangtieyaosai", "startingWorker": "1gangtiegongchengche", "hero": "1gangtietaitan"},
    "RevolutionOverdriveMadness": {"race": "Terran", "startingStructure": "3diguoqianshaojidi", "startingWorker": "3diguolaogong", "hero": "3diguozhijian"},
    "RevolutionOverdrivePirate": {"race": "Terran", "startingStructure": "9qianxianzhihuizhongxin", "startingWorker": "9shihuangzhe", "hero": "9chenmomalihao"},
    "RevolutionOverdriveCoverts": {"race": "Terran", "startingStructure": "CommandCenterC", "startingWorker": "SCVC", "hero": ""},
    "RevolutionOverdriveUmojan": {"race": "Terran", "startingStructure": "CommandCenterU", "startingWorker": "SCVU", "hero": "UmojanCommanderU"},
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_runtime_evidence_index() -> dict[tuple[str, str], dict]:
    if not RUNTIME_EVIDENCE_INDEX.is_file():
        return {}
    index = read_json(RUNTIME_EVIDENCE_INDEX)
    if index.get("schemaVersion") != 1 or index.get("classification") != "runtime":
        raise RuntimeError("unsupported Stage 10 runtime evidence index contract")
    records: dict[tuple[str, str], dict] = {}
    for record in index.get("cells", []):
        map_name = str(record.get("map", ""))
        commander = str(record.get("commander", ""))
        if not map_name or not commander or record.get("status") != "runtime_pass":
            raise RuntimeError("Stage 10 runtime evidence index contains an invalid cell")
        key = (map_name, commander)
        if key in records:
            raise RuntimeError(f"duplicate Stage 10 runtime evidence cell: {map_name}/{commander}")
        records[key] = record
    return records


def load_webui_commanders() -> list[dict]:
    webui = WORKSPACE / "tools" / "cmre-webui"
    sys.path.insert(0, str(webui))
    import server  # type: ignore  # pylint: disable=import-outside-toplevel

    return server.load_commanders() + server.load_revolution_commanders()


def load_webui_maps() -> list[dict]:
    webui = WORKSPACE / "tools" / "cmre-webui"
    sys.path.insert(0, str(webui))
    import server  # type: ignore  # pylint: disable=import-outside-toplevel

    return server.load_revolution_maps()


def dependency(provider: str, name: str, destination: str) -> dict:
    source = DEPENDENCY_SOURCES[provider]
    return {
        "name": name,
        "source": {
            "sourceId": source["sourceId"],
            "path": f"{source['root']}/{name}",
        },
        "destination": destination.replace("\\", "/"),
    }


def catalog_ids(root: Path) -> set[str]:
    ids: set[str] = set()
    if not root.is_dir():
        return ids
    pattern = re.compile(r'<CUnit(?:Hero)?\s+id="([A-Za-z0-9_]+)"')
    for path in root.rglob("UnitData*.xml"):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = pattern.search(line)
            if match:
                ids.add(match.group(1))
    return ids


def catalog_index() -> set[str]:
    roots = [
        PROJECT_ROOT / "packages" / "Commander" / "Mods",
        WORKSPACE / "src" / "projects" / "cmre-porting" / "packages" / "Mods",
        WORKSPACE.parent / "cmre-runtime" / "Mods",
    ]
    result: set[str] = set()
    for root in roots:
        result.update(catalog_ids(root))
    return result


def profile_for(commander: dict, alenger: dict, reborn: dict) -> dict:
    commander_id = commander["id"]
    group = commander["group"]
    race = commander.get("race") or "Terran"
    profile = dict(RACE_DEFAULTS[race])
    profile.update({
        "race": race,
        "hero": "",
        "workerCount": 5,
        "dependencies": [],
        "legacyNativeAdapter": False,
    })
    if group == "official":
        profile.update(OFFICIAL_OVERRIDES[commander_id])
        profile["dependencies"] = [
            dependency("cmre-core", "CMRE_Core_Base.SC2Mod", "Mods/CMRE/CMRE_Core_Base.SC2Mod"),
            dependency("cmre-runtime", "CMRE/CM_ArtPack", "Mods/CM_ArtPack"),
        ]
        if commander_id == "TerranSwann":
            profile["dependencies"].append(
                dependency("cmre-commanders", "CommanderUnits_Swann.SC2Mod", "Mods/Commanders/CommanderUnits_Swann.SC2Mod")
            )
        if commander_id == "TerranMengsk":
            profile["dependencies"].append(
                dependency("cmre-core", "CMRE_Core_Mengsk.SC2Mod", "Mods/CMRE/CMRE_Core_Mengsk.SC2Mod")
            )
        if commander_id == "ZergStetmann":
            profile["dependencies"].append(
                dependency("cmre-core", "CMRE_Core_Stetmann.SC2Mod", "Mods/CMRE/CMRE_Core_Stetmann.SC2Mod")
            )
        return profile
    if group == "alenger":
        bank = commander.get("bank", "")
        name = alenger.get("alengerIdToName", {}).get(bank, "")
        source = alenger.get("commanderProfiles", {}).get(name, {})
        profile.update({
            "startingStructure": source.get("startingStructure", profile["startingStructure"]),
            "startingWorker": source.get("startingWorker", profile["startingWorker"]),
            "workerCount": int(source.get("workerCount", 12)),
        })
        profile["dependencies"] = [
            dependency("cmre-commanders", f"{mod}.SC2Mod", f"Mods/Commanders/{mod}.SC2Mod")
            for mod in alenger.get("commanderToAlenger", {}).get(name, [])
        ]
        return profile
    if group == "reborn":
        reborn_name = commander.get("rebornName", "")
        source = next((item for item in reborn.get("commanders", []) if item.get("id") == reborn_name), {})
        expected = source.get("expected_units", []) or []
        profile.update({
            "hero": expected[0] if expected else "",
            "expectedUnits": expected,
            "expectedBuildings": source.get("expected_buildings", []) or [],
        })
        profile["dependencies"] = [
            dependency("cmre-runtime", f"reborn/{name}", f"Mods/reborn/{name}")
            for name in (
                "crys_swarm_assets.SC2Mod",
                "crys_the_swarm_reborn.SC2Mod",
                "sibirens_starhooks_common.SC2Mod",
                "sibirens_starhooks_swarmstoryutils.SC2Mod",
                "sibirens_sundries_swarm_reborn.SC2Mod",
            )
        ]
        return profile
    if group == "revolution-overdrive":
        profile.update(RO_FACTION_PROFILES[commander_id])
        profile["legacyNativeAdapter"] = True
        return profile
    raise RuntimeError(f"unsupported commander group: {group}")


def build_manifest() -> dict:
    commanders = load_webui_commanders()
    ids = [item["id"] for item in commanders]
    if len(commanders) != 50 or len(set(ids)) != 50:
        raise RuntimeError(f"expected 50 unique WebUI commanders, got {len(commanders)}/{len(set(ids))}")
    maps = load_webui_maps()
    map_ids = [item["id"] for item in maps]
    if len(map_ids) != 31 or "tarcade.SC2Map" not in map_ids:
        raise RuntimeError("expected the 31-map Revolution Overdrive registry including tarcade.SC2Map")
    alenger = read_json(ALENGER_CONFIG)
    reborn = read_json(REBORN_CONFIG)
    static_catalog = catalog_index()
    patches = []
    for commander in commanders:
        profile = profile_for(commander, alenger, reborn)
        targets = [profile["startingStructure"], profile["startingWorker"]]
        if profile["hero"]:
            targets.append(profile["hero"])
        unknown = sorted(set(targets) - static_catalog)
        if unknown:
            raise RuntimeError(f"unresolved static catalog targets for {commander['id']}: {', '.join(unknown)}")
        runtime_replacements = [
            {"from": source, "to": profile["startingStructure"], "players": [1]}
            for source in NATIVE_STRUCTURE_TYPES
            if source != profile["startingStructure"]
        ] + [
            {"from": source, "to": profile["startingWorker"], "players": [1]}
            for source in NATIVE_WORKER_TYPES
            if source != profile["startingWorker"]
        ]
        patches.append({
            "id": f"ro-patch-{commander['id']}",
            "commander": commander["id"],
            "bank": commander.get("bank", ""),
            "label": commander.get("label", commander["id"]),
            "group": commander["group"],
            "race": profile["race"],
            "status": "declared_runtime_patch",
            "mode": "legacy_native_adapter" if profile["legacyNativeAdapter"] else "runtime_galaxy_overlay",
            "legacyNativeAdapter": profile["legacyNativeAdapter"],
            "startup": {
                "startingStructure": profile["startingStructure"],
                "startingWorker": profile["startingWorker"],
                "workerCount": profile["workerCount"],
                "hero": profile["hero"],
                "anchorTypes": NATIVE_STRUCTURE_TYPES,
            },
            "runtimeReplacements": runtime_replacements,
            "runtimeCreate": ([{"unit": profile["hero"], "anchorTypes": NATIVE_STRUCTURE_TYPES, "player": 1}] if profile["hero"] else []),
            "dependencies": profile["dependencies"],
            "catalogContracts": [{"family": "Unit", "id": target, "required": True, "onMissing": "block"} for target in sorted(set(targets))],
            "expectedUnits": profile.get("expectedUnits", []),
            "expectedBuildings": profile.get("expectedBuildings", []),
            "sourceRefs": {
                "webui": "tools/cmre-webui/server.py",
                "alenger": "src/config/alenger-mods.json" if commander["group"] == "alenger" else "",
                "reborn": "src/config/reborn-commanders.json" if commander["group"] == "reborn" else "",
                "ro": "src/projects/revolution-overdrive-porting/packages/Commander/revolution-overdrive-commander.json" if commander["group"] == "revolution-overdrive" else "",
            },
        })
    return {
        "schemaVersion": 2,
        "id": "revolution-overdrive-commander-map-patches",
        "package": "revolution-overdrive",
        "description": "Git-managed runtime Galaxy overlays for every WebUI-selectable commander on Revolution Overdrive maps.",
        "runtimeTemplate": "src/projects/revolution-overdrive-porting/vibe/runtime_commander_overlay.galaxy.tpl",
        "mapPolicy": {
            "supportedMaps": sorted(name for name in map_ids if name != "tarcade.SC2Map"),
            "unsupportedMaps": ["tarcade.SC2Map"],
            "forbiddenMaps": ["亡者之夜.SC2Map"],
            "sourceMapsReadOnly": True,
            "patchTarget": "staged MapScript.galaxy only",
        },
        "commanderCount": len(patches),
        "commanders": patches,
    }


def build_matrix(manifest: dict) -> dict:
    maps = load_webui_maps()
    old_matrix_path = (
        WORKSPACE / "artifacts" / "projects" / "revolution-overdrive-porting" / "stage07-commander-closure" / "map-commander-matrix.json"
    )
    old = read_json(old_matrix_path) if old_matrix_path.exists() else {"cells": []}
    old_by_key = {(cell.get("map"), cell.get("commander")): cell for cell in old.get("cells", [])}
    runtime_by_key = load_runtime_evidence_index()
    cells = []
    for map_item in maps:
        map_name = map_item["id"]
        for patch in manifest["commanders"]:
            commander = patch["commander"]
            legacy_name = commander.removeprefix("RevolutionOverdrive")
            prior = old_by_key.get((map_name, legacy_name))
            runtime_record = runtime_by_key.get((map_name, commander))
            unsupported = map_name in manifest["mapPolicy"]["unsupportedMaps"]
            status = "unsupported" if unsupported else (
                runtime_record["status"] if runtime_record else (prior.get("status", "runtime_pending") if prior else "runtime_pending")
            )
            cells.append({
                "id": f"{map_name}__{commander}",
                "map": map_name,
                "commander": commander,
                "commanderGroup": patch["group"],
                "patchId": patch["id"],
                "status": status,
                "mapSource": f"src/projects/revolution-overdrive-porting/packages/Maps/{map_name}",
                "patchManifest": "src/projects/revolution-overdrive-porting/vibe/commander_map_patches.json",
                "targetCatalogs": [item["id"] for item in patch["catalogContracts"]],
                "dependencies": patch["dependencies"],
                "evidenceDir": f"artifacts/projects/revolution-overdrive-porting/stage10-all-commander-adaptation/runtime/{map_name}/{commander}",
                "runtimeEvidence": runtime_record.get("evidence", []) if runtime_record else [],
                "nextAction": (
                    "entry-flow probe required" if unsupported
                    else ("runtime evidence recorded" if runtime_record else "run approved launcher and realtime probe")
                ),
            })
    return {
        "schemaVersion": 1,
        "stage": "10-all-commander-adaptation",
        "classification": "static",
        "mapCount": len(maps),
        "commanderCount": len(manifest["commanders"]),
        "cellCount": len(cells),
        "maps": [item["id"] for item in maps],
        "commanders": [item["commander"] for item in manifest["commanders"]],
        "cells": cells,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", action="store_true")
    parser.add_argument("--matrix-output", type=Path, default=MATRIX_DEFAULT)
    args = parser.parse_args()
    manifest = build_manifest()
    matrix = build_matrix(manifest)
    if args.write_manifest:
        PATCH_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.matrix_output.parent.mkdir(parents=True, exist_ok=True)
    args.matrix_output.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(PATCH_MANIFEST), "matrix": str(args.matrix_output), "maps": matrix["mapCount"], "commanders": matrix["commanderCount"], "cells": matrix["cellCount"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
