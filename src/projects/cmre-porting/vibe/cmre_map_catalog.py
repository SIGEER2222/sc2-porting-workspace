"""CMRE cooperative-map extraction and simulator adapter.

The map package is the source of truth for coordinates, regions, native
objects, and mission vocabulary.  This module keeps three layers explicit:

* ``native_objects``: every ObjectUnit parsed from the unpacked map;
* ``scenario``: a bounded simulator slice plus an explicit starting-force
  adapter for P1/P2, because most cooperative maps create commanders at
  runtime rather than storing them as ObjectUnits;
* ``objectives``: a map-specific tactical contract derived from MapScript and
  region names.  It is not a claim that the simulator implements the native
  mission trigger graph.

The resulting metadata is suitable for a batch tactical probe and for the
single-file replay player.  Runtime SC2 evidence remains a separate lane.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Iterable, Optional

from .map_extractor import MapData, MapExtractor


P1_PLAYER_ID = 1
P2_PLAYER_ID = 2
NEUTRAL_PLAYER_ID = 0
MAP_ROOT = Path(__file__).resolve().parents[1] / "packages" / "Maps"
START_MARKER_TYPES = {"ACHeroSpawnPlacement", "PlayerStartLocation", "StartLocation"}
RESOURCE_TYPES = {"MineralField", "VespeneGeyser", "RichMineralField", "MineralField750"}
RESOURCE_TYPE_MAP = {
    "SpacePlatformGeyser": "VespeneGeyser",
    "UmojanLabMineralField": "MineralField",
}
STRUCTURE_HINTS = {
    "CommandCenter", "Hatchery", "Nexus", "Barracks", "Factory", "Starport",
    "SpawningPool", "RoachWarren", "EvolutionChamber", "InfestationPit",
    "HydraliskDen", "BanelingNest", "Spire", "GreaterSpire", "Hive",
    "Lair", "Bunker", "Cannon", "Forge", "Pylon", "Gateway", "WarpGate",
    "CyberneticsCore", "TwilightCouncil", "TemplarArchive", "DarkShrine",
    "RoboticsFacility", "RoboticsBay", "Stargate", "FleetBeacon", "PhotonCannon",
    "ShieldBattery", "SpineCrawler", "SporeCrawler", "MissileTurret",
    "SensorTower", "GhostAcademy", "FusionCore", "Armory", "EngineeringBay",
    "BarracksTechLab", "BarracksReactor", "FactoryTechLab", "FactoryReactor",
    "StarportTechLab", "StarportReactor", "NydusNetwork", "UltraliskCavern",
    "VoidShard", "VoidThrasher",
    "SuppressionTower", "WarpConduit", "ProtossDockingBayUnit", "IndustrialShip",
}


@dataclass(frozen=True)
class ObjectiveSpec:
    """A simulator-facing objective contract, not a native victory claim."""

    objective_id: str
    label: str
    kind: str
    target_count: int
    tactic: str


@dataclass(frozen=True)
class MapProfile:
    """Map-specific mission vocabulary and tactical priorities."""

    map_name: str
    archetype: str
    features: tuple[str, ...]
    region_hints: tuple[str, ...]
    objectives: tuple[ObjectiveSpec, ...]


@dataclass(frozen=True)
class MapGeometry:
    leader_position: tuple[float, float]
    base_position: tuple[float, float]
    expansion_position: tuple[float, float]
    build_offsets: dict[str, tuple[float, float]]
    attack_points: tuple[tuple[float, float], ...]
    scout_route: tuple[tuple[float, float], ...]
    evidence: dict[str, str]


MAP_PROFILES: dict[str, MapProfile] = {
    "黑暗杀星": MapProfile(
        "黑暗杀星", "void_shard", ("void_shard", "escort", "drop_waves"),
        ("Void Shard Area", "Bonus Objective"),
        (
            ObjectiveSpec("primary_void_shards", "摧毁 5 个虚空裂片", "destroy", 5, "focus_fire_objectives"),
            ObjectiveSpec("bonus_escort", "护送额外目标", "escort", 1, "escort_and_defend"),
        ),
    ),
    "机会渺茫": MapProfile(
        "机会渺茫", "resource_harvest", ("terrazine", "escort", "rescue", "timed_waves"),
        ("Player01_Start", "Player02_Start", "Terrazine Node", "Player01_Expac"),
        (
            ObjectiveSpec("terrazine_nodes", "采集 14 个 Terrazine 节点", "collect", 14, "secure_nodes_before_wave"),
            ObjectiveSpec("rescue_stalkers", "营救被困单位", "rescue", 2, "scout_and_clear_route"),
            ObjectiveSpec("destroy_enemy_base", "摧毁敌方基地", "destroy", 1, "timed_attack_after_economy"),
        ),
    ),
    "净网行动": MapProfile(
        "净网行动", "escort_locks", ("escort", "lock_capture", "holdout", "harass_waves"),
        ("InitialExplored", "Lock1_Beacons", "Lock2_Beacons", "Lock3_Beacons", "Lock4_BeaconsTurnON"),
        (
            ObjectiveSpec("purifier_locks", "护送净化者并启动 4 个锁", "capture", 4, "escort_with_holdout_defense"),
            ObjectiveSpec("destroy_enemy_base", "摧毁敌方基地", "destroy", 2, "split_attack_after_locks"),
        ),
    ),
    "聚铁成兵": MapProfile(
        "聚铁成兵", "train_escort", ("train", "escort", "multi_base", "enemy_bases"),
        ("Reveal Players Base", "Left Expand", "Right Expand", "Left Enemy Base", "Right Enemy Base", "Train"),
        (
            ObjectiveSpec("trains", "护送并保护 2 列列车", "escort", 2, "clear_railway_and_guard_train"),
            ObjectiveSpec("enemy_bases", "清除左右两侧敌方基地", "destroy", 2, "split_army_and_focus"),
        ),
    ),
    "克哈裂痕": MapProfile(
        "克哈裂痕", "void_shards", ("void_shard", "multi_stage", "expansion"),
        ("Reveal Players Base", "Player Expansion", "Reveal First Shard", "DeactivateBullies"),
        (
            ObjectiveSpec("void_shards", "按阶段摧毁虚空裂片", "destroy", 4, "stage_push_and_regroup"),
            ObjectiveSpec("bonus_crates", "阻止奖励目标被夺走", "defend", 2, "scout_bonus_and_defend"),
        ),
    ),
    "熔火危机": MapProfile(
        "熔火危机", "resource_defense", ("solarite", "defend", "worker_hunt", "lava"),
        ("Initial Reveal", "Expansion Area", "Attack Wave Spawn Ownership", "Critter Haven"),
        (
            ObjectiveSpec("solarite", "收集 Solarite", "collect", 1, "mine_and_expand"),
            ObjectiveSpec("salamander", "击杀 Salamander", "destroy", 1, "focus_fire_bonus"),
            ObjectiveSpec("enemy_base", "摧毁敌方基地", "destroy", 1, "defend_then_counterattack"),
        ),
    ),
    "升格之链": MapProfile(
        "升格之链", "tug_of_war", ("escort", "tug_of_war", "hybrid", "attack_waves"),
        ("BaseReveal", "Death Beacon", "Tug Of War", "Final Base", "Trickle Base"),
        (
            ObjectiveSpec("jinara_push", "护送 Ji'nara 推进战线", "escort", 1, "formation_escort_and_regroup"),
            ObjectiveSpec("hybrid_waves", "击退混合体攻击波", "defend", 4, "hold_line_and_focus"),
            ObjectiveSpec("final_base", "摧毁最终基地", "destroy", 1, "final_concentrated_push"),
        ),
    ),
    "死亡摇篮": MapProfile(
        "死亡摇篮", "branching_targets", ("nuke_targets", "branching", "bonus_objectives", "defend"),
        ("Target Facility", "Expansion", "Bonus Objective"),
        (
            ObjectiveSpec("target_facilities", "摧毁 4 个目标设施", "destroy", 4, "branch_clear_and_focus"),
            ObjectiveSpec("bonus_objectives", "处理 2 个奖励目标", "destroy", 2, "optional_scout_branch"),
        ),
    ),
    "天界封锁": MapProfile(
        "天界封锁", "lock_capture", ("lock_capture", "mechanism", "holdout", "rescue"),
        ("Capture Region", "Mechanism", "Enemy Bases", "Player Base Area"),
        (
            ObjectiveSpec("mechanisms", "占领 5 个机制点", "capture", 5, "sequential_capture_with_defense"),
            ObjectiveSpec("enemy_bases", "清除敌方基地", "destroy", 1, "counterattack_after_capture"),
        ),
    ),
    "亡者之夜": MapProfile(
        "亡者之夜", "night_survival", ("night_cycle", "base_defense", "infested_waves"),
        ("Barricade", "Area Revealer", "Expansion Check", "Infested Region"),
        (
            ObjectiveSpec("survive_nights", "存活 6 个夜晚", "survive", 6, "day_macro_night_defense"),
            ObjectiveSpec("clear_infested", "清除感染区", "destroy", 1, "night_counterattack"),
        ),
    ),
    "往日神庙": MapProfile(
        "往日神庙", "thrasher_defense", ("void_thrasher", "defend", "persistent_waves"),
        ("Visibility Base", "Void Thrasher", "Attack Blocker", "Rebuild Bullies"),
        (
            ObjectiveSpec("void_thrashes", "摧毁虚空撕裂者", "destroy", 4, "scout_and_focus_thrasher"),
            ObjectiveSpec("base_survival", "保护基地并应对持续攻击", "survive", 1, "defend_then_push"),
        ),
    ),
    "虚空降临": MapProfile(
        "虚空降临", "shuttle_defense", ("shuttle", "warp_conduit", "escort", "timed_waves"),
        ("Reveal_Players Base", "WarpConduit", "Expansion", "Bonus Objective"),
        (
            ObjectiveSpec("shuttles", "拦截 7 波穿梭机", "destroy", 7, "split_intercept_routes"),
            ObjectiveSpec("warp_conduits", "保护传送枢纽", "defend", 2, "hold_conduit_defense"),
        ),
    ),
    "虚空撕裂": MapProfile(
        "虚空撕裂", "thrasher_defense", ("void_thrasher", "fortress_defense", "attack_waves"),
        ("Reveal_INT_PlayersBase", "Thrasher", "Expansion", "DeactivateBullies"),
        (
            ObjectiveSpec("void_thrashers", "摧毁虚空撕裂者", "destroy", 4, "focus_thrasher_and_retreat"),
            ObjectiveSpec("fortress", "保护主堡", "defend", 1, "base_defense_priority"),
        ),
    ),
    "湮灭快车": MapProfile(
        "湮灭快车", "train_escort", ("train", "escort", "outposts", "attack_waves"),
        ("Default Exploration", "Expansion", "Escort Peel", "Train Escape"),
        (
            ObjectiveSpec("trains", "护送 2 列列车到终点", "escort", 2, "clear_route_and_escort"),
            ObjectiveSpec("outposts", "夺取并利用沿线前哨", "capture", 3, "scout_outposts_before_push"),
        ),
    ),
    "营救矿工": MapProfile(
        "营救矿工", "colony_ship_rescue", ("colony_ship", "escort", "base_defense", "transport_waves"),
        ("Players Base", "ColonyShip", "ColonyShip Waves", "Zerg Base", "Bonus Objective"),
        (
            ObjectiveSpec("colony_ships", "护送/营救 9 艘殖民船", "escort", 9, "sequential_rescue_and_defend"),
            ObjectiveSpec("enemy_base", "摧毁异虫基地", "destroy", 1, "final_attack_after_rescue"),
        ),
    ),
}


def list_cmre_maps(maps_root: Optional[str | Path] = None) -> list[Path]:
    """Return every unpacked CMRE cooperative map in stable order."""

    root = Path(maps_root) if maps_root is not None else MAP_ROOT
    return sorted(root.glob("*.SC2Map"), key=lambda path: path.name)


def _map_hash(map_dir: Path) -> str:
    digest = hashlib.sha256()
    for name in ("Objects", "Regions", "MapInfo", "MapScript.galaxy"):
        path = map_dir / name
        if path.is_file():
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def _repo_relative(path: Path) -> str:
    repo_root = Path(__file__).resolve().parents[4]
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return path.name


def _script_text(map_dir: Path) -> str:
    path = map_dir / "MapScript.galaxy"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _script_features(script: str) -> list[str]:
    checks = (
        ("escort", r"escort|colonyship|transport"),
        ("destroy", r"destroy|kill|defeat"),
        ("defend", r"defend|holdout|survive|protect"),
        ("wave", r"wave|attackwave|spawn"),
        ("resource", r"mineral|vespene|solarite|terrazine"),
        ("objective", r"objective|leaderboard"),
        ("hybrid", r"hybrid"),
    )
    lowered = script.lower()
    return [name for name, pattern in checks if re.search(pattern, lowered)]


def _region_center(region: dict) -> tuple[float, float]:
    return float(region.get("x", 0.0)), float(region.get("y", 0.0))


def _find_region(regions: Iterable[dict], hints: Iterable[str]) -> Optional[dict]:
    lowered = [str(hint).lower() for hint in hints]
    candidates = []
    for region in regions:
        name = str(region.get("name", ""))
        name_lower = name.lower()
        for index, hint in enumerate(lowered):
            if hint in name_lower:
                candidates.append((index, len(name), region))
                break
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[0], item[1]))[2]


def _resource_clusters(native_objects: list[dict], distance: float = 10.0) -> list[dict]:
    points = [obj for obj in native_objects if obj.get("unit_type") in RESOURCE_TYPES]
    clusters: list[list[dict]] = []
    for point in points:
        chosen = None
        for cluster in clusters:
            if any(
                math.hypot(float(point["x"]) - float(item["x"]), float(point["y"]) - float(item["y"])) <= distance
                for item in cluster
            ):
                chosen = cluster
                break
        if chosen is None:
            clusters.append([point])
        else:
            chosen.append(point)
    result = []
    for cluster in clusters:
        minerals = sum(1 for item in cluster if item.get("unit_type") in {"MineralField", "RichMineralField", "MineralField750"})
        gas = sum(1 for item in cluster if item.get("unit_type") == "VespeneGeyser")
        result.append({
            "x": round(sum(float(item["x"]) for item in cluster) / len(cluster), 4),
            "y": round(sum(float(item["y"]) for item in cluster) / len(cluster), 4),
            "resource_count": len(cluster),
            "mineral_count": minerals,
            "vespene_count": gas,
        })
    return sorted(result, key=lambda item: (-item["resource_count"], item["x"], item["y"]))


def _position_for_player(data: MapData, profile: MapProfile, player_id: int) -> tuple[tuple[float, float], str]:
    markers = [
        obj for obj in data.native_objects
        if obj.get("unit_type") in START_MARKER_TYPES and int(obj.get("player", 0)) == player_id
    ]
    if markers:
        marker = markers[0]
        return (float(marker["x"]), float(marker["y"])), "static_object_marker"

    region = _find_region(data.regions, profile.region_hints)
    clusters = _resource_clusters(data.native_objects)
    if region is not None:
        rx, ry = _region_center(region)
        if clusters:
            cluster = min(clusters, key=lambda item: math.hypot(item["x"] - rx, item["y"] - ry))
            return (cluster["x"], cluster["y"]), f"inferred_nearest_resource_to_region:{region['name']}"
        return (rx, ry), f"inferred_region:{region['name']}"

    if clusters:
        cluster = clusters[0]
        return (cluster["x"], cluster["y"]), "inferred_largest_resource_cluster"

    bounds = data.map_bounds
    return (
        (float(bounds.get("min_x", 0.0) + bounds.get("max_x", 0.0)) / 2.0,
         float(bounds.get("min_y", 0.0) + bounds.get("max_y", 0.0)) / 2.0),
        "inferred_map_center",
    )


def _enemy_points(data: MapData) -> list[tuple[float, float]]:
    enemies = [
        obj for obj in data.native_objects
        if int(obj.get("player", 0)) not in {0, P1_PLAYER_ID, P2_PLAYER_ID}
        and obj.get("unit_type") not in {"ACHeroSpawnPlacement"}
    ]
    by_owner: dict[int, list[dict]] = {}
    for enemy in enemies:
        by_owner.setdefault(int(enemy.get("player", 0)), []).append(enemy)
    points = []
    for owner in sorted(by_owner):
        group = by_owner[owner]
        points.append((
            sum(float(item["x"]) for item in group) / len(group),
            sum(float(item["y"]) for item in group) / len(group),
        ))
    return points


def _safe_build_offsets(
    data: MapData,
    base: tuple[float, float],
    anchors: Iterable[tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    """Choose a deterministic open construction ring from map objects."""

    bounds = data.map_bounds
    min_x = float(bounds.get("min_x", 0.0))
    max_x = float(bounds.get("max_x", 2048.0))
    min_y = float(bounds.get("min_y", 0.0))
    max_y = float(bounds.get("max_y", 2048.0))
    # The bounded simulator intentionally omits native static structures from
    # the loaded tactical slice.  Only resources and start markers can block
    # an adapter building there; treating every extracted object as occupied
    # collapses dense maps to one repeated offset and guarantees later clashes.
    occupied = [
        (float(obj.get("x", 0.0)), float(obj.get("y", 0.0)))
        for obj in data.native_objects
        if (
            obj.get("unit_type") in RESOURCE_TYPES
            or obj.get("unit_type") in RESOURCE_TYPE_MAP
            or obj.get("unit_type") in START_MARKER_TYPES
        )
    ]
    occupied.extend((float(x), float(y)) for x, y in anchors)
    # The simulator reserves a resource footprint plus a no-build margin and
    # also treats every placed structure as a pathing obstacle.  A five-unit
    # point-radius check is therefore too optimistic for dense co-op starts.
    candidates = (
        (-12.0, -10.0), (12.0, -10.0), (-16.0, 0.0), (16.0, 0.0),
        (-12.0, 12.0), (12.0, 12.0), (-20.0, -14.0), (20.0, -14.0),
        (-20.0, 14.0), (20.0, 14.0), (0.0, -18.0), (0.0, 18.0),
        (-24.0, -6.0), (24.0, -6.0), (-24.0, 8.0), (24.0, 8.0),
        (-8.0, -22.0), (8.0, -22.0), (-8.0, 22.0), (8.0, 22.0),
        (-30.0, -12.0), (30.0, -12.0), (-30.0, 12.0), (30.0, 12.0),
        (-18.0, -24.0), (18.0, -24.0), (-18.0, 24.0), (18.0, 24.0),
        (-36.0, -18.0), (36.0, -18.0), (-36.0, 18.0), (36.0, 18.0),
    )
    selected: list[tuple[float, float]] = []
    for dx, dy in candidates:
        x, y = base[0] + dx, base[1] + dy
        if not (min_x + 3.0 <= x <= max_x - 3.0 and min_y + 3.0 <= y <= max_y - 3.0):
            continue
        if any(math.hypot(x - ox, y - oy) < 9.0 for ox, oy in occupied):
            continue
        if any(math.hypot(x - sx, y - sy) < 9.0 for sx, sy in selected):
            continue
        selected.append((x, y))
    if not selected:
        # Keep a deterministic fallback for very small maps.  The caller's
        # starting-force adapter is still annotated as inferred, so this is
        # not promoted to native placement evidence.
        selected = [(base[0] - 12.0, base[1] - 12.0)]
    names = ("SupplyDepot", "Barracks", "Factory", "EngineeringBay", "Starport", "Armory")
    result = {}
    for index, name in enumerate(names):
        x, y = selected[index % len(selected)]
        result[name] = (round(x - base[0], 4), round(y - base[1], 4))
    # Supply depots are the only planned structure repeated by the ladder
    # macro.  Give each repeat its own map-derived slot; reusing the primary
    # depot offset is valid on an empty sketch but collides with the first
    # completed depot on dense cooperative starts.
    for index in range(2, 6):
        # Slots after the six primary structures are reserved for repeated
        # depots.  They must not alias Barracks/Factory/tech positions.
        selected_index = len(names) + index - 2
        if selected_index >= len(selected):
            selected_index = len(selected) - 1
        x, y = selected[selected_index]
        result[f"SupplyDepot{index}"] = (
            round(x - base[0], 4), round(y - base[1], 4)
        )
    return result


def _safe_route_points(
    data: MapData,
    points: Iterable[tuple[float, float]],
    extra_occupied: Iterable[tuple[float, float]] = (),
) -> tuple[tuple[float, float], ...]:
    """Offset route waypoints away from static footprints and resources."""

    bounds = data.map_bounds
    min_x = float(bounds.get("min_x", 0.0))
    max_x = float(bounds.get("max_x", 2048.0))
    min_y = float(bounds.get("min_y", 0.0))
    max_y = float(bounds.get("max_y", 2048.0))
    occupied = [
        (float(obj.get("x", 0.0)), float(obj.get("y", 0.0)))
        for obj in data.native_objects
    ]
    occupied.extend((float(x), float(y)) for x, y in extra_occupied)
    offsets = (
        (0.0, 0.0), (-7.0, 7.0), (-7.0, -7.0),
        (7.0, 7.0), (7.0, -7.0), (0.0, 10.0), (10.0, 0.0),
    )
    safe = []
    for point in points:
        chosen = point
        for dx, dy in offsets:
            candidate = (point[0] + dx, point[1] + dy)
            if not (min_x + 1.0 <= candidate[0] <= max_x - 1.0 and min_y + 1.0 <= candidate[1] <= max_y - 1.0):
                continue
            if not any(math.hypot(candidate[0] - ox, candidate[1] - oy) < 7.0 for ox, oy in occupied):
                chosen = candidate
                break
        if not any(math.hypot(chosen[0] - old[0], chosen[1] - old[1]) < 2.0 for old in safe):
            safe.append((round(chosen[0], 4), round(chosen[1], 4)))
    return tuple(safe)


def derive_map_geometry(data: MapData, profile: MapProfile) -> MapGeometry:
    """Derive tactical points from markers, regions, resources, and enemies."""

    p1, p1_evidence = _position_for_player(data, profile, P1_PLAYER_ID)
    p2, p2_evidence = _position_for_player(data, profile, P2_PLAYER_ID)
    if p2 == p1:
        clusters = [
            cluster for cluster in _resource_clusters(data.native_objects)
            if math.hypot(cluster["x"] - p1[0], cluster["y"] - p1[1]) >= 20.0
        ]
        if clusters:
            # Prefer a substantial second resource pocket, then the closest
            # deterministic candidate.  Offset away from P1 so the synthetic
            # CommandCenter/Barracks footprints cannot overlap the leader.
            cluster = max(
                clusters,
                key=lambda item: (
                    int(item["resource_count"]),
                    -round(math.hypot(item["x"] - p1[0], item["y"] - p1[1]), 4),
                    -float(item["x"]),
                    -float(item["y"]),
                ),
            )
            dx = cluster["x"] - p1[0]
            dy = cluster["y"] - p1[1]
            distance = math.hypot(dx, dy) or 1.0
            p2 = (
                cluster["x"] + (dx / distance) * 6.0,
                cluster["y"] + (dy / distance) * 6.0,
            )
            p2_evidence = f"{p2_evidence};adapter_second_resource_cluster_offset"
        else:
            p2 = (p1[0] + 12.0, p1[1] - 12.0)
            p2_evidence = f"{p2_evidence};adapter_safe_offset_from_p1"

    clusters = _resource_clusters(data.native_objects)
    expansion_region = _find_region(data.regions, ("expansion", "expand", "expo"))
    if expansion_region is not None:
        expansion = _region_center(expansion_region)
        expansion_evidence = f"static_region:{expansion_region['name']}"
    else:
        candidates = [
            cluster for cluster in clusters
            if math.hypot(cluster["x"] - p2[0], cluster["y"] - p2[1]) > 18.0
        ]
        expansion_cluster = candidates[0] if candidates else None
        if expansion_cluster is not None:
            expansion = (expansion_cluster["x"], expansion_cluster["y"])
            expansion_evidence = "inferred_second_resource_cluster"
        else:
            expansion = (p2[0] + 18.0, p2[1])
            expansion_evidence = "inferred_base_offset"

    objective_points: list[tuple[float, float]] = []
    objective_region = _find_region(data.regions, profile.region_hints[1:])
    if objective_region is not None:
        objective_points.append(_region_center(objective_region))
    objective_points.extend(
        (float(region["x"]), float(region["y"]))
        for region in data.regions
        if any(token.lower() in str(region.get("name", "")).lower() for token in profile.region_hints)
    )
    objective_points.extend(_enemy_points(data))
    unique_points: list[tuple[float, float]] = []
    for point in objective_points:
        if not any(math.hypot(point[0] - other[0], point[1] - other[1]) < 3.0 for other in unique_points):
            unique_points.append(point)
    if not unique_points:
        unique_points = [(p2[0] + 12.0, p2[1]), expansion]
    unique_points = unique_points[:6]
    first_target = unique_points[0] if unique_points else expansion
    target_dx = first_target[0] - p2[0]
    target_dy = first_target[1] - p2[1]
    target_distance = math.hypot(target_dx, target_dy) or 1.0
    direction = (target_dx / target_distance, target_dy / target_distance)
    # Probe a real map-directed opening without asking the simulator's
    # incomplete pathing model to jump directly onto a distant mission point.
    away_x = p2[0] - p1[0]
    away_y = p2[1] - p1[1]
    away_distance = math.hypot(away_x, away_y) or 1.0
    away = (away_x / away_distance, away_y / away_distance)
    side = (-away[1], away[0])
    local_route = [
        (p2[0] + away[0] * 12.0, p2[1] + away[1] * 12.0),
        (p2[0] + side[0] * 12.0, p2[1] + side[1] * 12.0),
        (p2[0] - side[0] * 12.0, p2[1] - side[1] * 12.0),
        (p2[0] + direction[0] * min(14.0, target_distance),
         p2[1] + direction[1] * min(14.0, target_distance)),
    ]
    build_offsets = _safe_build_offsets(data, p2, (p1, p2))
    adapter_structures = (
        p1,
        p2,
        (p2[0] - 3.0, p2[1] - 3.0),
        (p2[0] + 3.0, p2[1] - 3.0),
        (p2[0] + 4.0, p2[1] + 2.0),
    )
    adapter_structures = (*adapter_structures, *(
        (p2[0] + float(offset[0]), p2[1] + float(offset[1]))
        for offset in build_offsets.values()
    ))
    scout_route = _safe_route_points(data, local_route, adapter_structures)
    if not scout_route:
        scout_route = ((round(p2[0] + 10.0, 4), round(p2[1], 4)),)
    attack_points = tuple(unique_points)
    return MapGeometry(
        leader_position=(round(p1[0], 4), round(p1[1], 4)),
        base_position=(round(p2[0], 4), round(p2[1], 4)),
        expansion_position=(round(expansion[0], 4), round(expansion[1], 4)),
        build_offsets=build_offsets,
        attack_points=tuple((round(x, 4), round(y, 4)) for x, y in attack_points),
        scout_route=tuple((round(x, 4), round(y, 4)) for x, y in scout_route),
        evidence={
            "p1_base": p1_evidence,
            "p2_base": p2_evidence,
            "expansion": expansion_evidence,
            "attack_points": "objective_regions_then_enemy_owner_centroids",
            "scout_route": "adapter_local_staging_toward_first_objective",
        },
    )


def _starter_units(player_id: int, center: tuple[float, float], *, leader: bool = False) -> list[dict]:
    """Create the smallest explicit runtime commander adapter force."""

    cx, cy = center
    units = [
        {"unit_type_id": "CommandCenter", "owner_player_id": player_id, "x": cx, "y": cy, "adapter_starting_force": True},
        {"unit_type_id": "Barracks", "owner_player_id": player_id, "x": cx - 3.0, "y": cy - 3.0, "adapter_starting_force": True},
        {"unit_type_id": "SupplyDepot", "owner_player_id": player_id, "x": cx + 3.0, "y": cy - 3.0, "adapter_starting_force": True},
        {"unit_type_id": "Refinery", "owner_player_id": player_id, "x": cx + 4.0, "y": cy + 2.0, "adapter_starting_force": True},
    ]
    for index in range(8 if not leader else 2):
        units.append({
            "unit_type_id": "SCV", "owner_player_id": player_id,
            "x": cx - 2.5 + (index % 4), "y": cy + 1.0 + (index // 4),
            "adapter_starting_force": True,
        })
    for index in range(6 if not leader else 2):
        units.append({
            "unit_type_id": "Marine", "owner_player_id": player_id,
            "x": cx - 1.5 + (index % 3), "y": cy + 4.0 + (index // 3),
            "adapter_starting_force": True,
        })
    if not leader:
        units.extend([
            {"unit_type_id": "Marauder", "owner_player_id": player_id, "x": cx - 2.0, "y": cy + 5.0, "adapter_starting_force": True},
            {"unit_type_id": "SiegeTank", "owner_player_id": player_id, "x": cx + 2.0, "y": cy + 5.0, "adapter_starting_force": True},
        ])
    return units


def _sample_native_spawns(data: MapData, max_per_enemy: int) -> list[dict]:
    native = []
    resources = []
    seen_resource_keys: set[tuple[int, str, float, float]] = set()
    for obj in data.native_objects:
        if int(obj.get("player", 0)) != NEUTRAL_PLAYER_ID:
            continue
        source_type = str(obj.get("unit_type", ""))
        unit_type_id = source_type
        if unit_type_id not in RESOURCE_TYPES:
            unit_type_id = RESOURCE_TYPE_MAP.get(unit_type_id, "")
            if not unit_type_id:
                lowered = source_type.lower()
                if "mineralfield" in lowered:
                    unit_type_id = "MineralField"
                elif "geyser" in lowered:
                    unit_type_id = "VespeneGeyser"
        if unit_type_id not in {"MineralField", "VespeneGeyser"}:
            continue
        key = (
            int(obj.get("object_id") or 0),
            unit_type_id,
            float(obj.get("x", 0.0)),
            float(obj.get("y", 0.0)),
        )
        if key in seen_resource_keys:
            continue
        seen_resource_keys.add(key)
        resources.append({
            "unit_type_id": unit_type_id,
            "owner_player_id": NEUTRAL_PLAYER_ID,
            "x": float(obj.get("x", 0.0)),
            "y": float(obj.get("y", 0.0)),
            "resource_amount": obj.get("resource_amount"),
            "source_object_id": obj.get("object_id"),
            "source_unit_type_id": source_type,
            "adapter_resource_normalization": source_type != unit_type_id,
        })
    native.extend(resources)
    by_owner: dict[int, list[dict]] = {}
    for spawn in data.scenario.get("spawns", []):
        owner = int(spawn.get("owner_player_id", 0))
        if owner not in {NEUTRAL_PLAYER_ID, P1_PLAYER_ID, P2_PLAYER_ID}:
            by_owner.setdefault(owner, []).append(spawn)
    for owner in sorted(by_owner):
        group = by_owner[owner]
        # Structures are retained in ``static_objects`` for the replay layer,
        # but they are not placed in the bounded tactical slice: the reference
        # simulator treats every structure as a hard path obstacle, while the
        # unpacked map's terrain/pathing is not imported yet.
        mobile = [
            item for item in group
            if str(item.get("unit_type_id", "")) not in STRUCTURE_HINTS
            and not str(item.get("unit_type_id", "")).lower().endswith(("base", "facility"))
        ]
        selected = mobile or group
        selected.sort(key=lambda item: int(item.get("source_object_id") or 0))
        native.extend(selected[:max_per_enemy])
    return [dict(spawn) for spawn in native]


def _static_objects(data: MapData) -> list[dict]:
    return [
        {
            "id": obj.get("object_id"),
            "t": obj.get("unit_type"),
            "p": int(obj.get("player", 0)),
            "x": float(obj.get("x", 0.0)),
            "y": float(obj.get("y", 0.0)),
            "resource_amount": obj.get("resource_amount"),
        }
        for obj in data.native_objects
    ]


def build_cooperative_map_scenario(
    map_dir: str | Path,
    *,
    seed: int = 42,
    max_enemy_per_player: int = 16,
    max_loops: int = 320,
    initial_minerals: int = 1600,
    initial_vespene: int = 500,
    stage_enemies_for_full_game: bool = False,
) -> tuple[MapData, MapProfile, MapGeometry]:
    """Build a map-derived cooperative simulator scenario.

    Full-game adapter runs stage the sampled hostile cohort at the first
    map-derived scout entry. The unpacked map's terrain/pathing is not loaded
    into the reference simulator, so this keeps the bounded task reachable
    while preserving the map profile, source hash, and objective geometry.
    """

    path = Path(map_dir)
    data = MapExtractor(path).extract_all()
    profile = MAP_PROFILES.get(
        data.scenario["name"],
        MapProfile(
            data.scenario["name"], "generic", tuple(_script_features(_script_text(path))),
            ("base", "start", "expansion", "objective"),
            (ObjectiveSpec("enemy_clearance", "清除代表性敌方目标", "destroy", 1, "scout_attack_cleanup"),),
        ),
    )
    geometry = derive_map_geometry(data, profile)
    enemy_ids = sorted({
        int(spawn["owner_player_id"])
        for spawn in data.scenario.get("spawns", [])
        if int(spawn.get("owner_player_id", 0)) not in {0, 1, 2}
    })
    spawns = _sample_native_spawns(data, max_enemy_per_player)
    enemy_normalizations = []
    if stage_enemies_for_full_game:
        # The bounded M7 catalog does not model every CMRE unit/structure
        # matchup. Keep the native source type in metadata, but use one
        # stable low-tier hostile for the cross-map clearance contract.
        for spawn in spawns:
            if int(spawn.get("owner_player_id", 0)) in {0, 1, 2}:
                continue
            source_type = str(spawn.get("unit_type_id", ""))
            if source_type == "Zergling":
                continue
            spawn["source_unit_type_id"] = source_type
            spawn["unit_type_id"] = "Zergling"
            spawn["adapter_enemy_normalization"] = True
            enemy_normalizations.append(source_type)
    # The first six points are mission/objective-derived. Append one centroid
    # per sampled enemy owner so a full simulator run can discover every
    # represented hostile cohort without reading hidden world state.
    enemy_centers = []
    for owner in sorted({
        int(spawn["owner_player_id"])
        for spawn in spawns
        if int(spawn.get("owner_player_id", 0)) not in {0, 1, 2}
    }):
        owned = [
            spawn for spawn in spawns
            if int(spawn.get("owner_player_id", 0)) == owner
        ]
        if owned:
            enemy_centers.append((
                round(sum(float(spawn["x"]) for spawn in owned) / len(owned), 4),
                round(sum(float(spawn["y"]) for spawn in owned) / len(owned), 4),
            ))
    attack_points = list(geometry.attack_points)
    for point in enemy_centers:
        if not any(
            math.hypot(point[0] - existing[0], point[1] - existing[1]) < 3.0
            for existing in attack_points
        ):
            attack_points.append(point)
    geometry = replace(geometry, attack_points=tuple(attack_points))
    simulator_expansion_point = None
    if stage_enemies_for_full_game:
        resource_points = [
            (float(obj.get("x", 0.0)), float(obj.get("y", 0.0)))
            for obj in data.native_objects
            if int(obj.get("player", 0)) == NEUTRAL_PLAYER_ID
            and any(
                token in str(obj.get("unit_type", ""))
                for token in ("Mineral", "Geyser")
            )
        ]
        bounds = data.map_bounds
        candidates = []
        for dx in range(-60, 61, 12):
            for dy in range(-60, 61, 12):
                candidate = (
                    geometry.expansion_position[0] + float(dx),
                    geometry.expansion_position[1] + float(dy),
                )
                if (
                    candidate[0] < float(bounds["min_x"]) + 6.0
                    or candidate[1] < float(bounds["min_y"]) + 6.0
                    or candidate[0] > float(bounds["max_x"]) - 6.0
                    or candidate[1] > float(bounds["max_y"]) - 6.0
                ):
                    continue
                clearance = min(
                    [
                        math.hypot(candidate[0] - x, candidate[1] - y)
                        for x, y in resource_points
                    ]
                    + [
                        math.hypot(candidate[0] - geometry.base_position[0], candidate[1] - geometry.base_position[1]),
                        math.hypot(candidate[0] - geometry.leader_position[0], candidate[1] - geometry.leader_position[1]),
                    ]
                )
                candidates.append((clearance, candidate))
        if candidates:
            simulator_expansion_point = max(candidates, key=lambda item: item[0])[1]
    enemy_staging_point = None
    enemy_staging_route_index = None
    if stage_enemies_for_full_game:
        # The first scout entry is the stable handoff point for the bounded
        # simulator. Source-order spreading keeps a large unit from spawning
        # directly on top of the base while preserving deterministic contact.
        bounds = data.map_bounds
        min_x = float(bounds["min_x"]) + 1.0
        max_x = float(bounds["max_x"]) - 1.0
        min_y = float(bounds["min_y"]) + 1.0
        max_y = float(bounds["max_y"]) - 1.0
        raw_staging_point = geometry.scout_route[0]
        enemy_staging_point = (
            min(max(float(raw_staging_point[0]), min_x), max_x),
            min(max(float(raw_staging_point[1]), min_y), max_y),
        )
        enemy_staging_route_index = 0
        hostile_index = 0
        for spawn in spawns:
            if int(spawn.get("owner_player_id", 0)) in {0, 1, 2}:
                continue
            # Keep sampled hostile order in the placement so the same map
            # hash always produces the same bounded approach pattern.
            spawn["x"] = round(
                min(max(enemy_staging_point[0] + (hostile_index % 4) * 2.0, min_x), max_x),
                4,
            )
            spawn["y"] = round(
                min(max(enemy_staging_point[1] + (hostile_index // 4) * 2.0, min_y), max_y),
                4,
            )
            hostile_index += 1
    spawns.extend(_starter_units(P1_PLAYER_ID, geometry.leader_position, leader=True))
    spawns.extend(_starter_units(P2_PLAYER_ID, geometry.base_position))
    players = [
        {"id": 1, "name": "Player", "race": "terran", "allies": [2], "is_ai": False, "relation": "leader"},
        {"id": 2, "name": "AI Ally", "race": "terran", "allies": [1], "is_ai": True, "relation": "ally"},
        *[
            {"id": pid, "name": f"Map Enemy P{pid}", "race": "zerg", "allies": [], "is_ai": True, "relation": "enemy"}
            for pid in enemy_ids
        ],
        {"id": 0, "name": "Neutral", "race": "neutral", "allies": [], "is_ai": True, "relation": "neutral"},
    ]
    adapter_starting_force_count = sum(1 for spawn in spawns if spawn.get("adapter_starting_force"))
    adapter_resource_normalizations = sorted({
        str(spawn.get("source_unit_type_id"))
        for spawn in spawns
        if spawn.get("adapter_resource_normalization")
    })
    simulator_enemy_normalizations = sorted(set(enemy_normalizations))
    simulator_transformation_audit = {
        "source_static": {
            "map_path": _repo_relative(path),
            "map_hash": _map_hash(path),
            "native_object_count": len(data.native_objects),
            "native_spawn_count": len(data.scenario.get("spawns", [])),
        },
        "map_derived": {
            "geometry_evidence": asdict(geometry).get("evidence", {}),
            "objective_count": len(profile.objectives),
            "placement_marker_count": len([
                obj for obj in data.native_objects if obj.get("unit_type") in START_MARKER_TYPES
            ]),
        },
        "adapter_transforms": {
            "starting_force_injected": adapter_starting_force_count,
            "resource_normalized_from": adapter_resource_normalizations,
            "enemy_normalized_from": simulator_enemy_normalizations,
            "expansion_position_injected": simulator_expansion_point is not None,
        },
        "simulator_only": {
            "native_starting_force_injected": False,
            "adapter_starting_force": "simulator_only_runtime_overlay",
            "enemy_staged_for_full_game": bool(stage_enemies_for_full_game),
            "enemy_staging_point": list(enemy_staging_point) if enemy_staging_point else None,
        },
        "claim": "deterministic simulator adapter clearance only; no native SC2 mission completion",
    }
    static_metadata = {
        "source_kind": "cmre_map_catalog",
        "map_name": data.scenario["name"],
        "map_path": _repo_relative(path),
        "minimap_path": _repo_relative(path / "Minimap.tga") if (path / "Minimap.tga").is_file() else None,
        "map_hash": _map_hash(path),
        "map_bounds": dict(data.map_bounds),
        "native_object_count": len(data.native_objects),
        "native_spawn_count": len(data.scenario.get("spawns", [])),
        "native_spawn_counts_by_owner": {
            str(owner): sum(1 for spawn in data.scenario.get("spawns", []) if int(spawn.get("owner_player_id", 0)) == owner)
            for owner in sorted({int(spawn.get("owner_player_id", 0)) for spawn in data.scenario.get("spawns", [])})
        },
        "adapter_resource_normalizations": adapter_resource_normalizations,
        "placement_markers": [
            {"unit_type_id": obj.get("unit_type"), "owner_player_id": int(obj.get("player", 0)), "x": obj.get("x"), "y": obj.get("y"), "source_object_id": obj.get("object_id")}
            for obj in data.native_objects if obj.get("unit_type") in START_MARKER_TYPES
        ],
        "static_objects": _static_objects(data),
        "objective_profile": {
            "archetype": profile.archetype,
            "features": list(profile.features),
            "objectives": [asdict(objective) for objective in profile.objectives],
        },
        "geometry": asdict(geometry),
        "script_features": _script_features(_script_text(path)),
        "native_starting_force_injected": False,
        "adapter_starting_force": "simulator_only_runtime_overlay",
        "simulator_enemy_staging": {
            "enabled": bool(stage_enemies_for_full_game),
            "point": list(enemy_staging_point) if enemy_staging_point else None,
            "source": (
                f"map_geometry.scout_route[{enemy_staging_route_index}]"
                if enemy_staging_point else None
            ),
            "route_index": enemy_staging_route_index,
            "native_positions_retained": not bool(stage_enemies_for_full_game),
        },
        "simulator_enemy_normalizations": simulator_enemy_normalizations,
        "simulator_expansion_position": (
            list(simulator_expansion_point) if simulator_expansion_point else None
        ),
        "simulator_transformation_audit": simulator_transformation_audit,
        "evidence_classification": {"native_objects": "static", "geometry_markers": "static_or_inferred", "tactical_run": "simulator"},
    }
    data.scenario = {
        "schema_version": "m7",
        "name": f"cmre-map-{data.scenario['name']}-tactical-probe",
        "map_name": data.scenario["name"],
        "players": players,
        "spawns": spawns,
        "commands": [],
        "max_loops": max(1, int(max_loops)),
        "seed": int(seed),
        "initial_minerals": max(0, int(initial_minerals)),
        "initial_vespene": max(0, int(initial_vespene)),
        "strict": False,
        "win_condition": "enemy_elimination",
        "win_condition_params": {"enemy_player_ids": enemy_ids, "winner_player_id": 1},
        "_map_metadata": static_metadata,
        "_map_regions": data.regions,
        "_map_objectives": [asdict(objective) for objective in profile.objectives],
        "_map_geometry": asdict(geometry),
        "_map_source_kind": "cmre_map_catalog",
        "_map_native_starting_force": False,
        "_simulator_attack_points": (
            [
                *([list(enemy_staging_point)] if enemy_staging_point else []),
                *[list(point) for point in geometry.attack_points],
            ]
            if stage_enemies_for_full_game
            else None
        ),
        "_cooperative_enemy_player_ids": enemy_ids,
        "_simulator_expansion_position": (
            list(simulator_expansion_point) if simulator_expansion_point else None
        ),
    }
    return data, profile, geometry


def extract_all_cooperative_maps(maps_root: Optional[str | Path] = None) -> list[dict]:
    """Extract a compact, JSON-serializable inventory for every CMRE map."""

    records = []
    for map_dir in list_cmre_maps(maps_root):
        data, profile, geometry = build_cooperative_map_scenario(map_dir, max_enemy_per_player=1)
        metadata = data.scenario["_map_metadata"]
        records.append({
            "map_name": metadata["map_name"],
            "map_path": metadata["map_path"],
            "map_hash": metadata["map_hash"],
            "native_object_count": metadata["native_object_count"],
            "native_spawn_count": metadata["native_spawn_count"],
            "native_spawn_counts_by_owner": metadata["native_spawn_counts_by_owner"],
            "extraction": {
                "mapped": data.stats.units_mapped,
                "unsupported": data.stats.units_unsupported,
                "skipped": data.stats.units_skipped,
                "regions": len(data.regions),
                "bounds": data.map_bounds,
            },
            "script_features": metadata["script_features"],
            "profile": metadata["objective_profile"],
            "geometry": asdict(geometry),
            "placement_markers": metadata["placement_markers"],
            "enemy_player_ids": sorted(metadata["native_spawn_counts_by_owner"].keys()),
        })
    for record in records:
        record["enemy_player_ids"] = [
            int(pid) for pid in record["enemy_player_ids"] if int(pid) not in {0, 1, 2}
        ]
    return records


def write_map_inventory(output_path: str | Path, maps_root: Optional[str | Path] = None) -> dict:
    """Write the full extraction inventory and return its summary."""

    records = extract_all_cooperative_maps(maps_root)
    payload = {
        "schema_version": "cmre-map-catalog.v1",
        "evidence_type": "static",
        "runtime_claim": "none; native map extraction and inferred adapter geometry only",
        "map_count": len(records),
        "maps": records,
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


__all__ = [
    "MAP_PROFILES",
    "MAP_ROOT",
    "MapGeometry",
    "MapProfile",
    "ObjectiveSpec",
    "build_cooperative_map_scenario",
    "derive_map_geometry",
    "extract_all_cooperative_maps",
    "list_cmre_maps",
    "write_map_inventory",
]
