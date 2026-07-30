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
                "id": u.id, "race": u.race,
                "max_health": u.max_health.raw, "max_shields": u.max_shields.raw,
                "max_energy": u.max_energy.raw, "armor": u.armor.raw,
                "radius": u.radius.raw, "speed": u.speed.raw, "sight": u.sight.raw,
                "minerals": u.minerals, "vespene": u.vespene, "supply": u.supply,
                "build_time": u.build_time,
                "weapon_ground": _weapon_dict(u.weapon_ground),
                "weapon_air": _weapon_dict(u.weapon_air),
                "is_structure": u.is_structure, "is_worker": u.is_worker,
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
        "id": w.id, "damage": w.damage.raw, "attacks": w.attacks,
        "range": w.range.raw, "period": w.period,
        "damage_type": w.damage_type.value,
        "splash_type": w.splash_type.value, "splash_radius": w.splash_radius.raw,
        "projectile_speed": w.projectile_speed.raw, "heal_amount": w.heal_amount.raw,
    }


def wrap_catalog(snapshot: CatalogSnapshot, source: str = "sc2_simulator") -> CatalogHandle:
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

    @classmethod
    def from_world(cls, world, player_id: int) -> "Observation":
        from sc2_simulator.systems import vision as vision_system
        own = [_entity_brief(e, world) for e in world.entities_of(player_id)]
        vis = [_entity_brief(e, world) for e in vision_system.visible_enemies(world, player_id)]
        res = world.get_resources(player_id).snapshot()
        return cls(
            loop=world.clock.now.loop,
            player_id=player_id,
            own_units=own,
            visible_enemies=vis,
            resources=res,
            mission={"win_condition": getattr(world, "_win_condition", "annihilation")},
        )


def _entity_brief(e, world=None) -> dict:
    """实体摘要。world 可选，提供时附加 max_health（M4: HP 比例决策需要）。

    位置契约：``x`` / ``y`` 返回**世界单位 float**（= ``e.x.to_float()``），
    非 fixed-point raw int。原因：region/战术决策/查看器都以世界单位比较；
    health/shields/energy 等结算字段保留 raw int（P4A 断言 marine_hp=46080=45*1024）。
    """
    d = {
        "entity_id": e.entity_id, "unit_type_id": e.unit_type_id,
        "owner": e.owner_player_id,
        "x": e.x.to_float(), "y": e.y.to_float(),
        "health": e.health.raw, "shields": e.shields.raw, "energy": e.energy.raw,
        "state": e.state.value if hasattr(e.state, "value") else str(e.state),
    }
    if world is not None:
        try:
            ut = world.catalog.get(e.unit_type_id)
            d["max_health"] = ut.max_health.raw
        except Exception:  # noqa: BLE001 — catalog 缺失时优雅降级
            d["max_health"] = 0
    return d


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
    def from_catalog(cls, cat: CatalogHandle, used: Optional[list] = None) -> "CapabilityReport":
        return cls(
            catalog_hash=cat.content_hash,
            schema_version=cat.schema_version,
            fidelity=dict(cat.fidelity),
            used_in_run=list(used or []),
        )


__all__ = [
    "Fidelity", "CatalogHandle", "ScenarioHandle", "SnapshotHandle",
    "Observation", "TraceHandle", "CapabilityReport",
    "wrap_catalog", "compute_catalog_hash",
    "load_scenario", "build_world", "run_scenario", "clone_world",
    "RunResult", "snapshot_hash", "trace_hash",
]
