"""亡者之夜 AI 盟友自主对局 runner。

功能：
1. 从 cmre-runtime 提取亡者之夜地图数据（一比一复刻：单位位置/玩家/区域）
2. 构造 6 夜晚波次 mission（基于 MapScript.galaxy 昼夜时长）
3. DefendBasePolicy：玩家 AI 防守基地（检测威胁 → attack，无敌方 → hold）
4. EnemyAttackTrigger：敌方自动攻击玩家
5. 运行完整对局，生成结果报告

用法：
    python -m vibe.run_dead_of_night [--max-loops N] [--include-preset-enemies]
    python run_dead_of_night.py --max-loops 5000
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .map_extractor import (
    extract_dead_of_night,
    MapData,
    PLAYER_FACTIONS,
    LOOPS_PER_SECOND,
)
from .mission_engine import MissionEngine, Objective, Region, Trigger, Wave
from .simulator_session import SimulatorSession
from .sim_path import ensure_simulator_on_path

ensure_simulator_on_path()


# ---------------------------------------------------------------------------
# 波次构造
# ---------------------------------------------------------------------------

# 玩家基地位置（从 ACHeroSpawnPlacement 提取）
PLAYER_BASE_X = 85.0
PLAYER_BASE_Y = 94.0

# 4 个刷怪方向（地图边缘）
SPAWN_DIRECTIONS = [
    ("north", PLAYER_BASE_X, 160.0),  # 北
    ("east", 160.0, PLAYER_BASE_Y),  # 东
    ("south", PLAYER_BASE_X, 30.0),  # 南
    ("west", 30.0, PLAYER_BASE_Y),  # 西
]

# Persistent push targets do not need a command every simulation second. One
# Heavy-unit weapon period keeps the controller responsive while avoiding a
# large stream of duplicate attack orders in the 344-building probe.
CLEAR_PUSH_COMMAND_INTERVAL = 67
CLEAR_PUSH_STAGING_POINTS = [
    (50.0, 40.0),
    (125.0, 40.0),
    (50.0, 145.0),
    (125.0, 145.0),
]
REINFORCEMENT_LIFETIME_LOOPS = 336
CLEAR_PROBE_WALL_TIME_BUDGET_SEC = 120.0


def build_night_waves(
    wave_timing: dict,
    time_scale: float = 1.0,
    strength_scale: float = 1.0,
    seed: int = 42,
) -> list[Wave]:
    """构造 6 个夜晚的波次。

    每个夜晚从 4 个方向刷怪，难度递增：
    - Night 1-2: Zergling 为主
    - Night 3-4: + Hydralisk
    - Night 5-6: + Roach + Mutalisk + Ultralisk

    Args:
        wave_timing: 波次时机数据
        time_scale: 时间缩放（< 1.0 压缩昼夜循环，便于测试）
        strength_scale: 波次单位数量缩放。默认 1.0 保持完整波次。
        seed: 缩放后的随机取整和刷怪位置抖动种子。
    """
    rng = random.Random(seed)
    waves = []
    for night in wave_timing["nights"]:
        n = night["night_number"]
        start_loop = int(night["start_loop"] * time_scale)
        difficulty = night["difficulty"]

        # 每个方向的刷怪组成
        if n <= 2:
            # light: 4 Zergling + 1 Hydralisk per direction
            template = [("Zergling", 4), ("Hydralisk", 1)]
        elif n <= 4:
            # medium: 6 Zergling + 2 Hydralisk + 1 Roach per direction
            template = [("Zergling", 6), ("Hydralisk", 2), ("Roach", 1)]
        else:
            # heavy: 8 Zergling + 3 Hydralisk + 2 Roach + 1 Mutalisk + 1 Ultralisk
            template = [
                ("Zergling", 8),
                ("Hydralisk", 3),
                ("Roach", 2),
                ("Mutalisk", 1),
                ("Ultralisk", 1),
            ]

        # 为每个方向创建一个 wave（错开 50 loops 让刷怪有层次）
        for dir_idx, (dir_name, sx, sy) in enumerate(SPAWN_DIRECTIONS):
            spawns = []
            for unit_type, count in template:
                scaled_count = count * strength_scale
                spawn_count = int(scaled_count)
                if rng.random() < scaled_count - spawn_count:
                    spawn_count += 1
                for i in range(spawn_count):
                    # 在刷怪点附近散开
                    offset_x = (i % 3) * 1.5 - 1.5 + rng.uniform(-0.5, 0.5)
                    offset_y = (i // 3) * 1.5 - 1.5 + rng.uniform(-0.5, 0.5)
                    spawns.append(
                        {
                            "unit_type_id": unit_type,
                            "owner_player_id": 4,  # AMONS_FORCES
                            "x": sx + offset_x,
                            "y": sy + offset_y,
                        }
                    )
            waves.append(
                Wave(
                    name=f"night{n}_{dir_name}",
                    at_loop=start_loop + int(dir_idx * 50 * time_scale),
                    spawns=spawns,
                )
            )
    return waves


# ---------------------------------------------------------------------------
# 触发器
# ---------------------------------------------------------------------------


def make_enemy_attack_trigger(
    name: str,
    enemy_player_id: int,
    target_player_id: int,
    cooldown: int = 44,  # 2 秒
    active_entity_ids: Optional[
        set[int]
    ] = None,  # 只对这些 id 生效；None=该 player 所有单位
) -> Trigger:
    """让指定敌方玩家的单位攻击目标玩家最近的单位。

    active_entity_ids: 若提供，只对集合内的 entity_id 生效（用于区分波次单位 vs 营地单位）。
    若 None，对该 player 的所有存活单位生效（旧行为，不推荐用于含营地单位的场景）。
    """

    def condition(eng: MissionEngine) -> bool:
        s = eng.session
        if s.world is None:
            return False
        own = [
            e
            for e in s.world.entities.values()
            if e.owner_player_id == enemy_player_id
            and e.is_alive
            and (active_entity_ids is None or e.entity_id in active_entity_ids)
        ]
        targets = [
            e
            for e in s.world.entities.values()
            if e.owner_player_id == target_player_id and e.is_alive
        ]
        return bool(own and targets)

    def action(eng: MissionEngine) -> None:
        s = eng.session
        own = [
            e
            for e in s.world.entities.values()
            if e.owner_player_id == enemy_player_id
            and e.is_alive
            and (active_entity_ids is None or e.entity_id in active_entity_ids)
        ]
        targets = [
            e
            for e in s.world.entities.values()
            if e.owner_player_id == target_player_id and e.is_alive
        ]
        if not own or not targets:
            return
        for u in own:
            # 找最近的敌方单位
            nearest = min(
                targets,
                key=lambda e: (e.x.raw - u.x.raw) ** 2 + (e.y.raw - u.y.raw) ** 2,
            )
            try:
                s.unit_order(
                    [u.entity_id],
                    "attack_unit",
                    enemy_player_id,
                    target_entity_id=nearest.entity_id,
                )
            except Exception:
                pass  # 错误静默（单位可能已死）

    return Trigger(name, condition, action, cooldown=cooldown)


# ---------------------------------------------------------------------------
# DefendBasePolicy：玩家 AI 防守策略（已提取到 defend_policy.py 模块化）
# ---------------------------------------------------------------------------
from .defend_policy import (  # noqa: E402
    DefendAction,
    DefendBasePolicy,
    EconomyState,
    PLAYER_BASE_X,
    PLAYER_BASE_Y,
)


# ---------------------------------------------------------------------------
# 运行器
# ---------------------------------------------------------------------------


@dataclass
class GameReport:
    """对局结果报告。"""

    map_name: str
    end_loop: int
    end_reason: str
    terminated: bool
    player1_survivors: int
    enemy_survivors: dict
    total_waves_fired: int
    total_commands_issued: int
    total_commands_dispatched: int
    deadlock_detected: bool
    duration_sec: float
    nights_survived: int
    objectives: list[dict]
    verdict: str  # "victory" | "defeat" | "inconclusive"
    summary: str
    replay_log_path: str = ""  # JSONL 回放日志路径（空则未记录）
    cmd_ok_stats: dict = field(default_factory=dict)  # 命令成功统计 {kind: count}
    cmd_fail_stats: dict = field(
        default_factory=dict
    )  # 命令失败统计 {kind:ErrorCode: count}
    seed: int = 42
    time_scale: float = 1.0
    simulation_time_sec: float = 0.0
    logical_game_time_sec: float = 0.0
    victory_time_sec: Optional[float] = None
    wave_strength_scale: float = 1.0
    victory_mode: str = "survive"
    initial_enemy_structures: int = 0
    remaining_enemy_structures: int = 0
    infected_spawned: int = 0
    infected_cleared_in_day: int = 0
    building_reinforcements_spawned: int = 0
    structure_health_scale: float = 1.0
    push_unit_type: str = ""
    event_summary: dict = field(default_factory=dict)
    target_allocation_summary: dict = field(default_factory=dict)


def _unit_brief_for_log(e) -> dict:
    """把实体转成精简 dict 用于 JSONL 日志（只保留关键字段）。"""
    return {
        "id": e.entity_id,
        "t": e.unit_type_id,
        "p": e.owner_player_id,
        "x": round(e.x.to_float(), 2),
        "y": round(e.y.to_float(), 2),
        "hp": e.health.raw,
        "alive": e.is_alive,
    }


def _write_replay_frame(
    fp,
    loop: int,
    world,
    waves_fired: int,
    total_cmds: int,
    nights_data: dict,
    time_scale: float,
    p1_alive_count: int,
    enemy_alive_count: int,
    key_events_this_frame: list[dict],
    p1_resources: Optional[dict] = None,
) -> None:
    """写一帧回放日志到 JSONL 文件。

    key_events_this_frame: 仅本帧新发生的事件（已去重），避免历史事件在多帧中重复出现。
    p1_resources: Player 1 资源快照 {"minerals", "vespene", "supply_used", "supply_cap"}
    """
    import json as _json

    # 收集所有存活单位（按 owner 分组）
    entities_by_player: dict[int, list[dict]] = {}
    p1_units_by_type: dict[str, int] = {}
    enemy_units_by_type: dict[str, int] = {}
    for e in world.entities.values():
        if not e.is_alive:
            continue
        brief = _unit_brief_for_log(e)
        entities_by_player.setdefault(e.owner_player_id, []).append(brief)
        if e.owner_player_id == 1:
            p1_units_by_type[e.unit_type_id] = (
                p1_units_by_type.get(e.unit_type_id, 0) + 1
            )
        elif e.owner_player_id != 0:
            enemy_units_by_type[e.unit_type_id] = (
                enemy_units_by_type.get(e.unit_type_id, 0) + 1
            )

    # 当前所处夜晚
    current_night = 0
    for night in nights_data:
        scaled_start = int(night["start_loop"] * time_scale)
        scaled_end = int(night["end_loop"] * time_scale)
        if scaled_start <= loop < scaled_end:
            current_night = night["night_number"]
            break

    frame = {
        "loop": loop,
        "ts_sec": round(loop / 22.4, 1),  # 游戏内秒数
        "real_sec": round(loop * time_scale / 22.4, 1),  # 实际游戏秒数（按 time_scale）
        "current_night": current_night,
        "waves_fired": waves_fired,
        "total_cmds": total_cmds,
        "p1_alive": p1_alive_count,
        "enemy_alive": enemy_alive_count,
        "p1_units_by_type": p1_units_by_type,
        "enemy_units_by_type": enemy_units_by_type,
        "entities_by_player": {str(k): v for k, v in entities_by_player.items()},
        "key_events": key_events_this_frame,  # 仅本帧新事件
        "p1_resources": p1_resources or {},  # 经济指标
    }
    fp.write(_json.dumps(frame, ensure_ascii=False) + "\n")
    fp.flush()


def _find_nearest_mineral_field(world, x, y) -> Optional[int]:
    """找离 (x, y) 最近的 MineralField 实体 id。

    x/y 是世界单位 float；e.x.raw 是 Fixed 的 raw int（值×1024），
    必须用 to_float() 统一单位，否则距离计算全错。
    """
    best_id = None
    best_sq = float("inf")
    for e in world.entities.values():
        if not e.is_alive:
            continue
        if e.unit_type_id != "MineralField":
            continue
        dx = e.x.to_float() - x
        dy = e.y.to_float() - y
        sq = dx * dx + dy * dy
        if sq < best_sq:
            best_sq = sq
            best_id = e.entity_id
    return best_id


def _tally_cmd_results(world, pre_count: int, kind: str, ok_stats, fail_stats) -> None:
    """统计 unit_order 后新增的 CommandResult，按 code 分类。

    用于自校验：train/build/gather 失败原因不再被 except:pass 吞掉，
    而是按 ErrorCode.name 累计到 fail_stats，终局报告可见。
    """
    new_results = world.command_results[pre_count:]
    for r in new_results:
        if getattr(r, "ok", False):
            ok_stats[kind] += 1
        else:
            code_name = getattr(getattr(r, "code", None), "name", "UNKNOWN")
            fail_stats[f"{kind}:{code_name}"] += 1


def run_dead_of_night(
    max_loops: int = 15000,  # 约 11 分钟，覆盖 2-3 个夜晚
    include_preset_enemies: bool = True,
    enable_enemy_ai: bool = True,
    enable_player_ai: bool = True,
    verbose: bool = True,
    time_scale: float = 1.0,  # 时间缩放（< 1.0 压缩昼夜循环，便于测试）
    replay_log_path: Optional[str] = None,  # JSONL 回放日志路径；None 则自动生成
    replay_log_interval: int = 100,  # 每 N loop 记录一帧
    map_dir: Optional[str | Path] = None,  # 显式地图解包目录；None 使用默认路径
    wall_time_budget_sec: Optional[float] = None,
    seed: int = 42,
    wave_strength_scale: float = 1.0,
    clear_waves_after_final: bool = False,
    clear_enemy_structures: bool = False,
    push_army_size: int = 48,
    push_unit_type: str = "Marine",
    push_start_points: Optional[list[tuple[float, float]]] = None,
) -> GameReport:
    """运行亡者之夜 AI 盟友对局。

    Args:
        max_loops: 最大 loop 数（默认 15000，约 11 分钟）
        include_preset_enemies: 是否包含地图预放置的敌方单位（Player 3/4/5）
        enable_enemy_ai: 是否启用敌方 AI（自动攻击玩家）
        enable_player_ai: 是否启用玩家 AI（DefendBasePolicy）
        verbose: 是否打印进度
        time_scale: 时间缩放系数（< 1.0 压缩昼夜循环，便于测试。
                    例如 0.1 让 Night 1 从 loop 4704 → 470）
        replay_log_path: JSONL 回放日志输出路径。None 时自动生成到
                         artifacts/dead_of_night_replay_<timestamp>.jsonl
        replay_log_interval: 每 N loop 记录一帧回放日志
        map_dir: 地图解包目录。用于从项目内 packages/Maps 或 cmre-runtime 提取地图。
        wall_time_budget_sec: 可选 wall-clock 预算；超时返回 inconclusive。
        seed: 模拟器随机种子，用于多 seed Victory Time 基准。
        wave_strength_scale: 波次单位数量缩放，默认 1.0。
         clear_waves_after_final: 六夜全部触发后，清空波次单位即胜利。
         clear_enemy_structures: 将所有敌方建筑摧毁作为胜利条件，并启用昼夜感染规则。
         push_army_size: 清图模式开局集结的战斗单位数量；仅用于清图推进，不改变胜利条件。
         push_unit_type: 清图模式开局集结的单位类型；必须是可攻击地面目标的单位。
         push_start_points: 可选的清图分路集结点；省略时从玩家基地出发。
    """
    start_time = time.time()

    # 1. 提取地图数据
    if verbose:
        print("[1/4] 提取亡者之夜地图数据...")
    data = extract_dead_of_night(map_dir=map_dir)
    data.scenario["seed"] = seed

    # 过滤预放置敌方单位（如不需要）
    if not include_preset_enemies:
        enemy_players = {3, 4, 5}
        if clear_enemy_structures:
            from .sim_path import ensure_simulator_on_path as _ensure_sim

            _ensure_sim()
            from sc2_simulator.catalog.m7_units import m7_catalog as _m7_catalog

            _catalog = _m7_catalog()
            data.scenario["spawns"] = [
                spawn
                for spawn in data.scenario["spawns"]
                if spawn["owner_player_id"] not in enemy_players
                or _catalog.get(spawn["unit_type_id"]).is_structure
            ]
        else:
            data.scenario["spawns"] = [
                spawn
                for spawn in data.scenario["spawns"]
                if spawn["owner_player_id"] not in enemy_players
            ]
        # 显式保留 Player 3/4/5 的玩家声明（即使无预放置单位）。
        # 波次系统会为 Player 4（AMONS_FORCES）生成单位，若从 players 列表移除
        # 会导致模拟器 enemies_of() 抛出 KeyError。
        from .map_extractor import PLAYER_FACTIONS

        existing_ids = {p["id"] for p in data.scenario["players"]}
        for pid in (3, 4, 5):
            if pid not in existing_ids:
                f = PLAYER_FACTIONS.get(pid, {"name": f"Player{pid}", "race": "zerg"})
                data.scenario["players"].append(
                    {
                        "id": pid,
                        "name": f["name"],
                        "race": f["race"],
                        "allies": [],
                        "is_ai": True,
                    }
                )
        data.scenario["players"].sort(key=lambda p: p["id"])
        if verbose:
            print(
                f"  过滤预放置敌方单位后: {len(data.scenario['spawns'])} 单位"
                f"（保留 Player 3/4/5 用于波次生成）"
            )

    # 注意：不过滤 Player 0 的中立单位（MineralField 等）。
    # 它们不参与战斗，但保留可防止模拟器误触 annihilation 胜利条件
    # （当只有 Player 1 存活时会提前终止模拟）。
    # 在进度报告和结果统计中已排除 Player 0。

    # 2. 构造 mission
    if verbose:
        print("[2/4] 构造波次 mission...")
    waves = build_night_waves(
        data.wave_timing,
        time_scale=time_scale,
        strength_scale=wave_strength_scale,
        seed=seed,
    )
    if verbose:
        total_wave_units = sum(len(w.spawns) for w in waves)
        first_night = waves[0].at_loop if waves else 0
        print(
            f"  {len(waves)} 个波次, 共 {total_wave_units} 个刷怪单位, "
            f"首夜 @ loop {first_night} (time_scale={time_scale})"
        )

    # 3. 加载场景
    if verbose:
        print("[3/4] 加载场景到模拟器...")
    s = SimulatorSession()
    s.scenario_load(scenario_dict=data.scenario, catalog="m7")
    s.set_wave_timing(data.wave_timing)  # Stage 08: 用于胜利时间计算 nights_survived
    s.scenario_reset()
    structure_health_scale = 1.0
    push_unit_ids: set[int] = set()
    if clear_enemy_structures:
        if time_scale < 1.0:
            # 压缩回归只缩放建筑耐久，不删除建筑实体；胜利仍要求每个目标建筑死亡。
            # 这样真实地图的 344 个建筑可以在一分钟预算内完成可观测闭环。
            # Keep every real building as an objective, but make compressed probes
            # finish within their bounded wall-clock window. At 0.2%, even the
            # largest map building remains damageable and is one heavy volley.
            structure_health_scale = 0.002
            from sc2_simulator.world.entity import UnitState

            for entity in s.world.entities.values():
                unit_type = s.world.catalog.get(entity.unit_type_id)
                if (
                    entity.owner_player_id in (3, 4, 5)
                    and unit_type.is_structure
                    and unit_type.race != "neutral"
                ):
                    entity.health = entity.health.__class__(
                        max(1, int(unit_type.max_health.raw * structure_health_scale))
                    )
                    # Buildings remain real damageable objectives, but do not spend
                    # every compressed loop on autonomous camp scans. Damage events
                    # still flow through the normal combat path and trigger local
                    # reinforcements below.
                    entity.state = UnitState.HOLDING
        # The clear probe represents the co-op army already assembled for the
        # push. Buildings remain real entities and must still die. Keep this
        # force configurable because compressed map runs need enough coverage
        # to cross the full map while waves continue to pressure the base.
        if push_army_size < 0:
            raise ValueError("push_army_size must be non-negative")
        push_unit = s.world.catalog.get(push_unit_type)
        if push_unit.is_structure or push_unit.is_worker or push_unit.weapon_ground is None:
            raise ValueError(
                f"push_unit_type must be a non-worker ground attacker: {push_unit_type}"
            )
        staging_points = push_start_points or [(PLAYER_BASE_X, PLAYER_BASE_Y)]
        if any(len(point) != 2 for point in staging_points):
            raise ValueError("push_start_points must contain (x, y) pairs")
        for index in range(push_army_size):
            staging_x, staging_y = staging_points[index % len(staging_points)]
            formation_index = index // len(staging_points)
            spawn = s.unit_spawn(
                push_unit_type,
                1,
                staging_x + (formation_index % 8) * 0.8 - 2.8,
                staging_y + (formation_index // 8) * 0.8 - 2.0,
            )
            push_unit_ids.add(spawn["entity_id"])
    if verbose:
        print(f"  初始单位数: {len(s.world.entities)}")
        p1_count = sum(1 for e in s.world.entities.values() if e.owner_player_id == 1)
        print(f"  Player 1 单位数: {p1_count}")

    # 准备回放日志文件
    if replay_log_path is None:
        from datetime import datetime as _dt

        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        replay_log_path = str(
            Path(__file__).resolve().parents[1]
            / "artifacts"
            / f"dead_of_night_replay_{ts}.jsonl"
        )
    replay_path = Path(replay_log_path)
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    replay_fp = open(replay_path, "w", encoding="utf-8")
    if verbose:
        print(f"  回放日志: {replay_path}")

    # 构造 MissionEngine
    eng = MissionEngine(s)

    # 添加区域（基地 + 刷怪点）
    eng.add_region(
        Region(
            name="player_base", kind="circle", x=PLAYER_BASE_X, y=PLAYER_BASE_Y, r=15.0
        )
    )
    for dir_name, sx, sy in SPAWN_DIRECTIONS:
        eng.add_region(
            Region(name=f"spawn_{dir_name}", kind="circle", x=sx, y=sy, r=5.0)
        )

    # 添加波次
    for w in waves:
        eng.add_wave(w)

    # 添加目标：存活到 max_loops
    if clear_enemy_structures:
        eng.add_objective(
            Objective(
                name="clear_enemy_structures",
                kind="destroy_all_enemy_structures",
                params={"enemy_player_ids": [3, 4, 5], "defender_player_id": 1},
            )
        )
    else:
        eng.add_objective(
            Objective(
                name="survive",
                kind="survive_loops",
                params={"target_loops": max_loops},
            )
        )

    # 添加触发器：敌方攻击玩家
    # 设计原则（参考亡者之夜原版玩法）：
    # - 营地单位（Player 3/4/5 预放置的）：原地防守营地，不主动出击
    # - 波次单位（夜晚刷出的 Player 4 单位）：主动 attack_move 到玩家基地
    # 因此不给 P3/P5 加 attack trigger；P4 的 attack trigger 只作用于波次单位 id 集合
    wave_entity_ids: set[int] = set()  # 收集所有波次刷出的 entity_id
    infection_entity_ids: set[int] = set()
    reinforcement_entity_ids: set[int] = set()
    dynamic_enemy_entity_ids = wave_entity_ids
    if enable_enemy_ai:
        eng.add_trigger(
            make_enemy_attack_trigger(
                name="wave_enemies_attack",
                enemy_player_id=4,
                target_player_id=1,
                cooldown=44,
                active_entity_ids=dynamic_enemy_entity_ids,
            )
        )
        eng.add_trigger(
            make_enemy_attack_trigger(
                name="infected_enemies_attack",
                enemy_player_id=5,
                target_player_id=1,
                cooldown=44,
                active_entity_ids=infection_entity_ids,
            )
        )

    # 4. 运行对局
    if verbose:
        print(f"[4/4] 运行对局 (max_loops={max_loops})...")

    # 玩家 AI
    # Clear mode uses the dedicated push controller below.  The defensive policy's
    # full visibility/economy pass is intentionally not run over 344 structures.
    policy = (
        DefendBasePolicy(player_id=1)
        if enable_player_ai and not clear_enemy_structures
        else None
    )

    # 命令统计
    total_commands_issued = 0
    total_commands_dispatched = 0
    deadlock_loops = 0
    # 命令成功/失败统计（按 kind 和 ErrorCode 分类，自校验用）
    from collections import Counter as _Counter

    cmd_ok_stats: _Counter = _Counter()
    cmd_fail_stats: _Counter = _Counter()
    last_report_loop = 0
    last_replay_loop = -10_000  # 强制首帧立即记录
    # 进度报告间隔：取 max_loops / 20 与 100 的较大值，至少每 5% 报告一次
    report_interval = max(100, max_loops // 20)

    # 关键事件累计（贯穿整个对局，用于终局报告）
    all_key_events: list[dict] = []
    # 自上次日志帧以来的事件累积器（写入日志帧后清空）
    events_since_last_log: list[dict] = []
    # 实体信息缓存：entity_id -> (unit_type, owner_player_id)
    # 用于死亡时查回类型（实体死亡后会被 world 移除，无法直接读取）
    entity_info_cache: dict[int, tuple[str, int]] = {
        eid: (e.unit_type_id, e.owner_player_id) for eid, e in s.world.entities.items()
    }
    # 上一 loop 存活实体 ID 集合
    last_alive_ids: set[int] = set(s.world.entities.keys())
    # 已记录的波次名（避免重复）
    recorded_waves: set[str] = set()
    infected_spawned = 0
    infected_cleared_in_day = 0
    building_reinforcements_spawned = 0
    last_night = 0
    processed_event_count = 0
    reinforcement_cooldowns: dict[int, int] = {}
    push_targets: dict[int, int] = {}
    push_target_cursor = 0
    filtered_dead_push_unit_ids: set[int] = set()
    push_dispatch_cycles = 0
    push_target_allocations = 0
    push_target_reallocations = 0
    push_target_reallocation_reasons: _Counter = _Counter()
    push_target_ids: set[int] = set()
    max_active_push_assignments = 0

    def _night_at_loop(loop: int) -> int:
        for night_data in data.wave_timing["nights"]:
            start = int(night_data["start_loop"] * time_scale)
            end = int(night_data["end_loop"] * time_scale)
            if start <= loop < end:
                return night_data["night_number"]
        return 0

    def _enemy_structures():
        return [
            entity
            for entity in s.world.entities.values()
            if entity.is_alive
            and entity.owner_player_id in (3, 4, 5)
            and s.world.catalog.get(entity.unit_type_id).is_structure
        ]

    def _spawn_infected_people(loop: int, night_number: int) -> int:
        """Spawn a deterministic, bounded group from live enemy buildings."""
        structures = sorted(_enemy_structures(), key=lambda entity: entity.entity_id)
        if not structures:
            return 0
        cap = max(4, min(24, int(24 * max(wave_strength_scale, 0.25))))
        spawned = 0
        for structure in structures[:cap]:
            if spawned >= cap:
                break
            spawn_result = s.unit_spawn(
                "Marine", 5, structure.x.to_float(), structure.y.to_float()
            )
            infected = s.world.get_entity(spawn_result["entity_id"])
            if infected is None:
                continue
            infection_entity_ids.add(infected.entity_id)
            dynamic_enemy_entity_ids.add(infected.entity_id)
            entity_info_cache[infected.entity_id] = (
                infected.unit_type_id,
                infected.owner_player_id,
            )
            spawned += 1
            ev = {
                "loop": loop,
                "kind": "infected_spawned",
                "entity_id": infected.entity_id,
                "source_structure_id": structure.entity_id,
                "night": night_number,
                "ts_sec": round(loop / LOOPS_PER_SECOND, 1),
            }
            events_since_last_log.append(ev)
            all_key_events.append(ev)
        return spawned

    def _clear_daytime_infected(loop: int) -> int:
        cleared = 0
        for entity_id in list(infection_entity_ids):
            infected = s.world.get_entity(entity_id)
            if infected is None or not infected.is_alive:
                infection_entity_ids.discard(entity_id)
                continue
            infected.health = infected.health.__class__.zero()
            from sc2_simulator.world.entity import UnitState

            infected.state = UnitState.DEAD
            infection_entity_ids.discard(entity_id)
            cleared += 1
        if cleared:
            ev = {
                "loop": loop,
                "kind": "infected_cleared_day",
                "count": cleared,
                "ts_sec": round(loop / LOOPS_PER_SECOND, 1),
            }
            events_since_last_log.append(ev)
            all_key_events.append(ev)
        return cleared

    def _dispatch_structure_push(loop: int) -> int:
        """Advance a persistent, globally distributed structure-clear push by day."""
        nonlocal push_target_cursor
        nonlocal push_dispatch_cycles, push_target_allocations
        nonlocal push_target_reallocations, max_active_push_assignments
        if not clear_enemy_structures or _night_at_loop(loop) != 0:
            return 0
        structures = sorted(_enemy_structures(), key=lambda entity: entity.entity_id)
        if not structures:
            return 0
        push_dispatch_cycles += 1
        structures_by_id = {entity.entity_id: entity for entity in structures}
        combat_units = [
            entity
            for entity in s.world.entities.values()
            if entity.owner_player_id == 1
            and entity.is_alive
            and not s.world.catalog.get(entity.unit_type_id).is_structure
            and not s.world.catalog.get(entity.unit_type_id).is_worker
        ]
        live_push_unit_ids = {entity.entity_id for entity in combat_units}
        filtered_dead_push_unit_ids.update(push_unit_ids - live_push_unit_ids)
        issued = 0
        claimed_targets = {
            target_id
            for unit_id, target_id in push_targets.items()
            if s.world.get_entity(unit_id) is not None and target_id in structures_by_id
        }
        for unit in combat_units:
            current_target_id = push_targets.get(unit.entity_id, 0)
            target = structures_by_id.get(current_target_id)
            if target is None:
                had_target = bool(current_target_id)
                # Allocate from a stable global cursor instead of the nearest local
                # building. This makes the push cover remote camps after a local camp
                # has been cleared, while the mapping keeps each unit on its target
                # until that building is actually destroyed.
                target = None
                for offset in range(len(structures)):
                    candidate = structures[(push_target_cursor + offset) % len(structures)]
                    if candidate.entity_id not in claimed_targets:
                        target = candidate
                        push_target_cursor = (push_target_cursor + offset + 1) % len(structures)
                        break
                if target is None:
                    target = structures[push_target_cursor % len(structures)]
                    push_target_cursor = (push_target_cursor + 1) % len(structures)
                push_targets[unit.entity_id] = target.entity_id
                claimed_targets.add(target.entity_id)
                push_target_allocations += 1
                push_target_ids.add(target.entity_id)
                if had_target:
                    push_target_reallocations += 1
                    push_target_reallocation_reasons["target_destroyed"] += 1
            try:
                pre = len(s.world.command_results)
                s.unit_order(
                    [unit.entity_id],
                    "attack_unit",
                    1,
                    target_entity_id=target.entity_id,
                )
                _tally_cmd_results(s.world, pre, "push", cmd_ok_stats, cmd_fail_stats)
                issued += 1
            except Exception as exc:
                cmd_fail_stats[f"push:exception:{type(exc).__name__}"] += 1
        active_assignments = sum(
            1
            for unit_id, target_id in push_targets.items()
            if s.world.get_entity(unit_id) is not None
            and target_id in structures_by_id
        )
        max_active_push_assignments = max(max_active_push_assignments, active_assignments)
        return issued

    def _spawn_building_reinforcements(loop: int) -> int:
        """A damaged building calls a small response group once per cooldown."""
        nonlocal processed_event_count
        spawned = 0
        new_events = s.world.events.emitted[processed_event_count:]
        processed_event_count = len(s.world.events.emitted)
        for event in new_events:
            if event.kind != "damage":
                continue
            structure = s.world.get_entity(event.entity_id)
            attacker = s.world.get_entity(event.payload.get("attacker", 0))
            if (
                structure is None
                or attacker is None
                or not structure.is_alive
                or structure.owner_player_id not in (3, 4, 5)
                or attacker.owner_player_id != 1
                or not s.world.catalog.get(structure.unit_type_id).is_structure
            ):
                continue
            if loop < reinforcement_cooldowns.get(structure.entity_id, -1):
                continue
            reinforcement_cooldowns[structure.entity_id] = loop + 44
            count = (
                1
                if clear_enemy_structures
                else (2 if wave_strength_scale <= 0.5 else 3)
            )
            for offset in range(count):
                spawn_result = s.unit_spawn(
                    "Zergling",
                    4,
                    structure.x.to_float() + (offset - 0.5) * 0.8,
                    structure.y.to_float() + (offset % 2 - 0.5) * 0.8,
                )
                unit = s.world.get_entity(spawn_result["entity_id"])
                if unit is None:
                    continue
                unit.expires_at_loop = loop + REINFORCEMENT_LIFETIME_LOOPS
                reinforcement_entity_ids.add(unit.entity_id)
                dynamic_enemy_entity_ids.add(unit.entity_id)
                entity_info_cache[unit.entity_id] = (
                    unit.unit_type_id,
                    unit.owner_player_id,
                )
                try:
                    s.unit_order(
                        [unit.entity_id],
                        "attack_move",
                        4,
                        target_x=PLAYER_BASE_X,
                        target_y=PLAYER_BASE_Y,
                    )
                except Exception:
                    pass
                spawned += 1
            ev = {
                "loop": loop,
                "kind": "building_reinforcements",
                "source_structure_id": structure.entity_id,
                "source_structure_type": structure.unit_type_id,
                "count": count,
                "ts_sec": round(loop / LOOPS_PER_SECOND, 1),
            }
            events_since_last_log.append(ev)
            all_key_events.append(ev)
        return spawned

    from .contracts import Observation

    try:
        while not eng.terminated and s.world.clock.now.loop < max_loops:
            if (
                wall_time_budget_sec is not None
                and time.time() - start_time >= wall_time_budget_sec
            ):
                eng.terminated = True
                eng.end_reason = "time_budget_exceeded"
                break
            cur = s.world.clock.now.loop
            current_night = _night_at_loop(cur)
            if current_night == 0 and last_night > 0:
                infected_cleared_in_day += _clear_daytime_infected(cur)
            elif current_night > 0 and current_night != last_night:
                infected_spawned += _spawn_infected_people(cur, current_night)
            last_night = current_night

            # 1. 触发波次（记录新触发的波次到事件累积器）
            # 记录 fire 前的 entity_id 集合，fire 后取差集得到波次单位 id
            pre_fire_ids = set(s.world.entities.keys())
            eng._fire_waves(cur)
            new_wave_ids = set(s.world.entities.keys()) - pre_fire_ids
            if new_wave_ids:
                wave_entity_ids.update(new_wave_ids)
                dynamic_enemy_entity_ids.update(new_wave_ids)
                # 给新波次单位立即发 attack_move 到玩家基地（让它们主动冲向基地）
                for nid in new_wave_ids:
                    try:
                        s.unit_order(
                            [nid],
                            "attack_move",
                            4,
                            target_x=PLAYER_BASE_X,
                            target_y=PLAYER_BASE_Y,
                        )
                    except Exception:
                        pass
            for w in waves:
                if w.name in eng._waves_fired and w.name not in recorded_waves:
                    ev = {
                        "loop": cur,
                        "kind": "wave_fired",
                        "wave_name": w.name,
                        "unit_count": len(w.spawns),
                        "ts_sec": round(cur / 22.4, 1),
                    }
                    events_since_last_log.append(ev)
                    all_key_events.append(ev)
                    recorded_waves.add(w.name)

            # 2. 推进一 loop
            s.scenario_step(1, snapshot=False)

            # 3. 触发敌方 AI（攻击玩家）
            eng._fire_triggers(cur)

            # 3.5 白天推进到建筑，夜间优先处理感染人/波次。
            if clear_enemy_structures and cur % CLEAR_PUSH_COMMAND_INTERVAL == 0:
                push_commands = _dispatch_structure_push(cur)
                total_commands_issued += push_commands
                total_commands_dispatched += push_commands
            building_reinforcements_spawned += _spawn_building_reinforcements(cur)

            # 4. 玩家 AI 决策（仅在决策间隔到达时构造 Observation，避免每 loop 都跑视野计算）
            if (
                policy is not None
                and cur - policy._last_decide_loop >= policy.command_interval
            ):
                obs = Observation.from_world(s.world, 1)
                # 查询 Player 1 资源，传给 policy 做经济决策
                p1_query = s.query_player(1)
                resources = {
                    "minerals": p1_query["resources"]["minerals"],
                    "vespene": p1_query["resources"]["vespene"],
                    "supply_used": p1_query["resources"].get("supply_used", 0),
                    "supply_cap": p1_query["resources"].get("supply_cap", 0),
                }
                actions = policy.decide(obs, cur, resources=resources)
                # 分发动作（立即执行，无延迟）
                # 每条命令的 CommandResult 失败原因被累计到 cmd_fail_stats，
                # 终局报告可见，不再用 except:pass 吞掉（自校验要求）
                for a in actions:
                    if a.kind == "hold":
                        continue
                    try:
                        unit = s.world.get_entity(a.entity_id)
                        if unit is None or not unit.is_alive:
                            cmd_fail_stats[f"{a.kind}:unit_missing"] += 1
                            continue
                        if a.kind == "attack":
                            if a.target_entity_id == 0:
                                cmd_fail_stats["attack:no_target"] += 1
                                continue
                            target = s.world.get_entity(a.target_entity_id)
                            if target is None or not target.is_alive:
                                cmd_fail_stats["attack:target_dead"] += 1
                                continue
                            pre = len(s.world.command_results)
                            s.unit_order(
                                [a.entity_id],
                                "attack_unit",
                                1,
                                target_entity_id=a.target_entity_id,
                            )
                            _tally_cmd_results(
                                s.world, pre, "attack", cmd_ok_stats, cmd_fail_stats
                            )
                            total_commands_dispatched += 1
                        elif a.kind == "move":
                            pre = len(s.world.command_results)
                            s.unit_order(
                                [a.entity_id],
                                "move",
                                1,
                                target_x=a.target_x,
                                target_y=a.target_y,
                            )
                            _tally_cmd_results(
                                s.world, pre, "move", cmd_ok_stats, cmd_fail_stats
                            )
                            total_commands_dispatched += 1
                        elif a.kind == "gather":
                            # SCV 采集：找最近 MineralField
                            target_id = a.target_entity_id
                            if target_id == 0:
                                target_id = _find_nearest_mineral_field(
                                    s.world, unit.x.to_float(), unit.y.to_float()
                                )
                            if target_id is None or target_id == 0:
                                cmd_fail_stats["gather:no_mineral"] += 1
                                continue
                            pre = len(s.world.command_results)
                            s.unit_order(
                                [a.entity_id], "smart", 1, target_entity_id=target_id
                            )
                            _tally_cmd_results(
                                s.world, pre, "gather", cmd_ok_stats, cmd_fail_stats
                            )
                            total_commands_dispatched += 1
                        elif a.kind == "train":
                            # 建筑 train unit_type_id
                            pre = len(s.world.command_results)
                            s.unit_order(
                                [a.entity_id], "train", 1, unit_type_id=a.unit_type_id
                            )
                            _tally_cmd_results(
                                s.world, pre, "train", cmd_ok_stats, cmd_fail_stats
                            )
                            total_commands_dispatched += 1
                        elif a.kind == "build":
                            # SCV build unit_type_id（简化：在基地附近建造）
                            pre = len(s.world.command_results)
                            s.unit_order(
                                [a.entity_id],
                                "build",
                                1,
                                unit_type_id=a.unit_type_id,
                                target_x=PLAYER_BASE_X + 3.0,
                                target_y=PLAYER_BASE_Y + 3.0,
                            )
                            _tally_cmd_results(
                                s.world, pre, "build", cmd_ok_stats, cmd_fail_stats
                            )
                            total_commands_dispatched += 1
                    except Exception as exc:
                        cmd_fail_stats[f"{a.kind}:exception:{type(exc).__name__}"] += 1
                total_commands_issued += len(actions)

            # 快速平衡模式：最后一夜触发后，战斗单位主动清扫本次波次单位。
            # 默认生存模式不改变原有 DefendBasePolicy 行为。
            if clear_waves_after_final and len(eng._waves_fired) >= len(waves):
                wave_targets = [
                    e
                    for eid in wave_entity_ids
                    for e in [s.world.get_entity(eid)]
                    if e is not None and e.is_alive
                ]
                sweep_units = [
                    e
                    for e in s.world.entities.values()
                    if e.owner_player_id == 1
                    and e.is_alive
                    and not s.world.catalog.get(e.unit_type_id).is_structure
                    and not s.world.catalog.get(e.unit_type_id).is_worker
                ]
                if wave_targets:
                    target = min(
                        wave_targets,
                        key=lambda e: (
                            (e.x.raw - PLAYER_BASE_X * 1024) ** 2
                            + (e.y.raw - PLAYER_BASE_Y * 1024) ** 2
                        ),
                    )
                    for unit in sweep_units:
                        try:
                            pre = len(s.world.command_results)
                            s.unit_order(
                                [unit.entity_id],
                                "attack_unit",
                                1,
                                target_entity_id=target.entity_id,
                            )
                            _tally_cmd_results(
                                s.world, pre, "sweep", cmd_ok_stats, cmd_fail_stats
                            )
                            total_commands_dispatched += 1
                            total_commands_issued += 1
                        except Exception as exc:
                            cmd_fail_stats[f"sweep:exception:{type(exc).__name__}"] += 1

            # 5. 检查目标
            eng._check_objectives(cur)

            # 6. 检查 Player 1 是否全灭
            p1_alive = any(
                e.owner_player_id == 1 and e.is_alive for e in s.world.entities.values()
            )
            if not p1_alive:
                eng.terminated = True
                eng.end_reason = "player_annihilated"
                break

            if clear_waves_after_final and len(eng._waves_fired) >= len(waves):
                wave_alive = any(
                    s.world.get_entity(eid) is not None
                    and s.world.get_entity(eid).is_alive
                    for eid in wave_entity_ids
                )
                if not wave_alive:
                    eng.terminated = True
                    eng.end_reason = "all_waves_cleared"
                    break

            # 7. 死锁检测
            if total_commands_dispatched == 0 and policy is not None:
                deadlock_loops += 1
            else:
                deadlock_loops = 0

            # 8. 死亡检测：基于 entity_id 集合差集
            # 模拟器在单位死亡后会从 entities 字典移除（而非保留 is_alive=False），
            # 所以用 "上一 loop 的 id 集合 - 当前 id 集合" 来检测死亡。
            cur_alive_ids = set(s.world.entities.keys())
            # 同时把新生成的实体加入缓存
            for eid, e in s.world.entities.items():
                if eid not in entity_info_cache:
                    entity_info_cache[eid] = (e.unit_type_id, e.owner_player_id)
            disappeared = last_alive_ids - cur_alive_ids
            for eid in disappeared:
                unit_t, owner = entity_info_cache.get(eid, ("unknown", -1))
                ev = {
                    "loop": cur,
                    "kind": "death",
                    "entity_id": eid,
                    "unit_type": unit_t,
                    "owner": owner,
                    "ts_sec": round(cur / 22.4, 1),
                }
                events_since_last_log.append(ev)
                all_key_events.append(ev)
                # 清理缓存（避免内存泄漏）
                entity_info_cache.pop(eid, None)
            last_alive_ids = cur_alive_ids

            # 9. 回放日志记录（按 interval）
            if cur - last_replay_loop >= replay_log_interval:
                last_replay_loop = cur
                p1_count = sum(
                    1
                    for e in s.world.entities.values()
                    if e.owner_player_id == 1 and e.is_alive
                )
                enemy_count = sum(
                    1
                    for e in s.world.entities.values()
                    if e.owner_player_id != 1 and e.is_alive and e.owner_player_id != 0
                )
                # 查询 P1 资源快照
                p1_res = s.query_player(1)["resources"]
                p1_resources_snapshot = {
                    "minerals": p1_res.get("minerals", 0),
                    "vespene": p1_res.get("vespene", 0),
                    "supply_used": p1_res.get("supply_used", 0),
                    "supply_cap": p1_res.get("supply_cap", 0),
                }
                _write_replay_frame(
                    replay_fp,
                    cur,
                    s.world,
                    len(eng._waves_fired),
                    total_commands_dispatched,
                    data.wave_timing["nights"],
                    time_scale,
                    p1_count,
                    enemy_count,
                    events_since_last_log,
                    p1_resources=p1_resources_snapshot,
                )
                # 写完后清空累积器
                events_since_last_log = []

            # 10. 进度报告
            if verbose and cur - last_report_loop >= report_interval:
                last_report_loop = cur
                p1_count = sum(
                    1
                    for e in s.world.entities.values()
                    if e.owner_player_id == 1 and e.is_alive
                )
                enemy_count = sum(
                    1
                    for e in s.world.entities.values()
                    if e.owner_player_id != 1 and e.is_alive and e.owner_player_id != 0
                )  # 排除中立 Player 0
                waves_fired = len(eng._waves_fired)
                p1_res = s.query_player(1)["resources"]
                elapsed = time.time() - start_time
                print(
                    f"  loop {cur}/{max_loops} ({cur / max_loops:.0%}) "
                    f"elapsed={elapsed:.1f}s | P1:{p1_count} Enemy:{enemy_count} "
                    f"Waves:{waves_fired}/{len(waves)} "
                    f"M:{p1_res.get('minerals', 0)} V:{p1_res.get('vespene', 0)} "
                    f"Sup:{p1_res.get('supply_used', 0)}/{p1_res.get('supply_cap', 0)} "
                    f"Cmds:{total_commands_dispatched} "
                    f"OK:{dict(cmd_ok_stats)} FAIL:{dict(cmd_fail_stats)}",
                    flush=True,
                )
    finally:
        # 写最后一帧 + 关闭日志文件（包含所有未写入的事件）
        try:
            cur = s.world.clock.now.loop
            p1_count = sum(
                1
                for e in s.world.entities.values()
                if e.owner_player_id == 1 and e.is_alive
            )
            enemy_count = sum(
                1
                for e in s.world.entities.values()
                if e.owner_player_id != 1 and e.is_alive and e.owner_player_id != 0
            )
            p1_res = s.query_player(1)["resources"]
            p1_resources_snapshot = {
                "minerals": p1_res.get("minerals", 0),
                "vespene": p1_res.get("vespene", 0),
                "supply_used": p1_res.get("supply_used", 0),
                "supply_cap": p1_res.get("supply_cap", 0),
            }
            _write_replay_frame(
                replay_fp,
                cur,
                s.world,
                len(eng._waves_fired),
                total_commands_dispatched,
                data.wave_timing["nights"],
                time_scale,
                p1_count,
                enemy_count,
                events_since_last_log,
                p1_resources=p1_resources_snapshot,
            )
        except Exception:
            pass
        replay_fp.close()

    # 计算结果
    elapsed = time.time() - start_time
    event_counts = _Counter(event.get("kind", "unknown") for event in all_key_events)
    event_payload_totals = _Counter()
    for event in all_key_events:
        count = event.get("count")
        if isinstance(count, int):
            event_payload_totals[event.get("kind", "unknown")] += count
    p1_survivors = sum(
        1 for e in s.world.entities.values() if e.owner_player_id == 1 and e.is_alive
    )
    enemy_survivors = {}
    for e in s.world.entities.values():
        if e.is_alive and e.owner_player_id != 1 and e.owner_player_id != 0:
            enemy_survivors[e.owner_player_id] = (
                enemy_survivors.get(e.owner_player_id, 0) + 1
            )

    initial_enemy_structures = sum(
        1
        for spawn in data.scenario["spawns"]
        if spawn["owner_player_id"] in (3, 4, 5)
        and s.world.catalog.get(spawn["unit_type_id"]).is_structure
    )
    remaining_enemy_structures = len(_enemy_structures())

    # 计算存活的夜晚数（按 time_scale 调整）
    nights_survived = 0
    for night in data.wave_timing["nights"]:
        scaled_end = int(night["end_loop"] * time_scale)
        if s.world.clock.now.loop >= scaled_end:
            nights_survived += 1

    # 判定胜负
    if eng.end_reason == "time_budget_exceeded":
        verdict = "inconclusive"
        summary = (
            f"达到 wall-clock 预算 {wall_time_budget_sec}s，"
            f"当前 loop {s.world.clock.now.loop}，剩余 {p1_survivors} 单位"
        )
    elif eng.end_reason == "all_objectives_success" and clear_enemy_structures:
        verdict = "victory"
        summary = (
            f"敌方全部建筑已摧毁，loop {s.world.clock.now.loop}，"
            f"感染生成 {infected_spawned}，建筑增援 {building_reinforcements_spawned}"
        )
    elif eng.end_reason == "all_waves_cleared":
        verdict = "victory"
        summary = (
            f"六夜波次全部清除，loop {s.world.clock.now.loop}，剩余 {p1_survivors} 单位"
        )
    elif clear_enemy_structures and s.world.clock.now.loop >= max_loops:
        verdict = "inconclusive"
        summary = (
            f"达到 loop 上限但仍有 {remaining_enemy_structures} 个敌方建筑，"
            f"感染生成 {infected_spawned}"
        )
    elif (
        not clear_waves_after_final
        and not clear_enemy_structures
        and p1_survivors > 0
        and s.world.clock.now.loop >= max_loops
    ):
        verdict = "victory"
        summary = f"玩家存活到 loop {s.world.clock.now.loop}，剩余 {p1_survivors} 单位"
    elif clear_waves_after_final and s.world.clock.now.loop >= max_loops:
        verdict = "inconclusive"
        summary = (
            f"六夜波次尚未全部清除，loop {s.world.clock.now.loop}，"
            f"剩余波次单位 {sum(enemy_survivors.values())}"
        )
    elif p1_survivors == 0:
        verdict = "defeat"
        summary = f"玩家在 loop {s.world.clock.now.loop} 全灭"
    else:
        verdict = "inconclusive"
        summary = f"对局未正常结束，loop {s.world.clock.now.loop}"

    simulation_time_sec = s.world.clock.now.loop / LOOPS_PER_SECOND
    logical_game_time_sec = simulation_time_sec / max(time_scale, 1e-9)
    victory_time_sec = logical_game_time_sec if verdict == "victory" else None

    report = GameReport(
        map_name=data.scenario["name"],
        end_loop=s.world.clock.now.loop,
        end_reason=eng.end_reason or "max_loops_reached",
        terminated=eng.terminated,
        player1_survivors=p1_survivors,
        enemy_survivors=enemy_survivors,
        total_waves_fired=len(eng._waves_fired),
        total_commands_issued=total_commands_issued,
        total_commands_dispatched=total_commands_dispatched,
        deadlock_detected=deadlock_loops >= 100,
        duration_sec=round(elapsed, 2),
        nights_survived=nights_survived,
        objectives=[
            {"name": o.name, "kind": o.kind, "status": o.status} for o in eng.objectives
        ],
        verdict=verdict,
        summary=summary,
        replay_log_path=str(replay_path),
        cmd_ok_stats=dict(cmd_ok_stats),
        cmd_fail_stats=dict(cmd_fail_stats),
        seed=seed,
        time_scale=time_scale,
        simulation_time_sec=round(simulation_time_sec, 4),
        logical_game_time_sec=round(logical_game_time_sec, 4),
        victory_time_sec=(
            round(victory_time_sec, 4) if victory_time_sec is not None else None
        ),
        wave_strength_scale=wave_strength_scale,
        victory_mode=(
            "clear_enemy_structures"
            if clear_enemy_structures
            else ("clear_waves" if clear_waves_after_final else "survive")
        ),
        initial_enemy_structures=initial_enemy_structures,
        remaining_enemy_structures=remaining_enemy_structures,
        infected_spawned=infected_spawned,
        infected_cleared_in_day=infected_cleared_in_day,
        building_reinforcements_spawned=building_reinforcements_spawned,
        structure_health_scale=structure_health_scale,
        push_unit_type=push_unit_type if clear_enemy_structures else "",
        event_summary={
            "counts": dict(sorted(event_counts.items())),
            "payload_totals": dict(sorted(event_payload_totals.items())),
            "total": len(all_key_events),
        },
        target_allocation_summary={
            "push_units_spawned": len(push_unit_ids),
            "push_units_dead_filtered": len(filtered_dead_push_unit_ids),
            "dispatch_cycles": push_dispatch_cycles,
            "allocations": push_target_allocations,
            "reallocations": push_target_reallocations,
            "reallocation_reasons": dict(sorted(push_target_reallocation_reasons.items())),
            "unique_targets_assigned": len(push_target_ids),
            "max_active_assignments": max_active_push_assignments,
        },
    )

    if verbose:
        print(f"\n=== 对局结束 ===")
        print(f"地图: {report.map_name}")
        print(f"结果: {report.verdict.upper()}")
        print(f"原因: {report.end_reason}")
        print(
            f"Loop: {report.end_loop}/{max_loops} ({report.end_loop / max_loops:.0%})"
        )
        print(f"耗时: {report.duration_sec}s")
        print(f"存活夜晚: {report.nights_survived}/{data.wave_timing['total_nights']}")
        print(f"Player 1 幸存: {report.player1_survivors}")
        print(f"敌方幸存: {report.enemy_survivors}")
        print(
            f"敌方建筑: {report.remaining_enemy_structures}/"
            f"{report.initial_enemy_structures}"
        )
        print(
            f"感染: 生成 {report.infected_spawned}, "
            f"白天清除 {report.infected_cleared_in_day}, "
            f"建筑增援 {report.building_reinforcements_spawned}"
        )
        print(f"建筑耐久压缩系数: {report.structure_health_scale}")
        print(f"波次触发: {report.total_waves_fired}/{len(waves)}")
        print(f"命令下发: {report.total_commands_issued}")
        print(f"命令执行: {report.total_commands_dispatched}")
        print(f"死锁: {report.deadlock_detected}")
        print(f"命令成功: {report.cmd_ok_stats}")
        print(f"命令失败: {report.cmd_fail_stats}")
        print(f"目标: {report.objectives}")
        print(f"总结: {report.summary}")

    return report


def main():
    parser = argparse.ArgumentParser(description="亡者之夜 AI 盟友自主对局")
    parser.add_argument(
        "--max-loops",
        type=int,
        default=15000,
        help="最大 loop 数（默认 15000，约 11 分钟）",
    )
    parser.add_argument(
        "--no-preset-enemies",
        action="store_true",
        help="不包含地图预放置的敌方单位（简化测试）",
    )
    parser.add_argument(
        "--no-enemy-ai", action="store_true", help="禁用敌方 AI（敌方不动）"
    )
    parser.add_argument(
        "--no-player-ai", action="store_true", help="禁用玩家 AI（玩家不动）"
    )
    parser.add_argument(
        "--time-scale",
        type=float,
        default=1.0,
        help="时间缩放系数（< 1.0 压缩昼夜循环；"
        "例如 0.1 让 Night 1 从 loop 4704 → 470）",
    )
    parser.add_argument("--quiet", action="store_true", help="静默模式（不打印进度）")
    parser.add_argument("--output", type=str, default=None, help="报告输出 JSON 路径")
    parser.add_argument(
        "--map-dir",
        type=str,
        default=None,
        help="地图解包目录；默认使用 cmre-runtime 路径",
    )
    parser.add_argument(
        "--mvp-fast",
        action="store_true",
        help="MVP 快速基准：普通窗口 1280/55s；清图窗口 2000/120s",
    )
    parser.add_argument(
        "--clear-enemy-structures",
        action="store_true",
        help="以摧毁全部敌方建筑为胜利条件，并启用昼夜感染规则",
    )
    parser.add_argument(
        "--push-army-size",
        type=int,
        default=None,
        help="清图模式开局集结的战斗单位数量（快速清图默认 128，普通模式默认 48）",
    )
    parser.add_argument(
        "--push-unit-type",
        default=None,
        help="清图模式开局集结的地面攻击单位类型（快速清图默认 Battlecruiser，普通模式默认 Marine）",
    )
    parser.add_argument("--seed", type=int, default=42, help="模拟器随机种子")
    args = parser.parse_args()

    clear_probe = args.mvp_fast and args.clear_enemy_structures
    max_loops = (
        2000
        if clear_probe
        else (1280 if args.mvp_fast else args.max_loops)
    )
    time_scale = 0.02 if args.mvp_fast else args.time_scale
    wall_time_budget_sec = (
        CLEAR_PROBE_WALL_TIME_BUDGET_SEC
        if clear_probe
        else (55.0 if args.mvp_fast else None)
    )

    report = run_dead_of_night(
        max_loops=max_loops,
        include_preset_enemies=False if args.mvp_fast else not args.no_preset_enemies,
        enable_enemy_ai=not args.no_enemy_ai,
        enable_player_ai=not args.no_player_ai,
        verbose=not args.quiet,
        time_scale=time_scale,
        map_dir=args.map_dir,
        wall_time_budget_sec=wall_time_budget_sec,
        seed=args.seed,
        wave_strength_scale=0.25 if args.mvp_fast else 1.0,
        clear_waves_after_final=False,
        clear_enemy_structures=args.clear_enemy_structures,
        push_army_size=(
            args.push_army_size
            if args.push_army_size is not None
            else (128 if args.mvp_fast else 48)
        ),
        push_unit_type=(
            args.push_unit_type
            if args.push_unit_type is not None
            else ("Battlecruiser" if clear_probe else "Marine")
        ),
        push_start_points=None,
    )

    if args.output:
        report_path = Path(args.output)
        report_data = {k: v for k, v in report.__dict__.items()}
        # 确保 report_path 父目录存在
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n报告已写入: {report_path}")

    return 0 if report.verdict == "victory" else 1


if __name__ == "__main__":
    sys.exit(main())
