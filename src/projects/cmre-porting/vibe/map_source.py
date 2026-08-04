"""Read the unpacked SC2 map components without simulator normalization.

This module is intentionally a source reader, not a replay renderer and not a
scenario builder.  Values in ``object_units`` and ``object_points`` retain the
map's original catalog names, object ids, owners, and coordinates.  The
script contract is extracted only to make native API decisions auditable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional
import xml.etree.ElementTree as ET


SOURCE_COMPONENTS = (
    "MapInfo",
    "Objects",
    "ObjectStrings",
    "Regions",
    "Triggers",
    "MapScript.galaxy",
    "t3Terrain.xml",
    "t3HeightMap",
    "t3SyncHeightMap",
    "CellAttribute_Cda",
    "CellAttribute_Pnp",
    "t3CellFlags",
)


@dataclass(frozen=True)
class MapSource:
    """A JSON-serializable snapshot of source-map facts."""

    map_dir: str
    map_name: str
    source_hash: str
    component_hashes: dict[str, dict[str, Any]]
    map_info: dict[str, Any]
    map_bounds: dict[str, float]
    object_units: list[dict[str, Any]]
    object_points: list[dict[str, Any]]
    regions: list[dict[str, Any]]
    terrain: dict[str, Any]
    pathing: dict[str, Any]
    script: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _repo_relative(path: Path) -> str:
    repo_root = Path(__file__).resolve().parents[4]
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return path.name


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _component_inventory(map_dir: Path) -> tuple[dict[str, dict[str, Any]], str]:
    digest = hashlib.sha256()
    inventory: dict[str, dict[str, Any]] = {}
    for name in SOURCE_COMPONENTS:
        path = map_dir / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        file_hash = hashlib.sha256(data).hexdigest()
        inventory[name] = {
            "path": _repo_relative(path),
            "size": len(data),
            "sha256": file_hash,
        }
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return inventory, digest.hexdigest()


def _position(value: Optional[str]) -> tuple[float, float, float]:
    parts = (value or "0,0,0").split(",")
    try:
        numbers = [float(part.strip()) for part in parts[:3]]
    except ValueError:
        numbers = [0.0, 0.0, 0.0]
    numbers.extend([0.0] * (3 - len(numbers)))
    return numbers[0], numbers[1], numbers[2]


def _object_node(node: ET.Element, kind: str) -> dict[str, Any]:
    x, y, z = _position(node.get("Position"))
    item: dict[str, Any] = {
        "kind": kind,
        "object_id": int(node.get("Id")) if (node.get("Id") or "").isdigit() else None,
        "position": {"x": x, "y": y, "z": z},
        "raw_attributes": dict(sorted(node.attrib.items())),
    }
    if kind == "ObjectUnit":
        resources = node.get("Resources")
        item.update({
            "unit_type": node.get("UnitType", ""),
            "player": int(node.get("Player")) if (node.get("Player") or "").isdigit() else 0,
            "resource_amount": int(resources) if resources and resources.isdigit() else None,
        })
    else:
        item["name"] = node.get("Name", "")
    return item


def _parse_objects(map_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = ET.parse(map_dir / "Objects").getroot()
    units = [_object_node(node, "ObjectUnit") for node in root.iter("ObjectUnit")]
    points = [_object_node(node, "ObjectPoint") for node in root.iter("ObjectPoint")]
    return units, points


def _parse_regions(map_dir: Path) -> list[dict[str, Any]]:
    path = map_dir / "Regions"
    if not path.is_file():
        return []
    root = ET.parse(path).getroot()
    regions: list[dict[str, Any]] = []
    for region in root.iter("region"):
        name = region.find("name")
        shapes: list[dict[str, Any]] = []
        for shape in region.findall("shape"):
            shape_type = shape.get("type", "")
            if shape_type == "circle":
                center = shape.find("center")
                if center is None:
                    continue
                x, y, _ = _position(center.get("value"))
                radius_node = shape.find("radius")
                radius = float(radius_node.get("value", 0.0)) if radius_node is not None else 0.0
                shapes.append({"type": "circle", "x": x, "y": y, "r": radius})
            elif shape_type == "box":
                minimum = shape.find("min")
                maximum = shape.find("max")
                if minimum is None or maximum is None:
                    continue
                x1, y1, _ = _position(minimum.get("value"))
                x2, y2, _ = _position(maximum.get("value"))
                shapes.append({"type": "rect", "x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1})
        regions.append({
            "region_id": int(region.get("id")) if (region.get("id") or "").isdigit() else None,
            "name": name.get("value", "") if name is not None else "",
            "shapes": shapes,
        })
    return regions


def _parse_map_info(map_dir: Path) -> dict[str, Any]:
    data = (map_dir / "MapInfo").read_bytes()
    tokens = [token.decode("ascii", errors="ignore") for token in re.findall(rb"[ -~]{4,}", data)]
    return {
        "size": len(data),
        "magic_hex": data[:4].hex(),
        "ascii_tokens": tokens[:100],
        "binary_sha256": hashlib.sha256(data).hexdigest(),
    }


def _parse_terrain(map_dir: Path) -> dict[str, Any]:
    path = map_dir / "t3Terrain.xml"
    if not path.is_file():
        return {}
    root = ET.parse(path).getroot()
    height = root.find("heightMap")
    ramp_list = height.find("rampList") if height is not None else None
    return {
        "version": root.get("version"),
        "height_map": {
            key: height.get(key) for key in ("tileSet", "dim", "offset", "scale")
        } if height is not None else {},
        "ramp_count": int(ramp_list.get("num", 0)) if ramp_list is not None else 0,
        "cliff_sets": [node.get("name", "") for node in root.iter("cliffSet")],
        "texture_sets": [node.get("name", "") for node in root.iter("textureSet") if node.get("name")],
    }


def _pathing_inventory(map_dir: Path, components: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "source_files": {
            name: components[name]
            for name in ("t3HeightMap", "t3SyncHeightMap", "CellAttribute_Cda", "CellAttribute_Pnp", "t3CellFlags")
            if name in components
        },
        "decoded": False,
        "note": "Binary terrain/pathing components are retained as source inputs; no canvas projection or guessed walkability is used.",
    }


def _script_contract(script: str, points: dict[int, dict[str, Any]]) -> dict[str, Any]:
    spawn_times = {
        int(match.group(1)): float(match.group(2))
        for match in re.finditer(r"gv_spawnVoidShardTime\[(\d+)\]\s*=\s*([0-9.]+)", script)
    }
    stages: list[dict[str, Any]] = []
    stage_matches = list(re.finditer(r"lv_l_Stage\s*=\s*(\d+);", script))
    for index, match in enumerate(stage_matches):
        stage_number = int(match.group(1))
        end = stage_matches[index + 1].start() if index + 1 < len(stage_matches) else min(len(script), match.end() + 3000)
        block = script[match.end():end]
        point_ids = [int(value) for value in re.findall(r"gv_voidShardSpawnLocations\[[^]]+\]\[[^]]+\]\s*=\s*PointFromId\((\d+)\)", block)]
        if point_ids:
            stages.append({
                "stage": stage_number,
                "spawn_seconds": spawn_times.get(stage_number),
                "point_ids": point_ids,
                "points": [points[point_id] for point_id in point_ids if point_id in points],
            })
    return {
        "sha256": hashlib.sha256(script.encode("utf-8")).hexdigest(),
        "function_count": len(re.findall(r"^(?:bool|void|fixed|point|text|string|int)\s+[A-Za-z0-9_]+\s*\(", script, re.M)),
        "trigger_count": len(re.findall(r"^trigger\s+[A-Za-z0-9_]+", script, re.M)),
        "point_from_id": sorted({int(value) for value in re.findall(r"PointFromId\((\d+)\)", script)}),
        "stages": stages,
        "objective_required_count": int((re.search(r"gv_objectiveDestroyVoidShardsRequired\s*=\s*(\d+)", script) or [0, 0])[1]),
        "native_ai": {
            "p2_ai_start": bool(re.search(r"AIStart\(gv_pLAYER_02_USER", script)),
            "p2_condition": "PlayerType(gv_pLAYER_02_USER) != c_playerTypeUser",
            "enemy_players": [3, 4],
        },
        "alliance_contract": {
            "p1_p2_shared_vision": bool(re.search(r"SetPlayerGroupAlliance", script)),
            "p1_to_p2_defeat": bool(re.search(r"PlayerSetAlliance\(gv_pLAYER_01_USER, c_allianceIdDefeat, gv_pLAYER_02_USER", script)),
            "p2_to_p1_defeat": bool(re.search(r"PlayerSetAlliance\(gv_pLAYER_02_USER, c_allianceIdDefeat, gv_pLAYER_01_USER", script)),
        },
        "victory_triggers": [
            name for name in (
                "gt_ObjectiveDestroyVoidShardsComplete",
                "gt_VictoryDestorytheSpawningRiftsCompleted",
                "gt_VictorySequence",
                "gt_Victory",
            ) if name in script
        ],
    }


def read_map_source(map_dir: str | Path) -> MapSource:
    path = Path(map_dir).resolve()
    if not path.is_dir():
        raise NotADirectoryError(f"unpacked SC2Map directory required: {path}")
    required = ("MapInfo", "Objects", "MapScript.galaxy")
    missing = [name for name in required if not (path / name).is_file()]
    if missing:
        raise FileNotFoundError(f"map source missing components: {', '.join(missing)}")

    component_hashes, source_hash = _component_inventory(path)
    object_units, object_points = _parse_objects(path)
    points_by_id = {
        int(point["object_id"]): point
        for point in object_points
        if point.get("object_id") is not None
    }
    positions = [unit["position"] for unit in object_units]
    map_bounds = {
        "min_x": min(item["x"] for item in positions),
        "min_y": min(item["y"] for item in positions),
        "max_x": max(item["x"] for item in positions),
        "max_y": max(item["y"] for item in positions),
    }
    map_bounds["width"] = map_bounds["max_x"] - map_bounds["min_x"]
    map_bounds["height"] = map_bounds["max_y"] - map_bounds["min_y"]
    script = (path / "MapScript.galaxy").read_text(encoding="utf-8", errors="replace")
    return MapSource(
        map_dir=_repo_relative(path),
        map_name=path.name.removesuffix(".SC2Map"),
        source_hash=source_hash,
        component_hashes=component_hashes,
        map_info=_parse_map_info(path),
        map_bounds=map_bounds,
        object_units=object_units,
        object_points=object_points,
        regions=_parse_regions(path),
        terrain=_parse_terrain(path),
        pathing=_pathing_inventory(path, component_hashes),
        script=_script_contract(script, points_by_id),
    )


def resolve_map_source(runtime_map_name: str, explicit_path: str | Path | None = None) -> Optional[Path]:
    """Resolve an unpacked source map for the authoritative runtime name."""
    if explicit_path:
        path = Path(explicit_path)
        return path if path.is_dir() else None
    label = str(runtime_map_name).removeprefix("[CM] ").removesuffix(".SC2Map")
    root = Path(__file__).resolve().parents[1] / "packages" / "Maps"
    candidates = sorted(root.glob("*.SC2Map"))
    for candidate in candidates:
        stem = candidate.name.removesuffix(".SC2Map")
        if stem == label or stem.startswith(label):
            return candidate
    return None


def _main() -> int:
    parser = argparse.ArgumentParser(description="Read raw unpacked SC2 map source data")
    parser.add_argument("--map", required=True, help="unpacked .SC2Map directory")
    parser.add_argument("--output", required=True, help="audit JSON output")
    args = parser.parse_args()
    source = read_map_source(args.map)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(source.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "map_name": source.map_name,
        "source_hash": source.source_hash,
        "object_units": len(source.object_units),
        "object_points": len(source.object_points),
        "regions": len(source.regions),
        "stages": len(source.script["stages"]),
        "objective_required_count": source.script["objective_required_count"],
        "output": str(output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
