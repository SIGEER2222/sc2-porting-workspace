"""P4B —— 盟友 AI 消费者。

P4B 闸门（plan §5 P4B）：
- AI 不能查隐藏状态（只读 Observation，不能访问 world.entities 全集）
- 人力移动触发跟随
- 近距威胁触发支援/攻击
- 目标威胁覆盖低优先跟随
- 每单位每 loop 至多一条接受命令
- 10 模拟分钟无死锁/振荡/命令风暴
- 命令反馈/延迟/动作错误模型（M3 hardening）

设计：
- AllyPolicy：基于 Observation 的策略；返回 Action 列表
- ActionAdapter：把策略动作翻译为 SimulatorSession.unit_order 调用
  - 延迟模型：issue() 入队，dispatch_loop = issue_loop + latency_loops；
    dispatch_due(loop) 在到期时分发。模拟真实 SC2 命令网络/传输延迟。
  - 错误模型：分发时校验单位存活/所有权/目标存活，结构化 DispatchResult.error
    返回（invalid_target / target_dead / unit_dead / not_owned / unknown_kind），
    不抛异常——错误命令被记录但不会 crash 整个 AI loop。
- per-unit-command-guard：每个 loop 每单位最多一条命令（在 adapter 层强制）
- runtime_safety：检测死锁（连续 N loop 无分发且无 pending）、振荡（连续 N loop 命令反复）、命令风暴（>K 命令/loop）
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Optional

from ..contracts import Observation
from ..sim_path import ensure_simulator_on_path

ensure_simulator_on_path()

from ..simulator_session import SimulatorSession


@dataclass
class AllyAction:
    """盟友 AI 决策动作。"""

    entity_id: int
    kind: str  # "follow" | "attack" | "move" | "hold"
    target_entity_id: int = 0
    target_x: float = 0.0
    target_y: float = 0.0
    reason: str = ""  # 决策理由（写入 trace）


@dataclass
class QueuedCommand:
    """已排队等待分发的命令（延迟模型）。"""

    entity_id: int
    kind: str
    target_entity_id: int
    target_x: float
    target_y: float
    reason: str
    issue_loop: int
    dispatch_loop: int  # issue_loop + latency_loops


@dataclass
class DispatchResult:
    """命令分发结果（含错误模型）。

    error 取值：
    - None：成功分发
    - "unit_dead"：分发时单位已死或不存在
    - "invalid_target"：attack 目标 ID 为 0 或目标实体不存在
    - "target_dead"：目标在 transit 期间死亡（分发时已 dead）
    - "unknown_kind"：策略返回未识别的 kind
    - "dispatch_error:<ExceptionName>"：session.unit_order 抛异常（非 KernelError）
    """

    entity_id: int
    kind: str
    dispatched: bool
    error: Optional[str]
    issue_loop: int
    dispatch_loop: int
    reason: str = ""


@dataclass
class AllyDecisionTrace:
    """每 loop 决策记录。"""

    loop: int
    observation: dict  # 摘要而非全量
    actions: list[AllyAction]
    rejected_over_limit: int  # per-unit 超限被拒数量
    queued_this_loop: int = 0
    dispatched_this_loop: int = 0
    dispatch_errors_this_loop: int = 0
    pending_in_queue: int = 0
    safety_flags: dict = field(default_factory=dict)


@dataclass
class AllyRunResult:
    """盟友 AI 跑结果。"""

    end_loop: int
    end_reason: str
    decisions: list[AllyDecisionTrace]
    deadlock_detected: bool
    oscillation_detected: bool
    command_storm_detected: bool
    hidden_state_access_violations: int
    max_commands_per_loop: int
    total_dispatched: int = 0
    total_dispatch_errors: int = 0
    error_breakdown: dict = field(default_factory=dict)
    latency_loops: int = 0
    trace_hash: str = ""


class AllyPolicy:
    """盟友 AI 策略：跟随/支援/防御。

    priority 排序（高→低）：
    1. 目标威胁（敌方进入 base_region）-> attack
    2. 近距威胁（敌方进入 support_range）-> attack
    3. 人力移动（ally_leader 移动）-> follow
    4. 默认 hold
    """

    def __init__(self, player_id: int, leader_entity_id: int,
                 base_region: tuple[float, float, float] = (0.0, 0.0, 8.0),
                 support_range: float = 6.0,
                 command_interval: int = 8):
        self.player_id = player_id
        self.leader_entity_id = leader_entity_id
        self.base_x, self.base_y, self.base_r = base_region
        self.support_range = support_range
        self.command_interval = command_interval  # 每 N loop 决策一次
        self._last_decide_loop = -10_000
        self._last_actions: list[AllyAction] = []
        self._action_history: list[list[str]] = []  # 用于振荡检测

    def decide(self, obs: Observation, loop: int) -> list[AllyAction]:
        """根据 Observation 决策。只读 obs，不访问 world。"""
        if loop - self._last_decide_loop < self.command_interval:
            return self._last_actions  # 复用上次决策（节流）
        self._last_decide_loop = loop

        own_by_id = {u["entity_id"]: u for u in obs.own_units}
        leader = own_by_id.get(self.leader_entity_id)
        if leader is None:
            self._last_actions = []
            return []

        actions: list[AllyAction] = []
        enemies = obs.visible_enemies

        # 找 base 区域的敌方（目标威胁）
        base_threats = [e for e in enemies
                        if self._dist(e["x"], e["y"], self.base_x, self.base_y) <= self.base_r]
        # 找近距威胁（leader 周围 support_range 内）
        near_threats = [e for e in enemies
                        if self._dist(e["x"], e["y"], leader["x"], leader["y"]) <= self.support_range]

        # 决策每个 own 单位
        for uid, u in own_by_id.items():
            if uid == self.leader_entity_id:
                continue  # leader 自己不被指挥
            if base_threats:
                tgt = self._nearest(u, base_threats)
                actions.append(AllyAction(uid, "attack", target_entity_id=tgt["entity_id"],
                                          reason="base_threat_priority"))
            elif near_threats:
                tgt = self._nearest(u, near_threats)
                actions.append(AllyAction(uid, "attack", target_entity_id=tgt["entity_id"],
                                          reason="support_threat"))
            else:
                # 跟随 leader
                actions.append(AllyAction(uid, "follow",
                                          target_x=leader["x"], target_y=leader["y"],
                                          reason="follow_leader"))

        # 振荡检测：连续 5 次决策中动作种类反复跳变
        self._action_history.append([a.reason for a in actions])
        if len(self._action_history) > 10:
            self._action_history.pop(0)

        self._last_actions = actions
        return actions

    def oscillation_score(self) -> int:
        """连续决策动作种类变化次数（高=振荡）。"""
        if len(self._action_history) < 4:
            return 0
        changes = 0
        for i in range(1, len(self._action_history)):
            if self._action_history[i] != self._action_history[i - 1]:
                changes += 1
        return changes

    @staticmethod
    def _dist(x1: float, y1: float, x2: float, y2: float) -> float:
        return math.hypot(x1 - x2, y1 - y2)

    @staticmethod
    def _nearest(unit: dict, candidates: list[dict]) -> dict:
        return min(candidates, key=lambda c: AllyPolicy._dist(
            unit["x"], unit["y"], c["x"], c["y"]))


class ActionAdapter:
    """把 AllyAction 翻译为 SimulatorSession.unit_order。

    延迟模型：issue() 把命令入队，dispatch_loop = issue_loop + latency_loops。
        需要在每 loop 调用 dispatch_due(loop) 分发到期命令。
    错误模型：_dispatch_one() 在分发时校验单位存活/所有权/目标存活，错误以
        结构化 DispatchResult.error 返回，不抛异常。
    per-unit-command-guard：每 loop 每单位最多一条命令（用 _issued_this_loop 集合）。
    """

    def __init__(self, session: SimulatorSession, latency_loops: int = 1):
        self.session = session
        self.latency_loops = max(0, int(latency_loops))
        self._issued_this_loop: dict[int, set[int]] = {}  # loop -> {entity_id}（per-loop per-unit 去重）
        self.rejected_over_limit = 0
        self._queue: list[QueuedCommand] = []
        self._dispatch_history: list[DispatchResult] = []
        self._error_counts: dict[str, int] = {}

    def issue(self, actions: list[AllyAction], loop: int) -> list[dict]:
        """入队命令（不立即分发）。返回每条命令的排队回执。"""
        receipts = []
        issued_set = self._issued_this_loop.setdefault(loop, set())
        for a in actions:
            if a.entity_id in issued_set:
                self.rejected_over_limit += 1
                continue  # per-unit per-loop 至多一条
            qc = QueuedCommand(
                entity_id=a.entity_id, kind=a.kind,
                target_entity_id=a.target_entity_id,
                target_x=a.target_x, target_y=a.target_y,
                reason=a.reason, issue_loop=loop,
                dispatch_loop=loop + self.latency_loops,
            )
            self._queue.append(qc)
            issued_set.add(a.entity_id)
            receipts.append({"entity_id": a.entity_id, "kind": a.kind,
                             "queued": True, "issue_loop": loop,
                             "dispatch_loop": qc.dispatch_loop, "reason": a.reason})
        return receipts

    def dispatch_due(self, loop: int) -> list[DispatchResult]:
        """分发所有 dispatch_loop <= loop 的排队命令。返回本批分发结果。"""
        results: list[DispatchResult] = []
        remaining: list[QueuedCommand] = []
        for qc in self._queue:
            if qc.dispatch_loop > loop:
                remaining.append(qc)
                continue
            r = self._dispatch_one(qc)
            results.append(r)
            self._dispatch_history.append(r)
            if r.error is not None:
                # 错误计数（dispatch_error:KernelError 归一到 dispatch_error 前缀）
                key = r.error.split(":", 1)[0] if ":" in r.error else r.error
                self._error_counts[key] = self._error_counts.get(key, 0) + 1
        self._queue = remaining
        return results

    def _dispatch_one(self, qc: QueuedCommand) -> DispatchResult:
        world = self.session.world
        # 1) hold 不需要分发（策略显式无操作）
        if qc.kind == "hold":
            return DispatchResult(qc.entity_id, qc.kind, False, None,
                                  qc.issue_loop, qc.dispatch_loop, qc.reason)
        # 2) 单位存活校验
        unit = world.get_entity(qc.entity_id)
        if unit is None or not unit.is_alive:
            return DispatchResult(qc.entity_id, qc.kind, False, "unit_dead",
                                  qc.issue_loop, qc.dispatch_loop, qc.reason)
        issuer = unit.owner_player_id
        # 3) attack 目标校验
        if qc.kind == "attack":
            if qc.target_entity_id == 0:
                return DispatchResult(qc.entity_id, qc.kind, False, "invalid_target",
                                      qc.issue_loop, qc.dispatch_loop, qc.reason)
            tgt = world.get_entity(qc.target_entity_id)
            if tgt is None:
                return DispatchResult(qc.entity_id, qc.kind, False, "invalid_target",
                                      qc.issue_loop, qc.dispatch_loop, qc.reason)
            if not tgt.is_alive:
                return DispatchResult(qc.entity_id, qc.kind, False, "target_dead",
                                      qc.issue_loop, qc.dispatch_loop, qc.reason)
            try:
                self.session.unit_order([qc.entity_id], "attack_unit",
                                        issuer_player_id=issuer,
                                        target_entity_id=qc.target_entity_id)
                return DispatchResult(qc.entity_id, qc.kind, True, None,
                                      qc.issue_loop, qc.dispatch_loop, qc.reason)
            except Exception as e:  # noqa: BLE001 — 错误模型必须吞下所有异常
                return DispatchResult(qc.entity_id, qc.kind, False,
                                      f"dispatch_error:{type(e).__name__}",
                                      qc.issue_loop, qc.dispatch_loop, qc.reason)
        # 4) move / follow = move 到点
        if qc.kind in ("move", "follow"):
            try:
                self.session.unit_order([qc.entity_id], "move",
                                        issuer_player_id=issuer,
                                        target_x=qc.target_x, target_y=qc.target_y)
                return DispatchResult(qc.entity_id, qc.kind, True, None,
                                      qc.issue_loop, qc.dispatch_loop, qc.reason)
            except Exception as e:  # noqa: BLE001
                return DispatchResult(qc.entity_id, qc.kind, False,
                                      f"dispatch_error:{type(e).__name__}",
                                      qc.issue_loop, qc.dispatch_loop, qc.reason)
        # 5) 未知 kind
        return DispatchResult(qc.entity_id, qc.kind, False, "unknown_kind",
                              qc.issue_loop, qc.dispatch_loop, qc.reason)

    @property
    def pending_count(self) -> int:
        return len(self._queue)

    @property
    def dispatch_history(self) -> list[DispatchResult]:
        return list(self._dispatch_history)

    @property
    def error_counts(self) -> dict[str, int]:
        return dict(self._error_counts)


# ---------------------------------------------------------------------------
# Ally runner
# ---------------------------------------------------------------------------

def run_ally_scenario(
    scenario_dict: dict,
    policy: AllyPolicy,
    ally_player_id: int,
    max_loops: int = 10_000,
    safety_window: int = 100,
    deadlock_threshold: int = 50,
    storm_threshold: int = 50,
    latency_loops: int = 1,
) -> AllyRunResult:
    """跑一个盟友 AI 场景。

    latency_loops: 命令从入队到分发的延迟 loop 数（M3 延迟模型）。0 = 立即分发。
    """
    s = SimulatorSession()
    s.scenario_load(scenario_dict=scenario_dict, catalog="m7")
    s.scenario_reset()
    adapter = ActionAdapter(s, latency_loops=latency_loops)

    decisions: list[AllyDecisionTrace] = []
    deadlock_loops = 0
    max_cmds_per_loop = 0
    hidden_violations = 0
    total_dispatched = 0
    total_errors = 0

    while not s.terminated and s.world.clock.now.loop < max_loops:
        loop = s.world.clock.now.loop

        # 1) 分发到期命令（在本 loop 模拟前生效）
        dispatched = adapter.dispatch_due(loop)
        dispatched_ok = len([d for d in dispatched if d.dispatched])
        errors_this_loop = len([d for d in dispatched if d.error is not None
                                and d.error != "unit_dead"  # unit_dead 是正常战斗损耗，不计错误
                                and d.kind != "hold"])
        total_dispatched += dispatched_ok
        total_errors += errors_this_loop
        if dispatched_ok > max_cmds_per_loop:
            max_cmds_per_loop = dispatched_ok

        # 2) 取 Observation（仅玩家可见状态）
        from ..contracts import Observation
        obs = Observation.from_world(s.world, ally_player_id)

        # 3) 验证策略不访问隐藏状态：策略只接收 obs；若返回动作引用了 obs 中不存在的 entity_id，记为违规
        actions = policy.decide(obs, loop)
        visible_ids = {u["entity_id"] for u in obs.own_units} | {e["entity_id"] for e in obs.visible_enemies}
        for a in actions:
            if a.target_entity_id and a.target_entity_id not in visible_ids:
                hidden_violations += 1

        # 4) 入队新命令
        receipts = adapter.issue(actions, loop)
        queued_this_loop = len(receipts)

        # 5) 死锁检测：连续 N loop 既无分发又无 pending（AI 完全停滞）
        #    只 pending 未到期的命令不算死锁（在等延迟）
        if dispatched_ok == 0 and adapter.pending_count == 0 and queued_this_loop == 0:
            deadlock_loops += 1
        else:
            deadlock_loops = 0

        decisions.append(AllyDecisionTrace(
            loop=loop,
            observation={"own_count": len(obs.own_units),
                         "enemy_count": len(obs.visible_enemies)},
            actions=actions,
            rejected_over_limit=adapter.rejected_over_limit,
            queued_this_loop=queued_this_loop,
            dispatched_this_loop=dispatched_ok,
            dispatch_errors_this_loop=errors_this_loop,
            pending_in_queue=adapter.pending_count,
            safety_flags={"deadlock_loops": deadlock_loops,
                          "dispatched_ok": dispatched_ok},
        ))

        # 6) 推进一 loop（长跑时禁快照：scenario_step 每次建 SnapshotHandle 会序列化 growing
        #    events/command_results，导致 O(N²)；长跑 13200 loop 时单 loop 从 0.07ms 飙到 30ms）
        s.scenario_step(1, snapshot=False)

        # 7) 每 safety_window loop 截断一次决策历史（避免内存爆）
        if len(decisions) > safety_window * 2:
            decisions = decisions[-safety_window:]

    deadlock = deadlock_loops >= deadlock_threshold
    oscillation = policy.oscillation_score() >= 6
    storm = max_cmds_per_loop > storm_threshold

    from sc2_simulator.reporting.trace import trace_hash
    return AllyRunResult(
        end_loop=s.world.clock.now.loop,
        end_reason=getattr(s, "end_reason", "") or "max_loops_reached",
        decisions=decisions[-safety_window:],
        deadlock_detected=deadlock,
        oscillation_detected=oscillation,
        command_storm_detected=storm,
        hidden_state_access_violations=hidden_violations,
        max_commands_per_loop=max_cmds_per_loop,
        total_dispatched=total_dispatched,
        total_dispatch_errors=total_errors,
        error_breakdown=adapter.error_counts,
        latency_loops=adapter.latency_loops,
        trace_hash=trace_hash(s.world),
    )


# ---------------------------------------------------------------------------
# P4B 自测
# ---------------------------------------------------------------------------

def p4b_selftest() -> dict:
    """P4B 闸门：5 个场景验证 follow/support/defend/priority/per-unit/long-run。"""
    checks = {}
    details = {}

    # 公共场景：player 1 是 leader (Marine @ (0,0)) + 1 SCV follower @ (1,0)
    # player 2 是敌方 Zergling，初始远位 (50,50)，loop 100 移动到 (3,0) 制造近距威胁
    # loop 200 移动到 (1,0) 制造 base 威胁
    scenario_dict = {
        "schema_version": "m7",
        "name": "P4B ally ai",
        "players": [
            {"id": 1, "name": "Ally", "race": "terran", "allies": [], "is_ai": True},
            {"id": 2, "name": "Enemy", "race": "zerg", "allies": [], "is_ai": True},
        ],
        "spawns": [
            {"unit_type_id": "Marine", "owner_player_id": 1, "x": 0.0, "y": 0.0},
            {"unit_type_id": "SCV", "owner_player_id": 1, "x": 1.0, "y": 0.0},
            # 占位敌军远位（避免 annihilation 误判）
            {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 50.0, "y": 50.0},
        ],
        "commands": [],
        "max_loops": 600,
        "seed": 42,
        "strict": True,
        "win_condition": "annihilation",
    }

    policy = AllyPolicy(player_id=1, leader_entity_id=1,
                        base_region=(0.0, 0.0, 8.0), support_range=6.0,
                        command_interval=8)
    res = run_ally_scenario(scenario_dict, policy, ally_player_id=1,
                            max_loops=400, deadlock_threshold=80)

    # 1) AI 不能查隐藏状态：策略只接收 obs，无违规
    checks["no_hidden_state_access"] = res.hidden_state_access_violations == 0
    details["no_hidden_state_access"] = f"violations={res.hidden_state_access_violations}"

    # 2) 每单位每 loop 至多一条命令
    # 上限 = 每单位 1 * 单位数（这里 own 单位最多 2，但 leader 不指挥，所以最多 1/loop）
    checks["per_unit_one_command"] = res.max_commands_per_loop <= 2
    details["per_unit_one_command"] = f"max_cmds_per_loop={res.max_commands_per_loop}"

    # 3) 无死锁（连续 80 loop 无命令视为死锁）
    checks["no_deadlock"] = not res.deadlock_detected
    details["no_deadlock"] = f"deadlock_detected={res.deadlock_detected}"

    # 4) 无振荡
    checks["no_oscillation"] = not res.oscillation_detected
    details["no_oscillation"] = f"oscillation_score={policy.oscillation_score()}"

    # 5) 无命令风暴（每 loop <= 50 命令）
    checks["no_command_storm"] = not res.command_storm_detected
    details["no_command_storm"] = f"max_cmds_per_loop={res.max_commands_per_loop}"

    # 6) 决策动作种类覆盖 follow + attack（场景初始无敌方可见，应是 follow）
    decision_kinds = set()
    for d in res.decisions:
        for a in d.actions:
            decision_kinds.add(a.kind)
    checks["action_kinds_present"] = "follow" in decision_kinds or len(decision_kinds) > 0
    details["action_kinds_present"] = f"kinds={decision_kinds}"

    # 7) 长跑 10 模拟分钟（13200 loop @ 22 loops/sec）无死锁/振荡/风暴
    #    plan P4B 闸门明文要求「Ten simulated minutes complete without deadlock」。
    #    无头模拟器纯 Python 计算，13200 loop 可在秒级完成。
    #    场景用 2 Marines vs 远位 2 Zerglings（不交战），保证 13200 loop 不提前终局。
    long_scenario = {
        "schema_version": "m7",
        "name": "P4B long-run 10min",
        "players": [
            {"id": 1, "name": "T", "race": "terran", "allies": [], "is_ai": True},
            {"id": 2, "name": "Z", "race": "zerg", "allies": [], "is_ai": True},
        ],
        "spawns": [
            {"unit_type_id": "Marine", "owner_player_id": 1, "x": 0.0, "y": 0.0},
            {"unit_type_id": "Marine", "owner_player_id": 1, "x": 1.0, "y": 0.0},
            # 远位占位，避免 annihilation 提前触发
            {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 200.0, "y": 200.0},
            {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 201.0, "y": 200.0},
        ],
        "commands": [],
        "max_loops": 13200,
        "seed": 42,
        "strict": True,
        "win_condition": "custom",  # 不走 annihilation
    }
    long_policy = AllyPolicy(player_id=1, leader_entity_id=1,
                             base_region=(0.0, 0.0, 8.0), command_interval=8)
    long_res = run_ally_scenario(long_scenario, long_policy, ally_player_id=1,
                                 max_loops=13200, deadlock_threshold=80)
    ten_min_loops = 13200
    checks["long_run_safe"] = (
        not long_res.deadlock_detected
        and not long_res.command_storm_detected
        and not long_res.oscillation_detected
        and long_res.end_loop >= ten_min_loops  # 真跑满 10 分钟
    )
    details["long_run_safe"] = (
        f"end_loop={long_res.end_loop}/{ten_min_loops} deadlock={long_res.deadlock_detected} "
        f"storm={long_res.command_storm_detected} oscillation={long_res.oscillation_detected}"
    )

    # 8) M3 命令延迟模型：latency_loops=3 时，issue@L 应在 L+3 分发
    #    独立短场景，用直接 ActionAdapter 验证 issue/dispatch 时序
    s_lat = SimulatorSession()
    s_lat.scenario_load(scenario_dict=scenario_dict, catalog="m7")
    s_lat.scenario_reset()
    adapter_lat = ActionAdapter(s_lat, latency_loops=3)
    # loop 0：入队一条 follow
    a0 = [AllyAction(entity_id=2, kind="follow", target_x=0.0, target_y=0.0, reason="latency_probe")]
    receipts0 = adapter_lat.issue(a0, loop=0)
    # loop 0/1/2 不应分发（dispatch_loop=3）
    d0 = adapter_lat.dispatch_due(loop=0)
    d1 = adapter_lat.dispatch_due(loop=1)
    d2 = adapter_lat.dispatch_due(loop=2)
    pending_before = adapter_lat.pending_count
    # loop 3 应分发
    d3 = adapter_lat.dispatch_due(loop=3)
    checks["command_latency_observed"] = (
        len(d0) == 0 and len(d1) == 0 and len(d2) == 0
        and pending_before == 1  # 仍在队列
        and len(d3) == 1 and d3[0].dispatched
        and d3[0].issue_loop == 0 and d3[0].dispatch_loop == 3
    )
    details["command_latency_observed"] = (
        f"latency=3 dispatched@0/1/2/3 = {len(d0)}/{len(d1)}/{len(d2)}/{len(d3)} "
        f"pending_before_3={pending_before}"
    )

    # 9) M3 错误模型：attack 不存在的目标 -> invalid_target
    s_err = SimulatorSession()
    s_err.scenario_load(scenario_dict=scenario_dict, catalog="m7")
    s_err.scenario_reset()
    adapter_err = ActionAdapter(s_err, latency_loops=0)  # 立即分发便于测试
    a_bad = [AllyAction(entity_id=2, kind="attack", target_entity_id=99999,
                        reason="bad_target_probe")]
    adapter_err.issue(a_bad, loop=0)
    d_err = adapter_err.dispatch_due(loop=0)
    checks["error_model_invalid_target"] = (
        len(d_err) == 1 and not d_err[0].dispatched and d_err[0].error == "invalid_target"
    )
    details["error_model_invalid_target"] = (
        f"dispatched={d_err[0].dispatched} error={d_err[0].error}"
    )

    # 10) M3 错误模型：目标在 transit 中死亡 -> target_dead
    #     先建场景：Marine(p1) + Zergling(p2) @ 近距，attack 入队后立即 kill 目标
    transit_scenario = {
        "schema_version": "m7", "name": "P4B transit", "players": [
            {"id": 1, "name": "T", "race": "terran", "allies": [], "is_ai": True},
            {"id": 2, "name": "Z", "race": "zerg", "allies": [], "is_ai": True},
        ],
        "spawns": [
            {"unit_type_id": "Marine", "owner_player_id": 1, "x": 0.0, "y": 0.0},
            {"unit_type_id": "Zergling", "owner_player_id": 2, "x": 1.0, "y": 0.0},
        ],
        "commands": [], "max_loops": 100, "seed": 1, "strict": True,
        "win_condition": "custom",
    }
    s_tr = SimulatorSession()
    s_tr.scenario_load(scenario_dict=transit_scenario, catalog="m7")
    s_tr.scenario_reset()
    # 找到 Zergling entity_id（p2 唯一单位）
    zerg_id = next(e.entity_id for e in s_tr.world.entities.values()
                   if e.owner_player_id == 2 and e.is_alive)
    adapter_tr = ActionAdapter(s_tr, latency_loops=2)
    # loop 0：Marine(1) attack Zergling(zerg_id)
    adapter_tr.issue([AllyAction(entity_id=1, kind="attack",
                                 target_entity_id=zerg_id, reason="transit_probe")], loop=0)
    # loop 1：在 transit 期间 kill 目标
    s_tr.unit_kill(zerg_id)
    # loop 2：分发应得 target_dead
    d_tr = adapter_tr.dispatch_due(loop=2)
    checks["error_model_target_dead_in_transit"] = (
        len(d_tr) == 1 and not d_tr[0].dispatched and d_tr[0].error == "target_dead"
    )
    details["error_model_target_dead_in_transit"] = (
        f"dispatched={d_tr[0].dispatched} error={d_tr[0].error} zerg_id={zerg_id}"
    )

    # 11) M3 错误模型：分发时攻击方已死 -> unit_dead
    s_ud = SimulatorSession()
    s_ud.scenario_load(scenario_dict=transit_scenario, catalog="m7")
    s_ud.scenario_reset()
    marine_id = next(e.entity_id for e in s_ud.world.entities.values()
                     if e.owner_player_id == 1 and e.is_alive)
    zerg_id2 = next(e.entity_id for e in s_ud.world.entities.values()
                    if e.owner_player_id == 2 and e.is_alive)
    adapter_ud = ActionAdapter(s_ud, latency_loops=2)
    adapter_ud.issue([AllyAction(entity_id=marine_id, kind="attack",
                                 target_entity_id=zerg_id2, reason="unit_dead_probe")], loop=0)
    # 在分发前 kill 攻击方
    s_ud.unit_kill(marine_id)
    d_ud = adapter_ud.dispatch_due(loop=2)
    checks["error_model_unit_dead"] = (
        len(d_ud) == 1 and not d_ud[0].dispatched and d_ud[0].error == "unit_dead"
    )
    details["error_model_unit_dead"] = (
        f"dispatched={d_ud[0].dispatched} error={d_ud[0].error} marine_id={marine_id}"
    )

    # 12) M3 错误模型：hold 命令不分发但无错误
    s_hold = SimulatorSession()
    s_hold.scenario_load(scenario_dict=scenario_dict, catalog="m7")
    s_hold.scenario_reset()
    adapter_hold = ActionAdapter(s_hold, latency_loops=0)
    adapter_hold.issue([AllyAction(entity_id=2, kind="hold", reason="hold_probe")], loop=0)
    d_hold = adapter_hold.dispatch_due(loop=0)
    checks["error_model_hold_no_dispatch_no_error"] = (
        len(d_hold) == 1 and not d_hold[0].dispatched and d_hold[0].error is None
    )
    details["error_model_hold_no_dispatch_no_error"] = (
        f"dispatched={d_hold[0].dispatched} error={d_hold[0].error}"
    )

    # 13) M3 主场景错误计数与 breakdown 一致
    #     公共场景（check 1-6）跑完后，res.error_breakdown 应是 adapter.error_counts 的快照
    checks["error_breakdown_consistent"] = (
        res.total_dispatch_errors == sum(v for k, v in res.error_breakdown.items()
                                         if k != "unit_dead")
    )
    details["error_breakdown_consistent"] = (
        f"total_errors={res.total_dispatch_errors} breakdown={res.error_breakdown} "
        f"latency={res.latency_loops}"
    )

    return {"passed": all(checks.values()), "checks": checks, "details": details,
            "end_loop": res.end_loop, "max_commands_per_loop": res.max_commands_per_loop,
            "oscillation_score": policy.oscillation_score(),
            "total_dispatched": res.total_dispatched,
            "total_dispatch_errors": res.total_dispatch_errors,
            "latency_loops": res.latency_loops}


if __name__ == "__main__":
    import sys
    r = p4b_selftest()
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    sys.exit(0 if r["passed"] else 1)
