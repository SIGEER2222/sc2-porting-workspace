"""SC2 地图数据提取器：从 .SC2Map 目录提取数据，生成模拟器 scenario_dict。

支持：
- 解析 Objects XML → spawns（单位/建筑位置）
- 解析 Regions XML → regions（区域定义）
- 从 Objects 坐标范围推断地图大小
- 单位类型映射（地图特殊单位 → m7 支持单位）
- 波次时机生成（基于 MapScript.galaxy 的昼夜时长）

亡者之夜关键参数（从 MapScript.galaxy 第 2533-2535 行提取）：
- gv_day_Duration_First = 210（第一天天数时长，秒）
- gv_day_Duration = 240/240/210/210（普通天，按难度，秒）
- gv_night_Duration = 240.0（夜晚时长，秒）
- SC2 帧率 22.4 loops/sec → 210s ≈ 4704 loops, 240s ≈ 5376 loops

地图玩家结构（从 MapScript.galaxy 第 32-40 行）：
- Player 1: USER（玩家1）
- Player 2: USER（玩家2）
- Player 3: AMONS_FORCES（埃蒙部队-敌方主力）
- Player 4: AMONS_FORCES（埃蒙部队-敌方主力）
- Player 5: INFESTED（感染物-中立敌方）
- Player 6: SCIENCE_FACILITY
- Player 7: SPECIAL_INFESTED
- Player 8: HOSTILEROCKS
- Player 9: NEUTRALROCKS
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# SC2 帧率（loops per second）
LOOPS_PER_SECOND = 22.4

# m7_catalog 支持的 103 个单位（从 m7_units.py 提取）
SUPPORTED_UNITS = {
    "Adept",
    "Archon",
    "Armory",
    "Baneling",
    "BanelingNest",
    "Banshee",
    "Barracks",
    "BarracksReactor",
    "BarracksTechLab",
    "Battlecruiser",
    "BroodLord",
    "Broodling",
    "Bunker",
    "Carrier",
    "Colossus",
    "CommandCenter",
    "Corruptor",
    "CyberneticsCore",
    "Cyclone",
    "DarkShrine",
    "DarkTemplar",
    "Disruptor",
    "Drone",
    "EngineeringBay",
    "EvolutionChamber",
    "Extractor",
    "Factory",
    "FactoryReactor",
    "FactoryTechLab",
    "FleetBeacon",
    "Forge",
    "FusionCore",
    "Gateway",
    "Ghost",
    "GhostAcademy",
    "GreaterSpire",
    "Hatchery",
    "Hellbat",
    "Hellion",
    "HighTemplar",
    "Hive",
    "Hydralisk",
    "HydraliskDen",
    "Immortal",
    "InfestationPit",
    "Infestor",
    "Lair",
    "Larva",
    "Locust",
    "Marauder",
    "Marine",
    "Medivac",
    "MineralField",
    "MissileTurret",
    "Mutalisk",
    "Nexus",
    "NydusNetwork",
    "Observer",
    "Oracle",
    "Overlord",
    "Phoenix",
    "PhotonCannon",
    "Probe",
    "Pylon",
    "Queen",
    "Raven",
    "Reaper",
    "Refinery",
    "Roach",
    "RoachWarren",
    "RoboticsBay",
    "RoboticsFacility",
    "SCV",
    "SensorTower",
    "Sentry",
    "ShieldBattery",
    "SiegeTank",
    "SpawningPool",
    "SpineCrawler",
    "Spire",
    "SporeCrawler",
    "Stalker",
    "Stargate",
    "Starport",
    "StarportReactor",
    "StarportTechLab",
    "SupplyDepot",
    "SwarmHost",
    "Tempest",
    "TemplarArchive",
    "Thor",
    "TwilightCouncil",
    "Ultralisk",
    "UltraliskCavern",
    "VespeneGeyser",
    "Viking",
    "Viper",
    "VoidRay",
    "WarpGate",
    "WarpPrism",
    "WidowMine",
    "Zealot",
    "Zergling",
}

# 单位类型映射（地图特殊单位 → m7 支持单位）
# 亡者之夜有很多特殊单位（感染物、混合体、雇佣兵），需映射到 m7 支持的最近单位
UNIT_TYPE_MAP = {
    # 空军变形状态
    "VikingFighter": "Viking",
    "VikingAssault": "Viking",
    # Lurker 系列（m7 无 Lurker，映射到 Roach 作为地面远程）
    "LurkerMPBurrowed": "Roach",
    "LurkerMP": "Roach",
    # SwarmHost 变体
    "SwarmHostMP": "SwarmHost",
    # 雇佣兵（m7 不支持，映射到近似单位）
    "Goliath": "Viking",  # 步行机械对空对地
    "DevilDog": "Marauder",  # 雇佣兵劫掠者
    "Kraith": "Stalker",  # 雇佣兵追猎者
    "HellionTank": "Hellbat",  # 地狱火战车形态
    "DukesReaper": "Reaper",  # 雇佣兵收割者
    "SpartanCompany": "Marauder",
    "HammerSecurities": "Marauder",
    "CerbrosSecurities": "Marauder",
    # 混合体（m7 不支持，映射到强力单位）
    "HybridDestroyer": "Ultralisk",
    "HybridReaver": "Ultralisk",
    "HybridDominator": "Infestor",
    # 感染物（m7 不支持，映射到基础单位）
    "InfestedCivilian": "Marine",
    "InfestedTerranCampaign": "Marine",
    "InfestedAbomination": "Roach",
    "InfestedCocoon": "Bunker",  # 茧是静止的，映射到建筑
    "InfestedMaw": "SpineCrawler",
    # 感染建筑（目标建筑，映射到可破坏建筑）
    "JarbanInfestibleColonistHut": "Bunker",
    "InfestableBiodome": "Bunker",
    # 医疗兵（m7 无 Medic，映射到 Marine 作为步辅）
    "Medic": "Marine",
    "Medivac": "Medivac",  # 已支持，留作冗余映射
    # 其他
    "CreepTumorUsed": "SpineCrawler",
    "CreepTumor": "SpineCrawler",
    "Overseer": "Overlord",  # m7 无 Overseer，映射到 Overlord
    "OverseerSiegeMode": "Overlord",
    "BroodLordEscort": "BroodLord",
    # 资源/中立建筑
    "SpacePlatformGeyser": "VespeneGeyser",
    "InfestedMercHaven": "Barracks",
    "InfestableHut": "Bunker",
    "InfestableBiodome": "Bunker",
    # 英雄放置点（不提取，由 add_player_starting_units 处理）
    # "ACHeroSpawnPlacement" 不在映射表，会被跳过
}

# 跳过的装饰物/无关单位（不参与战斗）
SKIP_UNITS = {
    "DestructibleCityDebris6x6",
    "DestructibleCityDebris4x4",
    "DestructibleCityDebris2x2",
    "DestructibleRock6x6",
    "DestructibleRockEx1Large",
    "DestructibleRockEx2",
    "DestructibleSign",
    "DestructibleBillboard",
    "DestructibleGate",
    "DestructibleWall",
    "CollapsibleRockTower",
    "CollapsibleMetalGate",
    "SpacePlatformGutter",
    "YuanshenDiscordBlocker",  # 假设的装饰物
    "ClearBlocker",
    "WoodenFence",
}

# 玩家阵营定义（从 MapScript.galaxy 第 32-40 行）
PLAYER_FACTIONS = {
    1: {"name": "User1", "team": "user", "race": "terran"},
    2: {"name": "User2", "team": "user", "race": "terran"},
    3: {"name": "AmonsForces1", "team": "enemy", "race": "terran"},
    4: {"name": "AmonsForces2", "team": "enemy", "race": "zerg"},
    5: {"name": "Infested", "team": "enemy", "race": "zerg"},
    6: {"name": "ScienceFacility", "team": "neutral", "race": "terran"},
    7: {"name": "SpecialInfested", "team": "enemy", "race": "zerg"},
    8: {"name": "HostileRocks", "team": "neutral", "race": "neutral"},
    9: {"name": "NeutralRocks", "team": "neutral", "race": "neutral"},
}


@dataclass
class ExtractionStats:
    """提取统计信息。"""

    total_objects: int = 0
    units_extracted: int = 0
    units_mapped: int = 0
    units_skipped: int = 0
    units_unsupported: int = 0
    unit_type_counter: Counter = field(default_factory=Counter)
    mapped_counter: Counter = field(default_factory=Counter)
    skipped_counter: Counter = field(default_factory=Counter)
    unsupported_counter: Counter = field(default_factory=Counter)
    player_counter: Counter = field(default_factory=Counter)
    map_bounds: dict = field(default_factory=dict)


@dataclass
class MapData:
    """提取的地图数据。"""

    scenario: dict
    regions: list[dict]
    stats: ExtractionStats
    map_bounds: dict
    wave_timing: dict
    native_objects: list[dict] = field(default_factory=list)


class MapExtractor:
    """SC2 地图数据提取器。

    用法：
        ex = MapExtractor(map_dir)
        data = ex.extract_all()
        # data.scenario 可直接传给 SimulatorSession.scenario_load
        # data.regions 可传给 MissionEngine.add_region
    """

    def __init__(self, map_dir: str | Path):
        self.map_dir = Path(map_dir)
        self.stats = ExtractionStats()

    def extract_all(self) -> MapData:
        """提取完整地图数据。"""
        objects = self._parse_objects()
        regions = self._parse_regions()
        map_bounds = self._compute_map_bounds(objects)
        wave_timing = self._compute_wave_timing()

        # 构造 scenario_dict
        spawns = []
        for obj in objects:
            unit_type = obj["unit_type"]
            player = obj["player"]
            # 跳过装饰物
            if unit_type in SKIP_UNITS:
                self.stats.units_skipped += 1
                self.stats.skipped_counter[unit_type] += 1
                continue
            # 映射单位类型
            original = unit_type
            if unit_type not in SUPPORTED_UNITS:
                if unit_type in UNIT_TYPE_MAP:
                    unit_type = UNIT_TYPE_MAP[unit_type]
                    self.stats.units_mapped += 1
                    self.stats.mapped_counter[original] += 1
                else:
                    self.stats.units_unsupported += 1
                    self.stats.unsupported_counter[original] += 1
                    continue
            # 跳过中立装饰玩家（Player 8/9 是岩石）
            if player in (8, 9):
                self.stats.units_skipped += 1
                self.stats.skipped_counter[f"{original}(P{player})"] += 1
                continue
            spawns.append(
                {
                    "unit_type_id": unit_type,
                    "owner_player_id": player,
                    "x": obj["x"],
                    "y": obj["y"],
                    # These fields are ignored by the simulator loader but keep
                    # the replay/audit tied to the source ObjectUnit.
                    "source_object_id": obj.get("object_id"),
                    "source_unit_type_id": original,
                    "resource_amount": obj.get("resource_amount"),
                }
            )
            self.stats.units_extracted += 1
            self.stats.unit_type_counter[unit_type] += 1
            self.stats.player_counter[player] += 1

        # 构造 players 列表（基于 PLAYER_FACTIONS，只保留有单位的玩家）
        active_players = {s["owner_player_id"] for s in spawns}
        players = []
        for pid in sorted(active_players):
            if pid in PLAYER_FACTIONS:
                f = PLAYER_FACTIONS[pid]
            else:
                f = {"name": f"Player{pid}", "team": "neutral", "race": "neutral"}
            players.append(
                {
                    "id": pid,
                    "name": f["name"],
                    "race": f["race"],
                    "allies": [],
                    "is_ai": True,
                }
            )

        scenario = {
            "schema_version": "m7",
            "name": self.map_dir.name.replace(".SC2Map", ""),
            "players": players,
            "spawns": spawns,
            "commands": [],
            "max_loops": 30000,  # 约 22 分钟模拟时间
            "seed": 42,
            "strict": False,  # 亡者之夜有大量特殊单位，关闭 strict 避免拒绝
            "win_condition": "custom",
        }

        self.stats.total_objects = len(objects)
        self.stats.map_bounds = map_bounds

        return MapData(
            scenario=scenario,
            regions=regions,
            stats=self.stats,
            map_bounds=map_bounds,
            wave_timing=wave_timing,
            native_objects=objects,
        )

    def _parse_objects(self) -> list[dict]:
        """解析 Objects XML，提取所有 ObjectUnit。"""
        objects_path = self.map_dir / "Objects"
        if not objects_path.exists():
            raise FileNotFoundError(f"Objects 文件不存在: {objects_path}")
        tree = ET.parse(objects_path)
        root = tree.getroot()
        results = []
        for u in root.iter("ObjectUnit"):
            object_id = u.get("Id", "")
            try:
                object_id_value = int(object_id)
            except ValueError:
                object_id_value = None
            unit_type = u.get("UnitType", "")
            player_str = u.get("Player", "")
            pos = u.get("Position", "0,0,0")
            try:
                player = int(player_str)
            except ValueError:
                player = 0
            try:
                parts = pos.split(",")
                x = float(parts[0])
                y = float(parts[1])
            except (ValueError, IndexError):
                continue
            resource_amount = u.get("Resources")
            try:
                resource_amount_value = int(resource_amount) if resource_amount is not None else None
            except ValueError:
                resource_amount_value = None
            results.append(
                {
                    "object_id": object_id_value,
                    "unit_type": unit_type,
                    "player": player,
                    "x": x,
                    "y": y,
                    "resource_amount": resource_amount_value,
                }
            )
        return results

    def _parse_regions(self) -> list[dict]:
        """解析 Regions XML，提取所有区域。"""
        regions_path = self.map_dir / "Regions"
        if not regions_path.exists():
            return []
        tree = ET.parse(regions_path)
        root = tree.getroot()
        results = []
        for r in root.iter("region"):
            name_elem = r.find("name")
            name = (
                name_elem.get("value", f"region_{r.get('id', 'unknown')}")
                if name_elem is not None
                else f"region_{r.get('id', 'unknown')}"
            )
            # 解析所有 shape（circle/box）
            shapes = []
            for shape in r.findall("shape"):
                shape_type = shape.get("type", "")
                if shape_type == "circle":
                    center = shape.find("center")
                    radius = shape.find("radius")
                    if center is not None and radius is not None:
                        cx, cy = center.get("value", "0,0").split(",")
                        shapes.append(
                            {
                                "type": "circle",
                                "x": float(cx.strip()),
                                "y": float(cy.strip()),
                                "r": float(radius.get("value", "0")),
                            }
                        )
                elif shape_type == "box":
                    minp = shape.find("min")
                    maxp = shape.find("max")
                    if minp is not None and maxp is not None:
                        x1, y1 = minp.get("value", "0,0").split(",")
                        x2, y2 = maxp.get("value", "0,0").split(",")
                        shapes.append(
                            {
                                "type": "rect",
                                "x": float(x1.strip()),
                                "y": float(y1.strip()),
                                "w": float(x2.strip()) - float(x1.strip()),
                                "h": float(y2.strip()) - float(y1.strip()),
                            }
                        )
            if shapes:
                # 用第一个 shape 作为主区域代表（多 shape 的合并为 bounding box）
                first = shapes[0]
                results.append(
                    {
                        "name": name,
                        "kind": first["type"],
                        "x": first["x"],
                        "y": first["y"],
                        "w": first.get("w", 0.0),
                        "h": first.get("h", 0.0),
                        "r": first.get("r", 0.0),
                        "shapes": shapes,
                    }
                )
        return results

    def _compute_map_bounds(self, objects: list[dict]) -> dict:
        """从 Objects 坐标范围推断地图大小。"""
        if not objects:
            return {
                "width": 0,
                "height": 0,
                "min_x": 0,
                "min_y": 0,
                "max_x": 0,
                "max_y": 0,
            }
        xs = [o["x"] for o in objects]
        ys = [o["y"] for o in objects]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        return {
            "width": max_x - min_x,
            "height": max_y - min_y,
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
        }

    def _compute_wave_timing(self) -> dict:
        """计算亡者之夜的波次时机（基于 MapScript.galaxy 的昼夜时长）。

        亡者之夜昼夜循环：
        - Day 1: 0 - 210s (4704 loops)
        - Night 1: 210 - 450s (4704 - 10080 loops)
        - Day 2: 450 - 690s (10080 - 15456 loops)
        - Night 2: 690 - 930s (15456 - 20832 loops)
        - ...每个昼夜循环 480s (10752 loops)
        """
        day_first_sec = 210
        day_sec = 240
        night_sec = 240
        cycle_sec = day_sec + night_sec  # 480s 一个完整循环

        # 转换为 loops
        day_first_loops = int(day_first_sec * LOOPS_PER_SECOND)
        day_loops = int(day_sec * LOOPS_PER_SECOND)
        night_loops = int(night_sec * LOOPS_PER_SECOND)
        cycle_loops = int(cycle_sec * LOOPS_PER_SECOND)

        # 生成 6 个夜晚的时机（亡者之夜通常 6-7 个夜晚）
        nights = []
        # Night 1: 第一天结束后
        nights.append(
            {
                "night_number": 1,
                "start_loop": day_first_loops,
                "end_loop": day_first_loops + night_loops,
                "difficulty": "light",  # night 1-3: light
            }
        )
        # 后续夜晚：每隔 cycle_loops
        for n in range(2, 7):
            prev_end = nights[-1]["end_loop"]
            nights.append(
                {
                    "night_number": n,
                    "start_loop": prev_end + day_loops,
                    "end_loop": prev_end + day_loops + night_loops,
                    "difficulty": "light"
                    if n < 4
                    else ("heavy" if n >= 6 else "medium"),
                }
            )

        return {
            "day_first_loops": day_first_loops,
            "day_loops": day_loops,
            "night_loops": night_loops,
            "cycle_loops": cycle_loops,
            "nights": nights,
            "total_nights": 6,
            "loops_per_second": LOOPS_PER_SECOND,
        }


def extract_dead_of_night(
    map_dir: Optional[str | Path] = None,
    *,
    include_runtime_starting_units: bool = True,
) -> MapData:
    """提取亡者之夜地图数据。

    Args:
        map_dir: 地图目录路径。若为 None，使用默认 cmre-runtime 路径。

    亡者之夜的 Player 1/2 起始单位是 ACHeroSpawnPlacement（英雄放置点），
    不是真实单位——真实起始单位由游戏运行时触发器创建。
    ``include_runtime_starting_units=True`` 保留旧 runner 的兼容行为：用
    适配器构造 P1 的运行时开局。严格的地图派生场景必须传 False，
    此时 ``spawns`` 只包含 Objects 中提取出的原生实体。
    """
    if map_dir is None:
        # 优先使用项目内已解包的地图包；开发环境没有该目录时再回退到
        # 外部 cmre-runtime 绑定，保持原有运行方式兼容。
        project_root = Path(__file__).resolve().parents[1]
        packaged_map = project_root / "packages" / "Maps" / "亡者之夜.SC2Map"
        runtime_root = Path(__file__).resolve().parents[5]
        runtime_map = (
            runtime_root / "cmre-runtime" / "Maps" / "CMRE" / "亡者之夜.SC2Map"
        )
        map_dir = packaged_map if packaged_map.exists() else runtime_map
    ex = MapExtractor(map_dir)
    data = ex.extract_all()

    if include_runtime_starting_units:
        # Compatibility path for the older economy runner. These units are an
        # adapter overlay, not map-native Objects, and are never used by the
        # strict map-derived cooperative replay.
        starting_units = _build_player_starting_units(player_id=1, cx=85.0, cy=94.0)
        data.scenario["spawns"].extend(starting_units)
        for su in starting_units:
            data.stats.units_extracted += 1
            data.stats.unit_type_counter[su["unit_type_id"]] += 1
            data.stats.player_counter[su["owner_player_id"]] += 1

    # 确保 Player 1 在 players 列表中
    player_ids = {p["id"] for p in data.scenario["players"]}
    if 1 not in player_ids:
        data.scenario["players"].append(
            {
                "id": 1,
                "name": "User1",
                "race": "terran",
                "allies": [],
                "is_ai": True,
            }
        )
        # 按 id 排序
        data.scenario["players"].sort(key=lambda p: p["id"])

    return data


def build_dead_of_night_map_cooperative_scenario(
    map_dir: Optional[str | Path] = None,
) -> MapData:
    """Build a strict map-derived P1/P2 cooperative scenario.

    The map stores P1/P2 as ``ACHeroSpawnPlacement`` objects and creates the
    actual commander forces at runtime. This adapter therefore carries the
    placement markers and alliance/control semantics, but injects zero units.
    The source entities remain exactly the output of :class:`MapExtractor`.
    """
    data = extract_dead_of_night(
        map_dir=map_dir,
        include_runtime_starting_units=False,
    )
    players_by_id = {
        int(player["id"]): dict(player)
        for player in data.scenario.get("players", [])
    }

    # MapScript.galaxy's Init02Players contract: P1/P2 are human-side, the
    # Amon/Infested players are hostile to them, and P6/P8/P9 are neutral-side.
    human_side = {1, 2, 6, 8, 9}
    enemy_side = {3, 4, 5, 7}
    for player_id, faction in PLAYER_FACTIONS.items():
        player = players_by_id.setdefault(
            player_id,
            {
                "id": player_id,
                "name": faction["name"],
                "race": faction["race"],
                "allies": [],
                "is_ai": True,
            },
        )
        if player_id in (1, 2):
            player["is_ai"] = player_id == 2
            player["relation"] = "leader" if player_id == 1 else "ally"
        elif player_id in enemy_side:
            player["relation"] = "enemy"
        else:
            player["relation"] = "neutral"

        if player_id in human_side:
            player["allies"] = sorted(human_side - {player_id})
        elif player_id in enemy_side:
            player["allies"] = sorted(enemy_side - {player_id})
        else:
            player["allies"] = []

    # Preserve the neutral resource owner emitted by Objects, even though it
    # is not part of PLAYER_FACTIONS.
    for player_id, player in players_by_id.items():
        if player_id not in PLAYER_FACTIONS:
            player.setdefault("relation", "neutral")
            player.setdefault("allies", [])
            player.setdefault("is_ai", True)

    data.scenario["players"] = [players_by_id[player_id] for player_id in sorted(players_by_id)]
    data.scenario["_cooperative_enemy_player_ids"] = sorted(enemy_side)
    data.scenario["_map_source_kind"] = "map_extractor"
    data.scenario["_map_native_starting_force"] = False
    return data


def _build_player_starting_units(player_id: int, cx: float, cy: float) -> list[dict]:
    """构造玩家起始部队（合作模式中等开局）。

    Args:
        player_id: 玩家 ID
        cx, cy: 起始中心位置

    Returns: spawns 列表
    """
    units = []
    # 基地
    units.append(
        {
            "unit_type_id": "CommandCenter",
            "owner_player_id": player_id,
            "x": cx,
            "y": cy,
        }
    )
    # 采矿 SCV（4 个）
    for i, (dx, dy) in enumerate([(-1, -1), (-0.5, -1), (0.5, -1), (1, -1)]):
        units.append(
            {
                "unit_type_id": "SCV",
                "owner_player_id": player_id,
                "x": cx + dx,
                "y": cy + dy,
            }
        )
    # 建筑
    units.append(
        {
            "unit_type_id": "Barracks",
            "owner_player_id": player_id,
            "x": cx - 2,
            "y": cy - 2,
        }
    )
    units.append(
        {
            "unit_type_id": "Bunker",
            "owner_player_id": player_id,
            "x": cx + 2,
            "y": cy + 2,
        }
    )
    units.append(
        {
            "unit_type_id": "EngineeringBay",
            "owner_player_id": player_id,
            "x": cx - 2,
            "y": cy + 2,
        }
    )
    # SupplyDepot 5 个：supply_cap = 11(CC) + 5*8 = 51，足够起始部队(30) + 训练余量(21)
    for dx, dy in [(-3, 0), (3, -2), (-3, -2), (3, 0), (-3, 2)]:
        units.append(
            {
                "unit_type_id": "SupplyDepot",
                "owner_player_id": player_id,
                "x": cx + dx,
                "y": cy + dy,
            }
        )
    units.append(
        {
            "unit_type_id": "MissileTurret",
            "owner_player_id": player_id,
            "x": cx + 3,
            "y": cy + 2,
        }
    )
    units.append(
        {
            "unit_type_id": "Refinery",
            "owner_player_id": player_id,
            "x": cx + 4,
            "y": cy - 1,
        }
    )
    # 防守部队（8 Marine + 4 Marauder + 2 SiegeTank + 2 Medivac）
    marines = [
        (-1, 1),
        (-0.5, 1),
        (0, 1),
        (0.5, 1),
        (1, 1),
        (-1, 0.5),
        (0, 0.5),
        (1, 0.5),
    ]
    for dx, dy in marines:
        units.append(
            {
                "unit_type_id": "Marine",
                "owner_player_id": player_id,
                "x": cx + dx,
                "y": cy + dy,
            }
        )
    marauders = [(-1.5, 0), (1.5, 0), (-1.5, -0.5), (1.5, -0.5)]
    for dx, dy in marauders:
        units.append(
            {
                "unit_type_id": "Marauder",
                "owner_player_id": player_id,
                "x": cx + dx,
                "y": cy + dy,
            }
        )
    tanks = [(2, 1), (-2, 1)]
    for dx, dy in tanks:
        units.append(
            {
                "unit_type_id": "SiegeTank",
                "owner_player_id": player_id,
                "x": cx + dx,
                "y": cy + dy,
            }
        )
    medivacs = [(0, 3), (2, 3)]
    for dx, dy in medivacs:
        units.append(
            {
                "unit_type_id": "Medivac",
                "owner_player_id": player_id,
                "x": cx + dx,
                "y": cy + dy,
            }
        )
    return units


def print_extraction_report(data: MapData) -> None:
    """打印提取报告。"""
    stats = data.stats
    print(f"=== 地图提取报告: {data.scenario['name']} ===")
    print(f"地图边界: {data.map_bounds}")
    print(
        f"波次时机: {data.wave_timing['total_nights']} 个夜晚, "
        f"首夜开始 @ loop {data.wave_timing['nights'][0]['start_loop']}"
    )
    print()
    print(f"总物体数: {stats.total_objects}")
    print(f"成功提取: {stats.units_extracted}")
    print(f"映射单位: {stats.units_mapped}")
    print(f"跳过单位: {stats.units_skipped}")
    print(f"不支持单位: {stats.units_unsupported}")
    print()
    print("按玩家分布:")
    for pid in sorted(stats.player_counter):
        count = stats.player_counter[pid]
        faction = PLAYER_FACTIONS.get(pid, {"name": "Unknown", "team": "unknown"})
        print(f"  Player {pid} ({faction['name']}, {faction['team']}): {count}")
    print()
    print("Top 20 单位类型:")
    for ut, n in stats.unit_type_counter.most_common(20):
        print(f"  {ut}: {n}")
    if stats.mapped_counter:
        print()
        print("映射单位（特殊 → m7）:")
        for ut, n in stats.mapped_counter.most_common(20):
            mapped = UNIT_TYPE_MAP.get(ut, "?")
            print(f"  {ut} -> {mapped}: {n}")
    if stats.unsupported_counter:
        print()
        print(f"不支持单位（{sum(stats.unsupported_counter.values())} 个，已跳过）:")
        for ut, n in stats.unsupported_counter.most_common(20):
            print(f"  {ut}: {n}")
    if stats.skipped_counter:
        print()
        print(f"跳过的装饰物（{sum(stats.skipped_counter.values())} 个）:")
        for ut, n in stats.skipped_counter.most_common(10):
            print(f"  {ut}: {n}")
    print()
    print(f"区域数: {len(data.regions)}")
    # 打印前 10 个区域
    for r in data.regions[:10]:
        print(f"  {r['name']} ({r['kind']} @ ({r['x']:.1f},{r['y']:.1f}))")


if __name__ == "__main__":
    data = extract_dead_of_night()
    print_extraction_report(data)
    # 验证 scenario_dict 可被 SimulatorSession 加载
    print()
    print("=== 验证 scenario_dict 加载 ===")
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from vibe.simulator_session import SimulatorSession

    s = SimulatorSession()
    info = s.scenario_load(scenario_dict=data.scenario, catalog="m7")
    print(f"加载成功: {info}")
    reset_info = s.scenario_reset()
    print(f"重置成功: {reset_info}")
