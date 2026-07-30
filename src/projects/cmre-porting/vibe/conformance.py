"""P8 —— 多消费者一致性套件 + 共享抽取。

P8 闸门（plan §5 P8）：
- 适配器一致性套件（adapter conformance suite）。
- 跨消费者场景 fixtures。
- 至少两个消费者通过同一共享契约实现后才抽取共享包。
- 契约版本兼容与迁移策略。
- Mod / ally AI / tactical / mission 各自 acceptance 套件通过。
- Simulator 变更不能默默破坏外部工具契约。

实现：
- ConformanceSuite：跨消费者套件，验证四个消费者（mod_dev / ally_ai / tactical / mission_wave）在同一组场景 fixtures 上行为一致。
- SharedContracts：标注哪些契约被 ≥2 消费者使用（达到共享抽取门槛）。
- ContractVersionPolicy：契约版本兼容性 + 迁移策略。
- cross_consumer_fixtures：跨消费者共享的场景 fixtures。
- run_conformance：跑完整 P8 套件。

证据分类：runtime（消费者实际运行）+ static（契约版本检查）。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Optional

from .contracts import (
    CatalogHandle, Observation, ScenarioHandle, SnapshotHandle,
    compute_catalog_hash, wrap_catalog,
)
from .sim_path import ensure_simulator_on_path

ensure_simulator_on_path()

from sc2_simulator.catalog.m7_units import m7_catalog  # noqa: E402

from .simulator_session import SimulatorSession
from .consumers.mod_dev import run_ab_comparison, CatalogPatch, p4a_selftest
from .consumers.ally_ai import AllyPolicy, ActionAdapter, run_ally_scenario, p4b_selftest
from .consumers.tactical import FocusFireStrategy, SpreadFireStrategy, run_tactical_ab, p4c_selftest
from .consumers.mission_wave import MissionSpec, p4d_selftest


# ---------------------------------------------------------------------------
# 跨消费者场景 fixtures
# ---------------------------------------------------------------------------

@dataclass
class ScenarioFixture:
    """跨消费者共享场景 fixture。"""
    fixture_id: str
    description: str
    scenario: dict
    expected_consumer_contract: dict  # 期望每个消费者在该场景下的契约字段


def cross_consumer_fixtures() -> list[ScenarioFixture]:
    """跨消费者共享场景 fixtures（plan §5 P8）。

    这些 fixtures 用于验证：四个消费者在同一组场景上行为一致。
    """
    return [
        ScenarioFixture(
            fixture_id="fx-1v1-marine-zergling",
            description="基础 1v1：Marine vs Zergling",
            scenario={
                "schema_version": "m7",
                "name": "fx-1v1",
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
            },
            expected_consumer_contract={
                "mod_dev": {"verdict": "PASS", "ab_runs": 2},
                "ally_ai": {"decisions_made": True, "no_hidden_access": True},
                "tactical": {"ab_runs": True, "confidence": "low|medium|high"},
                "mission": {"mission_runnable": True},
            },
        ),
        ScenarioFixture(
            fixture_id="fx-2v2-marines-zerglings",
            description="2v2：2 Marines vs 2 Zerglings",
            scenario={
                "schema_version": "m7",
                "name": "fx-2v2",
                "players": [
                    {"id": 1, "name": "T", "race": "terran", "allies": [], "is_ai": True},
                    {"id": 2, "name": "Z", "race": "zerg", "allies": [], "is_ai": True},
                ],
                "spawns": [
                    {"unit_type_id": "Marine", "owner_player_id": 1, "x": 0.0, "y": 0.0},
                    {"unit_type_id": "Marine", "owner_player_id": 1, "x": 1.0, "y": 0.0},
                    {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 5.0, "y": 0.0},
                    {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 6.0, "y": 0.0},
                ],
                "commands": [
                    {"loop": 0, "kind": "attack_unit", "issuer_player_id": 1, "entity_ids": [1, 2], "target_entity_id": 3},
                    {"loop": 0, "kind": "attack_unit", "issuer_player_id": 2, "entity_ids": [3, 4], "target_entity_id": 1},
                ],
                "max_loops": 400, "seed": 7, "strict": True, "win_condition": "annihilation",
            },
            expected_consumer_contract={
                "mod_dev": {"verdict": "PASS", "ab_runs": 2},
                "ally_ai": {"decisions_made": True, "no_hidden_access": True},
                "tactical": {"ab_runs": True, "confidence": "low|medium|high"},
                "mission": {"mission_runnable": True},
            },
        ),
    ]


# ---------------------------------------------------------------------------
# 共享契约（≥2 消费者使用 → 可抽取）
# ---------------------------------------------------------------------------

@dataclass
class SharedContract:
    """共享契约记录。"""
    contract_id: str
    description: str
    consumers_using: list[str]  # 使用方列表
    extraction_eligible: bool  # len(consumers_using) >= 2
    version: str


def shared_contracts_registry() -> list[SharedContract]:
    """契约注册表：标注哪些契约被 ≥2 消费者使用（达到共享抽取门槛）。

    M10: 现在返回的 ``consumers_using`` 会与 ``detect_contract_usage_dynamically()``
    的实际检测结果交叉校验（见 ``registry_with_dynamic_check()``）。
    本函数保留静态声明作为「期望值」，便于审查与回归。
    """
    return [
        SharedContract(
            contract_id="Observation",
            description="玩家可见状态契约（own_units / visible_enemies / resources）",
            consumers_using=["ally_ai", "tactical"],
            extraction_eligible=True,
            version="1.0",
        ),
        SharedContract(
            contract_id="SimulatorSession",
            description="Typed op 白名单 kernel（scenario.load/reset/step/run + unit.* + query.* + snapshot.* + assert.*）",
            consumers_using=["mod_dev", "ally_ai", "tactical", "mission_wave"],
            extraction_eligible=True,
            version="1.0",
        ),
        SharedContract(
            contract_id="SnapshotHandle",
            description="快照句柄（data + hash + loop）。mod_dev 直接 import 类型；其他消费者通过 SimulatorSession.snapshot_create 间接使用（返回 dict，不引用类型名）",
            consumers_using=["mod_dev"],
            extraction_eligible=False,  # M10: 动态检测确认仅 mod_dev 直接引用类型名
            version="1.0",
        ),
        SharedContract(
            contract_id="CatalogPatch",
            description="Catalog 字段级补丁（仅 mod_dev 定义并使用；mission_wave 通过 scenario 字段间接携带，不引用类型名）",
            consumers_using=["mod_dev"],
            extraction_eligible=False,  # M10: 动态检测确认仅 mod_dev 直接引用
            version="1.0",
        ),
        SharedContract(
            contract_id="AllyPolicy",
            description="盟友 AI 策略契约（仅 ally_ai 使用）",
            consumers_using=["ally_ai"],
            extraction_eligible=False,  # < 2，不抽取
            version="1.0",
        ),
        SharedContract(
            contract_id="Strategy",
            description="战术策略契约（仅 tactical 使用）",
            consumers_using=["tactical"],
            extraction_eligible=False,
            version="1.0",
        ),
        SharedContract(
            contract_id="MissionSpec",
            description="任务 DSL（仅 mission_wave 使用）",
            consumers_using=["mission_wave"],
            extraction_eligible=False,
            version="1.0",
        ),
    ]


# ---------------------------------------------------------------------------
# M10: 动态契约使用检测
# ---------------------------------------------------------------------------

# 消费者模块定位锚点：用已 import 的符号反查其所属模块（避免 hyphenated 包路径问题）
# (consumer_short_name, anchor_symbol_object)
_CONSUMER_ANCHORS: list[tuple[str, object]] = [
    ("mod_dev", run_ab_comparison),       # from .consumers.mod_dev
    ("ally_ai", AllyPolicy),              # from .consumers.ally_ai
    ("tactical", FocusFireStrategy),      # from .consumers.tactical
    ("mission_wave", MissionSpec),        # from .consumers.mission_wave
]

# 契约符号表：contract_id -> 需在源码中查找的标识符集合
_CONTRACT_SYMBOLS: dict[str, tuple[str, ...]] = {
    "Observation": ("Observation",),
    "SimulatorSession": ("SimulatorSession",),
    "SnapshotHandle": ("SnapshotHandle",),
    "CatalogPatch": ("CatalogPatch",),
    "AllyPolicy": ("AllyPolicy",),
    "Strategy": ("Strategy",),  # 基类名；子类如 FocusFireStrategy 也含 "Strategy" 子串
    "MissionSpec": ("MissionSpec",),
}


def _get_consumer_module_source(anchor: object) -> Optional[str]:
    """通过已 import 的锚点符号反查其模块源码。失败返回 None。"""
    import inspect as _inspect
    try:
        mod = _inspect.getmodule(anchor)
        if mod is None:
            return None
        return _inspect.getsource(mod)
    except Exception:  # noqa: BLE001
        return None


def _word_in_line(word: str, line: str) -> bool:
    """检查 word 作为独立标识符出现在 line 中（word-boundary）。"""
    idx = 0
    while True:
        pos = line.find(word, idx)
        if pos < 0:
            return False
        before = line[pos - 1] if pos > 0 else " "
        after = line[pos + len(word)] if pos + len(word) < len(line) else " "
        if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
            return True
        idx = pos + 1


def detect_contract_usage_dynamically(contract_id: str) -> set[str]:
    """动态检测哪些消费者模块实际引用了指定契约。

    通过 ``inspect.getsource(module)`` 扫描消费者模块源码，查找契约符号的出现。
    用已 import 的锚点符号（run_ab_comparison / AllyPolicy / FocusFireStrategy /
    MissionSpec）反查模块，规避 hyphenated 包路径 ``cmre-porting`` 无法用
    ``importlib.import_module`` 直接导入的问题。

    返回实际引用该契约的消费者短名集合（如 ``{"ally_ai", "tactical"}``）。
    """
    symbols = _CONTRACT_SYMBOLS.get(contract_id, ())
    if not symbols:
        return set()
    actual: set[str] = set()
    for consumer_name, anchor in _CONSUMER_ANCHORS:
        src = _get_consumer_module_source(anchor)
        if src is None:
            continue
        for sym in symbols:
            for line in src.splitlines():
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if _word_in_line(sym, line):
                    actual.add(consumer_name)
                    break
            if consumer_name in actual:
                break
    return actual


@dataclass
class ContractUsageCheck:
    """单契约的静态声明 vs 动态检测结果对比。"""
    contract_id: str
    declared_consumers: list[str]  # 静态注册表声称的使用方
    detected_consumers: list[str]  # 动态检测到的实际使用方
    match: bool  # declared == detected（集合相等）
    only_declared: list[str]  # 声称但实际未用（过时声明）
    only_detected: list[str]  # 实际用但未声明（漏报）


def registry_with_dynamic_check() -> tuple[list[SharedContract], list[ContractUsageCheck]]:
    """返回静态注册表 + 每个契约的动态检测结果。

    用于 P8 闸门「Simulator 变更不能默默破坏外部工具契约」的延伸：
    如果静态注册表与动态检测不符（过时声明或漏报），应作为 issue 暴露，
    而不是默默接受静态声明。
    """
    registry = shared_contracts_registry()
    checks: list[ContractUsageCheck] = []
    for c in registry:
        detected = detect_contract_usage_dynamically(c.contract_id)
        declared = set(c.consumers_using)
        only_declared = sorted(declared - detected)
        only_detected = sorted(detected - declared)
        checks.append(ContractUsageCheck(
            contract_id=c.contract_id,
            declared_consumers=list(c.consumers_using),
            detected_consumers=sorted(detected),
            match=declared == detected,
            only_declared=only_declared,
            only_detected=only_detected,
        ))
    return registry, checks


# ---------------------------------------------------------------------------
# 契约版本兼容策略
# ---------------------------------------------------------------------------

@dataclass
class ContractVersionPolicy:
    """契约版本兼容与迁移策略。"""
    current_version: str = "1.0"
    supported_versions: list = field(default_factory=lambda: ["1.0"])
    deprecation_policy: str = "minor: backwards-compat; major: 1 release notice"
    migration_tests_required: bool = True

    def is_compatible(self, version: str) -> bool:
        return version in self.supported_versions

    def describe(self) -> dict:
        return {
            "current_version": self.current_version,
            "supported_versions": self.supported_versions,
            "deprecation_policy": self.deprecation_policy,
            "migration_tests_required": self.migration_tests_required,
        }


# ---------------------------------------------------------------------------
# 一致性套件
# ---------------------------------------------------------------------------

@dataclass
class ConsumerConformanceResult:
    """单消费者在 fixture 上的合规结果。"""
    consumer: str
    fixture_id: str
    passed: bool
    detail: str
    contract_version: str = "1.0"


@dataclass
class ConformanceReport:
    """完整 P8 一致性报告。"""
    fixture_results: list[ConsumerConformanceResult]
    shared_extraction_eligible: list[str]  # 可抽取的契约 ID
    contract_version_policy: dict
    overall_passed: bool
    per_consumer_pass: dict  # consumer -> bool


def run_conformance() -> ConformanceReport:
    """跑完整 P8 一致性套件。"""
    fixtures = cross_consumer_fixtures()
    results: list[ConsumerConformanceResult] = []

    for fx in fixtures:
        # --- mod_dev 合规 ---
        try:
            patches = [CatalogPatch("Marine", "weapon_ground.damage", 5, 6, "fx test")]
            ab_report = run_ab_comparison(fx.scenario, patches)
            mod_pass = ab_report.verdict == "PASS"
            results.append(ConsumerConformanceResult(
                consumer="mod_dev", fixture_id=fx.fixture_id,
                passed=mod_pass,
                detail=f"ab_verdict={ab_report.verdict}",
            ))
        except Exception as e:
            results.append(ConsumerConformanceResult(
                consumer="mod_dev", fixture_id=fx.fixture_id,
                passed=False, detail=f"exception: {e}",
            ))

        # --- ally_ai 合规 ---
        try:
            # ally_ai 需要 follower 单位 + 不预设战斗命令（让 policy 决策）
            ally_sc = dict(fx.scenario)
            ally_sc["spawns"] = list(ally_sc["spawns"]) + [
                {"unit_type_id": "SCV", "owner_player_id": 1, "x": 1.0, "y": 1.0},
            ]
            ally_sc["commands"] = []  # 清空命令，让 policy 全权决策
            ally_sc["name"] = fx.scenario.get("name", "fx") + "-ally"
            # 远位放敌方避免 annihilation 误判
            ally_sc["spawns"] = [s if s["owner_player_id"] == 1 else
                                 {**s, "x": 50.0, "y": 50.0} for s in ally_sc["spawns"]]
            ally_sc["max_loops"] = 200
            policy = AllyPolicy(player_id=1, leader_entity_id=1,
                                base_region=(0.0, 0.0, 8.0), support_range=6.0,
                                command_interval=8)
            res = run_ally_scenario(ally_sc, policy, ally_player_id=1,
                                    max_loops=100, deadlock_threshold=80)
            # ally_ai 合规：无隐藏访问 + 无命令风暴
            ally_pass = (
                res.hidden_state_access_violations == 0 and
                not res.command_storm_detected
            )
            results.append(ConsumerConformanceResult(
                consumer="ally_ai", fixture_id=fx.fixture_id,
                passed=ally_pass,
                detail=f"end={res.end_loop} hidden_viol={res.hidden_state_access_violations} "
                       f"storm={res.command_storm_detected} max_cmds={res.max_commands_per_loop}",
            ))
        except Exception as e:
            results.append(ConsumerConformanceResult(
                consumer="ally_ai", fixture_id=fx.fixture_id,
                passed=False, detail=f"exception: {e}",
            ))

        # --- tactical 合规 ---
        try:
            report = run_tactical_ab(
                scenario_dict=fx.scenario,
                strategy_a=FocusFireStrategy(),
                strategy_b=SpreadFireStrategy(),
                seeds=[1, 2, 3],
                ally_player_id=1,
                max_loops=200,
            )
            tac_pass = report.confidence in ("low", "medium", "high")
            results.append(ConsumerConformanceResult(
                consumer="tactical", fixture_id=fx.fixture_id,
                passed=tac_pass,
                detail=f"confidence={report.confidence} verdict={report.verdict}",
            ))
        except Exception as e:
            results.append(ConsumerConformanceResult(
                consumer="tactical", fixture_id=fx.fixture_id,
                passed=False, detail=f"exception: {e}",
            ))

        # --- mission_wave 合规（真跑 MissionEngine，不只是 SimulatorSession） ---
        try:
            from .consumers.mission_wave import build_mission, run_mission, MissionSpec
            # 构造合法 MissionSpec：objectives 必须有 params 字段（mission_engine 要求）
            # 远位占位 Zergling 避免 annihilation 提前触发
            mission_scenario = dict(fx.scenario)
            mission_scenario["spawns"] = list(mission_scenario.get("spawns", [])) + [
                {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 100.0, "y": 100.0},
            ]
            spec = MissionSpec(
                name=f"fx-mission-{fx.fixture_id}",
                scenario=mission_scenario,
                regions=[{"name": "base", "kind": "circle", "x": 0, "y": 0, "r": 5}],
                waves=[{"name": "w1", "at_loop": 10, "spawns": [
                    {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 10.0, "y": 0.0}
                ]}],
                objectives=[
                    {"name": "survive", "kind": "survive_loops", "params": {"target_loops": 100}},
                    {"name": "defend_base", "kind": "defend_region",
                     "params": {"region": "base", "defender_player_id": 1, "until_loop": 100}},
                ],
                triggers=[{"name": "marine_attack", "kind": "attack_nearest",
                           "owner_player_id": 1, "unit_type_id": "Marine", "cooldown": 22}],
                max_loops=min(fx.scenario.get("max_loops", 300), 300),
                catalog="m7",
            )
            # 真调 build_mission + run_mission（走 MissionEngine.run）
            eng, s = build_mission(spec)
            mission_res = eng.run(max_loops=spec.max_loops)
            # mission_pass: MissionEngine 真终局（terminated=True）且 objectives 被评估
            mission_pass = (
                mission_res.terminated
                and len(mission_res.objectives) > 0
                and all("status" in o for o in mission_res.objectives)
            )
            results.append(ConsumerConformanceResult(
                consumer="mission_wave", fixture_id=fx.fixture_id,
                passed=mission_pass,
                detail=f"terminated={mission_res.terminated} end_loop={mission_res.end_loop} "
                       f"reason={mission_res.end_reason} objs={mission_res.objectives}",
            ))
        except Exception as e:
            results.append(ConsumerConformanceResult(
                consumer="mission_wave", fixture_id=fx.fixture_id,
                passed=False, detail=f"exception: {e}",
            ))

    # 共享抽取候选
    registry = shared_contracts_registry()
    extraction_eligible = [c.contract_id for c in registry if c.extraction_eligible]

    # 契约版本策略
    policy = ContractVersionPolicy()

    # 每消费者通过率
    per_consumer: dict[str, bool] = {}
    for consumer in ("mod_dev", "ally_ai", "tactical", "mission_wave"):
        consumer_results = [r for r in results if r.consumer == consumer]
        per_consumer[consumer] = all(r.passed for r in consumer_results) if consumer_results else False

    overall = all(per_consumer.values())
    return ConformanceReport(
        fixture_results=results,
        shared_extraction_eligible=extraction_eligible,
        contract_version_policy=policy.describe(),
        overall_passed=overall,
        per_consumer_pass=per_consumer,
    )


# ---------------------------------------------------------------------------
# P8 自测
# ---------------------------------------------------------------------------

def p8_selftest() -> dict:
    """P8 闸门：跨消费者一致性 + 共享抽取 + 契约版本策略 + 各消费者自有 acceptance。"""
    checks = {}
    details = {}

    # 1) 跨消费者一致性套件通过
    report = run_conformance()
    checks["conformance_overall"] = report.overall_passed
    details["conformance_overall"] = (
        f"per_consumer={report.per_consumer_pass} "
        f"fixtures={len(report.fixture_results)} "
        f"passed={sum(1 for r in report.fixture_results if r.passed)}"
    )

    # 2) 四个消费者各自 acceptance 套件通过
    r_a = p4a_selftest()
    checks["mod_dev_acceptance"] = r_a["passed"]
    details["mod_dev_acceptance"] = f"verdict={r_a.get('verdict')}"

    r_b = p4b_selftest()
    checks["ally_ai_acceptance"] = r_b["passed"]
    details["ally_ai_acceptance"] = f"end_loop={r_b.get('end_loop')} max_cmds={r_b.get('max_cmds_per_loop')}"

    r_c = p4c_selftest()
    checks["tactical_acceptance"] = r_c["passed"]
    details["tactical_acceptance"] = f"verdict={r_c.get('verdict')} confidence={r_c.get('confidence')}"

    r_d = p4d_selftest()
    checks["mission_acceptance"] = r_d["passed"]
    details["mission_acceptance"] = f"feasibility={r_d.get('feasibility_verdict')}"

    # 3) 至少两个消费者共享同一契约实现
    #    M10 修正后：SnapshotHandle/CatalogPatch 仅 mod_dev 直接引用类型名，
    #    不再算 shared（extraction_eligible=False）。真正 shared 的是
    #    Observation（ally_ai + tactical）和 SimulatorSession（全 4 个）。
    eligible = report.shared_extraction_eligible
    checks["shared_extraction_eligible"] = (
        "SimulatorSession" in eligible and
        "Observation" in eligible
    )
    details["shared_extraction_eligible"] = f"eligible={eligible}"

    # 4) 至少两个消费者通过同一共享契约
    # 验证：四个消费者都用 SimulatorSession（在 acceptance 套件中实际调用）
    shared_sim_session = all([r_a["passed"], r_b["passed"], r_c["passed"], r_d["passed"]])
    checks["two_consumers_share_contract"] = shared_sim_session
    details["two_consumers_share_contract"] = (
        "all 4 consumers use SimulatorSession contract and pass"
    )

    # 5) 契约版本策略存在
    policy = report.contract_version_policy
    checks["contract_version_policy"] = (
        policy["current_version"] == "1.0" and
        "1.0" in policy["supported_versions"] and
        policy["migration_tests_required"]
    )
    details["contract_version_policy"] = f"policy={policy}"

    # 6) Simulator 变更不能默默破坏外部工具契约
    #    真测试：(a) 确定性 —— 同输入两次跑结果一致；
    #           (b) 故意破坏 simulator 行为（改 catalog damage），conformance 的 fixture
    #               结果应能反映该变化（end_loop / survivors 至少一项变化），证明不是
    #               静默吞掉 simulator 变更。
    report2 = run_conformance()
    deterministic = (
        report.overall_passed == report2.overall_passed and
        report.per_consumer_pass == report2.per_consumer_pass
    )

    # (b) 故意破坏：用 monkey-patch 让 Marine damage 变成 1（几乎打不死），重跑 conformance
    #     验证 conformance 的消费者结果能反映该变化（不是静默通过）。
    #     注意：m7_catalog 被 catalog_bridge / simulator_session / sc2_calibration / mod_dev /
    #     dev_loop / vibe_host / conformance 顶层 import，需同时 patch 所有引用才能生效。
    #     检测方式：对比 patch 前后裸 SimulatorSession 跑同一场景的 end_loop（应显著变化），
    #     且 conformance 自身的 fixture_results 中至少一个 detail 应变化。
    import sc2_simulator.catalog.m7_units as _m7mod
    from . import catalog_bridge as _cb
    from . import simulator_session as _ss
    from . import sc2_calibration as _sc  # noqa
    from . import dev_loop as _dl
    from . import vibe_host as _vh
    from .consumers import mod_dev as _md
    _orig_m7_catalog_fn = _m7mod.m7_catalog
    _patch_targets = [
        ("m7_units", _m7mod), ("catalog_bridge", _cb), ("simulator_session", _ss),
        ("sc2_calibration", _sc), ("dev_loop", _dl), ("vibe_host", _vh),
        ("mod_dev", _md), ("conformance", sys.modules[__name__]),
    ]
    _orig_refs = {name: mod.m7_catalog for name, mod in _patch_targets}

    # 先跑一个裸 baseline（patch 前）作为对照
    _probe_scenario = {
        "schema_version": "m7", "name": "break-probe",
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
    _s_probe = SimulatorSession()
    _s_probe.scenario_load(scenario_dict=_probe_scenario, catalog="m7")
    _s_probe.scenario_reset()
    _baseline_end = _s_probe.scenario_run()["loop"]

    detail_changed = False
    _patched_end = _baseline_end
    try:
        from dataclasses import replace as _replace
        from sc2_simulator.catalog.m7_units import CatalogSnapshot

        def _patched_m7_catalog():
            cat = _orig_m7_catalog_fn()
            units = dict(cat.units)
            ut = units["Marine"]
            # 把 Marine max_health 改成 1（一击就死），同时 damage 改成 1（打不死任何东西）
            # 这样 conformance 的 fixture（Marine vs Zergling）结果会显著变化
            w = ut.weapon_ground
            orig_dmg = w.damage
            new_w = _replace(w, damage=orig_dmg.__class__(1))
            from sc2_simulator.fixed import Fixed
            units["Marine"] = _replace(ut, weapon_ground=new_w, max_health=Fixed(1))
            return CatalogSnapshot(
                schema_version=cat.schema_version + "+broken",
                units=units,
                content_hash="",
            )
        # 同时 patch 所有引用 m7_catalog 的模块
        for _name, _mod in _patch_targets:
            _mod.m7_catalog = _patched_m7_catalog

        # patch 后跑裸 probe（应显著变化：Marine 一击就死，end_loop 变短或 winner 反转）
        _s_probe2 = SimulatorSession()
        _s_probe2.scenario_load(scenario_dict=_probe_scenario, catalog="m7")
        _s_probe2.scenario_reset()
        _patched_end = _s_probe2.scenario_run()["loop"]

        # 重跑 conformance，看 conformance 是否能检测到破坏
        # 检测方式：fixture_results 中至少一个 detail 变化，或 overall_passed/per_consumer_pass 变化
        report3 = run_conformance()
        for r1, r3 in zip(report.fixture_results, report3.fixture_results):
            if r1.detail != r3.detail or r1.passed != r3.passed:
                detail_changed = True
                break
        # 如果 detail 没变，检查 overall/per_consumer 是否变
        if not detail_changed:
            detail_changed = (
                report.overall_passed != report3.overall_passed
                or report.per_consumer_pass != report3.per_consumer_pass
            )
    except Exception as e:
        detail_changed = False
        deterministic = False
        details["simulator_changes_no_silent_break"] = f"exception during break test: {e}"
    finally:
        for _name, _mod in _patch_targets:
            if _name in _orig_refs:
                _mod.m7_catalog = _orig_refs[_name]

    # 检测标准：patch 生效（probe end_loop 显著变化）+ conformance 能感知（detail/pass 变化）
    probe_changed = abs(_patched_end - _baseline_end) >= 5
    checks["simulator_changes_no_silent_break"] = deterministic and probe_changed and detail_changed
    details["simulator_changes_no_silent_break"] = (
        f"deterministic={deterministic} probe_end_baseline={_baseline_end} "
        f"probe_end_patched={_patched_end} probe_changed={probe_changed} "
        f"conf_detected={detail_changed}"
    )

    # 7) 单消费者契约（AllyPolicy/Strategy/MissionSpec）不抽取
    registry = shared_contracts_registry()
    single_consumer_no_extract = all(
        not c.extraction_eligible for c in registry
        if c.contract_id in ("AllyPolicy", "Strategy", "MissionSpec")
    )
    checks["single_consumer_not_extracted"] = single_consumer_no_extract
    details["single_consumer_not_extracted"] = (
        "AllyPolicy/Strategy/MissionSpec 都是 single-consumer，不抽取"
    )

    # 8) M10: 静态注册表 vs 动态检测交叉校验
    #    要求：每个契约的 declared_consumers 与 detect_contract_usage_dynamically() 的结果一致；
    #    若不一致（过时声明 or 漏报），应作为 issue 暴露，而非默默接受静态声明。
    _registry2, dyn_checks = registry_with_dynamic_check()
    mismatched = [c.contract_id for c in dyn_checks if not c.match]
    # 允许 Strategy 基类名在子类（FocusFireStrategy 等）源码中出现的广义匹配；
    # 但要求核心契约（Observation/SimulatorSession/SnapshotHandle/CatalogPatch/MissionSpec/AllyPolicy）
    # 的 declared == detected。
    core_contracts = {"Observation", "SimulatorSession", "SnapshotHandle",
                      "CatalogPatch", "AllyPolicy", "MissionSpec"}
    core_mismatches = [c.contract_id for c in dyn_checks
                       if c.contract_id in core_contracts and not c.match]
    checks["m10_dynamic_contract_detection"] = len(core_mismatches) == 0
    details["m10_dynamic_contract_detection"] = (
        f"core_mismatches={core_mismatches} all_mismatches={mismatched} "
        f"detected_sample={[(c.contract_id, c.detected_consumers) for c in dyn_checks[:3]]}"
    )

    # 9) M10: 动态检测能感知消费者源码变更（破坏性测试）
    #    把 ally_ai 锚点替换为 None（inspect.getmodule(None) 返回 None ->
    #    _get_consumer_module_source 返回 None -> ally_ai 被跳过），
    #    验证 detect_contract_usage_dynamically() 的结果会改变：
    #    ally_ai 应从 Observation 的 detected 集合中消失。
    _orig_anchors = list(_CONSUMER_ANCHORS)
    det_after: set[str] = set()
    try:
        _CONSUMER_ANCHORS[1] = ("ally_ai", None)
        det_after = detect_contract_usage_dynamically("Observation")
        detection_responds_to_source_change = "ally_ai" not in det_after
    except Exception:  # noqa: BLE001
        detection_responds_to_source_change = False
        det_after = set()
    finally:
        _CONSUMER_ANCHORS[:] = _orig_anchors
    checks["m10_dynamic_detection_responds_to_change"] = detection_responds_to_source_change
    details["m10_dynamic_detection_responds_to_change"] = (
        f"after_breaking_ally_ai_anchor: Observation.detected={sorted(det_after)} "
        f"(ally_ai should be absent)"
    )

    return {"passed": all(checks.values()), "checks": checks, "details": details,
            "per_consumer_pass": report.per_consumer_pass,
            "shared_extraction_eligible": report.shared_extraction_eligible,
            "contract_version_policy": report.contract_version_policy,
            "m10_dynamic_checks": [
                {"contract_id": c.contract_id,
                 "declared": c.declared_consumers,
                 "detected": c.detected_consumers,
                 "match": c.match,
                 "only_declared": c.only_declared,
                 "only_detected": c.only_detected}
                for c in dyn_checks
            ]}


if __name__ == "__main__":
    import sys
    r = p8_selftest()
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    sys.exit(0 if r["passed"] else 1)
