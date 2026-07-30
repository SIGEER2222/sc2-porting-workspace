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
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .map_extractor import (
    extract_dead_of_night, MapData, PLAYER_FACTIONS, LOOPS_PER_SECOND,
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
    ("north", PLAYER_BASE_X, 160.0),   # 北
    ("east", 160.0, PLAYER_BASE_Y),    # 东
    ("south", PLAYER_BASE_X, 30.0),    # 南
    ("west", 30.0, PLAYER_BASE_Y),     # 西
]


def build_night_waves(wave_timing: dict, time_scale: float = 1.0) -> list[Wave]:
    """构造 6 个夜晚的波次。

    每个夜晚从 4 个方向刷怪，难度递增：
    - Night 1-2: Zergling 为主
    - Night 3-4: + Hydralisk
    - Night 5-6: + Roach + Mutalisk + Ultralisk

    Args:
        wave_timing: 波次时机数据
        time_scale: 时间缩放（< 1.0 压缩昼夜循环，便于测试）
    """
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
            template = [("Zergling", 8), ("Hydralisk", 3), ("Roach", 2),
                        ("Mutalisk", 1), ("Ultralisk", 1)]

        # 为每个方向创建一个 wave（错开 50 loops 让刷怪有层次）
        for dir_idx, (dir_name, sx, sy) in enumerate(SPAWN_DIRECTIONS):
            spawns = []
            for unit_type, count in template:
                for i in range(count):
                    # 在刷怪点附近散开
                    offset_x = (i % 3) * 1.5 - 1.5
                    offset_y = (i // 3) * 1.5 - 1.5
                    spawns.append({
                        "unit_type_id": unit_type,
                        "owner_player_id": 4,  # AMONS_FORCES
                        "x": sx + offset_x,
                        "y": sy + offset_y,
                    })
            waves.append(Wave(
                name=f"night{n}_{dir_name}",
                at_loop=start_loop + int(dir_idx * 50 * time_scale),
                spawns=spawns,
            ))
    return waves


# ---------------------------------------------------------------------------
# 触发器
# ---------------------------------------------------------------------------

def make_enemy_attack_trigger(
    name: str,
    enemy_player_id: int,
    target_player_id: int,
    cooldown: int = 44,  # 2 秒
) -> Trigger:
    """让指定敌方玩家的所有单位攻击目标玩家最近的单位。"""
    def condition(eng: MissionEngine) -> bool:
        s = eng.session
        if s.world is None:
            return False
        own = [e for e in s.world.entities.values()
               if e.owner_player_id == enemy_player_id and e.is_alive]
        targets = [e for e in s.world.entities.values()
                   if e.owner_player_id == target_player_id and e.is_alive]
        return bool(own and targets)

    def action(eng: MissionEngine) -> None:
        s = eng.session
        own = [e for e in s.world.entities.values()
               if e.owner_player_id == enemy_player_id and e.is_alive]
        targets = [e for e in s.world.entities.values()
                   if e.owner_player_id == target_player_id and e.is_alive]
        if not own or not targets:
            return
        for u in own:
            # 找最近的敌方单位
            nearest = min(targets, key=lambda e: (e.x.raw - u.x.raw) ** 2 + (e.y.raw - u.y.raw) ** 2)
            try:
                s.unit_order([u.entity_id], "attack_unit", enemy_player_id,
                             target_entity_id=nearest.entity_id)
            except Exception:
                pass  # 错误静默（单位可能已死）

    return Trigger(name, condition, action, cooldown=cooldown)


# ---------------------------------------------------------------------------
# DefendBasePolicy：玩家 AI 防守策略
# ---------------------------------------------------------------------------

@dataclass
class DefendAction:
    """玩家决策动作。"""
    entity_id: int
    kind: str  # "attack" | "hold" | "move"
    target_entity_id: int = 0
    target_x: float = 0.0
    target_y: float = 0.0
    reason: str = ""


class DefendBasePolicy:
    """防守基地策略。

    优先级（高→低）：
    1. 基地内威胁（敌方进入 base_region）→ attack 最近的威胁
    2. 近距威胁（敌方在 support_range 内）→ attack
    3. 低血量单位 → 后撤到基地
    4. 默认 → hold position（防守基地，不跟随）

    与 AllyPolicy 的区别：
    - 无 leader 概念，所有单位都受指挥
    - 无敌方时 hold 而非 follow（防守图不需要跟随）
    - 低血量单位后撤（保留战斗力）
    """

    def __init__(self, player_id: int,
                 base_region: tuple[float, float, float] = (PLAYER_BASE_X, PLAYER_BASE_Y, 15.0),
                 support_range: float = 12.0,
                 retreat_threshold: float = 0.3,  # 血量低于 30% 后撤
                 command_interval: int = 22):  # 1 秒决策一次
        self.player_id = player_id
        self.base_x, self.base_y, self.base_r = base_region
        self.support_range = support_range
        self.retreat_threshold = retreat_threshold
        self.command_interval = command_interval
        self._last_decide_loop = -10_000
        self._last_actions: list[DefendAction] = []

    def decide(self, obs, loop: int) -> list[DefendAction]:
        """根据 Observation 决策。

        obs 应有：
        - own_units: [{entity_id, unit_type_id, x, y, health, ...}, ...]
        - visible_enemies: [{entity_id, x, y, ...}, ...]
        """
        if loop - self._last_decide_loop < self.command_interval:
            return self._last_actions
        self._last_decide_loop = loop

        own_by_id = {u["entity_id"]: u for u in obs.own_units}
        enemies = obs.visible_enemies
        actions: list[DefendAction] = []

        # 基地内威胁
        base_threats = [e for e in enemies
                        if self._dist(e["x"], e["y"], self.base_x, self.base_y) <= self.base_r]
        # 近距威胁（任意己方单位周围 support_range 内）
        near_threats = []
        for u in obs.own_units:
            for e in enemies:
                if self._dist(e["x"], e["y"], u["x"], u["y"]) <= self.support_range:
                    near_threats.append(e)
        # 去重
        near_threats = list({e["entity_id"]: e for e in near_threats}.values())

        for uid, u in own_by_id.items():
            # 低血量单位后撤
            hp_ratio = self._hp_ratio(u)
            if hp_ratio < self.retreat_threshold and not base_threats:
                actions.append(DefendAction(
                    uid, "move",
                    target_x=self.base_x, target_y=self.base_y,
                    reason=f"retreat_low_hp({hp_ratio:.0%})",
                ))
                continue

            if base_threats:
                tgt = self._nearest(u, base_threats)
                actions.append(DefendAction(uid, "attack",
                                            target_entity_id=tgt["entity_id"],
                                            reason="base_threat"))
            elif near_threats:
                tgt = self._nearest(u, near_threats)
                actions.append(DefendAction(uid, "attack",
                                            target_entity_id=tgt["entity_id"],
                                            reason="near_threat"))
            else:
                # hold position（不发出命令）
                actions.append(DefendAction(uid, "hold", reason="defend_base"))

        self._last_actions = actions
        return actions

    @staticmethod
    def _dist(x1, y1, x2, y2) -> float:
        return math.hypot(x1 - x2, y1 - y2)

    @staticmethod
    def _nearest(unit: dict, candidates: list[dict]) -> dict:
        return min(candidates, key=lambda c: DefendBasePolicy._dist(
            unit["x"], unit["y"], c["x"], c["y"]))

    @staticmethod
    def _hp_ratio(unit: dict) -> float:
        """计算血量比例。health 是 raw int（Fixed），需除以 1024。"""
        health = unit.get("health", 0)
        # health 是 raw int，1024 = 1.0；不同单位 max_health 不同
        # 简化：用 health > 0 判断存活，用 health/max_health 估算
        # 这里用 health 值估算（Marine 45*1024=46080, SCV 45*1024=46080）
        # 简化：health < 30000 视为低血量（约 30 HP）
        if health == 0:
            return 0.0
        # 用单位类型估算 max_health
        max_hp_map = {
            "Marine": 45, "Marauder": 125, "SCV": 45, "SiegeTank": 160,
            "Medivac": 150, "CommandCenter": 1400, "Bunker": 400,
            "Barracks": 800, "SupplyDepot": 400, "EngineeringBay": 850,
            "MissileTurret": 250,
        }
        max_hp = max_hp_map.get(unit.get("unit_type_id", ""), 100)
        return min(1.0, health / 1024.0 / max_hp)


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


def _write_replay_frame(fp, loop: int, world, waves_fired: int, total_cmds: int,
                        nights_data: dict, time_scale: float,
                        p1_alive_count: int, enemy_alive_count: int,
                        key_events_this_frame: list[dict]) -> None:
    """写一帧回放日志到 JSONL 文件。

    key_events_this_frame: 仅本帧新发生的事件（已去重），避免历史事件在多帧中重复出现。
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
            p1_units_by_type[e.unit_type_id] = p1_units_by_type.get(e.unit_type_id, 0) + 1
        elif e.owner_player_id != 0:
            enemy_units_by_type[e.unit_type_id] = enemy_units_by_type.get(e.unit_type_id, 0) + 1

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
    }
    fp.write(_json.dumps(frame, ensure_ascii=False) + "\n")
    fp.flush()


def run_dead_of_night(
    max_loops: int = 15000,  # 约 11 分钟，覆盖 2-3 个夜晚
    include_preset_enemies: bool = True,
    enable_enemy_ai: bool = True,
    enable_player_ai: bool = True,
    verbose: bool = True,
    time_scale: float = 1.0,  # 时间缩放（< 1.0 压缩昼夜循环，便于测试）
    replay_log_path: Optional[str] = None,  # JSONL 回放日志路径；None 则自动生成
    replay_log_interval: int = 100,  # 每 N loop 记录一帧
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
    """
    start_time = time.time()

    # 1. 提取地图数据
    if verbose:
        print("[1/4] 提取亡者之夜地图数据...")
    data = extract_dead_of_night()

    # 过滤预放置敌方单位（如不需要）
    if not include_preset_enemies:
        enemy_players = {3, 4, 5}
        data.scenario["spawns"] = [
            s for s in data.scenario["spawns"]
            if s["owner_player_id"] not in enemy_players
        ]
        # 显式保留 Player 3/4/5 的玩家声明（即使无预放置单位）。
        # 波次系统会为 Player 4（AMONS_FORCES）生成单位，若从 players 列表移除
        # 会导致模拟器 enemies_of() 抛出 KeyError。
        from .map_extractor import PLAYER_FACTIONS
        existing_ids = {p["id"] for p in data.scenario["players"]}
        for pid in (3, 4, 5):
            if pid not in existing_ids:
                f = PLAYER_FACTIONS.get(pid, {"name": f"Player{pid}", "race": "zerg"})
                data.scenario["players"].append({
                    "id": pid, "name": f["name"], "race": f["race"],
                    "allies": [], "is_ai": True,
                })
        data.scenario["players"].sort(key=lambda p: p["id"])
        if verbose:
            print(f"  过滤预放置敌方单位后: {len(data.scenario['spawns'])} 单位"
                  f"（保留 Player 3/4/5 用于波次生成）")

    # 注意：不过滤 Player 0 的中立单位（MineralField 等）。
    # 它们不参与战斗，但保留可防止模拟器误触 annihilation 胜利条件
    # （当只有 Player 1 存活时会提前终止模拟）。
    # 在进度报告和结果统计中已排除 Player 0。

    # 2. 构造 mission
    if verbose:
        print("[2/4] 构造波次 mission...")
    waves = build_night_waves(data.wave_timing, time_scale=time_scale)
    if verbose:
        total_wave_units = sum(len(w.spawns) for w in waves)
        first_night = waves[0].at_loop if waves else 0
        print(f"  {len(waves)} 个波次, 共 {total_wave_units} 个刷怪单位, "
              f"首夜 @ loop {first_night} (time_scale={time_scale})")

    # 3. 加载场景
    if verbose:
        print("[3/4] 加载场景到模拟器...")
    s = SimulatorSession()
    s.scenario_load(scenario_dict=data.scenario, catalog="m7")
    s.scenario_reset()
    if verbose:
        print(f"  初始单位数: {len(s.world.entities)}")
        p1_count = sum(1 for e in s.world.entities.values() if e.owner_player_id == 1)
        print(f"  Player 1 单位数: {p1_count}")

    # 准备回放日志文件
    if replay_log_path is None:
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        replay_log_path = str(
            Path(__file__).resolve().parents[1] / "artifacts" / f"dead_of_night_replay_{ts}.jsonl"
        )
    replay_path = Path(replay_log_path)
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    replay_fp = open(replay_path, "w", encoding="utf-8")
    if verbose:
        print(f"  回放日志: {replay_path}")

    # 构造 MissionEngine
    eng = MissionEngine(s)

    # 添加区域（基地 + 刷怪点）
    eng.add_region(Region(name="player_base", kind="circle",
                          x=PLAYER_BASE_X, y=PLAYER_BASE_Y, r=15.0))
    for dir_name, sx, sy in SPAWN_DIRECTIONS:
        eng.add_region(Region(name=f"spawn_{dir_name}", kind="circle",
                              x=sx, y=sy, r=5.0))

    # 添加波次
    for w in waves:
        eng.add_wave(w)

    # 添加目标：存活到 max_loops
    eng.add_objective(Objective(
        name="survive", kind="survive_loops",
        params={"target_loops": max_loops},
    ))

    # 添加触发器：敌方攻击玩家
    if enable_enemy_ai:
        for enemy_pid in (3, 4, 5):
            # 检查该玩家是否有单位
            has_units = any(p["id"] == enemy_pid for p in data.scenario["players"])
            if has_units:
                eng.add_trigger(make_enemy_attack_trigger(
                    name=f"enemy_p{enemy_pid}_attack",
                    enemy_player_id=enemy_pid,
                    target_player_id=1,
                    cooldown=44,  # 2 秒
                ))
        # 波次刷怪也攻击
        eng.add_trigger(make_enemy_attack_trigger(
            name="wave_enemies_attack",
            enemy_player_id=4,  # 波次单位属于 Player 4
            target_player_id=1,
            cooldown=44,
        ))

    # 4. 运行对局
    if verbose:
        print(f"[4/4] 运行对局 (max_loops={max_loops})...")

    # 玩家 AI
    policy = DefendBasePolicy(player_id=1) if enable_player_ai else None

    # 命令统计
    total_commands_issued = 0
    total_commands_dispatched = 0
    deadlock_loops = 0
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

    from .contracts import Observation

    try:
        while not eng.terminated and s.world.clock.now.loop < max_loops:
            cur = s.world.clock.now.loop

            # 1. 触发波次（记录新触发的波次到事件累积器）
            eng._fire_waves(cur)
            for w in waves:
                if w.name in eng._waves_fired and w.name not in recorded_waves:
                    ev = {
                        "loop": cur, "kind": "wave_fired",
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

            # 4. 玩家 AI 决策（仅在决策间隔到达时构造 Observation，避免每 loop 都跑视野计算）
            if policy is not None and cur - policy._last_decide_loop >= policy.command_interval:
                obs = Observation.from_world(s.world, 1)
                actions = policy.decide(obs, cur)
                # 分发动作（立即执行，无延迟）
                for a in actions:
                    if a.kind == "hold":
                        continue
                    try:
                        unit = s.world.get_entity(a.entity_id)
                        if unit is None or not unit.is_alive:
                            continue
                        if a.kind == "attack":
                            if a.target_entity_id == 0:
                                continue
                            target = s.world.get_entity(a.target_entity_id)
                            if target is None or not target.is_alive:
                                continue
                            s.unit_order([a.entity_id], "attack_unit", 1,
                                         target_entity_id=a.target_entity_id)
                            total_commands_dispatched += 1
                        elif a.kind == "move":
                            s.unit_order([a.entity_id], "move", 1,
                                         target_x=a.target_x, target_y=a.target_y)
                            total_commands_dispatched += 1
                    except Exception:
                        pass  # 错误静默
                total_commands_issued += len(actions)

            # 5. 检查目标
            eng._check_objectives(cur)

            # 6. 检查 Player 1 是否全灭
            p1_alive = any(e.owner_player_id == 1 and e.is_alive
                           for e in s.world.entities.values())
            if not p1_alive:
                eng.terminated = True
                eng.end_reason = "player_annihilated"
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
                    "loop": cur, "kind": "death",
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
                p1_count = sum(1 for e in s.world.entities.values()
                               if e.owner_player_id == 1 and e.is_alive)
                enemy_count = sum(1 for e in s.world.entities.values()
                                  if e.owner_player_id != 1 and e.is_alive
                                  and e.owner_player_id != 0)
                _write_replay_frame(
                    replay_fp, cur, s.world, len(eng._waves_fired),
                    total_commands_dispatched, data.wave_timing["nights"],
                    time_scale, p1_count, enemy_count, events_since_last_log,
                )
                # 写完后清空累积器
                events_since_last_log = []

            # 10. 进度报告
            if verbose and cur - last_report_loop >= report_interval:
                last_report_loop = cur
                p1_count = sum(1 for e in s.world.entities.values()
                               if e.owner_player_id == 1 and e.is_alive)
                enemy_count = sum(1 for e in s.world.entities.values()
                                  if e.owner_player_id != 1 and e.is_alive
                                  and e.owner_player_id != 0)  # 排除中立 Player 0
                waves_fired = len(eng._waves_fired)
                elapsed = time.time() - start_time
                print(f"  loop {cur}/{max_loops} ({cur/max_loops:.0%}) "
                      f"elapsed={elapsed:.1f}s | P1:{p1_count} Enemy:{enemy_count} "
                      f"Waves:{waves_fired}/{len(waves)} Cmds:{total_commands_dispatched}",
                      flush=True)
    finally:
        # 写最后一帧 + 关闭日志文件（包含所有未写入的事件）
        try:
            cur = s.world.clock.now.loop
            p1_count = sum(1 for e in s.world.entities.values()
                           if e.owner_player_id == 1 and e.is_alive)
            enemy_count = sum(1 for e in s.world.entities.values()
                              if e.owner_player_id != 1 and e.is_alive
                              and e.owner_player_id != 0)
            _write_replay_frame(
                replay_fp, cur, s.world, len(eng._waves_fired),
                total_commands_dispatched, data.wave_timing["nights"],
                time_scale, p1_count, enemy_count, events_since_last_log,
            )
        except Exception:
            pass
        replay_fp.close()

    # 计算结果
    elapsed = time.time() - start_time
    p1_survivors = sum(1 for e in s.world.entities.values()
                       if e.owner_player_id == 1 and e.is_alive)
    enemy_survivors = {}
    for e in s.world.entities.values():
        if e.is_alive and e.owner_player_id != 1 and e.owner_player_id != 0:
            enemy_survivors[e.owner_player_id] = enemy_survivors.get(e.owner_player_id, 0) + 1

    # 计算存活的夜晚数（按 time_scale 调整）
    nights_survived = 0
    for night in data.wave_timing["nights"]:
        scaled_end = int(night["end_loop"] * time_scale)
        if s.world.clock.now.loop >= scaled_end:
            nights_survived += 1

    # 判定胜负
    if p1_survivors > 0 and s.world.clock.now.loop >= max_loops:
        verdict = "victory"
        summary = f"玩家存活到 loop {s.world.clock.now.loop}，剩余 {p1_survivors} 单位"
    elif p1_survivors == 0:
        verdict = "defeat"
        summary = f"玩家在 loop {s.world.clock.now.loop} 全灭"
    else:
        verdict = "inconclusive"
        summary = f"对局未正常结束，loop {s.world.clock.now.loop}"

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
        objectives=[{"name": o.name, "kind": o.kind, "status": o.status} for o in eng.objectives],
        verdict=verdict,
        summary=summary,
        replay_log_path=str(replay_path),
    )

    if verbose:
        print(f"\n=== 对局结束 ===")
        print(f"地图: {report.map_name}")
        print(f"结果: {report.verdict.upper()}")
        print(f"原因: {report.end_reason}")
        print(f"Loop: {report.end_loop}/{max_loops} ({report.end_loop/max_loops:.0%})")
        print(f"耗时: {report.duration_sec}s")
        print(f"存活夜晚: {report.nights_survived}/{data.wave_timing['total_nights']}")
        print(f"Player 1 幸存: {report.player1_survivors}")
        print(f"敌方幸存: {report.enemy_survivors}")
        print(f"波次触发: {report.total_waves_fired}/{len(waves)}")
        print(f"命令下发: {report.total_commands_issued}")
        print(f"命令执行: {report.total_commands_dispatched}")
        print(f"死锁: {report.deadlock_detected}")
        print(f"目标: {report.objectives}")
        print(f"总结: {report.summary}")

    return report


def main():
    parser = argparse.ArgumentParser(description="亡者之夜 AI 盟友自主对局")
    parser.add_argument("--max-loops", type=int, default=15000,
                        help="最大 loop 数（默认 15000，约 11 分钟）")
    parser.add_argument("--no-preset-enemies", action="store_true",
                        help="不包含地图预放置的敌方单位（简化测试）")
    parser.add_argument("--no-enemy-ai", action="store_true",
                        help="禁用敌方 AI（敌方不动）")
    parser.add_argument("--no-player-ai", action="store_true",
                        help="禁用玩家 AI（玩家不动）")
    parser.add_argument("--time-scale", type=float, default=1.0,
                        help="时间缩放系数（< 1.0 压缩昼夜循环；"
                             "例如 0.1 让 Night 1 从 loop 4704 → 470）")
    parser.add_argument("--quiet", action="store_true",
                        help="静默模式（不打印进度）")
    parser.add_argument("--output", type=str, default=None,
                        help="报告输出 JSON 路径")
    args = parser.parse_args()

    report = run_dead_of_night(
        max_loops=args.max_loops,
        include_preset_enemies=not args.no_preset_enemies,
        enable_enemy_ai=not args.no_enemy_ai,
        enable_player_ai=not args.no_player_ai,
        verbose=not args.quiet,
        time_scale=args.time_scale,
    )

    if args.output:
        report_path = Path(args.output)
        report_data = {k: v for k, v in report.__dict__.items()}
        # 确保 report_path 父目录存在
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已写入: {report_path}")

    return 0 if report.verdict == "victory" else 1


if __name__ == "__main__":
    sys.exit(main())
