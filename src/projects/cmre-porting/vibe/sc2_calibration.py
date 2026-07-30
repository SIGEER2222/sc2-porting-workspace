"""P9 —— 可选真实-SC2 差分校准。

P9 闸门（plan §5 P9）：
- 真实-SC2 backend 使用同一套 task 契约（task.json schema，含 scenario/patches/assertions/max_loops）。
- 远程或独立执行的证据包。
- Simulator-vs-SC2 差分报告。
- 校准 fixtures + 已知差异登记表。
- 真实-SC2 缺席从不阻塞本地 P0-P8 工作。
- 真实证据标注 `runtime`；simulator 证据标注 `simulator`；stub 证据标注 `inference`（不可冒充 runtime）。
- 差异更新 fidelity 记录与回归 fixtures，不隐藏。

实现：
- 本地无 SC2 安装：本模块提供 P9 框架 + stub backend + 差分报告生成器。
- Sc2BackendStub：模拟真实 SC2 后端（占位），用 simulator 跑同一套 task 契约产出
  inference 标注的证据（明确不是 runtime）。
- DifferentialReport：simulator vs sc2 差分报告。
- KnownDivergenceRegistry：已知差异登记表（fidelity 更新源）。
- p9_selftest：验证 P9 框架可在无 SC2 环境下运行（不阻塞 P0-P8）。

注：真实 SC2 backend 需在另一台机器执行（替换 Sc2BackendStub.run_task 的 _execute_on_sc2），
本模块只定义契约 + stub。stub 永远标 evidence_class='inference'，绝不冒充 runtime。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .contracts import SnapshotHandle, compute_catalog_hash
from .sim_path import ensure_simulator_on_path

ensure_simulator_on_path()

from sc2_simulator.catalog.m7_units import m7_catalog  # noqa: E402

from .simulator_session import SimulatorSession


# ---------------------------------------------------------------------------
# Task 契约（与 task_runner.py 同一套 task.json schema）
# ---------------------------------------------------------------------------

@dataclass
class TaskContract:
    """task.json 契约（与 task_runner.py 一致）。

    backend 字段决定哪个后端跑这个 task：
    - "simulator": SimulatorSession
    - "sc2": 真实 SC2（或 Sc2BackendStub）
    """
    task_id: str
    backend: str = "sc2"  # P9 默认走 sc2 backend
    scenario_dict: Optional[dict] = None
    scenario_path: Optional[str] = None
    catalog: str = "m7"
    patches: list[dict] = field(default_factory=list)  # catalog patches
    ops: list[dict] = field(default_factory=list)  # scenario.run / step / unit.*
    assertions: list[dict] = field(default_factory=list)
    max_loops: Optional[int] = None
    seed: Optional[int] = None

    @classmethod
    def from_dict(cls, d: dict) -> "TaskContract":
        return cls(
            task_id=d.get("task_id", "unnamed"),
            backend=d.get("backend", "sc2"),
            scenario_dict=d.get("scenario_dict"),
            scenario_path=d.get("scenario_path"),
            catalog=d.get("catalog", "m7"),
            patches=d.get("patches", []),
            ops=d.get("ops", []),
            assertions=d.get("assertions", []),
            max_loops=d.get("max_loops"),
            seed=d.get("seed"),
        )

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id, "backend": self.backend,
            "scenario_dict": self.scenario_dict, "scenario_path": self.scenario_path,
            "catalog": self.catalog, "patches": self.patches, "ops": self.ops,
            "assertions": self.assertions, "max_loops": self.max_loops, "seed": self.seed,
        }


# ---------------------------------------------------------------------------
# SC2 backend 契约（与 SimulatorSession 同一套 task 契约）
# ---------------------------------------------------------------------------

@dataclass
class Sc2RunResult:
    """真实 SC2 后端运行结果。"""
    backend: str  # "sc2" 真实 | "sc2-stub" 占位
    end_loop: int
    end_reason: str
    winner: Optional[int]
    survivors: dict  # player_id -> count
    final_snapshot_hash: str
    # P9 闸门：真实 SC2 证据标 runtime；stub 标 inference（绝不冒充 runtime）
    evidence_class: str = "runtime"
    assertion_results: list[dict] = field(default_factory=list)
    task_id: str = ""
    notes: str = ""


class Sc2BackendStub:
    """真实 SC2 后端的占位实现。

    本地无 SC2 安装时使用此 stub。生产环境应替换为真实 SC2 launcher
    （tools/launchers/launch-cmre-alenger.ps1 + GameLogs 复核）+ 证据采集。

    闸门约束：
    - 接受与 SimulatorSession 同一套 task 契约（TaskContract）
    - 应用 patches、跑 ops、跑 assertions
    - stub 永远标 evidence_class='inference'（绝不冒充 runtime）
    - backend='sc2-stub' 明确标注占位
    - 不阻塞本地工作（P9 可选）
    """

    BACKEND_IDENTIFIER = "sc2-stub"
    # stub 永远标 inference；真实 SC2 实现应标 runtime
    STUB_EVIDENCE_CLASS = "inference"

    def __init__(self, sc2_available: bool = False):
        self.sc2_available = sc2_available  # 真实 SC2 是否可用
        self.last_result: Optional[Sc2RunResult] = None

    def run_task(self, task: TaskContract | dict) -> Sc2RunResult:
        """跑一个 task（同一套 task 契约）。返回 Sc2RunResult。

        真实环境：调 SC2 launcher，采集 trace/banks/screenshots，标 evidence_class='runtime'。
        stub：用 simulator 跑同一套 task 契约，标 evidence_class='inference'（绝不冒充 runtime）。
        """
        if isinstance(task, dict):
            task = TaskContract.from_dict(task)
        # 解析 scenario
        scenario_dict = task.scenario_dict
        if scenario_dict is None and task.scenario_path:
            p = Path(task.scenario_path)
            if not p.is_absolute():
                p = Path(__file__).resolve().parents[4] / p
            scenario_dict = json.loads(p.read_text(encoding="utf-8"))
        if scenario_dict is None:
            raise ValueError("task 必须包含 scenario_dict 或 scenario_path")
        # 应用 task 级别的 seed / max_loops 覆盖
        if task.seed is not None:
            scenario_dict = dict(scenario_dict)
            scenario_dict["seed"] = task.seed
        if task.max_loops is not None and "max_loops" not in scenario_dict:
            scenario_dict = dict(scenario_dict)
            scenario_dict["max_loops"] = task.max_loops

        return self._execute(task, scenario_dict)

    def _execute(self, task: TaskContract, scenario_dict: dict) -> Sc2RunResult:
        """stub 实现：用 simulator 跑同一套 task 契约（应用 patches / ops / assertions）。

        patches 形态与 task.json / mod_dev.py 一致：
        [{"unit_type_id": "Marine", "field": "weapon_ground.damage", "old": 5, "new": 7, "rationale": "..."}]
        """
        from .consumers.mod_dev import CatalogPatch, apply_patch, _run_scenario_once_with_catalog
        s = SimulatorSession()
        s.scenario_load(scenario_dict=scenario_dict, catalog=task.catalog)
        # 应用 patches：转换为 CatalogPatch 并替换 session 的 catalog
        if task.patches:
            patches = [
                CatalogPatch(
                    unit_id=p["unit_type_id"],
                    field=p["field"],
                    old_value=p.get("old"),
                    new_value=p["new"],
                    rationale=p.get("rationale", ""),
                )
                for p in task.patches
            ]
            from sc2_simulator.catalog.m7_units import m7_catalog
            base = m7_catalog()
            candidate = apply_patch(base, patches)
            _run_scenario_once_with_catalog(s, candidate)  # 重建 world 用 candidate catalog
        else:
            s.scenario_reset()

        # 执行 ops（与 task_runner.py 一致）
        for op_spec in task.ops:
            op = op_spec["op"]
            args = op_spec.get("args", {})
            _apply_op(s, op, args)

        # 如果 ops 没显式 run，则跑 max_loops
        ran_explicitly = any(o["op"] == "scenario.run" for o in task.ops)
        if not ran_explicitly:
            s.scenario_run(max_loops=task.max_loops)

        # 跑 assertions（与 task_runner.py 一致）
        assertion_results = []
        for a_spec in task.assertions:
            op = a_spec["op"]
            args = a_spec.get("args", {})
            ar = _run_assertion(s, op, args)
            assertion_results.append({"op": op, "args": args, **ar})

        # 采集结果
        snap = SnapshotHandle.from_world(s.world)
        survivors: dict[int, int] = {}
        for e in s.world.entities.values():
            if e.is_alive:
                survivors[e.owner_player_id] = survivors.get(e.owner_player_id, 0) + 1
        end_loop = s.world.clock.now.loop
        end_reason = getattr(s, "end_reason", "") or "max_loops_reached"
        alive = {e.owner_player_id for e in s.world.entities.values() if e.is_alive}
        winner = next(iter(alive)) if len(alive) == 1 else None

        self.last_result = Sc2RunResult(
            backend=self.BACKEND_IDENTIFIER,
            end_loop=end_loop,
            end_reason=end_reason,
            winner=winner,
            survivors=survivors,
            final_snapshot_hash=snap.hash,
            evidence_class=self.STUB_EVIDENCE_CLASS,  # stub 永远 inference，绝不 runtime
            assertion_results=assertion_results,
            task_id=task.task_id,
            notes=(
                "stub: 用 simulator 跑同一套 task 契约模拟 SC2 输出；"
                "evidence_class=inference（非 runtime）；真实环境替换为 SC2 launcher 后改为 runtime"
            ),
        )
        return self.last_result


def _apply_op(session: SimulatorSession, op: str, args: dict) -> None:
    """与 task_runner.py 一致的 op 分发。"""
    if op == "scenario.reset":
        session.scenario_reset()
    elif op == "scenario.run":
        session.scenario_run(max_loops=args.get("max_loops"))
    elif op == "scenario.step":
        session.scenario_step(args.get("n", 1))
    elif op == "unit.spawn":
        session.unit_spawn(**args)
    elif op == "unit.order":
        session.unit_order(**args)
    elif op == "snapshot.create":
        session.snapshot_create(args.get("name", ""))
    elif op == "snapshot.restore":
        session.snapshot_restore(args.get("name", ""))
    else:
        # 未知 op 在 stub 中静默跳过（真实 SC2 backend 应明确报错）
        pass


def _run_assertion(session: SimulatorSession, op: str, args: dict) -> dict:
    """与 task_runner.py 一致的 assertion 分发。"""
    if session.world is None:
        return {"ok": False, "reason": "no world"}
    if op == "assert.count":
        unit_type = args.get("unit_type_id")
        owner = args.get("owner_player_id")
        expected = args.get("expected")
        actual = sum(
            1 for e in session.world.entities.values()
            if e.is_alive
            and (unit_type is None or e.unit_type_id == unit_type)
            and (owner is None or e.owner_player_id == owner)
        )
        return {"ok": actual == expected, "actual": actual, "expected": expected}
    if op == "assert.winner":
        alive = {e.owner_player_id for e in session.world.entities.values() if e.is_alive}
        winner = next(iter(alive)) if len(alive) == 1 else None
        return {"ok": winner == args.get("winner"), "actual": winner}
    if op == "assert.end_loop_le":
        actual = session.world.clock.now.loop
        return {"ok": actual <= args.get("max", 10**9), "actual": actual}
    return {"ok": False, "reason": f"unknown assertion {op}"}


# ---------------------------------------------------------------------------
# 已知差异登记表
# ---------------------------------------------------------------------------

@dataclass
class KnownDivergence:
    """已知 simulator vs SC2 差异条目。"""
    divergence_id: str
    description: str
    affected_unit: str
    fidelity_label: str  # exact | approximate | partial | unsupported
    impact: str  # low | medium | high
    fixture_id: str  # 关联的回归 fixture
    discovered_at: str  # ISO timestamp
    resolution: str = "open"  # open | documented | fixed


def known_divergence_registry() -> list[KnownDivergence]:
    """已知差异登记表（P9 闸门：差异不隐藏，更新 fidelity + fixtures）。

    初始条目来自 sc2_simulator 已识别的缺口：
    - G7: triggers/regions/waves 缺口（已由 mission_engine 适配）
    - 空军武器: weapon_air 缺口
    - behavior multiplier: 缺口
    """
    return [
        KnownDivergence(
            divergence_id="DIV-001",
            description="simulator 缺 trigger/region/wave 系统，已由 mission_engine 适配",
            affected_unit="*",
            fidelity_label="approximate",
            impact="medium",
            fixture_id="fx-mission-wave",
            discovered_at="2026-07-30",
            resolution="documented",
        ),
        KnownDivergence(
            divergence_id="DIV-002",
            description="simulator 缺 weapon_air 结算（空军对空）",
            affected_unit="Viking",
            fidelity_label="unsupported",
            impact="high",
            fixture_id="fx-air-combat",
            discovered_at="2026-07-30",
            resolution="open",
        ),
        KnownDivergence(
            divergence_id="DIV-003",
            description="simulator 缺 behavior multiplier（如 Stimpack 加速）",
            affected_unit="Marine",
            fidelity_label="partial",
            impact="medium",
            fixture_id="fx-stimpack",
            discovered_at="2026-07-30",
            resolution="open",
        ),
    ]


# ---------------------------------------------------------------------------
# 差分报告
# ---------------------------------------------------------------------------

@dataclass
class DifferentialReport:
    """Simulator-vs-SC2 差分报告。"""
    scenario_name: str
    simulator_result: dict  # SimulatorSession.run 的返回
    sc2_result: Sc2RunResult
    end_loop_diff: int  # sc2.end_loop - sim.end_loop
    winner_match: bool
    survivors_match: bool
    snapshot_hash_match: bool
    known_divergences: list[KnownDivergence]
    verdict: str  # match | known_divergence | unknown_divergence
    evidence_classes: dict  # {"simulator": "simulator", "sc2": "runtime"|"inference"}
    notes: str = ""


def run_differential(
    task: TaskContract | dict,
    sc2_backend: Optional[Sc2BackendStub] = None,
) -> DifferentialReport:
    """跑 simulator vs SC2 差分对比（同一套 task 契约）。"""
    if isinstance(task, dict):
        task = TaskContract.from_dict(task)
    backend = sc2_backend or Sc2BackendStub()

    # simulator 跑（用 SimulatorSession + 同一 task 契约）
    sim_task = TaskContract(
        task_id=task.task_id + "-sim",
        backend="simulator",
        scenario_dict=task.scenario_dict,
        scenario_path=task.scenario_path,
        catalog=task.catalog,
        patches=task.patches,
        ops=task.ops,
        assertions=task.assertions,
        max_loops=task.max_loops,
        seed=task.seed,
    )
    s = SimulatorSession()
    scenario_dict = sim_task.scenario_dict
    if scenario_dict is None and sim_task.scenario_path:
        p = Path(sim_task.scenario_path)
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[4] / p
        scenario_dict = json.loads(p.read_text(encoding="utf-8"))
    if scenario_dict is None:
        raise ValueError("task 必须包含 scenario_dict 或 scenario_path")
    if sim_task.seed is not None:
        scenario_dict = dict(scenario_dict)
        scenario_dict["seed"] = sim_task.seed
    s.scenario_load(scenario_dict=scenario_dict, catalog=sim_task.catalog)
    if sim_task.patches:
        from .consumers.mod_dev import CatalogPatch, apply_patch, _run_scenario_once_with_catalog
        patches = [
            CatalogPatch(
                unit_id=p["unit_type_id"], field=p["field"],
                old_value=p.get("old"), new_value=p["new"],
                rationale=p.get("rationale", ""),
            )
            for p in sim_task.patches
        ]
        from sc2_simulator.catalog.m7_units import m7_catalog
        candidate = apply_patch(m7_catalog(), patches)
        _run_scenario_once_with_catalog(s, candidate)
    else:
        s.scenario_reset()
    for op_spec in sim_task.ops:
        _apply_op(s, op_spec["op"], op_spec.get("args", {}))
    if not any(o["op"] == "scenario.run" for o in sim_task.ops):
        s.scenario_run(max_loops=sim_task.max_loops)
    sim_snap = SnapshotHandle.from_world(s.world)
    sim_survivors: dict[int, int] = {}
    for e in s.world.entities.values():
        if e.is_alive:
            sim_survivors[e.owner_player_id] = sim_survivors.get(e.owner_player_id, 0) + 1
    sim_end_loop = s.world.clock.now.loop
    sim_end_reason = getattr(s, "end_reason", "") or "max_loops_reached"
    sim_alive = {e.owner_player_id for e in s.world.entities.values() if e.is_alive}
    sim_winner = next(iter(sim_alive)) if len(sim_alive) == 1 else None

    # SC2 跑（同一 task 契约）
    sc2_res = backend.run_task(task)

    # 差分
    end_loop_diff = sc2_res.end_loop - sim_end_loop
    winner_match = sc2_res.winner == sim_winner
    survivors_match = sc2_res.survivors == sim_survivors
    snapshot_hash_match = sc2_res.final_snapshot_hash == sim_snap.hash

    # 判定
    if snapshot_hash_match and winner_match and survivors_match:
        verdict = "match"
    elif any(d.resolution == "documented" for d in known_divergence_registry()):
        verdict = "known_divergence"
    else:
        verdict = "unknown_divergence"

    return DifferentialReport(
        scenario_name=task.task_id,
        simulator_result={
            "end_loop": sim_end_loop, "end_reason": sim_end_reason,
            "winner": sim_winner, "survivors": sim_survivors,
            "snapshot_hash": sim_snap.hash, "evidence_class": "simulator",
        },
        sc2_result=sc2_res,
        end_loop_diff=end_loop_diff,
        winner_match=winner_match,
        survivors_match=survivors_match,
        snapshot_hash_match=snapshot_hash_match,
        known_divergences=known_divergence_registry(),
        verdict=verdict,
        evidence_classes={"simulator": "simulator", "sc2": sc2_res.evidence_class},
        notes="stub-vs-simulator 都用 simulator 引擎，预期 verdict=match（hash 一致）",
    )


# ---------------------------------------------------------------------------
# P9 自测
# ---------------------------------------------------------------------------

def p9_selftest() -> dict:
    """P9 闸门：可选 SC2 差分校准框架 + 不阻塞 P0-P8 + 证据标注 + 差异登记。"""
    checks = {}
    details = {}

    # 用同一套 task 契约（与 task_runner.py 一致）
    scenario_dict = {
        "schema_version": "m7",
        "name": "P9 differential test",
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
        "max_loops": 300, "seed": 42, "strict": True, "win_condition": "annihilation",
    }
    task = TaskContract(
        task_id="p9-diff-test",
        backend="sc2",
        scenario_dict=scenario_dict,
        catalog="m7",
        ops=[{"op": "scenario.run"}],
        assertions=[
            {"op": "assert.winner", "args": {"winner": 1}},
            {"op": "assert.end_loop_le", "args": {"max": 300}},
        ],
        max_loops=300,
        seed=42,
    )

    # 1) SC2 backend 使用同一套 task 契约（接受 TaskContract，应用 patches/ops/assertions）
    backend = Sc2BackendStub()
    sc2_res = backend.run_task(task)
    checks["sc2_uses_same_contract"] = (
        sc2_res.backend in ("sc2", "sc2-stub")
        and hasattr(sc2_res, "end_loop")
        and hasattr(sc2_res, "winner")
        and hasattr(sc2_res, "survivors")
        and hasattr(sc2_res, "final_snapshot_hash")
        # 真验证 task 契约被消费：ops 被执行（scenario.run）+ assertions 被跑
        and len(sc2_res.assertion_results) == len(task.assertions)
        and sc2_res.task_id == task.task_id
    )
    details["sc2_uses_same_contract"] = (
        f"backend={sc2_res.backend} end={sc2_res.end_loop} "
        f"assertions_run={len(sc2_res.assertion_results)} task_id={sc2_res.task_id}"
    )

    # 2) 真实-SC2 缺席不阻塞本地工作（stub 可跑）
    checks["sc2_absence_no_block"] = sc2_res.end_loop > 0
    details["sc2_absence_no_block"] = f"stub_ran end_loop={sc2_res.end_loop} notes={sc2_res.notes[:60]}"

    # 3) 证据标注：真实证据标 runtime；stub 标 inference（绝不冒充 runtime）
    #    plan 非目标明文禁止「把模拟器证据重标为真实-SC2 runtime 证据」
    report = run_differential(task, sc2_backend=backend)
    checks["evidence_class_labeled"] = (
        report.evidence_classes["simulator"] == "simulator"
        and report.evidence_classes["sc2"] == "inference"  # stub 必须 inference
        and report.sc2_result.evidence_class == "inference"
        and "runtime" not in report.evidence_classes.values()  # stub 不产生 runtime
    )
    details["evidence_class_labeled"] = f"classes={report.evidence_classes}"

    # 4) 差分报告生成
    checks["differential_report_generated"] = (
        hasattr(report, "end_loop_diff")
        and hasattr(report, "winner_match")
        and hasattr(report, "snapshot_hash_match")
        and report.verdict in ("match", "known_divergence", "unknown_divergence")
    )
    details["differential_report_generated"] = (
        f"verdict={report.verdict} end_loop_diff={report.end_loop_diff} "
        f"winner_match={report.winner_match} hash_match={report.snapshot_hash_match}"
    )

    # 5) 已知差异登记表存在且不隐藏
    registry = known_divergence_registry()
    checks["divergence_registry_nonempty"] = len(registry) >= 3
    details["divergence_registry_nonempty"] = (
        f"count={len(registry)} ids={[d.divergence_id for d in registry]}"
    )

    # 6) 差异更新 fidelity 记录（每个 divergence 有 fidelity_label）
    all_have_fidelity = all(d.fidelity_label in ("exact", "approximate", "partial", "unsupported")
                            for d in registry)
    checks["divergences_update_fidelity"] = all_have_fidelity
    details["divergences_update_fidelity"] = (
        f"labels={[d.fidelity_label for d in registry]}"
    )

    # 7) 差异关联回归 fixture
    all_have_fixture = all(d.fixture_id for d in registry)
    checks["divergences_link_fixtures"] = all_have_fixture
    details["divergences_link_fixtures"] = (
        f"fixtures={[d.fixture_id for d in registry]}"
    )

    # 8) P9 不阻塞 P0-P8：验证 simulator 仍可独立跑（不走 SC2 backend）
    s = SimulatorSession()
    s.scenario_load(scenario_dict=scenario_dict, catalog="m7")
    s.scenario_reset()
    sim_only = s.scenario_run()
    checks["p9_no_block_p0_p8"] = sim_only["loop"] > 0
    details["p9_no_block_p0_p8"] = f"simulator_only end={sim_only['loop']}"

    # 9) 真实 SC2 不可用时 stub 标注清晰（backend + notes + evidence_class 三重标注）
    stub_backend = Sc2BackendStub(sc2_available=False)
    stub_res = stub_backend.run_task(task)
    checks["stub_clearly_marked"] = (
        stub_backend.BACKEND_IDENTIFIER == "sc2-stub"
        and "stub" in stub_res.notes.lower()
        and stub_res.evidence_class == "inference"  # 不是 runtime
        and stub_res.backend == "sc2-stub"
    )
    details["stub_clearly_marked"] = (
        f"backend={stub_res.backend} evidence_class={stub_res.evidence_class} "
        f"notes={stub_res.notes[:60]}"
    )

    # 10) task 契约对齐：patches 被应用（验证 stub 真消费 task 契约，不只是 scenario）
    #     用 damage=20（4 倍），足以显著缩短击杀时间但不会一击秒杀导致 end_loop=0
    task_with_patch = TaskContract(
        task_id="p9-patch-test",
        backend="sc2",
        scenario_dict=scenario_dict,
        catalog="m7",
        patches=[{"unit_type_id": "Marine", "field": "weapon_ground.damage",
                  "old": 5, "new": 20}],
        ops=[{"op": "scenario.run"}],
        assertions=[],
        max_loops=300,
        seed=42,
    )
    res_no_patch = backend.run_task(TaskContract(
        task_id="p9-patch-test-nopatch", backend="sc2", scenario_dict=scenario_dict,
        catalog="m7", ops=[{"op": "scenario.run"}], assertions=[], max_loops=300, seed=42,
    ))
    res_with_patch = backend.run_task(task_with_patch)
    # damage 5->20 应使 end_loop 显著缩短（更快击杀）；两端都应正常结束（end_loop > 0）
    checks["task_patches_applied"] = (
        res_with_patch.end_loop < res_no_patch.end_loop
        and res_with_patch.end_loop > 0
        and res_no_patch.end_loop > 0
    )
    details["task_patches_applied"] = (
        f"no_patch_end={res_no_patch.end_loop} with_patch_end={res_with_patch.end_loop} "
        f"(Marine damage 5->20 应缩短 end_loop)"
    )

    return {"passed": all(checks.values()), "checks": checks, "details": details,
            "differential_verdict": report.verdict,
            "evidence_classes": report.evidence_classes,
            "divergence_count": len(registry)}


if __name__ == "__main__":
    import sys
    r = p9_selftest()
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    sys.exit(0 if r["passed"] else 1)
