"""把亡者之夜回放 JSONL 日志转成可动单文件 HTML 播放器。

输入：run_dead_of_night.py 生成的 .jsonl 文件
输出：单文件 HTML（Canvas 可动回放 + 时间轴 + 倍速 + 经济曲线 + 单位血条）

特性：
- 时间轴拖动跳帧（王者营地式）
- 播放/暂停（空格键）
- 倍速控制 0.5x/1x/2x/4x/8x
- 单位圆点 + 血条 + 阵营着色
- 实时经济曲线（矿物/瓦斯/补给）
- 单位悬停 tooltip
- 夜晚背景色带

用法：
    python -m vibe.replay_player <replay.jsonl> [--output player.html]
    python -m vibe.replay_player --latest
"""
from __future__ import annotations

import argparse
import base64
import binascii
import html
import io
import json
import struct
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


# 阵营颜色（与 replay_generator.py 一致）
PLAYER_COLORS = {
    1: "#4a90e2",   # 蓝（玩家）
    2: "#e24a4a",   # 红
    3: "#4ae24a",   # 绿（AmonsForces1）
    4: "#e2c84a",   # 黄（AmonsForces2 / 波次）
    5: "#c84ae2",   # 紫（Infested）
    6: "#4ae2c8",   # 青（ScienceFacility）
    0: "#888888",   # 中立
}

# 单位类型 → 半径（建筑大，工人小，战斗单位中）
UNIT_RADIUS = {
    "CommandCenter": 8, "Barracks": 6, "Factory": 6, "Starport": 6,
    "SupplyDepot": 5, "Bunker": 5, "EngineeringBay": 5, "MissileTurret": 4,
    "SensorTower": 4, "Refinery": 5, "Pylon": 4, "PhotonCannon": 4,
    "SpineCrawler": 5, "SporeCrawler": 4,
    "SCV": 3, "Probe": 3, "Drone": 3,
    "Marine": 3, "Marauder": 3.5, "Marauder": 3.5, "SiegeTank": 4,
    "Medivac": 3.5, "Viking": 3.5, "Ghost": 3,
    "Zergling": 2.5, "Hydralisk": 3, "Roach": 3.5, "Mutalisk": 3.5,
    "Ultralisk": 5, "Baneling": 3, "Infestor": 3, "Queen": 4,
    "Zealot": 3.5, "Stalker": 3.5, "DarkTemplar": 3.5, "HighTemplar": 3,
    "Archon": 5, "Immortal": 4, "Colossus": 5, "Carrier": 5,
    "MineralField": 4, "VespeneGeyser": 5,
}

# 单位类型 → 最大血量（用于血条比例，raw int 需除以 1024）
UNIT_MAX_HP = {
    "Marine": 45, "Marauder": 125, "SCV": 45, "SiegeTank": 160,
    "Medivac": 150, "Viking": 125, "Ghost": 100, "Reaper": 50,
    "CommandCenter": 1400, "Barracks": 800, "Factory": 1000, "Starport": 1000,
    "SupplyDepot": 400, "Bunker": 400, "EngineeringBay": 850, "MissileTurret": 250,
    "SensorTower": 275, "Refinery": 500, "Pylon": 200, "PhotonCannon": 200,
    "SpineCrawler": 300, "SporeCrawler": 300,
    "Zergling": 35, "Hydralisk": 80, "Roach": 145, "Mutalisk": 120,
    "Ultralisk": 500, "Baneling": 30, "Infestor": 90, "Queen": 175,
    "Zealot": 100, "Stalker": 80, "DarkTemplar": 40, "HighTemplar": 40,
    "Archon": 100, "Immortal": 200, "Colossus": 200, "Carrier": 300,
    "MineralField": 1500, "VespeneGeyser": 1500,
}


def load_replay(jsonl_path: Path) -> list[dict]:
    records = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _esc(s) -> str:
    return html.escape(str(s))


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _tga_to_png(path: Path) -> tuple[bytes, dict[str, int], dict[str, int]]:
    """Decode the unpacked map's ordinary true-color TGA into PNG bytes.

    SC2 stores ``Minimap.tga`` as an uncompressed BGR image. Keeping this
    decoder in the renderer avoids a new image dependency and lets the final
    HTML remain self-contained.
    """

    raw = path.read_bytes()
    if len(raw) < 18:
        raise ValueError(f"TGA header is truncated: {path}")
    id_length, image_type = raw[0], raw[2]
    width, height = struct.unpack_from("<HH", raw, 12)
    bits_per_pixel, descriptor = raw[16], raw[17]
    if image_type != 2 or bits_per_pixel not in (24, 32):
        raise ValueError(
            f"unsupported TGA format for {path}: type={image_type}, bpp={bits_per_pixel}"
        )
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid TGA dimensions for {path}: {width}x{height}")

    source_channels = bits_per_pixel // 8
    data_offset = 18 + id_length
    expected = width * height * source_channels
    pixels = raw[data_offset : data_offset + expected]
    if len(pixels) != expected:
        raise ValueError(f"TGA pixel data is truncated: {path}")

    top_origin = bool(descriptor & 0x20)
    right_origin = bool(descriptor & 0x10)
    output_channels = 4 if source_channels == 4 else 3
    rows = bytearray()
    min_x, min_y = width, height
    max_x, max_y = -1, -1
    for y in range(height):
        source_y = y if top_origin else height - 1 - y
        row = bytearray()
        for x in range(width):
            source_x = width - 1 - x if right_origin else x
            offset = (source_y * width + source_x) * source_channels
            blue, green, red = pixels[offset : offset + 3]
            alpha = pixels[offset + 3] if source_channels == 4 else 255
            row.extend((red, green, blue))
            if output_channels == 4:
                row.append(alpha)
            if alpha and (red or green or blue):
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
        rows.append(0)
        rows.extend(row)

    color_type = 6 if output_channels == 4 else 2
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png.extend(
        _png_chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0),
        )
    )
    png.extend(_png_chunk(b"IDAT", zlib.compress(bytes(rows), level=6)))
    png.extend(_png_chunk(b"IEND", b""))
    content_rect = (
        {"x": min_x, "y": min_y, "w": max_x - min_x + 1, "h": max_y - min_y + 1}
        if max_x >= min_x and max_y >= min_y
        else {"x": 0, "y": 0, "w": width, "h": height}
    )
    return bytes(png), {"width": width, "height": height}, content_rect


def _resolve_repo_path(value: str | Path, jsonl_path: Path) -> Path | None:
    candidate = Path(value)
    if candidate.is_absolute() and candidate.is_file():
        return candidate
    repo_root = Path(__file__).resolve().parents[4]
    candidates = (
        repo_root / candidate,
        jsonl_path.resolve().parent / candidate,
        Path.cwd() / candidate,
    )
    return next((path for path in candidates if path.is_file()), None)


def _resolve_repo_dir(value: str | Path, jsonl_path: Path) -> Path | None:
    candidate = Path(value)
    repo_root = Path(__file__).resolve().parents[4]
    candidates = []
    if candidate.is_absolute():
        candidates.append(candidate)
    candidates.extend((repo_root / candidate, jsonl_path.resolve().parent / candidate, Path.cwd() / candidate))
    return next((path for path in candidates if path.is_dir()), None)


def _repo_relative_path(path: Path) -> str:
    repo_root = Path(__file__).resolve().parents[4]
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return path.name


def _catalog_source_files(map_dir: Path | None) -> list[Path]:
    """Return project-owned Catalog files in map-first overlay order.

    The map's own overrides are considered before the reusable CMRE/runtime
    packages.  This is an audit view, not a replacement for SC2's full
    dependency resolver: inherited base-game values remain explicitly absent.
    """

    files: list[Path] = []
    catalog_prefixes = ("UnitData", "FootprintData", "ActorData", "ButtonData", "ModelData")
    if map_dir is not None:
        game_data = map_dir / "Base.SC2Data" / "GameData"
        files.extend(
            sorted(
                path
                for path in game_data.glob("*.xml")
                if path.name.startswith(catalog_prefixes)
            )
        )
    repo_root = Path(__file__).resolve().parents[4]
    packages = repo_root / "src" / "projects" / "cmre-porting" / "packages"
    if packages.is_dir():
        files.extend(
            sorted(
                path
                for path in packages.rglob("*.xml")
                if path.is_file()
                and "Base.SC2Data" in path.parts
                and "GameData" in path.parts
                and "Mods" in path.parts
                and path.name.startswith(catalog_prefixes)
            )
        )
    seen: set[Path] = set()
    return [path for path in files if not (path in seen or seen.add(path))]


def _xml_value(node: ET.Element | None, name: str) -> str | None:
    child = node.find(name) if node is not None else None
    if child is None:
        return None
    return child.get("value")


def _parse_footprint_defs(files: list[Path]) -> dict[str, dict]:
    definitions: dict[str, dict] = {}
    for path in files:
        if "FootprintData" not in path.name:
            continue
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        for footprint in root.findall("CFootprint"):
            footprint_id = footprint.get("id")
            if not footprint_id or footprint_id in definitions:
                continue
            layers = footprint.findall("Layers")
            place_layer = next(
                (layer for layer in layers if layer.get("index") == "Place"),
                layers[0] if layers else None,
            )
            rows = [row.get("value", "") for row in (place_layer.findall("Rows") if place_layer is not None else [])]
            rows = [row for row in rows if row]
            width = max((len(row) for row in rows), default=0)
            height = len(rows)
            shape = footprint.find("Shape")
            definitions[footprint_id] = {
                "id": footprint_id,
                "status": "exact" if width and height else "catalog_only",
                "width": width or None,
                "height": height or None,
                "rows": rows,
                "radius": _xml_value(shape, "Radius"),
                "source_path": _repo_relative_path(path),
            }
    return definitions


def _catalog_asset_path(asset_ref: str | None, catalog_file: Path) -> Path | None:
    if not asset_ref:
        return None
    normalized = asset_ref.replace("\\", "/").lstrip("/")
    if not normalized or normalized.startswith("../") or ":" in normalized:
        return None
    mod_root = next((parent for parent in catalog_file.parents if parent.name.lower().endswith(".sc2mod")), None)
    candidates = []
    if mod_root is not None:
        candidates.append(mod_root / normalized)
    candidates.extend((catalog_file.parent / normalized, catalog_file.parent.parent / normalized))
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _image_data_url(path: Path) -> str | None:
    """Encode a real Catalog-referenced image without adding generated files."""

    try:
        if path.suffix.lower() == ".png":
            payload = path.read_bytes()
            if payload[:8] != b"\x89PNG\r\n\x1a\n":
                return None
        elif path.suffix.lower() == ".tga":
            payload, _, _ = _tga_to_png(path)
        elif path.suffix.lower() == ".dds":
            from PIL import Image

            with Image.open(path) as image:
                output = io.BytesIO()
                image.convert("RGBA").save(output, format="PNG")
                payload = output.getvalue()
        else:
            return None
    except (OSError, ValueError, ImportError):
        return None
    if not payload or len(payload) > 2 * 1024 * 1024:
        return None
    return "data:image/png;base64," + base64.b64encode(payload).decode("ascii")


def _load_catalog_visuals(
    map_metadata: dict,
    jsonl_path: Path,
    static_objects: list[dict],
    frames: list[dict] | None = None,
) -> dict:
    """Build an auditable visual lookup from project Catalog XML.

    Exact geometry is limited to explicit CUnit footprint/radius fields and
    resolvable CFootprint rows.  Standard base-game values inherited from
    CASC are intentionally not guessed here.
    """

    map_dir = _resolve_repo_dir(str(map_metadata.get("map_path", "")), jsonl_path)
    files = _catalog_source_files(map_dir)
    footprint_defs = _parse_footprint_defs(files)
    requested = {str(obj.get("t", "")) for obj in static_objects if obj.get("t")}
    for frame in frames or []:
        for entities in (frame.get("entities_by_player") or {}).values():
            requested.update(str(entity.get("t", "")) for entity in entities if entity.get("t"))

    entries: dict[str, dict] = {}
    icon_candidates: dict[str, list[dict]] = {}
    source_files: list[str] = []
    for path in files:
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        relative = _repo_relative_path(path)
        source_files.append(relative)
        for unit in root.findall("CUnit") + root.findall("CUnitHero"):
            unit_id = unit.get("id")
            if not unit_id:
                continue
            entry = entries.setdefault(unit_id, {"unit_type": unit_id, "declarations": []})
            declaration = {"source_path": relative}
            for field in ("Footprint", "PlacementFootprint", "Radius", "MinimapRadius"):
                value = _xml_value(unit, field)
                if value is not None:
                    declaration[field] = value
                    entry.setdefault(field, value)
            entry["declarations"].append(declaration)
        for actor in root.findall("CActorUnit"):
            unit_type = actor.get("unitName") or actor.get("id")
            if not unit_type:
                continue
            icon = _xml_value(actor, "UnitIcon") or _xml_value(actor.find("GroupIcon"), "Image")
            if icon:
                icon_candidates.setdefault(unit_type, []).append({
                    "asset": icon,
                    "source_path": relative,
                    "asset_path": _catalog_asset_path(icon, path),
                })
        for button in root.findall("CButton"):
            button_id = button.get("id")
            icon = _xml_value(button, "Icon")
            if button_id and icon:
                icon_candidates.setdefault(button_id, []).append({
                    "asset": icon,
                    "source_path": relative,
                    "asset_path": _catalog_asset_path(icon, path),
                })

    for unit_type in sorted(requested):
        entry = entries.setdefault(unit_type, {"unit_type": unit_type, "declarations": []})
        footprint_id = entry.get("Footprint")
        footprint = footprint_defs.get(footprint_id) if footprint_id else None
        if footprint is not None:
            entry["footprint"] = dict(footprint)
        for field in ("Radius", "MinimapRadius"):
            if field in entry:
                try:
                    entry[field.lower()] = float(entry[field])
                except (TypeError, ValueError):
                    pass
        candidates = icon_candidates.get(unit_type, [])
        chosen = next((candidate for candidate in candidates if candidate["asset_path"] is not None), None)
        if chosen is None and candidates:
            chosen = candidates[0]
        if chosen:
            entry["icon"] = {
                "asset": chosen["asset"],
                "source_path": chosen["source_path"],
                "asset_path": _repo_relative_path(chosen["asset_path"]) if chosen["asset_path"] else None,
                "status": "embedded" if chosen["asset_path"] and _image_data_url(chosen["asset_path"]) else "referenced_unavailable",
            }
            if chosen["asset_path"]:
                data_url = _image_data_url(chosen["asset_path"])
                if data_url:
                    entry["icon"]["data_url"] = data_url
        entry.pop("declarations", None)

    entries = {unit_type: entries[unit_type] for unit_type in sorted(requested)}

    report = {
        "status": "PASS" if requested and all(unit_type in entries for unit_type in requested) else "PARTIAL",
        "basis": "project-owned CUnit/CActorUnit/CButton/CFootprint XML; inherited CASC values omitted",
        "requested_unit_type_count": len(requested),
        "catalog_entry_count": sum(1 for unit_type in requested if unit_type in entries),
        "exact_footprint_count": sum(1 for unit_type in requested if entries.get(unit_type, {}).get("footprint", {}).get("status") == "exact"),
        "embedded_icon_count": sum(1 for unit_type in requested if entries.get(unit_type, {}).get("icon", {}).get("status") == "embedded"),
        "referenced_unavailable_icon_count": sum(1 for unit_type in requested if entries.get(unit_type, {}).get("icon", {}).get("status") == "referenced_unavailable"),
        "missing_catalog_types": sorted(unit_type for unit_type in requested if unit_type not in entries),
        "source_files": sorted(set(source_files)),
        "checks": {
            "repo_relative_sources": all(not Path(path).is_absolute() for path in source_files),
            "missing_icons_have_no_fake_data": all(
                not entry.get("icon") or entry["icon"].get("status") == "embedded" or "data_url" not in entry["icon"]
                for entry in entries.values()
            ),
        },
    }
    return {"entries": entries, "report": report}


def _load_minimap_asset(
    map_metadata: dict, jsonl_path: Path
) -> tuple[str, dict[str, int], dict[str, int]]:
    """Return a self-contained minimap data URL and its source projection."""

    minimap_path_value = map_metadata.get("minimap_path")
    if not minimap_path_value and map_metadata.get("map_path"):
        map_path_value = str(map_metadata["map_path"]).rstrip("/\\\\")
        minimap_path_value = f"{map_path_value}/Minimap.tga"
    if not minimap_path_value:
        return "", {}, {}
    minimap_path = _resolve_repo_path(str(minimap_path_value), jsonl_path)
    if minimap_path is None:
        return "", {}, {}
    if minimap_path.suffix.lower() == ".tga":
        png_bytes, size, content_rect = _tga_to_png(minimap_path)
    elif minimap_path.suffix.lower() == ".png":
        png_bytes = minimap_path.read_bytes()
        if len(png_bytes) < 24 or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
            return "", {}, {}
        size = {
            "width": struct.unpack(">I", png_bytes[16:20])[0],
            "height": struct.unpack(">I", png_bytes[20:24])[0],
        }
        content_rect = {
            "x": 0,
            "y": 0,
            "w": size["width"],
            "h": size["height"],
        }
    else:
        return "", {}, {}
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}", size, content_rect


def _project_world_to_minimap(
    x: float,
    y: float,
    world_bounds: dict,
    minimap_size: dict[str, int],
    minimap_rect: dict[str, int],
) -> tuple[float, float]:
    """Project a source ObjectUnit coordinate into Minimap.tga pixels."""

    world_width = float(world_bounds["max_x"]) - float(world_bounds["min_x"])
    world_height = float(world_bounds["max_y"]) - float(world_bounds["min_y"])
    if world_width <= 0 or world_height <= 0:
        raise ValueError("map world bounds must have positive width and height")
    nx = (float(x) - float(world_bounds["min_x"])) / world_width
    ny = (float(world_bounds["max_y"]) - float(y)) / world_height
    return (
        (float(minimap_rect["x"]) + nx * float(minimap_rect["w"]))
        / float(minimap_size["width"]),
        (float(minimap_rect["y"]) + ny * float(minimap_rect["h"]))
        / float(minimap_size["height"]),
    )


def _projection_report(
    map_metadata: dict,
    static_objects: list[dict],
    minimap_data_url: str,
    minimap_size: dict[str, int],
    minimap_rect: dict[str, int],
    world_bounds: dict,
) -> dict:
    """Return an auditable source-coordinate calibration report."""

    report = {
        "status": "UNAVAILABLE",
        "basis": "ObjectUnit world bounds -> Minimap.tga non-black content rectangle",
        "source_map": map_metadata.get("map_path"),
        "minimap_path": map_metadata.get("minimap_path"),
        "world_bounds": dict(world_bounds),
        "minimap_size": dict(minimap_size),
        "content_rect": dict(minimap_rect),
        "static_object_count": len(static_objects),
        "projected_object_count": 0,
        "out_of_content_rect_count": 0,
        "samples": [],
        "checks": {
            "source_minimap_embedded": bool(minimap_data_url),
            "world_bounds_valid": False,
            "all_static_objects_inside_content_rect": False,
        },
    }
    if not minimap_data_url or not minimap_size or not minimap_rect:
        return report
    try:
        world_width = float(world_bounds["max_x"]) - float(world_bounds["min_x"])
        world_height = float(world_bounds["max_y"]) - float(world_bounds["min_y"])
    except (KeyError, TypeError, ValueError):
        return report
    report["checks"]["world_bounds_valid"] = world_width > 0 and world_height > 0
    if not report["checks"]["world_bounds_valid"]:
        return report

    sample_indexes = []
    resource_index = None
    start_index = None
    structure_index = None
    for index, object_data in enumerate(static_objects):
        unit_type = str(object_data.get("t", ""))
        is_resource = "Mineral" in unit_type or "Geyser" in unit_type
        is_start = unit_type in {"ACHeroSpawnPlacement", "PlayerStartLocation", "StartLocation"}
        is_structure = any(
            token in unit_type
            for token in (
                "CommandCenter", "Hatchery", "Nexus", "Barracks", "Factory",
                "Starport", "Pylon", "Gateway", "Cannon", "Bunker", "Turret",
                "SpawningPool", "Warren", "Spire", "Facility", "Depot",
            )
        )
        if is_resource and resource_index is None:
            resource_index = index
        if is_start and start_index is None:
            start_index = index
        if is_structure and structure_index is None:
            structure_index = index
    sample_indexes.extend(
        index for index in (0, resource_index, start_index, structure_index)
        if index is not None and index not in sample_indexes
    )
    sample_indexes.extend(
        index for index in range(len(static_objects))
        if index not in sample_indexes
    )
    sample_indexes = sample_indexes[:8]

    rect_x = float(minimap_rect["x"])
    rect_y = float(minimap_rect["y"])
    rect_right = rect_x + float(minimap_rect["w"])
    rect_bottom = rect_y + float(minimap_rect["h"])
    for index, object_data in enumerate(static_objects):
        try:
            nx, ny = _project_world_to_minimap(
                float(object_data["x"]),
                float(object_data["y"]),
                world_bounds,
                minimap_size,
                minimap_rect,
            )
        except (KeyError, TypeError, ValueError):
            continue
        px = nx * float(minimap_size["width"])
        py = ny * float(minimap_size["height"])
        report["projected_object_count"] += 1
        if not (rect_x <= px <= rect_right and rect_y <= py <= rect_bottom):
            report["out_of_content_rect_count"] += 1
        if index in sample_indexes:
            report["samples"].append({
                "id": object_data.get("id"),
                "type": object_data.get("t"),
                "owner": object_data.get("p"),
                "world": [float(object_data["x"]), float(object_data["y"])],
                "minimap": [round(px, 3), round(py, 3)],
            })
    report["checks"]["all_static_objects_inside_content_rect"] = (
        report["projected_object_count"] == len(static_objects)
        and report["out_of_content_rect_count"] == 0
    )
    report["status"] = "PASS" if all(report["checks"].values()) else "WARN"
    return report


def render_player_html(frames: list[dict], jsonl_path: Path, output_path: Path) -> None:
    """生成可动单文件 HTML 播放器。"""
    if not frames:
        output_path.write_text("<html><body>无回放数据</body></html>", encoding="utf-8")
        return

    records = list(frames)
    frame_records = [
        record for record in records
        if record.get("record_type") == "frame" or "entities_by_player" in record
    ]
    if frame_records:
        frames = frame_records
    actions = [record for record in records if record.get("record_type") == "action"]
    summary = next(
        (record for record in records if record.get("record_type") == "summary"),
        {},
    )
    header = next(
        (record for record in records if record.get("record_type") == "header"),
        {},
    )

    # 嵌入 JSONL 数据（压缩：去掉多余空白）
    frames_json = json.dumps(frames, ensure_ascii=False, separators=(",", ":"))
    actions_json = json.dumps(actions, ensure_ascii=False, separators=(",", ":"))
    summary_json = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
    owner_roles = header.get("owner_roles") or frames[0].get("owner_roles", {})
    owner_roles_json = json.dumps(owner_roles, ensure_ascii=False, separators=(",", ":"))
    map_metadata = header.get("map_metadata") or frames[0].get("map_metadata") or {}
    objective_profile = map_metadata.get("objective_profile") or {}
    geometry = map_metadata.get("geometry") or {}
    static_objects = map_metadata.get("static_objects") or []
    minimap_data_url, minimap_size, minimap_rect = _load_minimap_asset(
        map_metadata, jsonl_path
    )
    catalog_visuals = _load_catalog_visuals(
        map_metadata,
        jsonl_path,
        static_objects,
        frames,
    )

    # 计算地图边界（从所有帧的实体位置）
    all_x, all_y = [], []
    for f in frames:
        for pid_str, ents in f.get("entities_by_player", {}).items():
            for e in ents:
                if e.get("alive"):
                    all_x.append(e["x"])
                    all_y.append(e["y"])
    source_bounds = map_metadata.get("map_bounds") or {}
    has_source_bounds = all(
        key in source_bounds for key in ("min_x", "max_x", "min_y", "max_y")
    )
    if has_source_bounds:
        min_x = float(source_bounds["min_x"])
        max_x = float(source_bounds["max_x"])
        min_y = float(source_bounds["min_y"])
        max_y = float(source_bounds["max_y"])
    elif all_x:
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        pad = max(5.0, (max_x - min_x) * 0.05)
        min_x -= pad; max_x += pad
        min_y -= pad; max_y += pad
    else:
        min_x, max_x, min_y, max_y = 0, 100, 0, 100

    projection_report = _projection_report(
        map_metadata,
        static_objects,
        minimap_data_url,
        minimap_size,
        minimap_rect,
        {"min_x": min_x, "max_x": max_x, "min_y": min_y, "max_y": max_y},
    )

    map_source_text = map_metadata.get("map_path", "scenario fixture")
    map_hash_text = map_metadata.get("map_hash", "n/a")
    native_object_count = map_metadata.get("native_object_count", "n/a")
    native_spawn_count = map_metadata.get("native_spawn_count", "n/a")
    p2_native_spawn_count = header.get("p2_native_spawn_count", "n/a")
    minimap_source_text = map_metadata.get("minimap_path")
    if not minimap_source_text and map_metadata.get("map_path"):
        map_path_value = str(map_metadata["map_path"]).rstrip("/\\\\")
        minimap_source_text = f"{map_path_value}/Minimap.tga"
    minimap_source_text = minimap_source_text or "n/a"

    # 单位颜色映射（JSON 给 JS 用）
    colors_json = json.dumps({str(k): v for k, v in PLAYER_COLORS.items()})
    radius_json = json.dumps(UNIT_RADIUS)
    maxhp_json = json.dumps(UNIT_MAX_HP)

    last = frames[-1]
    first = frames[0]
    verdict = (
        "VICTORY"
        if summary.get("victory") or last.get("victory")
        else summary.get("status") or ("DEFEAT" if last.get("terminal") else "RUN")
    )
    verdict_color = "#4ae24a" if verdict in {"VICTORY", "PASS"} else "#e24a4a"
    replay_id = str(header.get("replay_id") or summary.get("replay_id") or "")
    if map_metadata.get("source_kind") == "cmre_map_catalog":
        title_text = f"{map_metadata.get('map_name', 'CMRE')} 合作 AI 战术回放"
    elif "ladder" in replay_id.lower():
        title_text = "CMRE 梯队 AI 完整局回放"
    else:
        title_text = "亡者之夜 AI 盟友对局回放"
    objective_lines = "".join(
        f"<div style=\"margin:3px 0;\"><span style=\"color:#d8b24a;\">{_esc(item.get('objective_id', 'objective'))}</span> "
        f"{_esc(item.get('label', ''))}<br><span style=\"color:#777;\">{_esc(item.get('tactic', ''))}</span></div>"
        for item in objective_profile.get("objectives", [])
    ) or "<span style=\"color:#666;\">未提供地图任务画像</span>"

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title_text}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0d0d0d; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; padding: 12px; }}
  .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; padding: 10px 16px; background: #1a1a1a; border-radius: 6px; border-left: 5px solid {verdict_color}; }}
  .header h1 {{ font-size: 16px; color: #fff; }}
  .verdict {{ font-size: 20px; font-weight: bold; color: {verdict_color}; }}
  .main {{ display: grid; grid-template-columns: 1fr 320px; gap: 10px; }}
  .canvas-wrap {{ background: #0a0a0a; border: 1px solid #222; border-radius: 6px; overflow: hidden; position: relative; }}
  canvas {{ display: block; width: 100%; height: auto; cursor: crosshair; }}
  .sidebar {{ display: flex; flex-direction: column; gap: 10px; }}
  .panel {{ background: #1a1a1a; border-radius: 6px; padding: 10px 12px; }}
  .panel h3 {{ font-size: 12px; color: #aaa; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }}
  .stat-row {{ display: flex; justify-content: space-between; font-size: 13px; padding: 2px 0; }}
  .stat-row .label {{ color: #888; }}
  .stat-row .value {{ color: #fff; font-weight: bold; font-family: "Consolas", monospace; }}
  .controls {{ display: flex; gap: 6px; flex-wrap: wrap; align-items: center; padding: 8px 12px; background: #1a1a1a; border-radius: 6px; }}
  .btn {{ background: #2a2a2a; color: #ddd; border: 1px solid #333; padding: 5px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; user-select: none; }}
  .btn:hover {{ background: #3a3a3a; }}
  .btn.active {{ background: #4a90e2; color: #fff; border-color: #4a90e2; }}
  .timeline-wrap {{ padding: 8px 12px; background: #1a1a1a; border-radius: 6px; }}
  .timeline {{ width: 100%; height: 28px; -webkit-appearance: none; background: #2a2a2a; border-radius: 4px; outline: none; }}
  .timeline::-webkit-slider-thumb {{ -webkit-appearance: none; width: 14px; height: 28px; background: #4a90e2; border-radius: 3px; cursor: pointer; }}
  .timeline::-moz-range-thumb {{ width: 14px; height: 28px; background: #4a90e2; border-radius: 3px; cursor: pointer; border: none; }}
  .time-label {{ font-size: 11px; color: #888; font-family: "Consolas", monospace; display: flex; justify-content: space-between; margin-top: 2px; }}
  .econ-chart {{ width: 100%; height: 120px; background: #0a0a0a; border-radius: 4px; }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 6px; font-size: 11px; }}
  .legend-item {{ display: flex; align-items: center; gap: 4px; }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; }}
  .tooltip {{ position: absolute; background: rgba(0,0,0,0.92); border: 1px solid #444; padding: 6px 10px; border-radius: 4px; font-size: 11px; color: #fff; pointer-events: none; z-index: 10; white-space: nowrap; display: none; font-family: "Consolas", monospace; }}
  .meta {{ font-size: 11px; color: #666; margin-top: 8px; }}
</style>
</head>
<body>
<div class="header">
  <h1>{title_text}</h1>
  <div class="verdict">{verdict}</div>
</div>

<div class="main">
  <div>
    <div class="canvas-wrap">
      <canvas id="map" width="1000" height="700"></canvas>
      <div class="tooltip" id="tooltip"></div>
    </div>
    <div class="controls" style="margin-top:8px;">
      <button class="btn" id="btnPlay" onclick="togglePlay()">▶ 播放</button>
      <button class="btn" onclick="stepFrame(-1)">◀ 帧</button>
      <button class="btn" onclick="stepFrame(1)">帧 ▶</button>
      <span style="color:#888;font-size:11px;">倍速:</span>
      <button class="btn speed-btn" data-speed="0.5" onclick="setSpeed(0.5)">0.5x</button>
      <button class="btn speed-btn active" data-speed="1" onclick="setSpeed(1)">1x</button>
      <button class="btn speed-btn" data-speed="2" onclick="setSpeed(2)">2x</button>
      <button class="btn speed-btn" data-speed="4" onclick="setSpeed(4)">4x</button>
      <button class="btn speed-btn" data-speed="8" onclick="setSpeed(8)">8x</button>
      <button class="btn" onclick="jumpToNight(-1)">◀ 上一夜</button>
      <button class="btn" onclick="jumpToNight(1)">下一夜 ▶</button>
    </div>
    <div class="timeline-wrap" style="margin-top:8px;">
      <input type="range" class="timeline" id="timeline" min="0" max="{len(frames)-1}" value="0" oninput="onTimelineChange(this.value)">
      <div class="time-label">
        <span id="timeStart">Loop {first['loop']} (0s)</span>
        <span id="timeCur">Loop {first['loop']} (0s)</span>
        <span id="timeEnd">Loop {last['loop']} ({last.get('real_sec', last['loop']/22.4):.0f}s)</span>
      </div>
    </div>
  </div>

  <div class="sidebar">
    <div class="panel">
      <h3>当前状态</h3>
      <div class="stat-row"><span class="label">Loop</span><span class="value" id="curLoop">0</span></div>
      <div class="stat-row"><span class="label">游戏时间</span><span class="value" id="curTime">0s</span></div>
      <div class="stat-row"><span class="label">当前夜晚</span><span class="value" id="curNight">-</span></div>
      <div class="stat-row"><span class="label">P1 玩家存活</span><span class="value" id="p1Alive" style="color:#4a90e2;">0</span></div>
      <div class="stat-row"><span class="label">P2 AI 盟友存活</span><span class="value" id="p2Alive" style="color:#4ae2c8;">0</span></div>
      <div class="stat-row"><span class="label">敌方存活</span><span class="value" id="enemyAlive" style="color:#e24a4a;">0</span></div>
      <div class="stat-row"><span class="label">波次触发</span><span class="value" id="wavesFired">0</span></div>
      <div class="stat-row"><span class="label">命令总数</span><span class="value" id="totalCmds">0</span></div>
    </div>

    <div class="panel">
      <h3>经济指标 (P2 AI 盟友)</h3>
      <div class="stat-row"><span class="label">矿物</span><span class="value" id="p1Minerals" style="color:#4ae2c8;">0</span></div>
      <div class="stat-row"><span class="label">瓦斯</span><span class="value" id="p1Vespene" style="color:#4ae24a;">0</span></div>
      <div class="stat-row"><span class="label">补给</span><span class="value" id="p1Supply">0/0</span></div>
      <canvas class="econ-chart" id="econChart" width="300" height="120"></canvas>
    </div>

    <div class="panel">
      <h3>P1 玩家兵种构成</h3>
      <div id="p1Types" style="font-size:11px;font-family:Consolas,monospace;line-height:1.6;"></div>
    </div>

    <div class="panel">
      <h3>P2 AI 盟友兵种构成</h3>
      <div id="enemyTypes" style="font-size:11px;font-family:Consolas,monospace;line-height:1.6;"></div>
    </div>

    <div class="panel">
      <h3>敌方兵种</h3>
      <div id="enemyTypesHostile" style="font-size:11px;font-family:Consolas,monospace;line-height:1.6;"></div>
    </div>

    <div class="panel">
      <h3>地图任务画像</h3>
      <div style="font-size:11px;line-height:1.45;">{objective_lines}</div>
    </div>

    <div class="panel">
      <h3>P1 指令 / P2 回执</h3>
      <div id="allyActions" style="font-size:11px;line-height:1.5;max-height:180px;overflow:auto;"></div>
    </div>

    <div class="panel">
      <h3>阵营图例</h3>
      <div class="legend" id="legend"></div>
    </div>

    <div class="meta">
      回放日志: {_esc(jsonl_path.name)}<br>
      总帧数: {len(frames)}<br>
      地图来源: {_esc(map_source_text)}<br>
      地图哈希: {_esc(map_hash_text)}<br>
      原生对象/实体: {_esc(native_object_count)} / {_esc(native_spawn_count)}<br>
      原生 P2 单位: {_esc(p2_native_spawn_count)}<br>
      地图边界: [{min_x:.1f},{min_y:.1f}] - [{max_x:.1f},{max_y:.1f}]<br>
      地图底图: {_esc(minimap_source_text) if minimap_data_url else "未嵌入"}<br>
      坐标校准: {_esc(projection_report["status"])} ({projection_report["projected_object_count"]}/{projection_report["static_object_count"]})<br>
      Catalog 视觉: {_esc(catalog_visuals["report"]["status"])}，精确 footprint {catalog_visuals["report"]["exact_footprint_count"]}，内嵌图标 {catalog_visuals["report"]["embedded_icon_count"]}
    </div>
  </div>
</div>

<script>
const FRAMES = {frames_json};
const ACTIONS = {actions_json};
const SUMMARY = {summary_json};
const OWNER_ROLES = {owner_roles_json};
const COLORS = {colors_json};
const RADIUS = {radius_json};
const MAX_HP = {maxhp_json};
const STATIC_OBJECTS = {json.dumps(static_objects, ensure_ascii=False, separators=(',', ':'))};
const OBJECTIVES = {json.dumps(objective_profile.get('objectives', []), ensure_ascii=False, separators=(',', ':'))};
const GEOMETRY = {json.dumps(geometry, ensure_ascii=False, separators=(',', ':'))};
const CATALOG_VISUALS = {json.dumps(catalog_visuals, ensure_ascii=False, separators=(',', ':'))};
const MAP_BOUNDS = {{minX: {min_x}, maxX: {max_x}, minY: {min_y}, maxY: {max_y}}};
const MINIMAP_DATA_URL = {json.dumps(minimap_data_url)};
const MINIMAP_SIZE = {json.dumps(minimap_size, separators=(',', ':'))};
const MINIMAP_RECT = {json.dumps(minimap_rect, separators=(',', ':'))};
const PROJECTION_REPORT = {json.dumps(projection_report, ensure_ascii=False, separators=(',', ':'))};
const TOTAL_FRAMES = FRAMES.length;

// 夜晚边界（用于"上一夜/下一夜"跳转）
const NIGHT_BOUNDS = [];
let prevNight = 0;
for (let i = 0; i < FRAMES.length; i++) {{
  const n = FRAMES[i].current_night || 0;
  if (n !== prevNight) {{
    NIGHT_BOUNDS.push({{frame: i, night: n}});
    prevNight = n;
  }}
}}

const canvas = document.getElementById('map');
const ctx = canvas.getContext('2d');
const tooltip = document.getElementById('tooltip');
const mapImage = new Image();
let mapImageReady = false;
if (MINIMAP_DATA_URL) {{
  mapImage.onload = () => {{ mapImageReady = true; drawFrame(curFrame); }};
  mapImage.src = MINIMAP_DATA_URL;
}}
const initialSettledFrame = FRAMES.findIndex(frame => {{
  const p1 = (frame.entities_by_player?.['1'] || []).some(entity => entity.alive !== false);
  const p2 = (frame.entities_by_player?.['2'] || []).some(entity => entity.alive !== false);
  return p1 && p2;
}});
let curFrame = initialSettledFrame >= 0 ? initialSettledFrame : 0;
let playing = false;
let speed = 1;
let lastTs = 0;
const W = canvas.width, H = canvas.height;
const ICON_IMAGES = {{}};
for (const [unitType, visual] of Object.entries(CATALOG_VISUALS.entries || {{}})) {{
  const dataUrl = visual.icon?.data_url;
  if (!dataUrl) continue;
  const image = new Image();
  image.onload = () => drawFrame(curFrame);
  image.src = dataUrl;
  ICON_IMAGES[unitType] = image;
}}

function worldToCanvas(x, y) {{
  if (MINIMAP_DATA_URL && MINIMAP_SIZE.width && MINIMAP_SIZE.height && MINIMAP_RECT.w) {{
    const nx = (x - MAP_BOUNDS.minX) / (MAP_BOUNDS.maxX - MAP_BOUNDS.minX);
    const ny = (MAP_BOUNDS.maxY - y) / (MAP_BOUNDS.maxY - MAP_BOUNDS.minY);
    return [
      ((MINIMAP_RECT.x + nx * MINIMAP_RECT.w) / MINIMAP_SIZE.width) * W,
      ((MINIMAP_RECT.y + ny * MINIMAP_RECT.h) / MINIMAP_SIZE.height) * H,
    ];
  }}
  const sx = (x - MAP_BOUNDS.minX) / (MAP_BOUNDS.maxX - MAP_BOUNDS.minX);
  const sy = (y - MAP_BOUNDS.minY) / (MAP_BOUNDS.maxY - MAP_BOUNDS.minY);
  return [sx * W, H - sy * H];  // Y 翻转
}}

function radiusFor(type) {{
  return RADIUS[type] || 3.5;
}}

function visualFor(type) {{
  return CATALOG_VISUALS.entries[String(type)] || {{}};
}}

function drawExactFootprint(type, x, y, color, alpha) {{
  const footprint = visualFor(type).footprint;
  if (!footprint || footprint.status !== 'exact' || !footprint.width || !footprint.height) return false;
  const [left, top] = worldToCanvas(Number(x) - Number(footprint.width) / 2, Number(y) + Number(footprint.height) / 2);
  const [right, bottom] = worldToCanvas(Number(x) + Number(footprint.width) / 2, Number(y) - Number(footprint.height) / 2);
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.strokeRect(left, top, right - left, bottom - top);
  return true;
}}

function iconFor(type) {{
  const image = ICON_IMAGES[String(type)];
  return image && image.complete && image.naturalWidth ? image : null;
}}

function isStaticBuilding(type) {{
  return /(?:CommandCenter|Hatchery|Nexus|Barracks|Factory|Starport|Pylon|Gateway|WarpGate|Cannon|Bunker|Turret|SpawningPool|Warren|Spire|Facility|Depot|Forge|Armory|Academy|Lair|Hive|InfestationPit|EvolutionChamber|CreepTumor)/.test(type);
}}

function maxHpFor(type) {{
  return MAX_HP[type] || 100;
}}

function colorFor(pid) {{
  return COLORS[String(pid)] || '#888';
}}

function roleFor(pid) {{
  return OWNER_ROLES[String(pid)] || {{relation: Number(pid) === 1 ? 'leader' : 'enemy', name: `P${{pid}}`}};
}}

function ownerLabel(pid) {{
  const role = roleFor(pid);
  if (role.relation === 'leader') return `P${{pid}} 玩家`;
  if (role.relation === 'ally') return `P${{pid}} AI 盟友`;
  if (role.relation === 'enemy') return `P${{pid}} 敌军`;
  return role.name || `P${{pid}}`;
}}

function relationOf(pid) {{
  return roleFor(pid).relation || 'enemy';
}}

function isHostile(pid) {{
  return relationOf(pid) === 'enemy';
}}

function drawFrame(idx) {{
  if (idx < 0) idx = 0;
  if (idx >= TOTAL_FRAMES) idx = TOTAL_FRAMES - 1;
  curFrame = idx;
  const f = FRAMES[idx];
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#0a0a0a';
  ctx.fillRect(0, 0, W, H);

  if (mapImageReady) {{
    ctx.drawImage(mapImage, 0, 0, W, H);
  }}

  // 夜晚背景色带
  if (f.current_night > 0) {{
    ctx.fillStyle = 'rgba(106, 74, 226, 0.12)';
    ctx.fillRect(0, 0, W, H);
  }}

  // Keep the grid only as the no-source-image fallback.
  if (!mapImageReady) {{
    ctx.strokeStyle = '#1a1a1a';
    ctx.lineWidth = 0.5;
    for (let gx = 0; gx <= W; gx += 50) {{
      ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, H); ctx.stroke();
    }}
    for (let gy = 0; gy <= H; gy += 50) {{
      ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(W, gy); ctx.stroke();
    }}
  }}

  // 地图派生的玩家基地标记
  const basePosition = GEOMETRY.base_position || [85.0, 94.0];
  const [bx, by] = worldToCanvas(basePosition[0], basePosition[1]);
  ctx.strokeStyle = '#4a90e2';
  ctx.lineWidth = 1;
  ctx.beginPath(); ctx.arc(bx, by, 20, 0, 2*Math.PI); ctx.stroke();
  ctx.fillStyle = '#4a90e2';
  ctx.font = '10px sans-serif';
  ctx.fillText('BASE', bx-12, by-22);

  // 原生地图 Objects 静态层。它不会随模拟器实体移动，用来校验点位与
  // 运行时切片的关系；动态实体仍由下方 entities_by_player 绘制。
  for (const object of STATIC_OBJECTS) {{
    const [sx, sy] = worldToCanvas(Number(object.x), Number(object.y));
    const type = String(object.t || '');
    const isResource = type.includes('Mineral') || type.includes('Geyser');
    const color = colorFor(Number(object.p || 0));
    ctx.globalAlpha = isResource ? 0.28 : 0.18;
    ctx.fillStyle = color;
    if (isResource) {{
      ctx.fillRect(sx - 2.5, sy - 2.5, 5, 5);
      ctx.strokeStyle = color;
      ctx.lineWidth = 0.7;
      ctx.strokeRect(sx - 3.5, sy - 3.5, 7, 7);
    }} else if (!drawExactFootprint(type, Number(object.x), Number(object.y), color, 0.3)) {{
      ctx.beginPath(); ctx.arc(sx, sy, 2.2, 0, 2*Math.PI); ctx.fill();
    }} else {{
      ctx.beginPath(); ctx.arc(sx, sy, 2.2, 0, 2*Math.PI); ctx.fill();
    }}
  }}
  ctx.globalAlpha = 1.0;

  // 任务区域/攻击点来自地图画像，不是天梯固定坐标。
  const attackPoints = GEOMETRY.attack_points || [];
  attackPoints.forEach((point, index) => {{
    const [tx, ty] = worldToCanvas(Number(point[0]), Number(point[1]));
    ctx.strokeStyle = '#d8b24a';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(tx, ty, 10, 0, 2*Math.PI); ctx.stroke();
    ctx.fillStyle = '#d8b24a';
    ctx.font = '10px sans-serif';
    ctx.fillText(String(index + 1), tx + 7, ty - 7);
  }});

  // 实体按中立、敌军、P1、P2 绘制，确保 P1/P2 关系在画面上稳定可辨。
  const drawOrder = Object.keys(f.entities_by_player || {{}}).sort((a, b) => {{
    const rank = pid => pid === '0' ? 0 : isHostile(Number(pid)) ? 1 : Number(pid) === 1 ? 2 : 3;
    return rank(a) - rank(b) || Number(a) - Number(b);
  }});
  for (const pidStr of drawOrder) {{
    const ents = f.entities_by_player[pidStr];
    if (!ents) continue;
    const pid = parseInt(pidStr);
    const color = colorFor(pid);
    for (const e of ents) {{
      if (!e.alive) continue;
      // source_x/source_y preserve the map's original ObjectUnit position;
      // the replay must draw the entity's current simulated position.
      const [cx, cy] = worldToCanvas(e.x, e.y);
      const r = radiusFor(e.t);
      // 中立资源点用小方块
      if (pidStr === '0') {{
        ctx.fillStyle = color;
        ctx.fillRect(cx-r, cy-r, r*2, r*2);
        continue;
      }}
      // Catalog 有真实图标时嵌入图标；缺失时保留阵营色点位。
      drawExactFootprint(e.t, e.x, e.y, color, 0.75);
      const icon = iconFor(e.t);
      if (icon) {{
        ctx.globalAlpha = 0.95;
        ctx.drawImage(icon, cx-r, cy-r, r*2, r*2);
        ctx.globalAlpha = 1.0;
        ctx.strokeStyle = color;
        ctx.lineWidth = 0.8;
        ctx.beginPath(); ctx.arc(cx, cy, r+0.5, 0, 2*Math.PI); ctx.stroke();
      }} else {{
        ctx.fillStyle = color;
        ctx.beginPath(); ctx.arc(cx, cy, r, 0, 2*Math.PI); ctx.fill();
      }}
      ctx.globalAlpha = 1.0;
      // 建筑加边框
      const isBuilding = ['CommandCenter','Barracks','Factory','Starport','SupplyDepot','Bunker','EngineeringBay','MissileTurret','SensorTower','Refinery','Pylon','PhotonCannon','SpineCrawler','SporeCrawler'].includes(e.t);
      if (isBuilding && visualFor(e.t).footprint?.status !== 'exact') {{
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 0.8;
        ctx.beginPath(); ctx.arc(cx, cy, r+1, 0, 2*Math.PI); ctx.stroke();
      }}
      // 血条（非中立、非资源点）
      if (pidStr !== '0' && e.t !== 'MineralField' && e.t !== 'VespeneGeyser') {{
        const maxHp = maxHpFor(e.t);
        const hpRatio = Math.max(0, Math.min(1, e.hp / 1024 / maxHp));
        const barW = r * 2.5;
        const barH = 2;
        const barX = cx - barW/2;
        const barY = cy + r + 2;
        ctx.fillStyle = '#400';
        ctx.fillRect(barX, barY, barW, barH);
        ctx.fillStyle = hpRatio > 0.6 ? '#4a4' : (hpRatio > 0.3 ? '#aa4' : '#a44');
        ctx.fillRect(barX, barY, barW * hpRatio, barH);
      }}
    }}
  }}

  // 当前帧事件标记（死亡=红叉，波次=标签）
  if (f.key_events) {{
    for (const ev of f.key_events) {{
      if (ev.kind === 'wave_fired') {{
        // 在顶部标注波次名
        ctx.fillStyle = '#6a4ae2';
        ctx.font = 'bold 11px sans-serif';
        ctx.fillText('▲ ' + ev.wave_name, 10, 20 + (ev.loop % 3) * 14);
      }} else if (ev.kind === 'death' && ev.x !== undefined && ev.y !== undefined) {{
        const [dx, dy] = worldToCanvas(Number(ev.x), Number(ev.y));
        ctx.strokeStyle = '#ff4a4a';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(dx - 5, dy - 5); ctx.lineTo(dx + 5, dy + 5);
        ctx.moveTo(dx + 5, dy - 5); ctx.lineTo(dx - 5, dy + 5);
        ctx.stroke();
      }}
    }}
  }}

  // HUD
  ctx.fillStyle = 'rgba(0,0,0,0.7)';
  ctx.fillRect(8, H-28, 280, 22);
  ctx.fillStyle = '#fff';
  ctx.font = '11px Consolas, monospace';
  ctx.fillText(`Frame ${{idx}}/${{TOTAL_FRAMES-1}} | Loop ${{f.loop}} | ${{(f.real_sec||f.ts_sec||0).toFixed(1)}}s | Night ${{f.current_night||0}}`, 14, H-12);

  updateSidebar(f, idx);
  drawEconChart(idx);
}}

function updateSidebar(f, idx) {{
  document.getElementById('curLoop').textContent = f.loop;
  document.getElementById('curTime').textContent = (f.real_sec || f.ts_sec || 0).toFixed(1) + 's';
  document.getElementById('curNight').textContent = f.current_night > 0 ? `Night ${{f.current_night}}` : '白天';
  document.getElementById('p1Alive').textContent = f.p1_alive || 0;
  document.getElementById('p2Alive').textContent = f.p2_alive || 0;
  document.getElementById('enemyAlive').textContent = f.enemy_alive || 0;
  document.getElementById('wavesFired').textContent = f.waves_fired || 0;
  document.getElementById('totalCmds').textContent = f.total_cmds || 0;
  const res = f.p2_resources || f.p1_resources || {{}};
  document.getElementById('p1Minerals').textContent = res.minerals || 0;
  document.getElementById('p1Vespene').textContent = res.vespene || 0;
  document.getElementById('p1Supply').textContent = `${{res.supply_used||0}}/${{res.supply_cap||0}}`;
  document.getElementById('timeCur').textContent = `Loop ${{f.loop}} (${{(f.real_sec||f.ts_sec||0).toFixed(0)}}s)`;

  // P1 玩家兵种
  const p1t = f.p1_units_by_type || {{}};
  let p1html = '';
  const p1sorted = Object.entries(p1t).sort((a,b) => b[1]-a[1]);
  for (const [t, n] of p1sorted) {{
    p1html += `<div><span style="color:#4a90e2;">●</span> ${{t}}: ${{n}}</div>`;
  }}
  document.getElementById('p1Types').innerHTML = p1html || '<span style="color:#666;">无存活单位</span>';

  // P2 AI 盟友兵种
  const at = f.p2_units_by_type || {{}};
  let allyhtml = '';
  const asorted = Object.entries(at).sort((a,b) => b[1]-a[1]);
  for (const [t, n] of asorted) {{
    allyhtml += `<div><span style="color:#4ae2c8;">●</span> ${{t}}: ${{n}}</div>`;
  }}
  document.getElementById('enemyTypes').innerHTML = allyhtml || '<span style="color:#666;">无存活单位</span>';

  const et = f.enemy_units_by_type || {{}};
  let ehtml = '';
  const esorted = Object.entries(et).sort((a,b) => b[1]-a[1]);
  for (const [t, n] of esorted) {{
    ehtml += `<div><span style="color:#e24a4a;">●</span> ${{t}}: ${{n}}</div>`;
  }}
  document.getElementById('enemyTypesHostile').innerHTML = ehtml || '<span style="color:#666;">无敌方单位</span>';
  renderAllyActions(f.loop);
}}

function renderAllyActions(loop) {{
  const visible = ACTIONS
    .filter(action => Number(action.loop ?? 0) <= Number(loop))
    .slice(-24)
    .reverse();
  const target = document.getElementById('allyActions');
  target.innerHTML = visible.map(action => {{
    const isCommand = action.kind === 'player_command';
    const accepted = isCommand ? action.accepted : action.dispatched?.success;
    const color = isCommand ? '#55a9ff' : '#4ae2c8';
    const label = isCommand
      ? `P1 -> P2: ${{action.arguments?.text || action.notice || ''}}`
      : `${{action.name || 'P2 action'}}${{action.reason ? ` · ${{action.reason}}` : ''}}`;
    const result = isCommand
      ? (accepted ? '已接收' : '已拒绝')
      : (action.dispatched ? (action.dispatched.success ? '已执行' : `失败: ${{action.dispatched.error || 'unknown'}}`) : '排队中');
    return `<div style="border-left:2px solid ${{color}};padding:3px 6px;margin:3px 0;background:#111;">
      <div style="color:${{color}};">L${{action.loop}} · ${{label}}</div>
      <div style="color:#888;">${{result}}${{action.mode ? ` · mode=${{action.mode}}` : ''}}</div>
    </div>`;
  }}).join('') || '<span style="color:#666;">暂无 P1/P2 指令</span>';
}}

function drawEconChart(curIdx) {{
  const c = document.getElementById('econChart');
  const cx = c.getContext('2d');
  const cw = c.width, ch = c.height;
  cx.clearRect(0, 0, cw, ch);
  cx.fillStyle = '#0a0a0a';
  cx.fillRect(0, 0, cw, ch);

  // 收集矿物/瓦斯曲线
  const minerals = [];
  const vespene = [];
  for (const f of FRAMES) {{
    const r = f.p2_resources || f.p1_resources || {{}};
    minerals.push(r.minerals || 0);
    vespene.push(r.vespene || 0);
  }}
  const maxVal = Math.max(50, ...minerals, ...vespene);

  // 矿物曲线（蓝）
  cx.strokeStyle = '#4a90e2';
  cx.lineWidth = 1.5;
  cx.beginPath();
  for (let i = 0; i < minerals.length; i++) {{
    const x = (i / Math.max(1, minerals.length-1)) * cw;
    const y = ch - (minerals[i] / maxVal) * ch;
    if (i === 0) cx.moveTo(x, y); else cx.lineTo(x, y);
  }}
  cx.stroke();

  // 瓦斯曲线（绿）
  cx.strokeStyle = '#4ae24a';
  cx.beginPath();
  for (let i = 0; i < vespene.length; i++) {{
    const x = (i / Math.max(1, vespene.length-1)) * cw;
    const y = ch - (vespene[i] / maxVal) * ch;
    if (i === 0) cx.moveTo(x, y); else cx.lineTo(x, y);
  }}
  cx.stroke();

  // 当前位置竖线
  const curX = (curIdx / Math.max(1, TOTAL_FRAMES-1)) * cw;
  cx.strokeStyle = '#fff';
  cx.lineWidth = 1;
  cx.beginPath(); cx.moveTo(curX, 0); cx.lineTo(curX, ch); cx.stroke();

  // 图例
  cx.fillStyle = '#888';
  cx.font = '9px sans-serif';
  cx.fillText('M', 4, 10);
  cx.fillText('V', 4, 22);
  cx.fillText(String(maxVal), cw-30, 10);
}}

function togglePlay() {{
  playing = !playing;
  const btn = document.getElementById('btnPlay');
  btn.textContent = playing ? '⏸ 暂停' : '▶ 播放';
  btn.classList.toggle('active', playing);
  if (playing) {{
    lastTs = performance.now();
    requestAnimationFrame(tick);
  }}
}}

function tick(ts) {{
  if (!playing) return;
  const dt = ts - lastTs;
  if (dt > 33) {{  // ~30fps
    const framesToAdvance = Math.max(1, Math.round(speed * dt / 33));
    curFrame += framesToAdvance;
    if (curFrame >= TOTAL_FRAMES) {{
      curFrame = TOTAL_FRAMES - 1;
      playing = false;
      document.getElementById('btnPlay').textContent = '▶ 播放';
      document.getElementById('btnPlay').classList.remove('active');
      return;
    }}
    document.getElementById('timeline').value = curFrame;
    drawFrame(curFrame);
    lastTs = ts;
  }}
  requestAnimationFrame(tick);
}}

function stepFrame(delta) {{
  playing = false;
  document.getElementById('btnPlay').textContent = '▶ 播放';
  document.getElementById('btnPlay').classList.remove('active');
  curFrame = Math.max(0, Math.min(TOTAL_FRAMES-1, curFrame + delta));
  document.getElementById('timeline').value = curFrame;
  drawFrame(curFrame);
}}

function setSpeed(s) {{
  speed = s;
  document.querySelectorAll('.speed-btn').forEach(b => b.classList.remove('active'));
  document.querySelector(`.speed-btn[data-speed="${{s}}"]`).classList.add('active');
}}

function onTimelineChange(v) {{
  playing = false;
  document.getElementById('btnPlay').textContent = '▶ 播放';
  document.getElementById('btnPlay').classList.remove('active');
  curFrame = parseInt(v);
  drawFrame(curFrame);
}}

function jumpToNight(dir) {{
  // 找当前帧所在的夜晚段，跳到上一夜/下一夜的开始
  const curNight = FRAMES[curFrame].current_night || 0;
  let target = -1;
  if (dir > 0) {{
    // 找下一个 night 变化的帧
    for (let i = curFrame+1; i < TOTAL_FRAMES; i++) {{
      if ((FRAMES[i].current_night||0) !== curNight) {{ target = i; break; }}
    }}
  }} else {{
    for (let i = curFrame-1; i >= 0; i--) {{
      if ((FRAMES[i].current_night||0) !== curNight) {{
        // 再往前找到这个 night 的开始
        const prevNight = FRAMES[i].current_night||0;
        for (let j = i; j >= 0; j--) {{
          if ((FRAMES[j].current_night||0) !== prevNight) {{ target = j+1; break; }}
        }}
        if (target === -1) target = 0;
        break;
      }}
    }}
  }}
  if (target >= 0) {{
    curFrame = target;
    document.getElementById('timeline').value = curFrame;
    drawFrame(curFrame);
  }}
}}

// 键盘快捷键
document.addEventListener('keydown', (e) => {{
  if (e.code === 'Space') {{ e.preventDefault(); togglePlay(); }}
  else if (e.code === 'ArrowLeft') {{ stepFrame(-1); }}
  else if (e.code === 'ArrowRight') {{ stepFrame(1); }}
}});

// 鼠标悬停 tooltip
canvas.addEventListener('mousemove', (e) => {{
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  const mx = (e.clientX - rect.left) * scaleX;
  const my = (e.clientY - rect.top) * scaleY;
  const f = FRAMES[curFrame];
  let found = null;
  for (const pidStr in f.entities_by_player) {{
    if (pidStr === '0') continue;  // 跳过中立资源点
    for (const ent of f.entities_by_player[pidStr]) {{
      if (!ent.alive) continue;
      const [cx, cy] = worldToCanvas(ent.x, ent.y);
      const r = radiusFor(ent.t) + 2;
      const dx = mx - cx, dy = my - cy;
      if (dx*dx + dy*dy <= r*r) {{ found = ent; break; }}
    }}
    if (found) break;
  }}
  if (found) {{
    const maxHp = maxHpFor(found.t);
    const hpRatio = (found.hp / 1024 / maxHp * 100).toFixed(0);
    tooltip.style.display = 'block';
    tooltip.style.left = (e.clientX - rect.left + 10) + 'px';
    tooltip.style.top = (e.clientY - rect.top + 10) + 'px';
    tooltip.innerHTML = `${{ownerLabel(found.p)}} ${{found.t}}<br>HP: ${{(found.hp/1024).toFixed(0)}}/${{maxHp}} (${{hpRatio}}%)<br>id=${{found.id}}<br>(${{found.x.toFixed(1)}}, ${{found.y.toFixed(1)}})`;
  }} else {{
    tooltip.style.display = 'none';
  }}
}});
canvas.addEventListener('mouseleave', () => {{ tooltip.style.display = 'none'; }});

// 渲染图例
function renderLegend() {{
  const f = FRAMES[0];
  const counts = {{}};
  for (const pidStr in f.entities_by_player) {{
    counts[pidStr] = f.entities_by_player[pidStr].filter(e => e.alive).length;
  }}
  const legend = document.getElementById('legend');
  const names = {{'0':'中立资源'}};
  let html = '';
  for (const pidStr of ['1','2','3','4','5','6','0']) {{
    if (!counts[pidStr]) continue;
    html += `<div class="legend-item"><span class="legend-dot" style="background:${{colorFor(parseInt(pidStr))}}"></span>${{names[pidStr]||ownerLabel(parseInt(pidStr))}} (${{counts[pidStr]}})</div>`;
  }}
  legend.innerHTML = html;
}}

// 初始化
renderLegend();
drawFrame(curFrame);
</script>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_doc, encoding="utf-8")


def find_latest_replay() -> Optional[Path]:
    artifacts = Path(__file__).resolve().parents[1] / "artifacts"
    if not artifacts.exists():
        return None
    replays = sorted(artifacts.glob("dead_of_night_replay_*.jsonl"))
    return replays[-1] if replays else None


def main():
    import sys
    parser = argparse.ArgumentParser(description="把亡者之夜 JSONL 回放日志转成可动 HTML 播放器")
    parser.add_argument("jsonl", type=str, nargs="?", default=None,
                        help="回放日志 JSONL 路径")
    parser.add_argument("--latest", action="store_true", help="转换最新的回放日志")
    parser.add_argument("--output", type=str, default=None, help="HTML 输出路径")
    args = parser.parse_args()

    if args.latest:
        p = find_latest_replay()
        if p is None:
            print("错误：未找到任何 dead_of_night_replay_*.jsonl", file=sys.stderr)
            return 1
        jsonl_path = p
    elif args.jsonl:
        jsonl_path = Path(args.jsonl)
    else:
        parser.error("需要提供 JSONL 路径或使用 --latest")
        return 1

    if not jsonl_path.exists():
        print(f"错误：文件不存在: {jsonl_path}", file=sys.stderr)
        return 1

    output_path = Path(args.output) if args.output else jsonl_path.with_suffix(".player.html")

    records = load_replay(jsonl_path)
    frames = [
        record for record in records
        if record.get("record_type") == "frame" or "entities_by_player" in record
    ]
    if not frames:
        print("错误：JSONL 为空", file=sys.stderr)
        return 1

    render_player_html(records, jsonl_path, output_path)
    print(f"可动回放 HTML 已生成: {output_path}")
    print(f"  帧数: {len(frames)}")
    print(f"  Loop 范围: {frames[0]['loop']} -> {frames[-1]['loop']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
