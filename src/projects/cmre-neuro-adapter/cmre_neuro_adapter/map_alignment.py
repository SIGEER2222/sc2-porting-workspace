"""Shared extraction and coordinate metadata for real-map replay artifacts."""

from __future__ import annotations

import struct
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


DEFAULT_MINIMAP_SIZE = (256, 256)
DEFAULT_IMAGE_RECT = {"x": 48, "y": 48, "w": 160, "h": 160}
DEFAULT_MAP_SIZE = (192, 192)
MAPINFO_SIZE_OFFSET = 16


def _read_png_info(path: Path) -> tuple[int, int, dict[str, int] | None]:
    raw = path.read_bytes()
    if len(raw) < 33 or raw[:8] != b"\x89PNG\r\n\x1a\n":
        return DEFAULT_MINIMAP_SIZE[0], DEFAULT_MINIMAP_SIZE[1], None
    width, height, depth, color_type, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", raw[16:29]
    )
    if depth != 8 or compression != 0 or filtering != 0 or interlace != 0:
        return width, height, None
    return width, height, {
        "color_type": color_type,
        "channels": {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type, 0),
    }


def _png_content_rect(path: Path) -> dict[str, int] | None:
    """Find the non-black minimap content rectangle for ordinary RGB PNGs."""

    raw = path.read_bytes()
    if len(raw) < 33 or raw[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width, height, depth, color_type, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", raw[16:29]
    )
    channels = {2: 3, 6: 4}.get(color_type)
    if depth != 8 or channels is None or compression != 0 or filtering != 0 or interlace != 0:
        return None
    offset = 8
    compressed = bytearray()
    while offset + 8 <= len(raw):
        size = struct.unpack(">I", raw[offset : offset + 4])[0]
        kind = raw[offset + 4 : offset + 8]
        payload = raw[offset + 8 : offset + 8 + size]
        offset += 12 + size
        if kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
    try:
        decoded = zlib.decompress(bytes(compressed))
    except zlib.error:
        return None
    row_size = width * channels
    expected = height * (row_size + 1)
    if len(decoded) < expected:
        return None
    previous = bytearray(row_size)
    min_x, min_y, max_x, max_y = width, height, -1, -1
    cursor = 0
    for y in range(height):
        filter_type = decoded[cursor]
        cursor += 1
        encoded = decoded[cursor : cursor + row_size]
        cursor += row_size
        row = bytearray(row_size)
        for index, value in enumerate(encoded):
            left = row[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                result = value
            elif filter_type == 1:
                result = value + left
            elif filter_type == 2:
                result = value + above
            elif filter_type == 3:
                result = value + ((left + above) // 2)
            elif filter_type == 4:
                estimate = left + above - upper_left
                pa = abs(estimate - left)
                pb = abs(estimate - above)
                pc = abs(estimate - upper_left)
                predictor = left if pa <= pb and pa <= pc else above if pb <= pc else upper_left
                result = value + predictor
            else:
                return None
            row[index] = result & 0xFF
        for x in range(width):
            pixel = row[x * channels : (x + 1) * channels]
            alpha = pixel[3] if channels == 4 else 255
            if alpha and any(channel for channel in pixel[:3]):
                min_x, max_x = min(min_x, x), max(max_x, x)
                min_y, max_y = min(min_y, y), max(max_y, y)
        previous = row
    if max_x < min_x or max_y < min_y:
        return None
    return {"x": min_x, "y": min_y, "w": max_x - min_x + 1, "h": max_y - min_y + 1}


def _read_map_size(path: Path) -> tuple[int, int] | None:
    if not path.is_file():
        return None
    raw = path.read_bytes()
    if len(raw) < MAPINFO_SIZE_OFFSET + 8 or raw[:4] != b"IpaM":
        return None
    width, height = struct.unpack_from("<II", raw, MAPINFO_SIZE_OFFSET)
    if width <= 0 or height <= 0 or width > 4096 or height > 4096:
        return None
    return width, height


def _read_terrain_dimension(path: Path) -> tuple[int, int] | None:
    root = ET.parse(path).getroot()
    height_map = root.find("heightMap")
    if height_map is None:
        return None
    values = (height_map.get("dim") or "").split()
    if len(values) < 2:
        return None
    try:
        width, height = int(values[0]), int(values[1])
    except ValueError:
        return None
    return (width, height) if width > 1 and height > 1 else None


def _source_id(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def _float_list(value: str | None) -> list[float] | None:
    if not value:
        return None
    try:
        return [float(item) for item in value.split(",")]
    except ValueError:
        return None


def parse_static_objects(objects_path: Path) -> list[dict[str, Any]]:
    root = ET.parse(objects_path).getroot()
    objects: list[dict[str, Any]] = []
    for index, unit in enumerate(root.iter("ObjectUnit"), start=1):
        position = unit.get("Position", "0,0,0").split(",")
        if len(position) < 2:
            continue
        try:
            x, y = float(position[0]), float(position[1])
            owner = int(unit.get("Player", "0"))
        except (ValueError, IndexError):
            continue
        object_id = _source_id(unit.get("Id"))
        stable_id = f"map-{object_id}" if object_id is not None else f"map-index-{index}"
        item: dict[str, Any] = {
            "id": stable_id,
            "source_object_id": object_id,
            "source_unit_type_id": unit.get("UnitType", ""),
            "unit_type_id": unit.get("UnitType", ""),
            "owner": owner,
            "x": x,
            "y": y,
            "source": "Objects",
        }
        rotation = _float_list(unit.get("Rotation"))
        scale = _float_list(unit.get("Scale"))
        if rotation:
            item["rotation"] = rotation[0] if len(rotation) == 1 else rotation
        if scale:
            item["scale"] = scale
        if unit.get("Variation") is not None:
            item["variation"] = unit.get("Variation")
        if unit.get("UserTag"):
            item["user_tag"] = unit.get("UserTag")
        objects.append(item)
    return objects


def read_map_geometry(map_source: Path) -> dict[str, Any]:
    minimap_path = map_source / "minimap.png"
    map_info_path = map_source / "MapInfo"
    terrain_path = map_source / "t3Terrain.xml"
    image_width, image_height, _ = _read_png_info(minimap_path)
    image_rect = _png_content_rect(minimap_path) or dict(DEFAULT_IMAGE_RECT)
    map_size = _read_map_size(map_info_path) or DEFAULT_MAP_SIZE
    terrain_dimension = _read_terrain_dimension(terrain_path)
    image_rect_width = min(image_rect["w"], map_size[0])
    image_rect_height = min(image_rect["h"], map_size[1])
    min_x = (map_size[0] - image_rect_width) / 2.0
    min_y = (map_size[1] - image_rect_height) / 2.0
    return {
        "map_size": {"width": map_size[0], "height": map_size[1]},
        "minimap_size": {"width": image_width, "height": image_height},
        "image_rect_px": image_rect,
        "world_bounds": {
            "min_x": min_x,
            "max_x": min_x + image_rect_width,
            "min_y": min_y,
            "max_y": min_y + image_rect_height,
        },
        "terrain_height_map_dim": list(terrain_dimension or (map_size[0] + 1, map_size[1] + 1)),
        "coordinate_system": "SC2 world coordinates; minimap y is inverted",
        "geometry_evidence": {
            "map_info": "MapInfo",
            "terrain": "t3Terrain.xml/heightMap@dim",
            "minimap": "minimap.png non-black content bounds",
        },
    }


def build_map_static_metadata(map_source: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    geometry = read_map_geometry(map_source)
    objects = parse_static_objects(map_source / "Objects")
    return geometry, objects


__all__ = ["build_map_static_metadata", "parse_static_objects", "read_map_geometry"]
