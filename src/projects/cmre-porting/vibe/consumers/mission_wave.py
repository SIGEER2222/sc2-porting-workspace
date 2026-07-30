"""P4D —— 任务与波次消费者。

P4D 闸门（plan §5 P4D）：
- 区域/计时器/触发器/波次/奖励/终局 DSL
- 难度曲线与可行性报告
- 生存/防御/护航/占领/自定义断言场景
- 正负终局路径被演练
- 重置/重放复现波次时机与结果
- 难度变化用声明指标与种子集测量

复用 P3 已有的 mission_engine（Region/Wave/Objective/Trigger/MissionEngine）。
本模块提供 JSON DSL 加载器 + 难度曲线测量器 + 正负终局验证套件。
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from typing import Optional

from ..mission_engine import (
    MissionEngine, Objective, Region, Trigger, Wave, MissionResult,
    RewardSpec, compute_reward,
)
from ..sim_path import ensure_simulator_on_path

ensure_simulator_on_path()

from sc2_simulator.reporting.trace import trace_hash  # noqa: E402

from ..simulator_session import SimulatorSession


# ---------------------------------------------------------------------------
# Mission DSL（JSON -> MissionEngine）
# ---------------------------------------------------------------------------

@dataclass
class MissionSpec:
    """任务 DSL 顶层规格。"""
    name: str
    scenario: dict  # 基础场景（players/spawns/...）
    regions: list[dict] = field(default_factory=list)
    waves: list[dict] = field(default_factory=list)
    objectives: list[dict] = field(default_factory=list)
    triggers: list[dict] = field(default_factory=list)
    max_loops: int = 1000
    catalog: str = "m7"

    @classmethod
    def from_dict(cls, d: dict) -> "MissionSpec":
        return cls(
            name=d.get("name", "unnamed"),
            scenario=d["scenario"],
            regions=d.get("regions", []),
            waves=d.get("waves", []),
            objectives=d.get("objectives", []),
            triggers=d.get("triggers", []),
            max_loops=d.get("max_loops", 1000),
            catalog=d.get("catalog", "m7"),
        )

    @classmethod
    def from_file(cls, path: str) -> "MissionSpec":
        import json as _json
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(_json.load(f))


def build_mission(spec: MissionSpec) -> tuple[MissionEngine, SimulatorSession]:
    """从 spec 构造 MissionEngine + session。"""
    s = SimulatorSession()
    s.scenario_load(scenario_dict=spec.scenario, catalog=spec.catalog)
    s.scenario_reset()
    eng = MissionEngine(s)

    for r in spec.regions:
        eng.add_region(Region(
            name=r["name"], kind=r["kind"], x=r["x"], y=r["y"],
            w=r.get("w", 0.0), h=r.get("h", 0.0), r=r.get("r", 0.0),
        ))
    for w in spec.waves:
        eng.add_wave(Wave(
            name=w["name"], at_loop=w["at_loop"],
            spawns=w.get("spawns", []), commands=w.get("commands", []),
        ))
    for o in spec.objectives:
        eng.add_objective(Objective(
            name=o["name"], kind=o["kind"], params=o.get("params", {}),
        ))
    # triggers 由 DSL 中的 predefined kinds 构造（attack_nearest 等）
    for t in spec.triggers:
        trig = _build_trigger(t)
        if trig is not None:
            eng.add_trigger(trig)
    return eng, s


def _build_trigger(spec: dict) -> Optional[Trigger]:
    """从 DSL 构造触发器。当前支持 'attack_nearest' / 'move_to_region'。"""
    kind = spec.get("kind", "")
    name = spec.get("name", kind)
    cooldown = spec.get("cooldown", 22)
    if kind == "attack_nearest":
        owner = spec.get("owner_player_id", 1)
        unit_type = spec.get("unit_type_id", "Marine")
        return _make_attack_nearest_trigger(name, owner, unit_type, cooldown)
    if kind == "move_to_region":
        owner = spec.get("owner_player_id", 1)
        unit_type = spec.get("unit_type_id", "Marine")
        region_name = spec["region"]
        return _make_move_to_region_trigger(name, owner, unit_type, region_name, cooldown)
    return None


def _make_attack_nearest_trigger(name: str, owner: int, unit_type: str, cooldown: int) -> Trigger:
    def condition(eng: MissionEngine):
        s = eng.session
        if s.world is None:
            return False
        own = [e for e in s.world.entities.values()
               if e.unit_type_id == unit_type and e.owner_player_id == owner and e.is_alive]
        enemies = [e for e in s.world.entities.values()
                   if e.owner_player_id != owner and e.is_alive]
        return bool(own and enemies)

    def action(eng: MissionEngine):
        s = eng.session
        own = [e for e in s.world.entities.values()
               if e.unit_type_id == unit_type and e.owner_player_id == owner and e.is_alive]
        enemies = [e for e in s.world.entities.values()
                   if e.owner_player_id != owner and e.is_alive]
        if not own or not enemies:
            return
        for u in own:
            nearest = min(enemies, key=lambda e: (e.x.raw - u.x.raw) ** 2 + (e.y.raw - u.y.raw) ** 2)
            s.unit_order([u.entity_id], "attack_unit", owner, target_entity_id=nearest.entity_id)

    return Trigger(name, condition, action, cooldown=cooldown)


def _make_move_to_region_trigger(name: str, owner: int, unit_type: str,
                                  region_name: str, cooldown: int) -> Trigger:
    def condition(eng: MissionEngine):
        s = eng.session
        if s.world is None:
            return False
        return any(e.unit_type_id == unit_type and e.owner_player_id == owner and e.is_alive
                   for e in s.world.entities.values())

    def action(eng: MissionEngine):
        s = eng.session
        r = eng.regions.get(region_name)
        if r is None:
            return
        own = [e for e in s.world.entities.values()
               if e.unit_type_id == unit_type and e.owner_player_id == owner and e.is_alive]
        for u in own:
            if not r.contains(u.x.to_float(), u.y.to_float()):
                s.unit_order([u.entity_id], "move", owner, target_x=r.x, target_y=r.y)

    return Trigger(name, condition, action, cooldown=cooldown)


# ---------------------------------------------------------------------------
# 难度曲线测量
# ---------------------------------------------------------------------------

@dataclass
class DifficultyMetrics:
    """单次任务的难度指标。"""
    end_loop: int
    end_reason: str
    terminated: bool
    objectives_status: list[dict]
    survivors: dict
    trace_hash: str
    difficulty_label: str


@dataclass
class DifficultyCurveReport:
    """难度曲线报告。"""
    mission_name: str
    difficulty_levels: list[DifficultyMetrics]
    seed_count: int
    feasibility_verdict: str  # "trivial" | "challenging" | "impossible"
    determinism_verified: bool
    evidence_class: str = "simulator"


def run_mission(spec: MissionSpec, seed: Optional[int] = None) -> DifficultyMetrics:
    """跑一次任务。"""
    if seed is not None:
        sc = dict(spec.scenario)
        sc["seed"] = seed
        spec_copy = MissionSpec(
            name=spec.name, scenario=sc, regions=spec.regions, waves=spec.waves,
            objectives=spec.objectives, triggers=spec.triggers,
            max_loops=spec.max_loops, catalog=spec.catalog,
        )
        spec = spec_copy
    eng, s = build_mission(spec)
    # M5: 记录初始敌方数（reward per_enemy_killed 用）
    eng._initial_enemy_count = sum(1 for e in s.world.entities.values()
                                   if e.owner_player_id != 1 and e.is_alive)
    res = eng.run(max_loops=spec.max_loops)
    survivors: dict[int, int] = {}
    for e in s.world.entities.values():
        if e.is_alive:
            survivors[e.owner_player_id] = survivors.get(e.owner_player_id, 0) + 1
    return DifficultyMetrics(
        end_loop=res.end_loop,
        end_reason=res.end_reason,
        terminated=res.terminated,
        objectives_status=res.objectives,
        survivors=survivors,
        trace_hash=trace_hash(s.world),
        difficulty_label="",
    )


def measure_difficulty_curve(
    base_spec: MissionSpec,
    difficulty_variants: list[tuple[str, dict]],  # [(label, override_dict), ...]
    seeds: list[int],
) -> DifficultyCurveReport:
    """测量难度曲线：对每个难度变体跑多个 seed。

    override_dict 可覆盖 wave 强度（spawn 数量）/ 时机（at_loop）等。
    """
    results: list[DifficultyMetrics] = []
    for label, override in difficulty_variants:
        spec = _apply_override(base_spec, override)
        for seed in seeds:
            m = run_mission(spec, seed=seed)
            m.difficulty_label = label
            results.append(m)

    # 确定性验证：同难度同 seed 两次跑结果一致
    if results:
        first = results[0]
        spec0 = _apply_override(base_spec, difficulty_variants[0][1])
        rerun = run_mission(spec0, seed=seeds[0])
        determinism = rerun.trace_hash == first.trace_hash
    else:
        determinism = True

    # 可行性判定：基于胜率（survive 目标 success 率）
    success_count = sum(1 for r in results
                        if any(o["status"] == "success" for o in r.objectives_status))
    rate = success_count / len(results) if results else 0.0
    if rate >= 0.9:
        verdict = "trivial"
    elif rate >= 0.3:
        verdict = "challenging"
    elif rate > 0:
        verdict = "impossible"
    else:
        verdict = "impossible"

    return DifficultyCurveReport(
        mission_name=base_spec.name,
        difficulty_levels=results,
        seed_count=len(seeds),
        feasibility_verdict=verdict,
        determinism_verified=determinism,
    )


def _apply_override(spec: MissionSpec, override: dict) -> MissionSpec:
    """对 spec 应用难度覆盖（如 wave 增量）。spec.waves 内部是 dict（DSL 形式）。"""
    new_spec = MissionSpec(
        name=spec.name + "+" + override.get("label", "x"),
        scenario=spec.scenario,
        regions=list(spec.regions),
        waves=list(spec.waves),
        objectives=list(spec.objectives),
        triggers=list(spec.triggers),
        max_loops=spec.max_loops,
        catalog=spec.catalog,
    )
    if "wave_count_multiplier" in override:
        mult = override["wave_count_multiplier"]
        new_waves = []
        for w in spec.waves:
            w = dict(w)
            w["name"] = w["name"] + f"x{mult}"
            w["spawns"] = list(w.get("spawns", [])) * mult
            new_waves.append(w)
        new_spec.waves = new_waves
    if "wave_timing_offset" in override:
        offset = override["wave_timing_offset"]
        new_waves = []
        for w in spec.waves:
            w = dict(w)
            w["at_loop"] = max(0, w["at_loop"] + offset)
            new_waves.append(w)
        new_spec.waves = new_waves
    return new_spec


# ---------------------------------------------------------------------------
# P4D 自测
# ---------------------------------------------------------------------------

def _make_defend_mission_spec(wave_count: int = 1, wave_loop: int = 10) -> MissionSpec:
    """构造防御任务 spec：1 Marine 守 (0,0)，wave 在指定 loop 生成 N Zerglings 进攻。"""
    scenario = {
        "schema_version": "m7",
        "name": f"P4D defend w{wave_count}@{wave_loop}",
        "players": [
            {"id": 1, "name": "Defender", "race": "terran", "allies": [], "is_ai": True},
            {"id": 2, "name": "Attacker", "race": "zerg", "allies": [], "is_ai": True},
        ],
        "spawns": [
            {"unit_type_id": "Marine", "owner_player_id": 1, "x": 0.0, "y": 0.0},
            # 远位占位，避免 annihilation
            {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 100.0, "y": 100.0},
        ],
        "commands": [],
        "max_loops": 500,
        "seed": 42,
        "strict": True,
        "win_condition": "custom",
    }
    wave_spawns = [{"unit_type_id": "Zergling", "owner_player_id": 2, "x": 8.0, "y": 0.0}
                   for _ in range(wave_count)]
    return MissionSpec(
        name=scenario["name"],
        scenario=scenario,
        regions=[{"name": "base", "kind": "circle", "x": 0.0, "y": 0.0, "r": 5.0}],
        waves=[{"name": "wave1", "at_loop": wave_loop, "spawns": wave_spawns}],
        objectives=[
            {"name": "survive", "kind": "survive_loops", "params": {"target_loops": 200}},
            {"name": "defend_base", "kind": "defend_region",
             "params": {"region": "base", "defender_player_id": 1, "until_loop": 200}},
        ],
        triggers=[{"name": "marine_attack", "kind": "attack_nearest",
                   "owner_player_id": 1, "unit_type_id": "Marine", "cooldown": 22}],
        max_loops=300,
        catalog="m7",
    )


def p4d_selftest() -> dict:
    """P4D 闸门：正负终局 / 重置复现 / 难度曲线。"""
    checks = {}
    details = {}

    # 1) 正终局：1 Marine vs 1 Zergling wave，防守成功
    spec_pos = _make_defend_mission_spec(wave_count=1, wave_loop=10)
    res_pos = run_mission(spec_pos, seed=42)
    pos_success = any(o["status"] == "success" for o in res_pos.objectives_status) and res_pos.terminated
    checks["positive_terminal"] = pos_success
    details["positive_terminal"] = (
        f"end_loop={res_pos.end_loop} reason={res_pos.end_reason} "
        f"objectives={res_pos.objectives_status}"
    )

    # 2) 负终局：1 Marine vs 5 Zerglings wave，防守失败（Marine 死亡或区域失守）
    spec_neg = _make_defend_mission_spec(wave_count=5, wave_loop=10)
    res_neg = run_mission(spec_neg, seed=42)
    # 5 Zerglings 进攻 1 Marine，预期 Marine 死亡（annihilation 且 defender 无幸存）或 objective_failed
    defender_dead = res_neg.survivors.get(1, 0) == 0
    neg_failed = (
        res_neg.terminated
        and (defender_dead
             or any(o["status"] == "failed" for o in res_neg.objectives_status)
             or res_neg.end_reason == "objective_failed"
             or res_neg.end_reason == "simulator_terminated")
    )
    checks["negative_terminal"] = neg_failed
    details["negative_terminal"] = (
        f"end_loop={res_neg.end_loop} reason={res_neg.end_reason} "
        f"objectives={res_neg.objectives_status} survivors={res_neg.survivors} "
        f"defender_dead={defender_dead}"
    )

    # 3) 重置/重放复现波次时机与结果（同 spec 同 seed 两次跑，trace_hash 一致）
    rerun1 = run_mission(spec_pos, seed=42)
    rerun2 = run_mission(spec_pos, seed=42)
    checks["replay_reproduces"] = (
        rerun1.trace_hash == rerun2.trace_hash
        and rerun1.end_loop == rerun2.end_loop
        and rerun1.end_reason == rerun2.end_reason
    )
    details["replay_reproduces"] = (
        f"trace1={rerun1.trace_hash[:12]} trace2={rerun2.trace_hash[:12]} equal={rerun1.trace_hash == rerun2.trace_hash}"
    )

    # 4) 难度曲线：变体 wave_count 1/3/5，多 seed
    variants = [
        ("easy", {"wave_count_multiplier": 1, "label": "easy"}),
        ("hard", {"wave_count_multiplier": 3, "label": "hard"}),
        ("brutal", {"wave_count_multiplier": 5, "label": "brutal"}),
    ]
    seeds = [42, 43, 44]
    report = measure_difficulty_curve(spec_pos, variants, seeds)

    # 难度曲线报告：每个难度都有结果，可行性有判定
    checks["difficulty_curve_measured"] = (
        len(report.difficulty_levels) == len(variants) * len(seeds)
        and report.feasibility_verdict in ("trivial", "challenging", "impossible")
        and report.determinism_verified
    )
    details["difficulty_curve_measured"] = (
        f"levels={len(report.difficulty_levels)} verdict={report.feasibility_verdict} "
        f"determinism={report.determinism_verified}"
    )

    # 5) 难度增加 -> 胜率下降或 end_loop 下降（更多敌人 = 更快失败）
    # 按难度聚合
    by_label: dict[str, list[DifficultyMetrics]] = {}
    for m in report.difficulty_levels:
        by_label.setdefault(m.difficulty_label, []).append(m)
    success_rates = {}
    for label, ms in by_label.items():
        wins = sum(1 for m in ms if any(o["status"] == "success" for o in m.objectives_status))
        success_rates[label] = wins / len(ms) if ms else 0.0
    # easy 应该 >= hard >= brutal 胜率
    monotonic = (
        success_rates.get("easy", 0) >= success_rates.get("hard", 0)
        and success_rates.get("hard", 0) >= success_rates.get("brutal", 0)
    )
    checks["difficulty_monotonic"] = monotonic
    details["difficulty_monotonic"] = f"success_rates={success_rates}"

    # 6) M5 escort_vip 目标：VIP 移动到目标区域 -> success
    #    场景：1 Marine(VIP) @ (0,0)，目标区域 (5,0, r=2)，trigger 让 VIP move 到 (5,0)
    escort_scenario = {
        "schema_version": "m7", "name": "P4D escort", "players": [
            {"id": 1, "name": "Escort", "race": "terran", "allies": [], "is_ai": True},
            {"id": 2, "name": "Ambush", "race": "zerg", "allies": [], "is_ai": True},
        ],
        "spawns": [
            {"unit_type_id": "Marine", "owner_player_id": 1, "x": 0.0, "y": 0.0},
            # 远位占位
            {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 100.0, "y": 100.0},
        ],
        "commands": [], "max_loops": 200, "seed": 42, "strict": True,
        "win_condition": "custom",
    }
    eng_esc, s_esc = build_mission(MissionSpec(
        name="escort_test",
        scenario=escort_scenario,
        regions=[{"name": "extract", "kind": "circle", "x": 5.0, "y": 0.0, "r": 2.0}],
        waves=[], objectives=[], triggers=[],
        max_loops=200, catalog="m7",
    ))
    # 找到 VIP entity_id
    vip_id = next(e.entity_id for e in s_esc.world.entities.values()
                  if e.owner_player_id == 1 and e.is_alive)
    eng_esc.add_objective(Objective(
        name="escort_vip", kind="escort_vip",
        params={"vip_entity_id": vip_id, "target_region": "extract", "until_loop": 200},
    ))
    # 让 VIP move 到目标区域
    s_esc.unit_order([vip_id], "move", 1, target_x=5.0, target_y=0.0)
    eng_esc._initial_enemy_count = sum(1 for e in s_esc.world.entities.values()
                                       if e.owner_player_id != 1 and e.is_alive)
    res_esc = eng_esc.run(max_loops=200)
    escort_success = any(o["status"] == "success" for o in res_esc.objectives)
    checks["escort_vip_success"] = escort_success and res_esc.terminated
    details["escort_vip_success"] = (
        f"end_loop={res_esc.end_loop} objectives={res_esc.objectives} vip_id={vip_id}"
    )

    # 7) M5 escort_vip 失败：VIP 被杀 -> failed
    eng_esc2, s_esc2 = build_mission(MissionSpec(
        name="escort_fail",
        scenario=escort_scenario,
        regions=[{"name": "extract", "kind": "circle", "x": 50.0, "y": 0.0, "r": 2.0}],
        waves=[], objectives=[], triggers=[],
        max_loops=200, catalog="m7",
    ))
    vip_id2 = next(e.entity_id for e in s_esc2.world.entities.values()
                   if e.owner_player_id == 1 and e.is_alive)
    eng_esc2.add_objective(Objective(
        name="escort_vip", kind="escort_vip",
        params={"vip_entity_id": vip_id2, "target_region": "extract", "until_loop": 200},
    ))
    # 立即杀 VIP
    s_esc2.unit_kill(vip_id2)
    eng_esc2._initial_enemy_count = 1
    res_esc2 = eng_esc2.run(max_loops=10)
    escort_failed = any(o["status"] == "failed" for o in res_esc2.objectives)
    checks["escort_vip_failed_when_killed"] = escort_failed
    details["escort_vip_failed_when_killed"] = (
        f"end_loop={res_esc2.end_loop} objectives={res_esc2.objectives}"
    )

    # 8) M5 capture_region 目标：己方单位在区域内停留 N loop -> success
    capture_scenario = {
        "schema_version": "m7", "name": "P4D capture", "players": [
            {"id": 1, "name": "Capper", "race": "terran", "allies": [], "is_ai": True},
            {"id": 2, "name": "Def", "race": "zerg", "allies": [], "is_ai": True},
        ],
        "spawns": [
            {"unit_type_id": "Marine", "owner_player_id": 1, "x": 5.0, "y": 0.0},  # 已在目标区域内
            {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 100.0, "y": 100.0},  # 远位
        ],
        "commands": [], "max_loops": 100, "seed": 42, "strict": True,
        "win_condition": "custom",
    }
    eng_cap, s_cap = build_mission(MissionSpec(
        name="capture_test",
        scenario=capture_scenario,
        regions=[{"name": "point", "kind": "circle", "x": 5.0, "y": 0.0, "r": 3.0}],
        waves=[], objectives=[], triggers=[],
        max_loops=100, catalog="m7",
    ))
    eng_cap.add_objective(Objective(
        name="capture_point", kind="capture_region",
        params={"region": "point", "owner_player_id": 1, "hold_loops": 10},
    ))
    eng_cap._initial_enemy_count = 1
    res_cap = eng_cap.run(max_loops=100)
    capture_success = any(o["status"] == "success" for o in res_cap.objectives)
    checks["capture_region_success"] = capture_success and res_cap.terminated
    details["capture_region_success"] = (
        f"end_loop={res_cap.end_loop} objectives={res_cap.objectives}"
    )

    # 9) M5 capture_region 失败：敌方进入区域 -> 重置进度（不立即失败，但 hold_loops 内未达成）
    capture_fail_scenario = dict(capture_scenario)
    capture_fail_scenario["spawns"] = [
        {"unit_type_id": "Marine", "owner_player_id": 1, "x": 5.0, "y": 0.0},
        {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 6.0, "y": 0.0},  # 敌方也在区域内
    ]
    eng_cf, s_cf = build_mission(MissionSpec(
        name="capture_fail",
        scenario=capture_fail_scenario,
        regions=[{"name": "point", "kind": "circle", "x": 5.0, "y": 0.0, "r": 3.0}],
        waves=[], objectives=[], triggers=[],
        max_loops=50, catalog="m7",
    ))
    eng_cf.add_objective(Objective(
        name="capture_point", kind="capture_region",
        params={"region": "point", "owner_player_id": 1, "hold_loops": 5},
    ))
    eng_cf._initial_enemy_count = 1
    res_cf = eng_cf.run(max_loops=30)
    # 敌方在区域内 -> capture 进度始终 0 -> 50 loop 内未达成 -> 未 success
    capture_blocked = not any(o["status"] == "success" for o in res_cf.objectives)
    checks["capture_region_blocked_by_enemy"] = capture_blocked
    details["capture_region_blocked_by_enemy"] = (
        f"end_loop={res_cf.end_loop} objectives={res_cf.objectives} "
        f"capture_progress={eng_cf._capture_progress.get('capture_point', 0)}"
    )

    # 10) M5 Reward DSL：多组件奖励计算
    reward_spec = RewardSpec.from_dict([
        {"name": "survival", "kind": "per_loop_survival", "weight": 0.1},
        {"name": "kills", "kind": "per_enemy_killed", "weight": 5.0},
        {"name": "obj_success", "kind": "per_objective_success", "weight": 10.0},
        {"name": "obj_fail_pen", "kind": "per_objective_failed", "weight": -5.0},
        {"name": "win", "kind": "win_bonus", "weight": 20.0},
    ])
    # 用正终局 mission（spec_pos）的 eng 计算 reward
    eng_rew, s_rew = build_mission(spec_pos)
    eng_rew._initial_enemy_count = sum(1 for e in s_rew.world.entities.values()
                                       if e.owner_player_id != 1 and e.is_alive)
    res_rew = eng_rew.run(max_loops=spec_pos.max_loops)
    rew = compute_reward(reward_spec, res_rew, eng_rew)
    # breakdown 应含全部 5 个组件
    checks["reward_dsl_breakdown_complete"] = (
        len(rew.breakdown) == 5
        and all(k in rew.breakdown for k in
                ["survival", "kills", "obj_success", "obj_fail_pen", "win"])
        and rew.spec_components == 5
    )
    details["reward_dsl_breakdown_complete"] = (
        f"total={rew.total:.2f} breakdown={rew.breakdown}"
    )

    # 11) M5 Reward DSL：不同结果产生不同奖励（正 vs 负终局）
    # 负终局：spec_neg（5 Zerglings）
    eng_neg, s_neg = build_mission(spec_neg)
    eng_neg._initial_enemy_count = sum(1 for e in s_neg.world.entities.values()
                                       if e.owner_player_id != 1 and e.is_alive)
    res_neg_eng = eng_neg.run(max_loops=spec_neg.max_loops)
    rew_neg = compute_reward(reward_spec, res_neg_eng, eng_neg)
    # 正终局应比负终局奖励高（至少 obj_success 组件差异）
    checks["reward_dsl_differentiates_outcomes"] = rew.total > rew_neg.total
    details["reward_dsl_differentiates_outcomes"] = (
        f"positive_total={rew.total:.2f} negative_total={rew_neg.total:.2f} "
        f"positive_breakdown={rew.breakdown} negative_breakdown={rew_neg.breakdown}"
    )

    # 12) M5 Reward DSL：vip_alive_bonus 组件
    reward_vip = RewardSpec.from_dict([
        {"name": "vip_alive", "kind": "vip_alive_bonus", "weight": 15.0},
    ])
    # 用 escort 成功场景
    eng_vip, s_vip = build_mission(MissionSpec(
        name="escort_reward",
        scenario=escort_scenario,
        regions=[{"name": "extract", "kind": "circle", "x": 5.0, "y": 0.0, "r": 2.0}],
        waves=[], objectives=[], triggers=[],
        max_loops=200, catalog="m7",
    ))
    vip_id_r = next(e.entity_id for e in s_vip.world.entities.values()
                    if e.owner_player_id == 1 and e.is_alive)
    eng_vip._initial_enemy_count = 1
    res_vip = eng_vip.run(max_loops=50)
    rew_vip = compute_reward(reward_vip, res_vip, eng_vip, vip_entity_id=vip_id_r)
    # VIP 在 escort_scenario 中不会被杀（远位敌人），应得 15.0
    checks["reward_dsl_vip_alive_bonus"] = (
        rew_vip.total == 15.0 and rew_vip.breakdown["vip_alive"] == 15.0
    )
    details["reward_dsl_vip_alive_bonus"] = (
        f"total={rew_vip.total} breakdown={rew_vip.breakdown} vip_id={vip_id_r}"
    )

    return {"passed": all(checks.values()), "checks": checks, "details": details,
            "feasibility_verdict": report.feasibility_verdict,
            "success_rates": success_rates,
            "positive_end_loop": res_pos.end_loop,
            "negative_end_loop": res_neg.end_loop,
            "reward_positive_total": rew.total,
            "reward_negative_total": rew_neg.total}


if __name__ == "__main__":
    import sys
    r = p4d_selftest()
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    sys.exit(0 if r["passed"] else 1)
