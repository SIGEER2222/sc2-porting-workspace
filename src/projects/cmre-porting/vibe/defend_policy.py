"""防守基地策略 + 经济管理（正式模块化版本）。

本模块从 run_dead_of_night.py 提取，消除 run_dead_of_night_live.py 的 exec 动态提取 hack。
设计原则：只依赖 dataclass/math/typing，不依赖 simulator_session / sc2_simulator，
使真机 runner（run_dead_of_night_live.py）和模拟器 runner（run_dead_of_night.py）
都能直接 import。

借鉴：
- sharpy-sc2 的 reserve 池（解决资源争抢）
- ares-sc2 的比例+优先级配兵 dict（替代 if/elif 链）
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# 基地坐标（亡者之夜玩家出生点）
PLAYER_BASE_X = 85.0
PLAYER_BASE_Y = 94.0


@dataclass
class DefendAction:
    """玩家决策动作。"""
    entity_id: int
    kind: str  # "attack" | "hold" | "move" | "gather" | "train" | "build"
    target_entity_id: int = 0
    target_x: float = 0.0
    target_y: float = 0.0
    unit_type_id: str = ""  # train/build 用
    reason: str = ""


class EconomyState:
    """每帧清零的资源预留池（借鉴 sharpy-sc2 Knowledge.reserve）。

    解决"AI 只造 SCV 不造兵"问题：先为高优先级战斗单位预留资源，
    再让 SCV 训练通过 can_afford 检查（已扣预留），自然不会抢光矿物。
    """
    __slots__ = ("reserved_minerals", "reserved_vespene")

    def __init__(self):
        self.reserved_minerals = 0
        self.reserved_vespene = 0

    def reset(self) -> None:
        self.reserved_minerals = 0
        self.reserved_vespene = 0

    def reserve(self, minerals: int, vespene: int) -> None:
        self.reserved_minerals += minerals
        self.reserved_vespene += vespene

    def can_afford(self, minerals: int, vespene: int,
                   have_min: int, have_gas: int) -> bool:
        return (minerals <= have_min - self.reserved_minerals
                and vespene <= have_gas - self.reserved_vespene)


class DefendBasePolicy:
    """防守基地策略 + 经济管理。

    优先级（高→低）：
    1. 基地内威胁（敌方进入 base_region）→ attack 最近的威胁
    2. 近距威胁（敌方在 support_range 内）→ attack
    3. 低血量战斗单位 → 后撤到基地
    4. SCV 经济管理：空闲 SCV 采集最近的矿物
    5. 战斗单位生产（按比例+优先级配兵 dict）
    6. SCV 生产（受 reserve 池约束，不抢战斗单位的资源）
    7. 默认 → hold position（防守基地）
    """

    # 单位类型分类
    WORKER_TYPES = {"SCV", "Probe", "Drone"}
    BUILDING_TYPES = {
        "CommandCenter", "OrbitalCommand", "PlanetaryFortress", "SupplyDepot",
        "Refinery", "Barracks", "Factory", "Starport", "EngineeringBay",
        "MissileTurret", "Bunker", "SensorTower", "BarracksTechLab",
        "BarracksReactor", "FactoryTechLab", "FactoryReactor", "StarportTechLab",
        "StarportReactor",
    }
    # Mission/commander caster units can appear in raw observations but do not
    # expose a weapon. They must not be treated as combat units by the policy.
    NON_COMBAT_TYPES = {
        "CoopCasterRaynor",
        "CoopCasterFenix",
        "CoopAssistCasterRaynor",
        "CoopAssistCasterFenix",
    }
    PRODUCER_TYPES = {
        "CommandCenter": ["SCV"],
        "Barracks": ["Marine", "Marauder"],
        "Factory": ["Hellion", "SiegeTank"],
        "Starport": ["Medivac", "Viking"],
    }

    # 战术配兵 dict（借鉴 ares-sc2 SpawnController）
    # priority 数字小=优先级高；proportion=目标比例
    # 顺序：SiegeTank > Medivac > Marine > Marauder
    ARMY_COMP = {
        "SiegeTank": {"proportion": 0.20, "priority": 0, "producer": "Factory",
                      "min_m": 150, "min_v": 125, "supply": 3},
        "Medivac":  {"proportion": 0.15, "priority": 1, "producer": "Starport",
                      "min_m": 100, "min_v": 100, "supply": 2},
        "Marine":   {"proportion": 0.50, "priority": 2, "producer": "Barracks",
                      "min_m": 50,  "min_v": 0,   "supply": 1},
        "Marauder": {"proportion": 0.15, "priority": 3, "producer": "Barracks",
                      "min_m": 100, "min_v": 25,  "supply": 2},
    }

    # The native opening must establish production before the army policy can
    # train units.  Keep this list deterministic so a trace can prove which
    # SCV built which missing structure.
    BUILD_PLAN = (
        {"unit_type_id": "Barracks", "min_m": 150, "min_v": 0, "offset": (5.0, 0.0)},
        {"unit_type_id": "Refinery", "min_m": 75, "min_v": 0, "offset": (0.0, 5.0)},
    )

    # SCV 训练参数
    SCV_COST_M = 50
    SCV_COST_V = 0
    SCV_SUPPLY = 1
    # SCV 数量阈值：低于此值时 SCV 训练优先级提升；高于此值时让位给战斗单位
    SCV_FLOOR = 4      # 低于此值强制造 SCV（即使抢资源）
    SCV_CEIL = 16      # 达到此值停止造 SCV

    def __init__(self, player_id: int,
                 base_region: tuple[float, float, float] = (PLAYER_BASE_X, PLAYER_BASE_Y, 15.0),
                 support_range: float = 12.0,
                 retreat_threshold: float = 0.3,  # 血量低于 30% 后撤
                 command_interval: int = 22,  # 1 秒决策一次
                 econ_interval: int = 44,  # 2 秒决策一次经济（更积极训练）
                 minerals_floor: int = 0,  # 不保留矿物下限（有矿物就训练）
                 ):
        self.player_id = player_id
        self.base_x, self.base_y, self.base_r = base_region
        self.support_range = support_range
        self.retreat_threshold = retreat_threshold
        self.command_interval = command_interval
        self.econ_interval = econ_interval
        self.minerals_floor = minerals_floor
        self._last_decide_loop = -10_000
        self._last_econ_loop = -10_000
        self._last_actions: list[DefendAction] = []
        # 已发过采集命令的 SCV id 集合（避免重复发命令）
        self._gathering_scvs: set[int] = set()
        # 已发过训练命令的建筑 id 集合（本轮已发，等下一轮）
        self._producers_in_queue: set[int] = set()
        self._build_issued: set[str] = set()
        # 资源预留池（借鉴 sharpy-sc2 Knowledge.reserve）
        # 每个经济决策周期开头 reset()，先为高优先级战斗单位 reserve，
        # 再让 SCV 训练通过 can_afford 检查（已扣预留）
        self._econ = EconomyState()

    def decide(self, obs, loop: int, resources: Optional[dict] = None) -> list[DefendAction]:
        """根据 Observation 决策。

        obs 应有：
        - own_units: [{entity_id, unit_type_id, x, y, health, ...}, ...]
        - visible_enemies: [{entity_id, x, y, ...}, ...]

        resources 可选：{"minerals": int, "vespene": int, "supply_used": int, "supply_cap": int}
        """
        if loop - self._last_decide_loop < self.command_interval:
            return self._last_actions
        self._last_decide_loop = loop

        own_by_id = {u["entity_id"]: u for u in obs.own_units}
        enemies = obs.visible_enemies
        actions: list[DefendAction] = []

        # ===== 战斗决策 =====
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

        # 收集需要战斗的单位和非战斗单位
        combat_units = []
        econ_units = []  # SCV 等工人
        producers = []  # 兵营/基地等生产建筑
        for uid, u in own_by_id.items():
            ut = u.get("unit_type_id", "")
            if ut in self.WORKER_TYPES:
                econ_units.append(u)
            elif ut in self.PRODUCER_TYPES:
                producers.append(u)
            elif ut in self.NON_COMBAT_TYPES or ut in self.BUILDING_TYPES:
                continue
            else:
                combat_units.append(u)

        # 战斗决策：战斗单位优先处理威胁
        for u in combat_units:
            uid = u["entity_id"]
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
                actions.append(DefendAction(uid, "hold", reason="defend_base"))

        # SCV 决策：有基地威胁时撤退到基地，否则保持采集
        for u in econ_units:
            uid = u["entity_id"]
            if base_threats:
                # 基地受袭，SCV 撤退（避免被屠农）
                actions.append(DefendAction(
                    uid, "move",
                    target_x=self.base_x, target_y=self.base_y,
                    reason="worker_retreat_base_threat",
                ))
            else:
                # 保持采集（已采集的 SCV 不重复发命令）
                if uid not in self._gathering_scvs:
                    actions.append(DefendAction(uid, "hold", reason="worker_idle"))
                # 不发动作 = 保持当前状态（采集中的 SCV 会继续采集）

        # ===== 经济决策（较低频率）=====
        econ_due = loop - self._last_econ_loop >= self.econ_interval
        if econ_due and resources is not None:
            self._last_econ_loop = loop
            self._producers_in_queue.clear()  # 新一轮，清空队列记录
            econ_actions = self._decide_economy(obs, resources, econ_units, producers, enemies)
            actions.extend(econ_actions)

        self._last_actions = actions
        return actions

    def _decide_economy(self, obs, resources: dict,
                        econ_units: list[dict], producers: list[dict],
                        enemies: list[dict]) -> list[DefendAction]:
        """经济决策：SCV 建造/采集 + 战斗单位配兵 + SCV 训练。

        决策顺序（借鉴 sharpy reserve 池 + ares 比例配兵）：
        1. 重置 reserve 池
        2. 缺少兵营/气矿时派空闲 SCV 建造
        3. 其余空闲 SCV 派去采集
        4. 按配兵 dict 优先级训练战斗单位
        5. SCV 训练：通过 can_afford 检查，SCV 数量 >= SCV_CEIL 时停止
        """
        actions: list[DefendAction] = []
        # 每个经济决策周期开头重置 reserve 池
        self._econ.reset()

        minerals = resources.get("minerals", 0)
        vespene = resources.get("vespene", 0)
        supply_used = resources.get("supply_used", 0)
        supply_cap = resources.get("supply_cap", 200)
        supply_remaining = supply_cap - supply_used

        # 1. Build the native production opening before training or gathering.
        builder_ids: set[int] = set()
        for build in self.BUILD_PLAN:
            building_type = build["unit_type_id"]
            if any(u.get("unit_type_id") == building_type for u in obs.own_units):
                self._build_issued.discard(building_type)
                continue
            if building_type in self._build_issued:
                continue
            if not self._econ.can_afford(
                    build["min_m"], build["min_v"], minerals, vespene):
                continue
            builder = next(
                (
                    worker for worker in econ_units
                    if worker["entity_id"] not in builder_ids
                    and not worker.get("orders")
                ),
                None,
            )
            if builder is None:
                continue
            offset_x, offset_y = build["offset"]
            actions.append(DefendAction(
                builder["entity_id"],
                "build",
                target_x=self.base_x + offset_x,
                target_y=self.base_y + offset_y,
                unit_type_id=building_type,
                reason=f"build_{building_type}",
            ))
            builder_ids.add(builder["entity_id"])
            self._build_issued.add(building_type)
            self._econ.reserve(build["min_m"], build["min_v"])
            minerals -= build["min_m"]
            vespene -= build["min_v"]

        # 2. Empty SCVs gather minerals. A builder is never double-booked.
        for u in econ_units:
            uid = u["entity_id"]
            if uid not in builder_ids and uid not in self._gathering_scvs:
                actions.append(DefendAction(
                    uid, "gather",
                    target_entity_id=0,  # runner 会替换为最近 MineralField id
                    reason="gather_minerals",
                ))
                self._gathering_scvs.add(uid)

        # 3. 战斗单位配兵（按 ARMY_COMP 的 priority 升序：0=最高优先）
        # 统计现有战斗单位总数和各兵种数量（含训练中）
        own_types: dict[str, int] = {}
        for u in obs.own_units:
            t = u.get("unit_type_id", "")
            own_types[t] = own_types.get(t, 0) + 1
        combat_total = sum(own_types.get(t, 0) for t in self.ARMY_COMP)
        scv_count = own_types.get("SCV", 0)

        # 按 priority 升序遍历（SiegeTank=0, Medivac=1, Marine=2, Marauder=3）
        # MIN_ARMY_BEFORE_PROP：军队规模小于此值时无视比例，按优先级扩张
        MIN_ARMY_BEFORE_PROP = 24
        for unit_type, info in sorted(self.ARMY_COMP.items(),
                                       key=lambda x: x[1]["priority"]):
            # 比例检查：当前比例 >= 目标比例 且 军队已足够大时才跳过
            # 军队小时无视比例持续扩产（借鉴 ares over_produce_on_low_tech）
            current_prop = own_types.get(unit_type, 0) / max(combat_total, 1)
            if (current_prop >= info["proportion"]
                    and combat_total >= MIN_ARMY_BEFORE_PROP):
                continue
            # 资源检查（用 can_afford 扣除已 reserve 的部分）
            if not self._econ.can_afford(info["min_m"], info["min_v"],
                                          minerals, vespene):
                # 造不起本兵种 → continue 尝试更便宜的低优先级兵种
                # （原 ares 模式用 break 锁资源给高优先级，但前提是收入能攒够；
                #  这里经济规模小，break 会导致 Marine 永远造不出，故用 continue）
                continue
            if supply_remaining < info["supply"]:
                continue
            # 找空闲生产建筑
            producer_type = info["producer"]
            idle_producer = None
            for p in producers:
                if p.get("unit_type_id") != producer_type:
                    continue
                if (p["entity_id"] in self._producers_in_queue
                        or p.get("orders")):
                    continue
                idle_producer = p
                break
            if idle_producer is None:
                # 没有空闲建筑 → reserve 资源（sharpy ActUnit priority 模式），
                # 让后续低优先级单位造不起，避免抢资源
                self._econ.reserve(info["min_m"], info["min_v"])
                continue
            # 下单
            actions.append(DefendAction(
                idle_producer["entity_id"], "train",
                unit_type_id=unit_type,
                reason=f"train_{unit_type}(prop={current_prop:.0%}/{info['proportion']:.0%})",
            ))
            self._producers_in_queue.add(idle_producer["entity_id"])
            # 虚拟扣减（让本帧后续决策看到变少的余额）
            self._econ.reserve(info["min_m"], info["min_v"])
            minerals -= info["min_m"]
            vespene -= info["min_v"]
            supply_remaining -= info["supply"]
            own_types[unit_type] = own_types.get(unit_type, 0) + 1
            combat_total += 1

        # 4. SCV 训练（受 reserve 池约束）
        # SCV 数量 < SCV_FLOOR 时强制训练（不检查 reserve，紧急恢复经济）
        # SCV 数量 >= SCV_CEIL 时停止
        # 中间区间：通过 can_afford 检查（已扣战斗单位 reserve）
        if scv_count < self.SCV_CEIL:
            cc_idle = None
            for p in producers:
                if p.get("unit_type_id") != "CommandCenter":
                    continue
                if (p["entity_id"] in self._producers_in_queue
                        or p.get("orders")):
                    continue
                cc_idle = p
                break
            if cc_idle is not None:
                force_train = scv_count < self.SCV_FLOOR
                can_train = (force_train or
                             self._econ.can_afford(self.SCV_COST_M, self.SCV_COST_V,
                                                   minerals, vespene))
                if can_train and supply_remaining >= self.SCV_SUPPLY:
                    actions.append(DefendAction(
                        cc_idle["entity_id"], "train",
                        unit_type_id="SCV",
                        reason=f"train_scv(count={scv_count},force={force_train})",
                    ))
                    self._producers_in_queue.add(cc_idle["entity_id"])
                    self._econ.reserve(self.SCV_COST_M, self.SCV_COST_V)

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
        if health == 0:
            return 0.0
        max_hp_map = {
            "Marine": 45, "Marauder": 125, "SCV": 45, "SiegeTank": 160,
            "Medivac": 150, "CommandCenter": 1400, "Bunker": 400,
            "Barracks": 800, "SupplyDepot": 400, "EngineeringBay": 850,
            "MissileTurret": 250,
        }
        max_hp = max_hp_map.get(unit.get("unit_type_id", ""), 100)
        return min(1.0, health / 1024.0 / max_hp)
