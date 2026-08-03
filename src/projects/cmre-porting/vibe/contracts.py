"""§4.4 稳定工具契约 facade —— 在项目本地适配层暴露 Catalog/Scenario/Observation/
Action/Snapshot/Trace/Capability，底层委托给只读的 ``sc2_simulator``。

设计原则：
- 不编辑 sc2_simulator；本层是薄适配，吸收其公共 API 缺失（capability matrix SIM-CAP-GAP-004）。
- 不假设 sc2_simulator 行为正确；调用方应通过断言验证（P1 闸门：同 task/catalog/seed/版本同 trace 哈希）。
- 契约以 dataclass + 方法暴露，便于消费者依赖稳定表面，而非深 import sc2_simulator 子模块。

证据分类：本层是 ``static`` 适配代码；其行为正确性由 ``simulator_session`` 的运行时验证（``simulator`` 证据）保证。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .sim_path import ensure_simulator_on_path

ensure_simulator_on_path()

from sc2_simulator.catalog.model import CatalogSnapshot, UnitType, WeaponType  # noqa: E402
from sc2_simulator.scenario.loader import load_scenario  # noqa: E402
from sc2_simulator.scenario.model import ScenarioDefinition  # noqa: E402
from sc2_simulator.scenario.runner import RunResult, build_world, run_scenario  # noqa: E402
from sc2_simulator.world.snapshot import snapshot_hash, clone_world  # noqa: E402
from sc2_simulator.reporting.trace import trace_hash  # noqa: E402

# ---------------------------------------------------------------------------
# Catalog 契约
# ---------------------------------------------------------------------------

# 保真度标签（§4.2）：sc2_simulator 当前无逐单位保真度，本层补上。
# exact=与 SC2 一致 / approximate=数值近似 / partial=部分规则 / unsupported=未实现。
Fidelity = str  # "exact" | "approximate" | "partial" | "unsupported"


@dataclass(frozen=True)
class CatalogHandle:
    """Catalog 不可变句柄。包裹 sc2_simulator.CatalogSnapshot + 计算内容哈希 + 保真度表。"""

    snapshot: CatalogSnapshot
    content_hash: str
    fidelity: Mapping[str, Fidelity]  # unit_id -> fidelity
    schema_version: str
    source: str  # 来源标识（如 "sc2_simulator.m7"）

    def get(self, unit_id: str) -> UnitType:
        return self.snapshot.get(unit_id)

    def fidelity_of(self, unit_id: str) -> Fidelity:
        return self.fidelity.get(unit_id, "approximate")


def _unit_fidelity(ut: UnitType) -> Fidelity:
    """根据 capability matrix 标注逐单位保真度。

    sc2_simulator 缺口状态（stage 06 修复后）：
    - SIM-CAP-GAP-002（空战）已修复：weapon_air 实际可开火，对空单位不再 unsupported。
    - SIM-CAP-GAP-003（行为乘数）已修复：speed/attack_speed/armor_add/damage_add 已接入规则。
    - 所有单位仍为手写 IR（非真实 CMRE XML 导入），默认 approximate。
    - 真实 CMRE XML 导入留待后续 stage（需 writeScope 扩展到 CMRE mod 源）。
    """
    # stage 06 后无 unsupported 单位（空战 + 行为乘数已接线）
    # 所有单位仍为手写数值，标 approximate
    return "approximate"


def compute_catalog_hash(snapshot: CatalogSnapshot) -> str:
    """计算 Catalog 真实内容哈希（覆盖 schema + 单位字段），替代 sc2_simulator 的静态字符串。"""
    payload = {
        "schema_version": snapshot.schema_version,
        "units": {
            uid: {
                "id": u.id,
                "race": u.race,
                "max_health": u.max_health.raw,
                "max_shields": u.max_shields.raw,
                "max_energy": u.max_energy.raw,
                "armor": u.armor.raw,
                "radius": u.radius.raw,
                "speed": u.speed.raw,
                "sight": u.sight.raw,
                "minerals": u.minerals,
                "vespene": u.vespene,
                "supply": u.supply,
                "build_time": u.build_time,
                "weapon_ground": _weapon_dict(u.weapon_ground),
                "weapon_air": _weapon_dict(u.weapon_air),
                "is_structure": u.is_structure,
                "is_worker": u.is_worker,
            }
            for uid, u in snapshot.units.items()
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _weapon_dict(w: Optional[WeaponType]) -> Optional[dict]:
    if w is None:
        return None
    return {
        "id": w.id,
        "damage": w.damage.raw,
        "attacks": w.attacks,
        "range": w.range.raw,
        "period": w.period,
        "damage_type": _catalog_value(w.damage_type),
        "splash_type": _catalog_value(w.splash_type),
        "splash_radius": w.splash_radius.raw,
        "projectile_speed": w.projectile_speed.raw,
        "heal_amount": w.heal_amount.raw,
    }


def _catalog_value(value: Any) -> str:
    """Normalize Enum and legacy string Catalog fields for stable hashing."""
    raw = getattr(value, "value", value)
    return str(raw).lower()


def wrap_catalog(
    snapshot: CatalogSnapshot, source: str = "sc2_simulator"
) -> CatalogHandle:
    fidelity = {uid: _unit_fidelity(u) for uid, u in snapshot.units.items()}
    return CatalogHandle(
        snapshot=snapshot,
        content_hash=compute_catalog_hash(snapshot),
        fidelity=fidelity,
        schema_version=snapshot.schema_version,
        source=source,
    )


# ---------------------------------------------------------------------------
# Scenario 契约
# ---------------------------------------------------------------------------


@dataclass
class ScenarioHandle:
    """场景句柄。包裹 sc2_simulator.ScenarioDefinition。"""

    definition: ScenarioDefinition
    path: Optional[str] = None

    @classmethod
    def from_file(cls, path: str) -> "ScenarioHandle":
        return cls(definition=load_scenario(path), path=path)

    @classmethod
    def from_dict(cls, data: dict) -> "ScenarioHandle":
        return cls(definition=load_scenario(data))


# ---------------------------------------------------------------------------
# Snapshot 契约
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SnapshotHandle:
    """快照句柄。包裹 world.snapshot() 的 dict + 哈希。"""

    data: dict
    hash: str
    loop: int

    @classmethod
    def from_world(cls, world) -> "SnapshotHandle":
        data = world.snapshot()
        return cls(data=data, hash=snapshot_hash(data), loop=world.clock.now.loop)


# ---------------------------------------------------------------------------
# Observation 契约（玩家可见状态 + 可选全知测试状态）
# ---------------------------------------------------------------------------


@dataclass
class Observation:
    """玩家可见观察。AI 消费者（P4B）只读此对象，不能访问全知 world。"""

    loop: int
    player_id: int
    own_units: list[dict]
    visible_enemies: list[dict]
    resources: dict
    mission: dict  # 任务/目标摘要（P4D 填充；P1 仅占位）
    visible_allies: list[dict] = field(default_factory=list)
    alliance_summary: list[dict] = field(default_factory=list)
    # Neutral resources are part of the visible tactical surface.  Keeping
    # them on Observation prevents policies from reaching into WorldState.
    mineral_fields: list[dict] = field(default_factory=list)
    vespene_geysers: list[dict] = field(default_factory=list)
    # Technology is public player state: completed upgrades plus research
    # currently visible on owned research facilities.
    tech: dict = field(default_factory=dict)

    @classmethod
    def from_world(cls, world, player_id: int) -> "Observation":
        from sc2_simulator.systems import vision as vision_system

        own = [_entity_brief(e, world) for e in world.entities_of(player_id)]
        vis = [
            _entity_brief(e, world)
            for e in vision_system.visible_enemies(world, player_id)
            if not _is_neutral_entity(world, e)
        ]
        allies = [
            _entity_brief(e, world)
            for e in world.entities.values()
            if e.is_alive
            and e.owner_player_id != player_id
            and world.players.is_ally(player_id, e.owner_player_id)
            and vision_system.is_visible(world, player_id, e)
        ]
        visible_resources = [
            _entity_brief(e, world)
            for e in world.entities.values()
            if e.is_alive
            and e.unit_type_id in {"MineralField", "VespeneGeyser"}
            and vision_system.is_visible(world, player_id, e)
        ]
        res = world.get_resources(player_id).snapshot()
        researching = [
            {
                "entity_id": entity.entity_id,
                "unit_type_id": entity.unit_type_id,
                "upgrade_id": entity.research_upgrade_id,
                "progress": int(entity.research_progress),
                "total": int(entity.research_total),
            }
            for entity in world.entities_of(player_id)
            if entity.is_alive and entity.research_upgrade_id
        ]
        tech = {
            "completed_upgrades": sorted(
                str(upgrade_id)
                for upgrade_id in world.completed_upgrades.get(player_id, [])
            ),
            "researching": researching,
        }
        alliance_summary = []
        observer = world.players.get(player_id)
        observed_player_ids = [player_id] + sorted(observer.allies)
        for observed_player_id in observed_player_ids:
            if observed_player_id not in world.players.players:
                continue
            units = own if observed_player_id == player_id else [
                unit for unit in allies if unit["owner"] == observed_player_id
            ]
            leader = min(units, key=lambda unit: unit["entity_id"], default=None)
            position = None if leader is None else {
                "x": leader["x"],
                "y": leader["y"],
            }
            player = world.players.get(observed_player_id)
            alliance_summary.append({
                "player_id": observed_player_id,
                "is_self": observed_player_id == player_id,
                "is_ai": player.is_ai,
                "unit_count": len(units),
                "alive": bool(units),
                "leader_position": position,
                "base_position": position,
            })
        return cls(
            loop=world.clock.now.loop,
            player_id=player_id,
            own_units=own,
            visible_enemies=vis,
            resources=res,
            mission={"win_condition": getattr(world, "_win_condition", "annihilation")},
            visible_allies=allies,
            alliance_summary=alliance_summary,
            mineral_fields=[
                resource for resource in visible_resources
                if resource["unit_type_id"] == "MineralField"
            ],
            vespene_geysers=[
                resource for resource in visible_resources
                if resource["unit_type_id"] == "VespeneGeyser"
            ],
            tech=tech,
        )


def _entity_brief(e, world=None) -> dict:
    """实体摘要。world 可选，提供时附加 max_health（M4: HP 比例决策需要）。

    位置契约：``x`` / ``y`` 返回**世界单位 float**（= ``e.x.to_float()``），
    非 fixed-point raw int。原因：region/战术决策/查看器都以世界单位比较；
    health/shields/energy 等结算字段保留 raw int（P4A 断言 marine_hp=46080=45*1024）。
    """
    d = {
        "entity_id": e.entity_id,
        "unit_type_id": e.unit_type_id,
        "owner": e.owner_player_id,
        "x": e.x.to_float(),
        "y": e.y.to_float(),
        "health": e.health.raw,
        "shields": e.shields.raw,
        "energy": e.energy.raw,
        "state": e.state.value if hasattr(e.state, "value") else str(e.state),
    }
    if world is not None:
        try:
            ut = world.catalog.get(e.unit_type_id)
            d["max_health"] = ut.max_health.raw
            attributes = {
                getattr(attribute, "value", str(attribute))
                for attribute in getattr(ut, "attributes", ())
            }
            d["attributes"] = sorted(attributes)
            d["is_biological"] = "biological" in attributes
            d["build_progress"] = (
                1.0
                if e.build_total_loops <= 0
                else min(1.0, e.build_progress / e.build_total_loops)
            )
        except Exception:  # noqa: BLE001 — catalog 缺失时优雅降级
            d["max_health"] = 0
            d["build_progress"] = 1.0

        # Mirror the subset of SC2 raw orders consumed by the strategy.  The
        # old facade omitted this state, so a producer or builder looked idle
        # on every observation and received duplicate commands.
        orders: list[dict] = []
        state = e.state.value if hasattr(e.state, "value") else str(e.state)
        unit_type = world.catalog.get(e.unit_type_id)
        has_weapon = (
            getattr(unit_type, "weapon_ground", None) is not None
            or getattr(unit_type, "weapon_air", None) is not None
        )
        if e.attack_target_id and has_weapon:
            orders.append({
                "ability_id": (
                    "Heal"
                    if getattr(unit_type.weapon_ground, "is_heal", False)
                    else "Attack"
                ),
                "target_unit_tag": int(e.attack_target_id),
            })
        elif state == "building" and e.build_target_id:
            orders.append({
                "ability_id": "Build",
                "target_unit_tag": int(e.build_target_id),
                "unit_type_id": e.build_product_unit_id,
            })
        elif state == "gathering" and e.gather_target_id:
            orders.append({
                "ability_id": "Smart",
                "target_unit_tag": int(e.gather_target_id),
            })
        elif state in {"moving", "attack_moving"}:
            orders.append({
                "ability_id": "Move",
                "target_x": e.move_target_x.to_float(),
                "target_y": e.move_target_y.to_float(),
            })
        elif e.production_queue or e.secondary_production_queue:
            queue = e.production_queue or e.secondary_production_queue
            item = queue[0]
            orders.append({
                "ability_id": "Train",
                "unit_type_id": item.product_unit_id,
                "remaining_loops": int(item.remaining_loops),
            })
        elif e.research_upgrade_id:
            orders.append({
                "ability_id": "Research",
                "upgrade_id": e.research_upgrade_id,
                "progress": int(e.research_progress),
                "total": int(e.research_total),
            })
        d["orders"] = orders
    return d


def _is_neutral_entity(world, entity) -> bool:
    """Keep neutral map objects out of the policy's hostile-unit view.

    The read-only simulator's player relation primitive treats every
    non-ally owner as hostile, including player 0 neutral resources.  The
    project-owned observation contract must preserve the SC2 distinction:
    neutral resources are exposed through ``mineral_fields``/``vespene_geysers``
    but are never tactical enemies.
    """
    unit_type = world.catalog.get(entity.unit_type_id)
    race = getattr(unit_type, "race", "")
    return getattr(race, "value", race) == "neutral"


# ---------------------------------------------------------------------------
# Trace 契约
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TraceHandle:
    """trace 句柄。包裹 world.events + 哈希。"""

    hash: str
    event_count: int
    command_result_count: int

    @classmethod
    def from_world(cls, world) -> "TraceHandle":
        return cls(
            hash=trace_hash(world),
            event_count=len(world.events.emitted),
            command_result_count=len(world.command_results),
        )


# ---------------------------------------------------------------------------
# Capability 契约
# ---------------------------------------------------------------------------


@dataclass
class CapabilityReport:
    """能力报告：保真度 + 运行时使用覆盖。"""

    catalog_hash: str
    schema_version: str
    fidelity: Mapping[str, Fidelity]
    used_in_run: list[str] = field(default_factory=list)

    @classmethod
    def from_catalog(
        cls, cat: CatalogHandle, used: Optional[list] = None
    ) -> "CapabilityReport":
        return cls(
            catalog_hash=cat.content_hash,
            schema_version=cat.schema_version,
            fidelity=dict(cat.fidelity),
            used_in_run=list(used or []),
        )


# ---------------------------------------------------------------------------
# Victory Time 契约（Stage 08 MVP 核心指标）
# ---------------------------------------------------------------------------


@dataclass
class VictoryTimeMetric:
    """胜利时间指标（核心 KPI）。"""

    end_loop: int
    game_time_sec: float
    nights_survived: int
    victory: bool
    end_reason: str

    @classmethod
    def from_mission_result(cls, result, world) -> "VictoryTimeMetric":
        nights = 0
        if hasattr(world, "_wave_timing") and world._wave_timing:
            for night in world._wave_timing.get("nights", []):
                if result.end_loop >= night.get("end_loop", 0):
                    nights += 1
        return cls(
            end_loop=result.end_loop,
            game_time_sec=result.end_loop / 22.4,
            nights_survived=nights,
            victory=result.terminated
            and result.end_reason in ("all_objectives_success", "survive_loops"),
            end_reason=result.end_reason,
        )

    @classmethod
    def from_simulator_session(
        cls, session, terminated: bool, end_reason: str
    ) -> "VictoryTimeMetric":
        loop = session.world.clock.now.loop if session.world else 0
        nights = 0
        if hasattr(session, "_wave_timing") and session._wave_timing:
            for night in session._wave_timing.get("nights", []):
                if loop >= night.get("end_loop", 0):
                    nights += 1
        return cls(
            end_loop=loop,
            game_time_sec=loop / 22.4,
            nights_survived=nights,
            victory=terminated
            and end_reason in ("max_loops_reached", "all_objectives_success"),
            end_reason=end_reason,
        )


# 扩展 Observation 增加胜利时间相关字段（可选，不破坏现有消费者）
# 在 from_world 时可由上层注入


__all__ = [
    "Fidelity",
    "CatalogHandle",
    "ScenarioHandle",
    "SnapshotHandle",
    "Observation",
    "TraceHandle",
    "CapabilityReport",
    "VictoryTimeMetric",
    "wrap_catalog",
    "compute_catalog_hash",
    "load_scenario",
    "build_world",
    "run_scenario",
    "clone_world",
    "RunResult",
    "snapshot_hash",
    "trace_hash",
]
