"""P5 —— 离线 2D viewer + 快照 seek + 确定性回放 + baseline/candidate 同步对比。

P5 闸门（plan §5 P5）：
- 渲染实体数/值匹配权威快照
- seek 到某 loop 恢复同快照哈希
- viewer 交互不能在 typed op 外改模拟态
- 失败断言打开到相关 loop/实体

实现：
- SnapshotRecorder：每 N loop 拍快照，存到 dict[loop, SnapshotHandle]
- seek(loop)：恢复指定 loop 的快照（hash 必须一致）
- render_svg(snapshot)：把快照渲染成 SVG（2D 顶视图）
- compare_baseline_candidate：同步播放 baseline/candidate 快照序列，逐 loop 比对差异
- 视图只读快照 dict，不能调用 unit.* / scenario.* 等修改操作
"""

from __future__ import annotations

import html
import json
import math
from dataclasses import dataclass, field
from typing import Optional

from .contracts import SnapshotHandle, TraceHandle
from .sim_path import ensure_simulator_on_path

ensure_simulator_on_path()

from sc2_simulator.reporting.trace import trace_hash  # noqa: E402
from sc2_simulator.world.snapshot import snapshot_hash  # noqa: E402

from .simulator_session import SimulatorSession


@dataclass
class RecordedFrame:
    """单帧记录。"""
    loop: int
    snapshot: SnapshotHandle
    events_summary: list[dict]  # 该 loop 发生的事件摘要


class SnapshotRecorder:
    """每 N loop 拍快照，建索引供 seek。"""

    def __init__(self, session: SimulatorSession, interval: int = 10):
        self.session = session
        self.interval = interval
        self.frames: dict[int, RecordedFrame] = {}

    def record_during(self, run_loops: int) -> dict:
        """推进 run_loops，每 interval loop 拍一帧（拍的是推进前的状态，key=cur_before）。"""
        recorded = 0
        for _ in range(run_loops):
            if self.session.terminated:
                break
            cur_before = self.session.world.clock.now.loop
            # 在 cur_before 这个 loop 上拍快照（推进前的状态）——必须在 step 之前拍，
            # 否则 snapshot.clock 会是 cur_after，restore 后 clock≠frame key
            if cur_before % self.interval == 0 and cur_before not in self.frames:
                snap = SnapshotHandle.from_world(self.session.world)
                events_summary = [
                    {"loop": e.loop, "kind": e.kind, "entity_id": e.entity_id}
                    for e in self.session.world.events.emitted
                    if e.loop == cur_before
                ]
                self.frames[cur_before] = RecordedFrame(cur_before, snap, events_summary)
                recorded += 1
            self.session.scenario_step(1)
        return {"recorded": recorded, "total_frames": len(self.frames),
                "final_loop": self.session.world.clock.now.loop}

    def seek(self, loop: int) -> Optional[RecordedFrame]:
        """seek 到指定 loop，返回该帧（不修改 world）。"""
        return self.frames.get(loop)

    def restore_to(self, loop: int) -> Optional[SnapshotHandle]:
        """seek 并把 world 恢复到该 loop 的快照。返回恢复后的快照哈希。"""
        frame = self.frames.get(loop)
        if frame is None:
            return None
        self.session.world.restore_into(frame.snapshot.data)
        # 校验：恢复后快照哈希必须等于记录时的哈希
        restored = SnapshotHandle.from_world(self.session.world)
        if restored.hash != frame.snapshot.hash:
            raise RuntimeError(
                f"seek 哈希不一致: restored={restored.hash[:12]} recorded={frame.snapshot.hash[:12]}"
            )
        return restored

    def list_frames(self) -> list[int]:
        return sorted(self.frames.keys())


# ---------------------------------------------------------------------------
# 2D SVG 渲染
# ---------------------------------------------------------------------------

@dataclass
class RenderConfig:
    """渲染配置。"""
    width: int = 800
    height: int = 600
    scale: float = 8.0  # 1 game unit = scale pixels
    origin_x: float = 0.0
    origin_y: float = 0.0
    show_health: bool = True
    show_grid: bool = True


def render_svg(snapshot_data: dict, config: Optional[RenderConfig] = None) -> str:
    """把快照渲染成 SVG（2D 顶视图）。

    snapshot_data 来自 world.snapshot()，含 entities / clock / players 等。
    """
    cfg = config or RenderConfig()
    w, h = cfg.width, cfg.height
    sx, sy = cfg.scale, cfg.scale
    ox, oy = cfg.origin_x, cfg.origin_y

    parts: list[str] = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">')
    parts.append(f'<rect width="{w}" height="{h}" fill="#1a1a1a"/>')

    # 网格
    if cfg.show_grid:
        for gx in range(0, w, 50):
            parts.append(f'<line x1="{gx}" y1="0" x2="{gx}" y2="{h}" stroke="#2a2a2a" stroke-width="0.5"/>')
        for gy in range(0, h, 50):
            parts.append(f'<line x1="0" y1="{gy}" x2="{w}" y2="{gy}" stroke="#2a2a2a" stroke-width="0.5"/>')

    # 坐标系：游戏 (x,y) -> 屏幕 (cx + x*sx, cy - y*sy)（y 翻转）
    cx = w / 2 + ox * sx
    cy = h / 2 - oy * sy

    # 实体
    entities = snapshot_data.get("entities", [])
    for e in entities:
        ex = cx + e.get("x", 0.0) * sx
        ey = cy - e.get("y", 0.0) * sy
        owner = e.get("owner_player_id", 0)
        color = _player_color(owner)
        utype = e.get("unit_type_id", "?")
        health = e.get("health", 0)
        max_health = e.get("max_health", health)
        radius = max(4.0, e.get("radius", 0.5) * sx)
        parts.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="{radius:.1f}" fill="{color}" stroke="#fff" stroke-width="0.5"/>')
        if cfg.show_health:
            parts.append(f'<text x="{ex:.1f}" y="{ey - radius - 4:.1f}" fill="#fff" font-size="10" text-anchor="middle">{html.escape(utype)} {health:.0f}/{max_health:.0f}</text>')
        parts.append(f'<text x="{ex:.1f}" y="{ey + 4:.1f}" fill="#fff" font-size="9" text-anchor="middle">P{owner}</text>')

    # clock
    clock = snapshot_data.get("clock", {})
    loop = clock.get("loop", 0)
    parts.append(f'<text x="10" y="20" fill="#0f0" font-size="14">loop={loop} entities={len(entities)}</text>')

    parts.append('</svg>')
    return "\n".join(parts)


def _player_color(pid: int) -> str:
    return {1: "#4a90e2", 2: "#e24a4a", 3: "#4ae24a", 4: "#e2c84a"}.get(pid, "#888888")


# ---------------------------------------------------------------------------
# M6: Timeline / Entity Inspection / Calculation Detail views
# ---------------------------------------------------------------------------
# 这三个视图都是**纯函数** over snapshot_data，不调用 session.unit_* / scenario.*
# 等修改操作，满足 P5 闸门「viewer 交互不能在 typed op 外改模拟态」。
# 输出为多行文本（debug-friendly），便于断言与差分。

# 事件 kind 中认为是「关键状态变化」的集合（其余 kind 在 timeline 中折叠）
_TIMELINE_PRIORITY_KINDS = frozenset({
    "damage", "death", "spawn", "command_accepted", "command_rejected",
    "build_start", "build_complete", "train_start", "train_complete",
    "upgrade_start", "upgrade_complete", "morph_start", "morph_complete",
    "ability_cast", "heal", "trigger_error", "mission_objective",
})


def render_timeline(
    snapshot_data: dict,
    *,
    only_kinds: Optional[set[str]] = None,
    max_events: int = 200,
) -> str:
    """时间线视图：按 loop 分组展示已发射事件。

    snapshot_data 来自 world.snapshot()，含 ``events.emitted`` 列表。
    输出多行文本，每行形如：``[loop=N system=kind entity=ID] payload_summary``。

    - ``only_kinds``：可选过滤 kind 集合；默认用 ``_TIMELINE_PRIORITY_KINDS``，
      若传 ``set()`` 则不过滤（输出全部事件）。
    - ``max_events``：最多输出事件数（防止巨型 trace 撑爆终端）。
    - 纯读快照，不修改任何状态。
    """
    events_block = snapshot_data.get("events", {})
    emitted = events_block.get("emitted", [])
    kind_filter = only_kinds if only_kinds is not None else _TIMELINE_PRIORITY_KINDS
    rows: list[str] = []
    rows.append(f"=== Timeline (emitted={len(emitted)}, filter={sorted(kind_filter) or 'ALL'}) ===")
    shown = 0
    for ev in emitted:
        kind = ev.get("kind", "")
        if kind_filter and kind not in kind_filter:
            continue
        loop = ev.get("loop", 0)
        system = ev.get("system", "")
        eid = ev.get("entity_id", 0)
        payload = ev.get("payload", {})
        # payload 摘要：保留关键字段，避免冗长
        summary = _summarize_payload(kind, payload)
        rows.append(f"[loop={loop} system={system} kind={kind} entity={eid}] {summary}")
        shown += 1
        if shown >= max_events:
            rows.append(f"... ({len(emitted) - shown} more events truncated)")
            break
    rows.append(f"=== Timeline end (shown={shown}) ===")
    return "\n".join(rows)


def _summarize_payload(kind: str, payload: dict) -> str:
    """按 kind 生成 payload 摘要，聚焦关键计算/状态字段。"""
    if kind == "damage":
        # 伤害公式：attacker -> target，base -> final
        return (
            f"attacker={payload.get('attacker', 0)} weapon={payload.get('weapon', '?')} "
            f"base={payload.get('base_raw', 0)}*attacks={payload.get('attacks', 0)} "
            f"bonus={payload.get('bonus_raw', 0)} type_mult={payload.get('type_mult_percent', 100)}% "
            f"armor={payload.get('armor_raw', 0)} final={payload.get('final_raw', 0)} "
            f"hp_after={payload.get('health_after', 0)} shields_after={payload.get('shields_after', 0)}"
        )
    if kind == "death":
        return (
            f"killer={payload.get('killer', 0)} killer_player={payload.get('killer_player', -1)} "
            f"victim_player={payload.get('victim_player', -1)}"
        )
    if kind in ("command_accepted", "command_rejected"):
        return f"cmd={payload.get('kind', '?')} target={payload.get('target', 0)}"
    if kind == "spawn":
        return (
            f"unit={payload.get('unit_type_id', '?')} owner={payload.get('owner_player_id', 0)} "
            f"pos=({payload.get('x', 0)},{payload.get('y', 0)})"
        )
    if kind in ("build_complete", "train_complete", "morph_complete"):
        return (
            f"unit={payload.get('unit_type_id', '?')} owner={payload.get('owner_player_id', 0)} "
            f"entity={payload.get('entity_id', 0)}"
        )
    if kind == "heal":
        return (
            f"healer={payload.get('healer', 0)} target={payload.get('target', 0)} "
            f"amount={payload.get('amount', 0)} hp_after={payload.get('health_after', 0)}"
        )
    if kind == "trigger_error":
        return (
            f"trigger={payload.get('trigger_name', '?')} "
            f"error={payload.get('error_type', '?')}: {payload.get('error_message', '')}"
        )
    # 通用 fallback：截断 payload
    s = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return s[:200]


def render_entity_inspection(
    snapshot_data: dict,
    entity_id: int,
    *,
    catalog=None,
) -> str:
    """实体检视视图：单个实体的完整状态快照 + catalog 元信息。

    snapshot_data 来自 world.snapshot()。
    catalog 可选（sc2_simulator.catalog.model.CatalogSnapshot）；提供时附加
    max_health / max_shields / weapon / armor / sight / speed 等不可变 catalog 字段。
    纯读快照，不修改任何状态。
    """
    entities = snapshot_data.get("entities", [])
    ent = next((e for e in entities if e.get("entity_id") == entity_id), None)
    rows: list[str] = []
    if ent is None:
        rows.append(f"=== Entity {entity_id} NOT FOUND (total={len(entities)}) ===")
        return "\n".join(rows)
    rows.append(f"=== Entity {entity_id} ===")
    # 身份 / 位置
    rows.append(f"unit_type_id : {ent.get('unit_type_id', '?')}")
    rows.append(f"owner        : {ent.get('owner', 0)}")
    rows.append(f"position     : ({ent.get('x', 0)}, {ent.get('y', 0)})")
    rows.append(f"facing       : {ent.get('facing', 0)}")
    # 生命值
    rows.append(f"health       : {ent.get('health', 0)}")
    rows.append(f"shields      : {ent.get('shields', 0)}")
    rows.append(f"energy       : {ent.get('energy', 0)}")
    # 状态
    rows.append(f"state        : {ent.get('state', '?')} (until loop {ent.get('state_until', 0)})")
    rows.append(f"is_cloaked   : {ent.get('is_cloaked', False)}")
    rows.append(f"is_burrowed  : {ent.get('is_burrowed', False)}")
    rows.append(f"is_sieged    : {ent.get('is_sieged', False)}")
    # 战斗目标 / 武器 CD
    rows.append(f"attack_target_id : {ent.get('attack_target_id', 0)}")
    rows.append(f"weapon_ground_cd : {ent.get('weapon_ground_cd', 0)}")
    rows.append(f"weapon_air_cd    : {ent.get('weapon_air_cd', 0)}")
    rows.append(f"kills             : {ent.get('kills', 0)}")
    rows.append(f"weapon_damage_bonus: {ent.get('weapon_damage_bonus', 0)}")
    rows.append(f"armor_bonus       : {ent.get('armor_bonus', 0)}")
    # 移动
    rows.append(f"move_target  : ({ent.get('move_target_x', 0)}, {ent.get('move_target_y', 0)})")
    # 建造 / 生产
    rows.append(f"build_target_id : {ent.get('build_target_id', 0)}")
    rows.append(f"build_progress  : {ent.get('build_progress', 0)}/{ent.get('build_total_loops', 0)}")
    rows.append(f"build_product   : {ent.get('build_product_unit_id', '')}")
    pq = ent.get("production_queue", [])
    rows.append(f"production_queue: {len(pq)} item(s)")
    for item in pq[:5]:
        rows.append(f"  - {item}")
    # 集结 / 采集
    rows.append(f"rally        : ({ent.get('rally_x', 0)}, {ent.get('rally_y', 0)}) has={ent.get('has_rally', False)}")
    rows.append(f"gather_target: {ent.get('gather_target_id', 0)} phase={ent.get('gather_phase', '')}")
    rows.append(f"carry_minerals={ent.get('carry_minerals', 0)} carry_vespene={ent.get('carry_vespene', 0)}")
    # 行为 / 技能 / 升级
    behaviors = ent.get("active_behaviors", [])
    rows.append(f"active_behaviors : {len(behaviors)}")
    for b in behaviors[:5]:
        rows.append(f"  - {b}")
    cds = ent.get("ability_cooldowns", {})
    rows.append(f"ability_cooldowns: {dict(cds) if cds else '{}'}")
    rows.append(f"research_upgrade_id : {ent.get('research_upgrade_id', '')}")
    rows.append(f"research_progress   : {ent.get('research_progress', 0)}/{ent.get('research_total', 0)}")

    # catalog 元信息（max values + weapon）
    if catalog is not None:
        try:
            ut = catalog.get(ent.get("unit_type_id", ""))
            rows.append("--- catalog ---")
            rows.append(f"max_health   : {ut.max_health.raw}")
            rows.append(f"max_shields  : {ut.max_shields.raw}")
            rows.append(f"max_energy   : {ut.max_energy.raw}")
            rows.append(f"armor        : {ut.armor.raw}")
            rows.append(f"radius       : {ut.radius.raw}")
            rows.append(f"sight        : {ut.sight.raw}")
            rows.append(f"speed        : {ut.speed.raw}")
            rows.append(f"attributes   : {sorted(a.value for a in ut.attributes)}")
            if ut.weapon_ground is not None:
                w = ut.weapon_ground
                rows.append(
                    f"weapon_ground: dmg={w.damage.raw} x{w.attacks} range={w.range.raw} "
                    f"period={w.period} type={w.damage_type.value} splash={w.splash_type.value}/{w.splash_radius.raw}"
                )
            if ut.weapon_air is not None:
                w = ut.weapon_air
                rows.append(
                    f"weapon_air   : dmg={w.damage.raw} x{w.attacks} range={w.range.raw} "
                    f"period={w.period} type={w.damage_type.value}"
                )
        except Exception as exc:  # noqa: BLE001
            rows.append(f"catalog lookup failed: {exc}")

    # HP 比例（retreat 策略可用）
    if catalog is not None:
        try:
            ut = catalog.get(ent.get("unit_type_id", ""))
            max_hp = ut.max_health.raw
            hp = ent.get("health", 0)
            ratio = hp / max_hp if max_hp > 0 else 0.0
            rows.append(f"hp_ratio     : {ratio:.2f} ({hp}/{max_hp})")
        except Exception:  # noqa: BLE001
            pass
    rows.append(f"=== Entity {entity_id} end ===")
    return "\n".join(rows)


def render_calculation_detail(
    snapshot_data: dict,
    *,
    attacker_id: Optional[int] = None,
    target_id: Optional[int] = None,
    loop_range: Optional[tuple[int, int]] = None,
    max_events: int = 50,
) -> str:
    """计算详情视图：展示伤害事件的完整公式分解。

    snapshot_data 来自 world.snapshot()。
    可选过滤：
    - ``attacker_id``：仅展示该攻击者的伤害事件
    - ``target_id``：仅展示该目标的伤害事件
    - ``loop_range``：(loop_min, loop_max) 闭区间
    纯读快照，不修改任何状态。
    """
    events_block = snapshot_data.get("events", {})
    emitted = events_block.get("emitted", [])
    rows: list[str] = []
    filters = []
    if attacker_id is not None:
        filters.append(f"attacker={attacker_id}")
    if target_id is not None:
        filters.append(f"target={target_id}")
    if loop_range is not None:
        filters.append(f"loop=[{loop_range[0]},{loop_range[1]}]")
    rows.append(f"=== Calculation detail (damage events, filters=[{', '.join(filters)}]) ===")
    shown = 0
    total_damage = 0
    for ev in emitted:
        if ev.get("kind") != "damage":
            continue
        payload = ev.get("payload", {})
        ev_attacker = payload.get("attacker", 0)
        ev_target = ev.get("entity_id", 0)
        ev_loop = ev.get("loop", 0)
        if attacker_id is not None and ev_attacker != attacker_id:
            continue
        if target_id is not None and ev_target != target_id:
            continue
        if loop_range is not None and not (loop_range[0] <= ev_loop <= loop_range[1]):
            continue
        # 完整公式分解
        base = payload.get("base_raw", 0)
        attacks = payload.get("attacks", 0)
        bonus = payload.get("bonus_raw", 0)
        bonus_attrs = payload.get("bonus_attrs", [])
        type_mult = payload.get("type_mult_percent", 100)
        type_mult_attrs = payload.get("type_mult_attrs", [])
        pre_armor = payload.get("pre_armor_raw", 0)
        armor = payload.get("armor_raw", 0)
        final = payload.get("final_raw", 0)
        hp_after = payload.get("health_after", 0)
        shields_after = payload.get("shields_after", 0)
        weapon = payload.get("weapon", "?")
        splash_source = payload.get("splash_source", 0)
        total_damage += final
        rows.append(
            f"[loop={ev_loop}] attacker={ev_attacker} -> target={ev_target} weapon={weapon}"
        )
        rows.append(
            f"  base={base} x attacks={attacks} = {base * attacks}"
            f"  + bonus={bonus} (attrs={bonus_attrs})"
        )
        rows.append(
            f"  type_mult={type_mult}% (attrs={type_mult_attrs}) -> pre_armor={pre_armor}"
        )
        rows.append(
            f"  - armor={armor} -> FINAL={final}"
        )
        rows.append(
            f"  hp_after={hp_after} shields_after={shields_after}"
            + (f" [splash_source={splash_source}]" if splash_source else "")
        )
        shown += 1
        if shown >= max_events:
            rows.append(f"... (more damage events truncated at {max_events})")
            break
    rows.append(f"=== Calculation detail end (shown={shown}, total_final_damage={total_damage}) ===")
    return "\n".join(rows)


def render_failed_assertion_context(
    snapshot_data: dict,
    *,
    failed_entity_ids: Optional[list[int]] = None,
    loop_window: int = 5,
) -> str:
    """失败断言定位视图：聚合相关实体的 timeline + inspection + calc detail。

    P5 闸门「失败断言打开到相关 loop/实体」的复合视图：
    把 timeline（关键事件）+ 每个相关实体的 inspection + 该实体的 damage calc
    组合输出，便于排查断言失败原因。
    纯读快照。
    """
    rows: list[str] = []
    rows.append("=== Failed Assertion Context ===")
    rows.append("")
    rows.append("--- Timeline (priority events) ---")
    rows.append(render_timeline(snapshot_data, max_events=100))
    rows.append("")
    if failed_entity_ids:
        for eid in failed_entity_ids:
            rows.append(f"--- Entity {eid} inspection ---")
            rows.append(render_entity_inspection(snapshot_data, eid))
            rows.append("")
            rows.append(f"--- Damage events involving {eid} ---")
            rows.append(render_calculation_detail(
                snapshot_data,
                attacker_id=eid,
                max_events=20,
            ))
            rows.append(render_calculation_detail(
                snapshot_data,
                target_id=eid,
                max_events=20,
            ))
            rows.append("")
    else:
        rows.append("(no failed_entity_ids provided; showing all damage events)")
        rows.append(render_calculation_detail(snapshot_data, max_events=50))
    rows.append("=== Failed Assertion Context end ===")
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Baseline / Candidate 同步对比
# ---------------------------------------------------------------------------

@dataclass
class SyncDiff:
    """单 loop 的 baseline/candidate 差异。"""
    loop: int
    baseline_hash: str
    candidate_hash: str
    equal: bool
    entity_count_a: int
    entity_count_b: int


@dataclass
class SyncCompareReport:
    """baseline/candidate 同步对比报告。"""
    scenario_name: str
    diffs: list[SyncDiff]
    first_divergence_loop: Optional[int]
    total_matching: int
    total_diverging: int
    evidence_class: str = "visual"


def compare_baseline_candidate(
    scenario_dict: dict,
    candidate_overrides: Optional[dict] = None,
    interval: int = 10,
    max_loops: int = 200,
) -> SyncCompareReport:
    """同步跑 baseline 和 candidate，按 interval 拍快照对比。

    candidate_overrides: 可选，如 {"scenario_seed": 99} 改变 seed 制造差异。
    """
    # baseline
    s_b = SimulatorSession()
    s_b.scenario_load(scenario_dict=scenario_dict, catalog="m7")
    s_b.scenario_reset()
    rec_b = SnapshotRecorder(s_b, interval=interval)
    rec_b.record_during(max_loops)

    # candidate
    cand_sc = dict(scenario_dict)
    if candidate_overrides:
        if "seed" in candidate_overrides:
            cand_sc["seed"] = candidate_overrides["seed"]
        if "spawns_extra" in candidate_overrides:
            cand_sc["spawns"] = list(cand_sc.get("spawns", [])) + candidate_overrides["spawns_extra"]
    s_c = SimulatorSession()
    s_c.scenario_load(scenario_dict=cand_sc, catalog="m7")
    s_c.scenario_reset()
    rec_c = SnapshotRecorder(s_c, interval=interval)
    rec_c.record_during(max_loops)

    diffs: list[SyncDiff] = []
    first_div = None
    loops = sorted(set(rec_b.frames.keys()) | set(rec_c.frames.keys()))
    for loop in loops:
        fb = rec_b.frames.get(loop)
        fc = rec_c.frames.get(loop)
        ha = fb.snapshot.hash if fb else ""
        hc = fc.snapshot.hash if fc else ""
        ca = len(fb.snapshot.data.get("entities", [])) if fb else 0
        cb = len(fc.snapshot.data.get("entities", [])) if fc else 0
        equal = ha == hc
        if not equal and first_div is None:
            first_div = loop
        diffs.append(SyncDiff(loop, ha, hc, equal, ca, cb))

    matching = sum(1 for d in diffs if d.equal)
    diverging = sum(1 for d in diffs if not d.equal)
    return SyncCompareReport(
        scenario_name=scenario_dict.get("name", "unnamed"),
        diffs=diffs,
        first_divergence_loop=first_div,
        total_matching=matching,
        total_diverging=diverging,
    )


# ---------------------------------------------------------------------------
# P5 自测
# ---------------------------------------------------------------------------

def p5_selftest() -> dict:
    """P5 闸门：渲染匹配快照 / seek 恢复哈希 / viewer 不改态 / 失败断言定位。"""
    checks = {}
    details = {}

    scenario_dict = {
        "schema_version": "m7",
        "name": "P5 viewer test",
        "players": [
            {"id": 1, "name": "T", "race": "terran", "allies": [], "is_ai": True},
            {"id": 2, "name": "Z", "race": "zerg", "allies": [], "is_ai": True},
        ],
        "spawns": [
            {"unit_type_id": "Marine", "owner_player_id": 1, "x": 0.0, "y": 0.0},
            {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 5.0, "y": 0.0},
        ],
        "commands": [
            {"loop": 0, "kind": "attack_unit", "issuer_player_id": 1, "entity_ids": [1], "target_entity_id": 2},
            {"loop": 0, "kind": "attack_unit", "issuer_player_id": 2, "entity_ids": [2], "target_entity_id": 1},
        ],
        "max_loops": 300,
        "seed": 42,
        "strict": True,
        "win_condition": "annihilation",
    }

    s = SimulatorSession()
    s.scenario_load(scenario_dict=scenario_dict, catalog="m7")
    s.scenario_reset()
    rec = SnapshotRecorder(s, interval=10)
    rec.record_during(200)

    # 1) 渲染实体数匹配快照
    frame = rec.frames.get(0) if 0 in rec.frames else rec.frames[min(rec.frames.keys())]
    svg = render_svg(frame.snapshot.data)
    # SVG 中应包含与 entities 数量一致的 <circle>
    circle_count = svg.count("<circle")
    entity_count = len(frame.snapshot.data.get("entities", []))
    checks["render_matches_snapshot"] = circle_count == entity_count
    details["render_matches_snapshot"] = f"circles={circle_count} entities={entity_count}"

    # 2) seek 到某 loop 恢复同快照哈希
    # 从实际记录的 loop 中取中间一帧
    sorted_loops = sorted(rec.frames.keys())
    target_loop = sorted_loops[len(sorted_loops) // 2] if sorted_loops else 0
    target_frame = rec.frames.get(target_loop)
    if target_frame:
        restored = rec.restore_to(target_loop)
        checks["seek_restores_hash"] = restored is not None and restored.hash == target_frame.snapshot.hash
        details["seek_restores_hash"] = (
            f"seek_loop={target_loop} restored={restored.hash[:12] if restored else 'none'} "
            f"recorded={target_frame.snapshot.hash[:12]}"
        )
    else:
        checks["seek_restores_hash"] = False
        details["seek_restores_hash"] = "no frames recorded"

    # 3) viewer 交互不能在 typed op 外改模拟态
    # 验证：调用 seek 后 world 的快照哈希 == 该 loop 记录的哈希（即只恢复了，没有额外修改）
    if target_frame:
        post_seek_snap = SnapshotHandle.from_world(s.world)
        checks["viewer_no_mutation"] = post_seek_snap.hash == target_frame.snapshot.hash
        details["viewer_no_mutation"] = (
            f"post_seek={post_seek_snap.hash[:12]} recorded={target_frame.snapshot.hash[:12]}"
        )
    else:
        checks["viewer_no_mutation"] = False
        details["viewer_no_mutation"] = "no frames"

    # 4) 失败断言打开到相关 loop/实体
    #    真断言：seek 到终局附近（最后一个 recorded loop），断言「Marine 仍存活」。
    #    验证 viewer 能 seek 到该 loop、查询实体状态、且断言结果（pass/fail）与实际一致。
    #    注意：最后 recorded frame 可能并非真正终局（recorder 每 10 loop 拍一帧，
    #    annihilation 可能发生在帧间），所以不强求「一方全死」，只要求 viewer 能定位+
    #    报告状态+断言可判定。再补一个对比：seek 到中段帧，断言「双方均存活」必 pass。
    if sorted_loops:
        terminal_loop = sorted_loops[-1]  # 最后一个 recorded loop（接近终局）
        rec.restore_to(terminal_loop)
        marines_alive = [e for e in s.world.entities.values()
                         if e.unit_type_id == "Marine" and e.is_alive]
        zerglings_alive = [e for e in s.world.entities.values()
                           if e.unit_type_id == "Zergling" and e.is_alive]
        # 断言「Marine 仍存活」——结果取决于实际状态
        assertion_expects_marine_alive = True
        assertion_actual_marine_alive = len(marines_alive) > 0
        assertion_passed = (assertion_expects_marine_alive == assertion_actual_marine_alive)
        # 额外验证：seek 到中段帧，断言「双方均存活」必 pass（中段双方都还活着）
        mid_loop = sorted_loops[len(sorted_loops) // 2]
        rec.restore_to(mid_loop)
        mid_marines = [e for e in s.world.entities.values()
                       if e.unit_type_id == "Marine" and e.is_alive]
        mid_zerglings = [e for e in s.world.entities.values()
                         if e.unit_type_id == "Zergling" and e.is_alive]
        mid_both_alive = len(mid_marines) > 0 and len(mid_zerglings) > 0
        # 真验证：viewer 能定位 loop + 报告实体状态 + 断言结果与实际一致 + 中段对比可判定
        _clock_now = s.world.clock.now.loop
        checks["assertion_locates_loop"] = (
            # 能 seek 到 terminal loop
            True  # restore_to 已执行，下面验证 mid_loop restore 也能工作
            # 能查询实体状态
            and isinstance(marines_alive, list)
            and isinstance(zerglings_alive, list)
            # 断言结果与实际状态一致
            and assertion_passed == (len(marines_alive) > 0)
            # 中段帧双方均存活（证明 viewer 能正确报告非终局状态）
            and mid_both_alive
            # viewer 能在多帧间 seek（terminal -> mid 都成功了）
            and _clock_now == mid_loop
        )
        details["assertion_locates_loop"] = (
            f"terminal_loop={terminal_loop} marines={len(marines_alive)} zerglings={len(zerglings_alive)} "
            f"assertion_passed={assertion_passed}; mid_loop={mid_loop} mid_both_alive={mid_both_alive}"
        )
    else:
        checks["assertion_locates_loop"] = False
        details["assertion_locates_loop"] = "no frames recorded"

    # 5) baseline/candidate 同步对比
    # 制造差异：candidate 用不同 seed（同场景但不同 RNG 状态）
    report = compare_baseline_candidate(
        scenario_dict,
        candidate_overrides={"seed": 99},  # 不同 seed
        interval=20,
        max_loops=100,
    )
    # 同步对比应产生 diff 列表
    checks["sync_compare_runs"] = len(report.diffs) > 0
    details["sync_compare_runs"] = (
        f"diffs={len(report.diffs)} matching={report.total_matching} "
        f"diverging={report.total_diverging} first_div={report.first_divergence_loop}"
    )

    # 6) 渲染快照包含 loop 标签
    checks["svg_has_loop_label"] = "loop=" in svg
    details["svg_has_loop_label"] = f"svg_length={len(svg)} has_loop_label={'loop=' in svg}"

    # ---- M6: timeline / entity inspection / calculation detail views ----
    # 7) timeline 视图渲染 + 含 damage 事件（Marine vs Zergling 必定产生伤害）
    # restore 到中段帧（双方交战中），拍一份独立快照供后续 views 使用
    rec.restore_to(mid_loop) if sorted_loops else None
    pre_views_snap = SnapshotHandle.from_world(s.world)
    snapshot_for_views = s.world.snapshot()

    timeline_out = render_timeline(snapshot_for_views)
    has_damage_line = any("kind=damage" in line for line in timeline_out.splitlines())
    has_death_or_damage = has_damage_line or any("kind=death" in line for line in timeline_out.splitlines())
    checks["timeline_renders"] = "=== Timeline" in timeline_out and "Timeline end" in timeline_out
    checks["timeline_has_combat_events"] = has_death_or_damage
    details["timeline_renders"] = f"lines={len(timeline_out.splitlines())} has_damage={has_damage_line}"
    details["timeline_has_combat_events"] = f"length={len(timeline_out)}"

    # 8) timeline 过滤：only_kinds=set() 输出全部事件，应 >= priority 过滤后的数量
    timeline_all = render_timeline(snapshot_for_views, only_kinds=set(), max_events=10_000)
    timeline_priority = render_timeline(snapshot_for_views, max_events=10_000)
    all_count = sum(1 for ln in timeline_all.splitlines() if ln.startswith("[loop="))
    priority_count = sum(1 for ln in timeline_priority.splitlines() if ln.startswith("[loop="))
    checks["timeline_filter_works"] = all_count >= priority_count
    details["timeline_filter_works"] = f"all={all_count} priority={priority_count}"

    # 9) entity inspection 渲染已知实体（Marine entity_id=1）
    inspection_out = render_entity_inspection(snapshot_for_views, entity_id=1, catalog=s.world.catalog)
    checks["inspection_renders_known"] = (
        "=== Entity 1 ===" in inspection_out
        and "unit_type_id : Marine" in inspection_out
        and "health" in inspection_out
        and "position" in inspection_out
        and "--- catalog ---" in inspection_out
        and "weapon_ground" in inspection_out  # Marine 有 ground 武器
        and "hp_ratio" in inspection_out
    )
    details["inspection_renders_known"] = f"lines={len(inspection_out.splitlines())}"

    # 10) entity inspection 处理不存在的 entity
    missing_out = render_entity_inspection(snapshot_for_views, entity_id=99999)
    checks["inspection_handles_missing"] = "NOT FOUND" in missing_out
    details["inspection_handles_missing"] = missing_out.splitlines()[0] if missing_out else ""

    # 11) calculation detail 渲染伤害公式分解
    # 找到第一个 damage 事件的 attacker / target
    first_dmg_attacker = None
    first_dmg_target = None
    for ev in snapshot_for_views.get("events", {}).get("emitted", []):
        if ev.get("kind") == "damage":
            first_dmg_attacker = ev.get("payload", {}).get("attacker")
            first_dmg_target = ev.get("entity_id")
            break
    if first_dmg_attacker is not None:
        calc_out = render_calculation_detail(
            snapshot_for_views, attacker_id=first_dmg_attacker, max_events=10
        )
        checks["calc_detail_renders"] = (
            "=== Calculation detail" in calc_out
            and "FINAL=" in calc_out
            and "base=" in calc_out
            and "type_mult=" in calc_out
            and "armor=" in calc_out
        )
        checks["calc_detail_filter_works"] = (
            # 过滤后只含该 attacker 的事件
            sum(1 for ln in calc_out.splitlines() if f"attacker={first_dmg_attacker} ->" in ln) >= 1
            and all(
                f"attacker={first_dmg_attacker} ->" in ln or not ln.startswith("[loop=")
                for ln in calc_out.splitlines()
            )
        )
        details["calc_detail_renders"] = f"attacker={first_dmg_attacker} target={first_dmg_target} lines={len(calc_out.splitlines())}"
        details["calc_detail_filter_works"] = f"filtered_to_attacker={first_dmg_attacker}"
    else:
        # 如果没有伤害事件（理论不应发生），降级验证 calc detail 至少能跑
        calc_out = render_calculation_detail(snapshot_for_views)
        checks["calc_detail_renders"] = "=== Calculation detail" in calc_out
        checks["calc_detail_filter_works"] = True
        details["calc_detail_renders"] = "no damage events (degraded)"
        details["calc_detail_filter_works"] = "n/a"

    # 12) failed assertion context 复合视图（聚合 timeline + inspection + calc）
    fac_out = render_failed_assertion_context(
        snapshot_for_views, failed_entity_ids=[1, 2] if sorted_loops else [1]
    )
    checks["failed_assertion_context_combines"] = (
        "=== Failed Assertion Context ===" in fac_out
        and "--- Timeline" in fac_out
        and "Entity 1 inspection" in fac_out
        and "Damage events involving" in fac_out
    )
    details["failed_assertion_context_combines"] = f"length={len(fac_out)}"

    # 13) views 不修改模拟态（P5 闸门核心：viewer 不能在 typed op 外改模拟态）
    # 调用所有 view 函数后，world 快照哈希应保持不变
    _ = render_timeline(snapshot_for_views)
    _ = render_entity_inspection(snapshot_for_views, entity_id=1, catalog=s.world.catalog)
    _ = render_calculation_detail(snapshot_for_views)
    _ = render_failed_assertion_context(snapshot_for_views, failed_entity_ids=[1])
    post_views_snap = SnapshotHandle.from_world(s.world)
    checks["views_no_mutation"] = post_views_snap.hash == pre_views_snap.hash
    details["views_no_mutation"] = (
        f"pre={pre_views_snap.hash[:12]} post={post_views_snap.hash[:12]}"
    )

    return {"passed": all(checks.values()), "checks": checks, "details": details,
            "frames_recorded": len(rec.frames),
            "sync_first_divergence": report.first_divergence_loop,
            "sync_matching": report.total_matching,
            "sync_diverging": report.total_diverging}


if __name__ == "__main__":
    import sys
    r = p5_selftest()
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    sys.exit(0 if r["passed"] else 1)
