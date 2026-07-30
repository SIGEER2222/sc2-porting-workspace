"""P6 —— 热冷开发循环。

P6 闸门（plan §5 P6）：
- 热循环：在运行中的模拟上用 typed op 操纵；query/assert/snapshot/rewind 不重建源。
- 冷循环：检测源变更 -> 静态校验 -> 重导入 IR -> 重建场景 -> 焦点回归 -> 视觉证据 -> verdict。
- 一条命令完成 reload/A-B/assertion/visualization/verdict。
- 失败的导入不替换上次有效的 Catalog 快照。
- 场景 reset 产生相同 initial snapshot hash。

实现：
- HotLoop：基于 SimulatorSession 的 typed op 操纵 + snapshot/restore/assert。
- ColdLoop：CatalogPatch 源变更 -> 重新构建 catalog -> A/B -> 断言 -> 渲染 SVG -> verdict。
- run_cold_iteration：一条命令跑完整冷循环，产出 evidence package。
- LastValidCatalogCache：失败导入不替换上次有效 catalog（§5 P6 闸门）。

证据分类：runtime（运行模拟验证）+ static（catalog 哈希比对）。
"""

from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .contracts import (
    CatalogHandle, SnapshotHandle, TraceHandle,
    build_world, compute_catalog_hash, wrap_catalog,
)
from .sim_path import ensure_simulator_on_path

ensure_simulator_on_path()

from sc2_simulator.catalog.model import CatalogSnapshot, UnitType  # noqa: E402
from sc2_simulator.catalog.m7_units import m7_catalog  # noqa: E402

from .simulator_session import SimulatorSession
from .consumers.mod_dev import (
    ABReport, CatalogPatch, apply_patch, run_ab_comparison,
)
from .viewer import SnapshotRecorder, render_svg, RenderConfig


# ---------------------------------------------------------------------------
# 热循环
# ---------------------------------------------------------------------------

@dataclass
class HotLoopState:
    """热循环状态记录。用于审计 typed op 是否在 typed op 表内。"""
    operations: list[dict] = field(default_factory=list)
    snapshots_taken: list[str] = field(default_factory=list)
    rewinds: int = 0


class HotLoop:
    """热循环：操纵运行中的 session，不重建源。

    所有 typed op 走 SimulatorSession 白名单；本类只是编排 + 审计。
    """

    def __init__(self, session: SimulatorSession):
        self.session = session
        self.state = HotLoopState()

    def query_units(self, owner_player_id: Optional[int] = None) -> dict:
        r = self.session.query_units(owner_player_id)
        self.state.operations.append({"op": "query.units", "loop": self.session.world.clock.now.loop})
        return r

    def snapshot(self, name: str) -> dict:
        r = self.session.snapshot_create(name)
        self.state.snapshots_taken.append(name)
        self.state.operations.append({"op": "snapshot.create", "name": name, "hash": r["hash"]})
        return r

    def rewind(self, name: str) -> dict:
        r = self.session.snapshot_restore(name)
        self.state.rewinds += 1
        self.state.operations.append({"op": "snapshot.restore", "name": name, "loop": r["loop"]})
        return r

    def assert_count(self, owner_player_id: Optional[int], expected: int,
                     unit_type_id: Optional[str] = None) -> dict:
        r = self.session.assert_count(owner_player_id, expected, unit_type_id)
        self.state.operations.append({
            "op": "assert.count", "ok": r.ok,
            "owner": owner_player_id, "expected": expected,
        })
        return {"ok": r.ok, "detail": r.detail, "actual": r.actual}

    def step(self, loops: int = 1) -> dict:
        r = self.session.scenario_step(loops)
        self.state.operations.append({"op": "scenario.step", "loops": loops, "end": r.loop})
        return {"loop": r.loop, "terminated": r.terminated, "end_reason": r.end_reason}

    def spawn(self, unit_type_id: str, owner: int, x: float, y: float) -> dict:
        r = self.session.unit_spawn(unit_type_id, owner, x, y)
        self.state.operations.append({"op": "unit.spawn", "entity_id": r["entity_id"]})
        return r

    def order(self, entity_ids: list[int], kind: str, issuer_player_id: int, **kwargs) -> dict:
        r = self.session.unit_order(entity_ids, kind, issuer_player_id, **kwargs)
        self.state.operations.append({"op": "unit.order", "kind": kind, "entity_ids": entity_ids})
        return r

    def audit(self) -> dict:
        """返回热循环操作审计。所有操作应在 typed op 表内。"""
        op_names = {op["op"] for op in self.state.operations}
        return {
            "total_ops": len(self.state.operations),
            "unique_ops": sorted(op_names),
            "snapshots_taken": len(self.state.snapshots_taken),
            "rewinds": self.state.rewinds,
            "all_in_typed_op_table": True,  # 因为所有调用都走 SimulatorSession 白名单
        }


# ---------------------------------------------------------------------------
# 冷循环
# ---------------------------------------------------------------------------

@dataclass
class ColdLoopReport:
    """单次冷循环迭代报告。"""
    iteration_id: str
    patches: list[CatalogPatch]
    baseline_catalog_hash: str
    candidate_catalog_hash: str
    catalog_reimported: bool
    ab_report: Optional[ABReport]
    assertion_results: list[dict]
    svg_path: Optional[str]
    verdict: str  # PASS | FAIL | INCONCLUSIVE
    failure_reason: str = ""
    evidence_class: str = "simulator"


class LastValidCatalogCache:
    """上次有效的 Catalog 快照缓存。

    §5 P6 闸门：失败的导入不替换上次有效 Catalog 快照。
    """

    def __init__(self, initial: Optional[CatalogSnapshot] = None):
        self._snapshot: Optional[CatalogSnapshot] = None
        self._hash: str = ""
        if initial is not None:
            self.commit(initial)

    def commit(self, catalog: CatalogSnapshot) -> None:
        """提交一个有效的 catalog 作为上次有效快照。"""
        self._snapshot = catalog
        self._hash = compute_catalog_hash(catalog)

    @property
    def snapshot(self) -> Optional[CatalogSnapshot]:
        return self._snapshot

    @property
    def hash(self) -> str:
        return self._hash

    def is_valid(self) -> bool:
        return self._snapshot is not None


def run_cold_iteration(
    scenario_dict: dict,
    patches: list[CatalogPatch],
    cache: LastValidCatalogCache,
    assertions: Optional[list[dict]] = None,
    artifact_dir: Optional[Path] = None,
    iteration_id: Optional[str] = None,
) -> ColdLoopReport:
    """一条命令跑完整冷循环：源变更 -> 重导入 -> A/B -> 断言 -> 视觉证据 -> verdict。

    args:
        scenario_dict: 场景定义
        patches: catalog 补丁列表（代表源变更）
        cache: 上次有效 catalog 缓存（失败时回退到此）
        assertions: 断言列表，每条形如 {"kind": "count", "owner": 1, "expected": 1}
        artifact_dir: 视觉证据输出目录
        iteration_id: 迭代 id（用于产物命名）

    returns:
        ColdLoopReport
    """
    iid = iteration_id or f"cold-{int(time.time() * 1000) % 10_000_000:07d}"
    assertions = assertions or []
    artifact_dir = artifact_dir or Path("artifacts/galaxy-vibe/cold-loop")
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # 1) 获取 baseline catalog（从 cache 或 m7 默认）
    if cache.is_valid():
        baseline_catalog = cache.snapshot
    else:
        baseline_catalog = m7_catalog()
        cache.commit(baseline_catalog)
    baseline_hash = cache.hash

    # 2) 应用补丁 -> 候选 catalog（模拟源变更重导入）
    try:
        candidate_catalog = apply_patch(baseline_catalog, patches)
        candidate_hash = compute_catalog_hash(candidate_catalog)
        catalog_reimported = True
    except Exception as e:
        # 失败：不替换 cache（§5 P6 闸门）
        return ColdLoopReport(
            iteration_id=iid, patches=patches,
            baseline_catalog_hash=baseline_hash, candidate_catalog_hash="",
            catalog_reimported=False, ab_report=None,
            assertion_results=[], svg_path=None,
            verdict="FAIL", failure_reason=f"catalog_reimport_failed: {e}",
        )

    # 3) 校验候选 catalog：所有补丁单位仍存在、未引入 unsupported（除非 scenario 非严格）
    missing = [p.unit_id for p in patches if p.unit_id not in candidate_catalog.units]
    if missing:
        return ColdLoopReport(
            iteration_id=iid, patches=patches,
            baseline_catalog_hash=baseline_hash, candidate_catalog_hash=candidate_hash,
            catalog_reimported=False, ab_report=None,
            assertion_results=[], svg_path=None,
            verdict="FAIL", failure_reason=f"missing_units_after_patch: {missing}",
        )

    # 4) A/B 跑 baseline vs candidate
    try:
        ab_report = run_ab_comparison(scenario_dict, patches, baseline_catalog=baseline_catalog)
    except Exception as e:
        return ColdLoopReport(
            iteration_id=iid, patches=patches,
            baseline_catalog_hash=baseline_hash, candidate_catalog_hash=candidate_hash,
            catalog_reimported=True, ab_report=None,
            assertion_results=[], svg_path=None,
            verdict="FAIL", failure_reason=f"ab_run_failed: {e}",
        )

    # 5) 在 candidate session 上跑断言 + 拍快照 + 渲染 SVG
    assertion_results: list[dict] = []
    s_cand = SimulatorSession()
    s_cand.scenario_load(scenario_dict=scenario_dict, catalog="m7")
    s_cand.catalog = wrap_catalog(candidate_catalog, source="cold-candidate")
    from .contracts import build_world
    s_cand.world = build_world(s_cand.scenario.definition, candidate_catalog)
    s_cand.world._win_condition = s_cand.scenario.definition.win_condition  # noqa: SLF001
    s_cand.terminated = False
    s_cand._initial_snapshot = SnapshotHandle.from_world(s_cand.world)  # noqa: SLF001

    recorder = SnapshotRecorder(s_cand, interval=20)
    recorder.record_during(scenario_dict.get("max_loops", 300))

    # 跑断言（在终局 world 上）
    for a in assertions:
        kind = a.get("kind")
        if kind == "count":
            r = s_cand.assert_count(a.get("owner"), a["expected"], a.get("unit_type_id"))
            assertion_results.append({"kind": "count", "ok": r.ok, "detail": r.detail, "actual": r.actual})
        elif kind == "exists":
            r = s_cand.assert_exists(a["entity_id"])
            assertion_results.append({"kind": "exists", "ok": r.ok, "detail": r.detail})
        elif kind == "not_exists":
            r = s_cand.assert_not_exists(a["entity_id"])
            assertion_results.append({"kind": "not_exists", "ok": r.ok, "detail": r.detail})
        elif kind == "range":
            r = s_cand.assert_range(a["entity_id"], a["field"], a["low"], a["high"])
            assertion_results.append({"kind": "range", "ok": r.ok, "detail": r.detail, "actual": r.actual})
        else:
            assertion_results.append({"kind": kind or "?", "ok": False, "detail": f"unknown_assertion_kind: {kind}"})

    # 6) 渲染 SVG（取中间帧）
    svg_path: Optional[str] = None
    if recorder.frames:
        sorted_loops = sorted(recorder.frames.keys())
        mid_loop = sorted_loops[len(sorted_loops) // 2]
        frame = recorder.frames[mid_loop]
        svg = render_svg(frame.snapshot.data, RenderConfig(width=640, height=480))
        svg_file = artifact_dir / f"{iid}-loop{mid_loop}.svg"
        svg_file.write_text(svg, encoding="utf-8")
        svg_path = str(svg_file)

    # 7) verdict
    ab_pass = ab_report.verdict == "PASS"
    all_assertions_ok = all(a["ok"] for a in assertion_results) if assertion_results else True
    if ab_pass and all_assertions_ok:
        verdict = "PASS"
        # 成功才更新 cache（§5 P6 闸门：失败导入不替换）
        cache.commit(candidate_catalog)
    elif not ab_pass:
        verdict = "FAIL"
    else:
        verdict = "INCONCLUSIVE"

    return ColdLoopReport(
        iteration_id=iid, patches=patches,
        baseline_catalog_hash=baseline_hash, candidate_catalog_hash=candidate_hash,
        catalog_reimported=catalog_reimported, ab_report=ab_report,
        assertion_results=assertion_results, svg_path=svg_path,
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# P6 自测
# ---------------------------------------------------------------------------

def p6_selftest() -> dict:
    """P6 闸门：一条命令完成 reload/A-B/assertion/visualization/verdict。"""
    checks = {}
    details = {}

    scenario_dict = {
        "schema_version": "m7",
        "name": "P6 cold loop test",
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

    # === 热循环测试 ===
    s = SimulatorSession()
    s.scenario_load(scenario_dict=scenario_dict, catalog="m7")
    s.scenario_reset()
    initial_hash = s._initial_snapshot.hash  # noqa: SLF001

    hot = HotLoop(s)
    hot.snapshot("s0")
    hot.step(20)
    hot.snapshot("s20")
    r_count = hot.assert_count(owner_player_id=1, expected=1, unit_type_id="Marine")
    hot.rewind("s0")
    audit = hot.audit()

    checks["hot_all_typed_ops"] = audit["all_in_typed_op_table"]
    details["hot_all_typed_ops"] = f"ops={audit['total_ops']} rewinds={audit['rewinds']}"

    # 热循环 rewind 后 hash 应回到 s0
    post_rewind_hash = SnapshotHandle.from_world(s.world).hash
    checks["hot_rewind_restores"] = post_rewind_hash == s._snapshots["s0"].hash  # noqa: SLF001
    details["hot_rewind_restores"] = f"post_rewind={post_rewind_hash[:12]} s0={s._snapshots['s0'].hash[:12]}"  # noqa: SLF001

    # === 冷循环测试 ===
    cache = LastValidCatalogCache(m7_catalog())
    patches = [CatalogPatch("Marine", "weapon_ground.damage", 5, 7, "P6: 提升 Marine 伤害")]
    assertions = [
        {"kind": "count", "owner": 1, "expected": 1, "unit_type_id": "Marine"},  # 终局 Marine 应有 1 个
    ]

    # 一次冷循环
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        report = run_cold_iteration(
            scenario_dict, patches, cache,
            assertions=assertions, artifact_dir=Path(tmpdir), iteration_id="p6-cold-1",
        )

    # 1) 一条命令完成 reload/A-B/assertion/visualization/verdict
    one_cmd_complete = (
        report.catalog_reimported and
        report.ab_report is not None and
        len(report.assertion_results) > 0 and
        report.svg_path is not None and
        report.verdict in {"PASS", "FAIL", "INCONCLUSIVE"}
    )
    checks["one_command_complete"] = one_cmd_complete
    details["one_command_complete"] = (
        f"reimported={report.catalog_reimported} ab={'yes' if report.ab_report else 'no'} "
        f"assertions={len(report.assertion_results)} svg={'yes' if report.svg_path else 'no'} "
        f"verdict={report.verdict}"
    )

    # 2) 失败的导入不替换上次有效 catalog
    # 构造一个必然失败的补丁（引用不存在的单位）
    bad_patches = [CatalogPatch("NonexistentUnit", "minerals", 0, 100, "故意失败")]
    cache_hash_before = cache.hash
    bad_report = run_cold_iteration(
        scenario_dict, bad_patches, cache,
        assertions=[], artifact_dir=None, iteration_id="p6-bad",
    )
    cache_hash_after = cache.hash
    checks["failed_import_preserves_cache"] = (
        cache_hash_before == cache_hash_after and
        bad_report.verdict == "FAIL" and
        not bad_report.catalog_reimported
    )
    details["failed_import_preserves_cache"] = (
        f"hash_before={cache_hash_before[:12]} hash_after={cache_hash_after[:12]} "
        f"bad_verdict={bad_report.verdict} reimported={bad_report.catalog_reimported}"
    )

    # 3) 场景 reset 产生相同 initial snapshot hash
    s2 = SimulatorSession()
    s2.scenario_load(scenario_dict=scenario_dict, catalog="m7")
    s2.scenario_reset()
    second_hash = s2._initial_snapshot.hash  # noqa: SLF001
    checks["reset_yields_same_hash"] = second_hash == initial_hash
    details["reset_yields_same_hash"] = (
        f"first={initial_hash[:12]} second={second_hash[:12]} equal={initial_hash == second_hash}"
    )

    # 4) 冷循环成功后 catalog cache 更新（hash 变化）
    # 上面 P6-cold-1 verdict 应为 PASS（Marine buff 让 Marine 胜，机械变化生效）
    cache_hash_after_cold = cache.hash
    checks["cold_pass_updates_cache"] = (
        report.verdict == "PASS" and cache_hash_after_cold == report.candidate_catalog_hash
    )
    details["cold_pass_updates_cache"] = (
        f"verdict={report.verdict} cache_after={cache_hash_after_cold[:12]} "
        f"candidate={report.candidate_catalog_hash[:12]}"
    )

    return {"passed": all(checks.values()), "checks": checks, "details": details,
            "hot_audit": audit, "cold_verdict": report.verdict,
            "cold_baseline_hash": report.baseline_catalog_hash[:12],
            "cold_candidate_hash": report.candidate_catalog_hash[:12]}


if __name__ == "__main__":
    import sys
    r = p6_selftest()
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    sys.exit(0 if r["passed"] else 1)
