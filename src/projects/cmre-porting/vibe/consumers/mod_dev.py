"""P4A —— Mod 开发消费者。

P4A 闸门（plan §5 P4A）：
- 真实单位成本/伤害/生产时间变更可导入对比
- 报告显示预期机械变化且无关回归稳定
- 不支持行为在 verdict 可见

实现：
- 候选补丁（CatalogPatch）：对 baseline catalog 应用字段级变更（damage / cost / build_time 等）
- A/B runner：同场景跑 baseline vs candidate，输出差异报告
- verdict：聚合机械变化是否生效 + 不相关字段是否未变 + unsupported 是否显式标注
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Optional

from ..catalog_bridge import CatalogBridge, Provenance, cmre_slice_catalog, make_bridge
from ..contracts import CatalogHandle, compute_catalog_hash, wrap_catalog
from ..sim_path import ensure_simulator_on_path

ensure_simulator_on_path()

from sc2_simulator.catalog.model import CatalogSnapshot, UnitType, WeaponType  # noqa: E402
from sc2_simulator.catalog.m7_units import m7_catalog  # noqa: E402
from sc2_simulator.fixed import Fixed, fixed_from  # noqa: E402
from sc2_simulator.reporting.trace import trace_hash  # noqa: E402

from ..simulator_session import SimulatorSession


@dataclass
class CatalogPatch:
    """单位字段级补丁。"""

    unit_id: str
    field: str  # "weapon_ground.damage" | "minerals" | "build_time" | "armor" | "max_health"
    old_value: object
    new_value: object
    rationale: str = ""

    def describe(self) -> str:
        return f"{self.unit_id}.{self.field}: {self.old_value} -> {self.new_value} ({self.rationale})"


@dataclass
class ABRunResult:
    """单次 A/B 跑结果。"""

    label: str
    end_loop: int
    end_reason: str
    winner: Optional[int]
    trace_hash: str
    survivors: dict  # player_id -> count
    final_snapshot_hash: str


@dataclass
class ABReport:
    """A/B 对比报告。"""

    scenario_name: str
    baseline: ABRunResult
    candidate: ABRunResult
    patches: list[CatalogPatch]
    mechanical_changes_observed: dict  # field -> {baseline, candidate, changed}
    unrelated_fields_stable: bool
    unsupported_units_used: list[str]
    verdict: str  # PASS | FAIL | INCONCLUSIVE
    evidence_class: str = "simulator"


def apply_patch(baseline: CatalogSnapshot, patches: list[CatalogPatch]) -> CatalogSnapshot:
    """对 baseline catalog 应用补丁，返回新的 candidate CatalogSnapshot。

    由于 UnitType/WeaponType 是 frozen dataclass，用 dataclasses.replace 重建。
    """
    units = dict(baseline.units)
    for p in patches:
        if p.unit_id not in units:
            raise ValueError(f"补丁引用不存在单位: {p.unit_id}")
        ut = units[p.unit_id]
        if p.field == "minerals":
            units[p.unit_id] = _replace_ut(ut, minerals=int(p.new_value))
        elif p.field == "vespene":
            units[p.unit_id] = _replace_ut(ut, vespene=int(p.new_value))
        elif p.field == "build_time":
            units[p.unit_id] = _replace_ut(ut, build_time=int(p.new_value))
        elif p.field == "supply":
            units[p.unit_id] = _replace_ut(ut, supply=int(p.new_value))
        elif p.field == "armor":
            units[p.unit_id] = _replace_ut(ut, armor=fixed_from(p.new_value))
        elif p.field == "max_health":
            units[p.unit_id] = _replace_ut(ut, max_health=fixed_from(p.new_value))
        elif p.field == "weapon_ground.damage":
            w = ut.weapon_ground
            if w is None:
                raise ValueError(f"{p.unit_id} 无 weapon_ground")
            new_w = _replace_w(w, damage=fixed_from(p.new_value))
            units[p.unit_id] = _replace_ut(ut, weapon_ground=new_w)
        elif p.field == "weapon_ground.range":
            w = ut.weapon_ground
            if w is None:
                raise ValueError(f"{p.unit_id} 无 weapon_ground")
            new_w = _replace_w(w, range=fixed_from(p.new_value))
            units[p.unit_id] = _replace_ut(ut, weapon_ground=new_w)
        elif p.field == "weapon_ground.period":
            w = ut.weapon_ground
            if w is None:
                raise ValueError(f"{p.unit_id} 无 weapon_ground")
            new_w = _replace_w(w, period=int(p.new_value))
            units[p.unit_id] = _replace_ut(ut, weapon_ground=new_w)
        else:
            raise ValueError(f"未支持补丁字段: {p.field}")
    return CatalogSnapshot(
        schema_version=baseline.schema_version + "+patched",
        units=units,
        content_hash="",
    )


def _replace_ut(ut: UnitType, **kwargs) -> UnitType:
    from dataclasses import replace
    return replace(ut, **kwargs)


def _replace_w(w: WeaponType, **kwargs) -> WeaponType:
    from dataclasses import replace
    return replace(w, **kwargs)


def _run_scenario_once_with_catalog(
    s: SimulatorSession,
    catalog_snap: CatalogSnapshot,
    scenario_dict: Optional[dict] = None,
) -> None:
    """在已有 session 上应用指定 catalog，重建 world（不跑 scenario.run）。

    若提供 scenario_dict，先 scenario_load(m7) 再替换；否则假定已 load。
    供 mod_dev._run_scenario_once 和 sc2_calibration.Sc2BackendStub 共用。
    """
    if scenario_dict is not None:
        s.scenario_load(scenario_dict=scenario_dict, catalog="m7")
    # 替换 catalog handle
    handle = wrap_catalog(catalog_snap, source="ab-run")
    s.catalog = handle
    s.scenario_reset()
    # 重建 world 用新 catalog（reset 已用 m7 建 world，但单位字段已固化在 entity 上）
    from ..contracts import build_world
    s.world = build_world(s.scenario.definition, catalog_snap)
    s.world._win_condition = s.scenario.definition.win_condition  # noqa: SLF001
    s.terminated = False
    s._initial_snapshot = None  # noqa: SLF001
    from ..contracts import SnapshotHandle
    s._initial_snapshot = SnapshotHandle.from_world(s.world)  # noqa: SLF001


def _run_scenario_once(scenario_dict: dict, catalog_snap: CatalogSnapshot) -> ABRunResult:
    """用指定 catalog 跑一次场景。"""
    s = SimulatorSession()
    _run_scenario_once_with_catalog(s, catalog_snap, scenario_dict)

    run_res = s.scenario_run()
    from ..contracts import SnapshotHandle, TraceHandle
    final_snap = SnapshotHandle.from_world(s.world)
    survivors: dict[int, int] = {}
    for e in s.world.entities.values():
        if e.is_alive:
            survivors[e.owner_player_id] = survivors.get(e.owner_player_id, 0) + 1
    return ABRunResult(
        label="",
        end_loop=run_res["loop"],
        end_reason=run_res["end_reason"],
        winner=run_res.get("winner"),
        trace_hash=run_res.get("trace_hash", ""),
        survivors=survivors,
        final_snapshot_hash=final_snap.hash,
    )


def run_ab_comparison(
    scenario_dict: dict,
    patches: list[CatalogPatch],
    baseline_catalog: Optional[CatalogSnapshot] = None,
) -> ABReport:
    """跑 baseline vs candidate A/B 对比。"""
    base = baseline_catalog if baseline_catalog is not None else m7_catalog()
    candidate = apply_patch(base, patches)

    base_run = _run_scenario_once(scenario_dict, base)
    base_run.label = "baseline"
    cand_run = _run_scenario_once(scenario_dict, candidate)
    cand_run.label = "candidate"

    # 检查机械变化是否生效：补丁字段在 catalog 中确实变化
    mechanical: dict[str, dict] = {}
    for p in patches:
        ut_b = base.units[p.unit_id]
        ut_c = candidate.units[p.unit_id]
        b_val = _get_field(ut_b, p.field)
        c_val = _get_field(ut_c, p.field)
        mechanical[p.field] = {
            "unit": p.unit_id,
            "baseline": b_val,
            "candidate": c_val,
            "changed": b_val != c_val,
        }
    all_changes_observed = all(m["changed"] for m in mechanical.values())

    # 不相关字段稳定：未补丁单位的 hash 不变（用 catalog 子集 hash 校验）
    unrelated_stable = True
    patched_ids = {p.unit_id for p in patches}
    for uid, ut_b in base.units.items():
        if uid in patched_ids:
            continue
        ut_c = candidate.units.get(uid)
        if ut_c is None:
            unrelated_stable = False
            break
        # 用 _unit_source_hash 同思路
        if _unit_quick_hash(ut_b) != _unit_quick_hash(ut_c):
            unrelated_stable = False
            break

    # unsupported 单位检查（已知空军/behavior multiplier 缺口）
    base_handle = wrap_catalog(base, source="baseline")
    cand_handle = wrap_catalog(candidate, source="candidate")
    unsupported_used: list[str] = []
    for sp in scenario_dict.get("spawns", []):
        uid = sp["unit_type_id"]
        if base_handle.fidelity_of(uid) == "unsupported":
            unsupported_used.append(uid)
        elif cand_handle.fidelity_of(uid) == "unsupported":
            unsupported_used.append(uid)

    # verdict
    if all_changes_observed and unrelated_stable:
        verdict = "PASS"
    elif not all_changes_observed:
        verdict = "FAIL"
    else:
        verdict = "INCONCLUSIVE"

    return ABReport(
        scenario_name=scenario_dict.get("name", "unnamed"),
        baseline=base_run,
        candidate=cand_run,
        patches=patches,
        mechanical_changes_observed=mechanical,
        unrelated_fields_stable=unrelated_stable,
        unsupported_units_used=unsupported_used,
        verdict=verdict,
    )


def _get_field(ut: UnitType, field: str):
    if field == "minerals":
        return ut.minerals
    if field == "vespene":
        return ut.vespene
    if field == "build_time":
        return ut.build_time
    if field == "supply":
        return ut.supply
    if field == "armor":
        return ut.armor.raw
    if field == "max_health":
        return ut.max_health.raw
    if field == "weapon_ground.damage":
        return ut.weapon_ground.damage.raw if ut.weapon_ground else None
    if field == "weapon_ground.range":
        return ut.weapon_ground.range.raw if ut.weapon_ground else None
    if field == "weapon_ground.period":
        return ut.weapon_ground.period if ut.weapon_ground else None
    return None


def _unit_quick_hash(ut: UnitType) -> str:
    payload = json.dumps({
        "id": ut.id, "race": ut.race, "max_health": ut.max_health.raw,
        "armor": ut.armor.raw, "speed": ut.speed.raw, "minerals": ut.minerals,
        "vespene": ut.vespene, "supply": ut.supply, "build_time": ut.build_time,
    }, sort_keys=True, separators=(",", ":"))
    import hashlib
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Source-to-Catalog import (P4A deliverable: "Source-to-Catalog import for the
# first real Mod slice"). Parses a JSON source file into CatalogSnapshot +
# provenance, demonstrating the import flow without requiring real CMRE XML
# (which needs a writeScope extension to CMRE mod source).
# ---------------------------------------------------------------------------

def import_catalog_from_json(source_path: str) -> tuple[CatalogHandle, dict]:
    """从 JSON 源文件导入 Catalog 切片。

    JSON schema（见 artifacts/galaxy-vibe/cmre-slice-source.json）：
    - schema_version / source / notes：元信息
    - units: [{id, race, attributes, max_health, armor, speed, sight, minerals,
               vespene, supply, build_time, radius, is_worker, is_structure,
               weapon_ground: {id, damage, attacks, range, period, damage_type,
                                target_filters, projectile_speed} | null,
               weapon_air: {...} | null}, ...]

    返回 (CatalogHandle, provenance_dict)。每单位溯源到 source_path + JSON 字段哈希。
    """
    from pathlib import Path
    import hashlib
    from sc2_simulator.catalog.model import Attribute, DamageType, TargetFilter

    with open(source_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    units: dict[str, UnitType] = {}
    prov: dict[str, Provenance] = {}

    for u_def in raw["units"]:
        uid = u_def["id"]
        # 解析武器
        def _parse_weapon(w_def: Optional[dict]) -> Optional[WeaponType]:
            if w_def is None:
                return None
            return WeaponType(
                id=w_def["id"],
                damage=Fixed.from_int(int(w_def["damage"])),
                attacks=int(w_def.get("attacks", 1)),
                range=Fixed.from_float(float(w_def.get("range", 1))),
                period=int(w_def.get("period", 22)),
                damage_type=DamageType(w_def.get("damage_type", "normal").lower()),
                target_filters=frozenset(
                    TargetFilter(t.lower()) for t in w_def.get("target_filters", ["ground"])
                ),
                projectile_speed=Fixed.from_float(float(w_def.get("projectile_speed", 0))),
            )

        ut = UnitType(
            id=uid,
            race=u_def["race"],
            attributes=frozenset(Attribute(a.lower()) for a in u_def.get("attributes", [])),
            max_health=Fixed.from_int(int(u_def["max_health"])),
            armor=Fixed.from_int(int(u_def.get("armor", 0))),
            speed=Fixed.from_float(float(u_def.get("speed", 0))),
            sight=Fixed.from_int(int(u_def.get("sight", 8))),
            minerals=int(u_def.get("minerals", 0)),
            vespene=int(u_def.get("vespene", 0)),
            supply=int(u_def.get("supply", 0)),
            build_time=int(u_def.get("build_time", 0)),
            radius=Fixed.from_float(float(u_def.get("radius", 1))),
            is_worker=bool(u_def.get("is_worker", False)),
            is_structure=bool(u_def.get("is_structure", False)),
            weapon_ground=_parse_weapon(u_def.get("weapon_ground")),
            weapon_air=_parse_weapon(u_def.get("weapon_air")),
        )
        units[uid] = ut
        # 溯源：基于该单位的 JSON 字段计算源哈希
        unit_payload = json.dumps(u_def, sort_keys=True, separators=(",", ":"))
        source_hash = hashlib.sha256(unit_payload.encode("utf-8")).hexdigest()[:12]
        prov[uid] = Provenance(
            unit_id=uid,
            source="json-source",
            source_path=str(Path(source_path).as_posix()),  # 相对风格路径
            source_hash=source_hash,
            derivation="derived-from-json",
            fidelity="approximate",
            notes=f"Imported from JSON source slice ({raw.get('source', 'unknown')})",
        )

    cat_snap = CatalogSnapshot(
        schema_version=raw["schema_version"],
        units=units,
        content_hash="",  # 由 wrap_catalog 计算
    )
    handle = wrap_catalog(cat_snap, source=f"json-import:{Path(source_path).name}")
    return handle, prov


# ---------------------------------------------------------------------------
# P4A 自测
# ---------------------------------------------------------------------------

def p4a_selftest() -> dict:
    """P4A 闸门：真实单位成本/伤害变更可导入对比 + 报告显示机械变化 + 不相关字段稳定 + unsupported 可见。"""
    checks = {}
    details = {}

    # 场景：1 Marine vs 1 Zergling（CMRE 切片覆盖）
    scenario_dict = {
        "schema_version": "m7",
        "name": "P4A marine damage buff",
        "players": [
            {"id": 1, "name": "Terran", "race": "terran", "allies": [], "is_ai": True},
            {"id": 2, "name": "Zerg", "race": "zerg", "allies": [], "is_ai": True},
        ],
        "spawns": [
            {"unit_type_id": "Marine", "owner_player_id": 1, "x": 0.0, "y": 0.0},
            {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 5.0, "y": 0.0},
        ],
        "commands": [
            {"loop": 0, "kind": "attack_unit", "issuer_player_id": 1, "entity_ids": [1], "target_entity_id": 2},
            {"loop": 0, "kind": "attack_unit", "issuer_player_id": 2, "entity_ids": [2], "target_entity_id": 1},
        ],
        "max_loops": 500,
        "seed": 42,
        "strict": True,
        "win_condition": "annihilation",
    }

    # 补丁：Marine weapon_ground.damage 5 -> 7（预期 Marine 胜）
    patches = [CatalogPatch("Marine", "weapon_ground.damage", 5, 7, "测试候选：提升 Marine 伤害")]

    report = run_ab_comparison(scenario_dict, patches)

    # 1) 补丁可导入对比（catalog 哈希不同）
    base_h = compute_catalog_hash(m7_catalog())
    cand_h = compute_catalog_hash(apply_patch(m7_catalog(), patches))
    checks["patch_imported"] = base_h != cand_h
    details["patch_imported"] = f"baseline={base_h[:12]} candidate={cand_h[:12]}"

    # 2) 机械变化生效
    mech_ok = all(m["changed"] for m in report.mechanical_changes_observed.values())
    checks["mechanical_change_observed"] = mech_ok
    details["mechanical_change_observed"] = report.mechanical_changes_observed

    # 3) 不相关字段稳定
    checks["unrelated_stable"] = report.unrelated_fields_stable
    details["unrelated_stable"] = f"unrelated_fields_stable={report.unrelated_fields_stable}"

    # 4) baseline vs candidate 行为有差异（end_loop 或 winner 或 survivors 不同）
    behavior_differs = (
        report.baseline.end_loop != report.candidate.end_loop
        or report.baseline.winner != report.candidate.winner
        or report.baseline.survivors != report.candidate.survivors
        or report.baseline.trace_hash != report.candidate.trace_hash
    )
    checks["behavior_differs"] = behavior_differs
    details["behavior_differs"] = (
        f"baseline: end={report.baseline.end_loop} winner={report.baseline.winner} "
        f"survivors={report.baseline.survivors} | "
        f"candidate: end={report.candidate.end_loop} winner={report.candidate.winner} "
        f"survivors={report.candidate.survivors}"
    )

    # 5) stage 06 修复后 Viking 不再是 unsupported（空战 + 行为乘数已接线）
    #    unsupported_units_used 应为空（所有单位 supported）
    v_scenario = {
        "schema_version": "m7",
        "name": "P4A stage06 fidelity check",
        "players": [{"id": 1, "name": "T", "race": "terran", "allies": [], "is_ai": True}],
        "spawns": [{"unit_type_id": "Viking", "owner_player_id": 1, "x": 0.0, "y": 0.0}],
        "commands": [],
        "max_loops": 10,
        "seed": 42,
        "strict": False,
        "win_condition": "annihilation",
    }
    v_report = run_ab_comparison(v_scenario, patches)
    checks["no_unsupported_after_stage06"] = len(v_report.unsupported_units_used) == 0
    details["no_unsupported_after_stage06"] = (
        f"unsupported_units_used={v_report.unsupported_units_used} "
        f"(stage 06 修复前 Viking=unsupported, 修复后=approximate)"
    )

    # 6) verdict
    checks["verdict_pass"] = report.verdict == "PASS"
    details["verdict_pass"] = f"verdict={report.verdict}"

    # 7) Source-to-Catalog import（P4A deliverable: "Source-to-Catalog import for
    #    the first real Mod slice"）。从 JSON 源文件导入，验证：
    #    (a) 导入成功且单位数匹配源
    #    (b) 重复导入同源文件哈希一致（稳定性）
    #    (c) 每单位有 provenance 溯源
    #    (d) 导入的 Marine 字段值与源 JSON 一致（max_health=45, weapon_ground.damage=5）
    import os
    src_path = os.path.join("artifacts", "galaxy-vibe", "cmre-slice-source.json")
    if os.path.exists(src_path):
        imp_h1, imp_p1 = import_catalog_from_json(src_path)
        imp_h2, imp_p2 = import_catalog_from_json(src_path)  # 重复导入
        marine_ut = imp_h1.snapshot.units.get("Marine")
        checks["source_import_roundtrip"] = (
            len(imp_h1.snapshot.units) == 3  # Marine + SCV + CommandCenter
            and imp_h1.content_hash == imp_h2.content_hash  # 稳定性
            and all(uid in imp_p1 for uid in imp_h1.snapshot.units)  # 全溯源
            and marine_ut is not None
            and marine_ut.max_health == Fixed.from_int(45)  # Fixed 定点比较
            and marine_ut.weapon_ground is not None
            and marine_ut.weapon_ground.damage == Fixed.from_int(5)
            and marine_ut.weapon_air is not None  # Marine 有对空武器
        )
        details["source_import_roundtrip"] = (
            f"units={len(imp_h1.snapshot.units)} hash_stable={imp_h1.content_hash == imp_h2.content_hash} "
            f"marine_hp={marine_ut.max_health.raw if marine_ut else '?'} (expect 46080=45*1024) "
            f"marine_dmg={marine_ut.weapon_ground.damage.raw if marine_ut and marine_ut.weapon_ground else '?'} (expect 5120=5*1024) "
            f"provenance_count={len(imp_p1)}"
        )
    else:
        checks["source_import_roundtrip"] = False
        details["source_import_roundtrip"] = f"source file not found: {src_path}"

    return {"passed": all(checks.values()), "checks": checks, "details": details,
            "verdict": report.verdict, "baseline": report.baseline.__dict__,
            "candidate": report.candidate.__dict__}


if __name__ == "__main__":
    import sys
    r = p4a_selftest()
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    sys.exit(0 if r["passed"] else 1)
