"""P3 G7 适配层 —— 任务引擎（触发器/区域/波次/目标/终局）。

sc2_simulator 的 TriggerEngine 是死代码（SIM-CAP-GAP-001），runner 不调用。
本模块在**项目本地适配层**吸收该缺口：包裹 SimulatorSession，在 step 之间注入
区域检测、波次生成、触发器 firing、目标判定与终局状态。

不编辑 sc2_simulator；通过 scenario.step + unit.spawn + unit.order + assert 操纵。

支持的目标类型（P4D DSL）：
- ``annihilation``：全歼敌方（委托 sc2_simulator 原生）
- ``defend_region``：守住指定区域 N loop（敌方未进入）
- ``survive_loops``：存活到指定 loop
- ``destroy_unit``：摧毁指定实体
- ``destroy_all_enemy_structures``：摧毁所有指定敌方玩家的建筑
- ``timer``：到时即胜/败
- ``escort_vip``（M5）：VIP 存活且到达目标区域
- ``capture_region``（M5）：连续控制区域 N loop（仅己方单位在内）

Reward DSL（M5）：
- ``RewardComponent``：name / kind / weight
- ``RewardSpec``：组件列表
- ``compute_reward()``：任务结束时按组件计算标量奖励
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .simulator_session import SimulatorSession
from .contracts import VictoryTimeMetric


@dataclass
class Region:
    """矩形或圆形区域。"""

    name: str
    kind: str  # "rect" | "circle"
    x: float
    y: float
    w: float = 0.0  # rect 用
    h: float = 0.0  # rect 用
    r: float = 0.0  # circle 用

    def contains(self, x: float, y: float) -> bool:
        if self.kind == "rect":
            return self.x <= x <= self.x + self.w and self.y <= y <= self.y + self.h
        # circle
        dx, dy = x - self.x, y - self.y
        return dx * dx + dy * dy <= self.r * self.r


@dataclass
class Wave:
    """波次：在指定 loop 生成一组单位。"""

    name: str
    at_loop: int
    spawns: list[dict]  # [{unit_type_id, owner_player_id, x, y}, ...]
    commands: list[dict] = field(default_factory=list)  # [{kind, entity_ids, ...}, ...]


@dataclass
class Objective:
    """任务目标。"""

    name: str
    kind: str  # annihilation | defend_region | survive_loops | destroy_unit | destroy_all_enemy_structures | timer
    params: dict = field(default_factory=dict)
    status: str = "active"  # active | success | failed


@dataclass
class Trigger:
    """触发器：条件满足时执行动作。"""

    name: str
    condition: Callable[["MissionEngine"], bool]
    action: Callable[["MissionEngine"], None]
    cooldown: int = 0
    last_fired: int = -10_000


@dataclass
class MissionResult:
    terminated: bool
    end_loop: int
    end_reason: str
    objectives: list[dict]
    # Stage 08: 胜利时间指标
    game_time_sec: float = 0.0
    nights_survived: int = 0
    victory: bool = False

    @classmethod
    def from_engine(cls, eng: "MissionEngine") -> "MissionResult":
        loop = eng.session.world.clock.now.loop if eng.session.world else 0
        nights = 0
        if hasattr(eng.session, "_wave_timing") and eng.session._wave_timing:
            for night in eng.session._wave_timing.get("nights", []):
                if loop >= night.get("end_loop", 0):
                    nights += 1
        victory = eng.terminated and eng.end_reason in (
            "all_objectives_success",
            "survive_loops",
            "max_loops_reached",
        )
        return cls(
            terminated=eng.terminated,
            end_loop=loop,
            end_reason=eng.end_reason,
            objectives=[
                {"name": o.name, "kind": o.kind, "status": o.status}
                for o in eng.objectives
            ],
            game_time_sec=loop / 22.4,
            nights_survived=nights,
            victory=victory,
        )


class MissionEngine:
    """任务引擎：包裹 SimulatorSession，叠加区域/波次/触发器/目标/终局。

    用法：
      eng = MissionEngine(session)
      eng.add_region(...); eng.add_wave(...); eng.add_objective(...); eng.add_trigger(...)
      eng.run(max_loops=...)
    """

    def __init__(self, session: SimulatorSession):
        self.session = session
        self.regions: dict[str, Region] = {}
        self.waves: list[Wave] = []
        self.objectives: list[Objective] = []
        self.triggers: list[Trigger] = []
        self.terminated = False
        self.end_reason = ""
        self._waves_fired: set[str] = set()
        # M5: capture_region 进度跟踪（objective.name -> 已连续控制的 loop 数）
        self._capture_progress: dict[str, int] = {}
        self._initial_enemy_count: int = -1  # M5: reward 计算用

    # ----- DSL 构造 -----
    def add_region(self, r: Region) -> "MissionEngine":
        self.regions[r.name] = r
        return self

    def add_wave(self, w: Wave) -> "MissionEngine":
        self.waves.append(w)
        return self

    def add_objective(self, o: Objective) -> "MissionEngine":
        self.objectives.append(o)
        return self

    def add_trigger(self, t: Trigger) -> "MissionEngine":
        self.triggers.append(t)
        return self

    # ----- 区域查询 -----
    def units_in_region(
        self, region_name: str, owner_player_id: Optional[int] = None
    ) -> list[dict]:
        r = self.regions[region_name]
        units = self.session.query_units(owner_player_id)["units"]
        return [u for u in units if r.contains(u["x"], u["y"])]

    def enemies_in_region(
        self, region_name: str, defender_player_id: int
    ) -> list[dict]:
        r = self.regions[region_name]
        enemies = [
            e
            for e in self.session.query_units()["units"]
            if e["owner"] != defender_player_id and r.contains(e["x"], e["y"])
        ]
        return enemies

    # ----- 主循环 -----
    def step(self, loops: int = 1) -> MissionResult:
        for _ in range(loops):
            if self.terminated:
                break
            cur = self.session.world.clock.now.loop if self.session.world else 0
            self._fire_waves(cur)
            self.session.scenario_step(1, snapshot=False)
            self._fire_triggers(cur)
            self._check_objectives(cur)
            if self.session.terminated:
                # sc2_simulator 原生终局（如 annihilation）
                self.terminated = True
                self.end_reason = (
                    getattr(self.session, "end_reason", "") or "simulator_terminated"
                )
        return self._result()

    def _result(self) -> MissionResult:
        return MissionResult.from_engine(self)

    def run(self, max_loops: int = 10_000) -> MissionResult:
        return self.step(max_loops)

    def _fire_waves(self, cur_loop: int) -> None:
        for w in self.waves:
            if w.at_loop <= cur_loop and w.name not in self._waves_fired:
                self._waves_fired.add(w.name)
                for sp in w.spawns:
                    self.session.unit_spawn(
                        sp["unit_type_id"], sp["owner_player_id"], sp["x"], sp["y"]
                    )
                for c in w.commands:
                    self.session.unit_order(
                        c.get("entity_ids", []),
                        c["kind"],
                        c["issuer_player_id"],
                        c.get("target_entity_id", 0),
                        c.get("target_x", 0.0),
                        c.get("target_y", 0.0),
                        c.get("unit_type_id", ""),
                        c.get("ability_id", ""),
                    )

    def _fire_triggers(self, cur_loop: int) -> None:
        for t in self.triggers:
            if cur_loop - t.last_fired < t.cooldown:
                continue
            try:
                if t.condition(self):
                    t.action(self)
                    t.last_fired = cur_loop
            except Exception as exc:  # noqa: BLE001
                # 触发器失败不崩任务，但必须留痕：写入 world.events 队列
                # （L1：原实现 except: pass 把异常静默吞掉，违反 evidence rules）
                world = self.session.world
                if world is not None:
                    import traceback as _tb

                    world.events.schedule(
                        loop=cur_loop,
                        system="system",
                        kind="trigger_error",
                        entity_id=0,
                        payload={
                            "trigger_name": t.name,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                            "traceback": _tb.format_exc().splitlines()[-5:],
                        },
                    )

    def _check_objectives(self, cur_loop: int) -> None:
        all_done = True
        for o in self.objectives:
            if o.status != "active":
                continue
            status = self._evaluate_objective(o, cur_loop)
            if status:
                o.status = status
            else:
                all_done = False
        # 若所有目标已 success 且无 failed -> 任务成功
        if all_done and self.objectives:
            if all(o.status == "success" for o in self.objectives):
                self.terminated = True
                self.end_reason = "all_objectives_success"
            elif any(o.status == "failed" for o in self.objectives):
                self.terminated = True
                self.end_reason = "objective_failed"

    def _evaluate_objective(self, o: Objective, cur_loop: int) -> Optional[str]:
        if o.kind == "survive_loops":
            if cur_loop >= o.params["target_loops"]:
                return "success"
            return None
        if o.kind == "defend_region":
            # 守住区域：敌方未进入
            enemies = self.enemies_in_region(
                o.params["region"], o.params["defender_player_id"]
            )
            if enemies:
                return "failed"
            if cur_loop >= o.params.get("until_loop", 10_000):
                return "success"
            return None
        if o.kind == "destroy_unit":
            e = (
                self.session.world.get_entity(o.params["entity_id"])
                if self.session.world
                else None
            )
            if e is None or not e.is_alive:
                return "success"
            return None
        if o.kind == "destroy_all_enemy_structures":
            enemy_players = set(o.params.get("enemy_player_ids", []))
            defender = o.params.get("defender_player_id")
            if not enemy_players and defender is not None:
                enemy_players = {
                    e.owner_player_id
                    for e in self.session.world.entities.values()
                    if e.owner_player_id != defender
                }
            structures = [
                e
                for e in self.session.world.entities.values()
                if e.is_alive
                and (not enemy_players or e.owner_player_id in enemy_players)
                and self.session.world.catalog.get(e.unit_type_id).is_structure
                and self.session.world.catalog.get(e.unit_type_id).race != "neutral"
            ]
            return "success" if not structures else None
        if o.kind == "timer":
            if cur_loop >= o.params["target_loops"]:
                return o.params.get("on_expire", "success")
            return None
        if o.kind == "escort_vip":
            # M5: VIP 存活且到达目标区域
            vip_id = o.params["vip_entity_id"]
            vip = self.session.world.get_entity(vip_id) if self.session.world else None
            if vip is None or not vip.is_alive:
                return "failed"
            target_region = self.regions.get(o.params["target_region"])
            if target_region is None:
                return None
            if target_region.contains(vip.x.to_float(), vip.y.to_float()):
                return "success"
            # 超时判定
            if cur_loop >= o.params.get("until_loop", 10_000):
                return "failed"
            return None
        if o.kind == "capture_region":
            # M5: 连续控制区域 N loop（仅己方单位在内，无敌方）
            region_name = o.params["region"]
            owner = o.params["owner_player_id"]
            hold_loops = o.params["hold_loops"]
            r = self.regions.get(region_name)
            if r is None:
                return None
            enemies = self.enemies_in_region(region_name, owner)
            own = [
                u
                for u in self.session.query_units(owner)["units"]
                if r.contains(u["x"], u["y"])
            ]
            if enemies or not own:
                # 敌方在内或己方无单位 -> 重置进度
                self._capture_progress[o.name] = 0
                return None
            # 己方控制中 -> 累加进度
            self._capture_progress[o.name] = self._capture_progress.get(o.name, 0) + 1
            if self._capture_progress[o.name] >= hold_loops:
                return "success"
            return None
        return None


def _result(self) -> MissionResult:
    return MissionResult.from_engine(self)


# ---------------------------------------------------------------------------
# M5: Reward DSL
# ---------------------------------------------------------------------------


@dataclass
class RewardComponent:
    """奖励组件：name + kind + weight。

    kind 取值：
    - ``per_loop_survival``：weight * end_loop（存活越久奖励越多）
    - ``per_loop_penalty``：weight * end_loop（负 weight = 惩罚越久）
    - ``per_enemy_killed``：weight * (initial_enemies - final_enemies)
    - ``per_objective_success``：weight * count(objectives status=success)
    - ``per_objective_failed``：weight * count(objectives status=failed)
    - ``vip_alive_bonus``：weight * (1 if VIP alive else 0)
    - ``win_bonus``：weight * (1 if all objectives success else 0)
    - ``flat``：weight（固定奖励/惩罚）
    """

    name: str
    kind: str
    weight: float

    @classmethod
    def from_dict(cls, d: dict) -> "RewardComponent":
        return cls(name=d["name"], kind=d["kind"], weight=float(d["weight"]))


@dataclass
class RewardSpec:
    """奖励规格：组件列表。"""

    components: list[RewardComponent] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: list[dict]) -> "RewardSpec":
        return cls(components=[RewardComponent.from_dict(c) for c in d])


@dataclass
class RewardResult:
    """奖励计算结果。"""

    total: float
    breakdown: dict[str, float]  # component.name -> contribution
    spec_components: int


def compute_reward(
    spec: RewardSpec,
    mission_result: MissionResult,
    eng: MissionEngine,
    vip_entity_id: Optional[int] = None,
    initial_enemy_count: Optional[int] = None,
) -> RewardResult:
    """按 RewardSpec 计算标量奖励。

    eng: 用于查询 final world state（敌方剩余数等）
    vip_entity_id: vip_alive_bonus 组件用
    initial_enemy_count: per_enemy_killed 组件用（若 None 则从 eng._initial_enemy_count 取）
    """
    breakdown: dict[str, float] = {}
    total = 0.0
    end_loop = mission_result.end_loop
    obj_success = sum(1 for o in mission_result.objectives if o["status"] == "success")
    obj_failed = sum(1 for o in mission_result.objectives if o["status"] == "failed")
    all_success = obj_success > 0 and obj_failed == 0 and mission_result.terminated

    # 敌方击杀数
    if initial_enemy_count is None:
        initial_enemy_count = eng._initial_enemy_count
    if initial_enemy_count < 0 and eng.session.world is not None:
        # 退化：用当前 world 敌方存活数估算（不精确，仅 fallback）
        initial_enemy_count = sum(
            1 for e in eng.session.world.entities.values() if e.owner_player_id != 1
        )
    final_enemies = 0
    if eng.session.world is not None:
        final_enemies = sum(
            1
            for e in eng.session.world.entities.values()
            if e.owner_player_id != 1 and e.is_alive
        )
    enemies_killed = (
        max(0, initial_enemy_count - final_enemies) if initial_enemy_count >= 0 else 0
    )

    # VIP 存活
    vip_alive = False
    if vip_entity_id is not None and eng.session.world is not None:
        vip = eng.session.world.get_entity(vip_entity_id)
        vip_alive = vip is not None and vip.is_alive

    for c in spec.components:
        if c.kind == "per_loop_survival":
            contrib = c.weight * end_loop
        elif c.kind == "per_loop_penalty":
            contrib = c.weight * end_loop
        elif c.kind == "per_enemy_killed":
            contrib = c.weight * enemies_killed
        elif c.kind == "per_objective_success":
            contrib = c.weight * obj_success
        elif c.kind == "per_objective_failed":
            contrib = c.weight * obj_failed
        elif c.kind == "vip_alive_bonus":
            contrib = c.weight * (1.0 if vip_alive else 0.0)
        elif c.kind == "win_bonus":
            contrib = c.weight * (1.0 if all_success else 0.0)
        elif c.kind == "flat":
            contrib = c.weight
        else:
            contrib = 0.0
        breakdown[c.name] = contrib
        total += contrib

    return RewardResult(
        total=total, breakdown=breakdown, spec_components=len(spec.components)
    )


__all__ = [
    "Region",
    "Wave",
    "Objective",
    "Trigger",
    "MissionEngine",
    "MissionResult",
    "RewardComponent",
    "RewardSpec",
    "RewardResult",
    "compute_reward",
]
