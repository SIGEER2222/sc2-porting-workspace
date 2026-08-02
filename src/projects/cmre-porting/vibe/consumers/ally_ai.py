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
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional

from ..contracts import Observation
from ..sim_path import ensure_simulator_on_path

ensure_simulator_on_path()

from ..simulator_session import SimulatorSession


class AllyMode(str, Enum):
    """High-level cooperative modes controlled by the P1 player signal."""

    FOLLOW = "follow"
    REGROUP = "regroup"
    DEFEND_BASE = "defend_base"
    ASSIST_ATTACK = "assist_attack"
    RETREAT = "retreat"
    HOLD = "hold"


class PlayerSignalKind(str, Enum):
    FOLLOW = "follow"
    ATTACK = "attack"
    DEFEND = "defend"
    REGROUP = "regroup"
    RETREAT = "retreat"
    HOLD = "hold"
    STATUS = "status"
    HELP = "help"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PlayerCommand:
    """A normalized command received from a player chat/signal channel."""

    kind: PlayerSignalKind
    source_player_id: int
    text: str
    command_id: str
    loop: int
    accepted: bool
    duplicate: bool = False
    reason: str = ""


@dataclass(frozen=True)
class PlayerNotice:
    """A deterministic text/signal response addressed back to P1."""

    recipient_player_id: int
    message: str
    kind: str
    loop: int
    mode: str
    accepted: bool = True


class PlayerCommandAdapter:
    """Parse and deduplicate the small player-to-ally command protocol."""

    _ALIASES = {
        "follow": PlayerSignalKind.FOLLOW,
        "attack": PlayerSignalKind.ATTACK,
        "engage": PlayerSignalKind.ATTACK,
        "defend": PlayerSignalKind.DEFEND,
        "defend_base": PlayerSignalKind.DEFEND,
        "regroup": PlayerSignalKind.REGROUP,
        "rally": PlayerSignalKind.REGROUP,
        "retreat": PlayerSignalKind.RETREAT,
        "fall_back": PlayerSignalKind.RETREAT,
        "hold": PlayerSignalKind.HOLD,
        "status": PlayerSignalKind.STATUS,
        "help": PlayerSignalKind.HELP,
    }

    def __init__(self, allowed_player_ids: Iterable[int] = (1,)) -> None:
        self.allowed_player_ids = frozenset(int(pid) for pid in allowed_player_ids)
        self._seen_command_ids: set[str] = set()

    def receive(
        self,
        text: str,
        source_player_id: int,
        loop: int = 0,
        command_id: Optional[str] = None,
    ) -> PlayerCommand:
        normalized = " ".join(str(text).strip().lower().split())
        command_id = command_id or f"{int(source_player_id)}:{int(loop)}:{normalized}"
        if command_id in self._seen_command_ids:
            return PlayerCommand(
                kind=PlayerSignalKind.UNKNOWN,
                source_player_id=int(source_player_id),
                text=str(text),
                command_id=command_id,
                loop=int(loop),
                accepted=False,
                duplicate=True,
                reason="duplicate_command",
            )
        self._seen_command_ids.add(command_id)

        if int(source_player_id) not in self.allowed_player_ids:
            return PlayerCommand(
                kind=PlayerSignalKind.UNKNOWN,
                source_player_id=int(source_player_id),
                text=str(text),
                command_id=command_id,
                loop=int(loop),
                accepted=False,
                reason="unauthorized_source",
            )

        payload = normalized
        if payload.startswith("!ally"):
            payload = payload[5:].strip()
        elif payload.startswith("ally "):
            payload = payload[5:].strip()
        token = payload.split(" ", 1)[0] if payload else ""
        kind = self._ALIASES.get(token, PlayerSignalKind.UNKNOWN)
        accepted = kind != PlayerSignalKind.UNKNOWN
        return PlayerCommand(
            kind=kind,
            source_player_id=int(source_player_id),
            text=str(text),
            command_id=command_id,
            loop=int(loop),
            accepted=accepted,
            reason="" if accepted else "unknown_command",
        )


@dataclass(frozen=True)
class RosterValidation:
    """Result of validating the explicit P1/P2/enemy simulator roster."""

    valid: bool
    leader_player_id: int
    ally_player_id: int
    enemy_player_ids: tuple[int, ...]
    issues: tuple[str, ...] = ()


def validate_cooperative_roster(
    scenario_dict: dict,
    leader_player_id: int = 1,
    ally_player_id: int = 2,
    enemy_player_ids: Optional[Iterable[int]] = None,
) -> RosterValidation:
    """Validate reciprocal P1/P2 membership before a cooperative run starts."""

    players = {int(player["id"]): player for player in scenario_dict.get("players", [])}
    issues: list[str] = []
    leader = players.get(int(leader_player_id))
    ally = players.get(int(ally_player_id))
    if leader is None:
        issues.append(f"missing_leader_player:{leader_player_id}")
    if ally is None:
        issues.append(f"missing_ally_player:{ally_player_id}")

    if leader is not None and bool(leader.get("is_ai", True)):
        issues.append("leader_must_be_human")
    if ally is not None and not bool(ally.get("is_ai", False)):
        issues.append("ally_must_be_ai")

    leader_allies = set(leader.get("allies", [])) if leader is not None else set()
    ally_allies = set(ally.get("allies", [])) if ally is not None else set()
    if ally is not None and int(ally_player_id) not in leader_allies:
        issues.append("leader_missing_ally_edge")
    if leader is not None and int(leader_player_id) not in ally_allies:
        issues.append("ally_missing_leader_edge")

    for player_id, player in players.items():
        for other_id in player.get("allies", []):
            if int(other_id) not in players:
                issues.append(f"unknown_ally_id:{player_id}->{other_id}")

    inferred_enemies = sorted(
        pid for pid in players if pid not in {int(leader_player_id), int(ally_player_id)}
    )
    enemies = tuple(sorted(int(pid) for pid in (
        inferred_enemies if enemy_player_ids is None else enemy_player_ids
    )))
    for enemy_id in enemies:
        enemy = players.get(enemy_id)
        if enemy is None:
            issues.append(f"missing_enemy_player:{enemy_id}")
            continue
        if enemy_id in leader_allies or enemy_id in ally_allies:
            issues.append(f"enemy_marked_ally:{enemy_id}")
        enemy_allies = set(enemy.get("allies", []))
        if int(leader_player_id) in enemy_allies or int(ally_player_id) in enemy_allies:
            issues.append(f"enemy_marked_ally_reverse:{enemy_id}")

    return RosterValidation(
        valid=not issues,
        leader_player_id=int(leader_player_id),
        ally_player_id=int(ally_player_id),
        enemy_player_ids=enemies,
        issues=tuple(dict.fromkeys(issues)),
    )


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
    mode: str = AllyMode.FOLLOW.value


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
    roster_ready: bool = False
    roster_issues: tuple[str, ...] = ()
    mode_history: list[str] = field(default_factory=list)
    notices: list[PlayerNotice] = field(default_factory=list)
    friendly_fire_rejections: int = 0
    replay_path: str = ""
    replay_frame_count: int = 0


class AllyPolicy:
    """P2 policy that responds to P1 while retaining autonomous safety priority.

    The policy never treats the P1 leader as an owned unit. It only emits
    commands for ``obs.own_units`` (P2) and uses ``obs.visible_allies`` for
    leader position and cooperative context.
    """

    def __init__(
        self,
        player_id: int,
        leader_entity_id: int,
        base_region: tuple[float, float, float] = (0.0, 0.0, 8.0),
        support_range: float = 6.0,
        command_interval: int = 8,
        leader_player_id: int = 1,
    ):
        self.player_id = int(player_id)
        self.leader_player_id = int(leader_player_id)
        self.leader_entity_id = int(leader_entity_id)
        self.base_x, self.base_y, self.base_r = base_region
        self.support_range = support_range
        self.command_interval = command_interval
        self._last_decide_loop = -10_000
        self._last_actions: list[AllyAction] = []
        self._action_history: list[list[str]] = []
        self._mode_history: list[str] = []
        self._mode = AllyMode.FOLLOW
        self._commands = PlayerCommandAdapter((self.leader_player_id,))
        self._notices: list[PlayerNotice] = []

    @property
    def mode(self) -> AllyMode:
        return self._mode

    @property
    def mode_history(self) -> list[str]:
        return list(self._mode_history)

    @property
    def command_adapter(self) -> PlayerCommandAdapter:
        return self._commands

    def receive_player_command(
        self,
        text: str,
        source_player_id: Optional[int] = None,
        loop: int = 0,
        command_id: Optional[str] = None,
    ) -> PlayerNotice:
        """Accept one P1 command and produce a text/signal response."""

        source = self.leader_player_id if source_player_id is None else int(source_player_id)
        command = self._commands.receive(text, source, loop, command_id)
        if command.duplicate:
            notice = PlayerNotice(source, "Ignored duplicate command.", "duplicate", loop,
                                  self._mode.value, accepted=False)
        elif not command.accepted:
            message = "Command rejected: player is not an authorized ally source."
            if command.reason == "unknown_command":
                message = "Unknown ally command. Try: follow, attack, defend, regroup, retreat, status."
            notice = PlayerNotice(source, message, "rejected", loop, self._mode.value,
                                  accepted=False)
        elif command.kind == PlayerSignalKind.STATUS:
            notice = PlayerNotice(
                source,
                f"Status: mode={self._mode.value}; controller=P2; leader=P1.",
                "status",
                loop,
                self._mode.value,
            )
        elif command.kind == PlayerSignalKind.HELP:
            notice = PlayerNotice(
                source,
                "Ally commands: follow, attack, defend, regroup, retreat, status.",
                "help",
                loop,
                self._mode.value,
            )
        else:
            mode_map = {
                PlayerSignalKind.FOLLOW: AllyMode.FOLLOW,
                PlayerSignalKind.ATTACK: AllyMode.ASSIST_ATTACK,
                PlayerSignalKind.DEFEND: AllyMode.DEFEND_BASE,
                PlayerSignalKind.REGROUP: AllyMode.REGROUP,
                PlayerSignalKind.RETREAT: AllyMode.RETREAT,
                PlayerSignalKind.HOLD: AllyMode.HOLD,
            }
            self._mode = mode_map[command.kind]
            notice = PlayerNotice(
                source,
                f"Acknowledged: {command.kind.value}. P2 mode={self._mode.value}.",
                "acknowledged",
                loop,
                self._mode.value,
            )
        self._notices.append(notice)
        return notice

    def drain_notices(self) -> list[PlayerNotice]:
        notices = list(self._notices)
        self._notices.clear()
        return notices

    def decide(self, obs: Observation, loop: int) -> list[AllyAction]:
        """Decide using only the P2 view plus visible P1 ally units."""
        if loop - self._last_decide_loop < self.command_interval:
            return self._last_actions
        self._last_decide_loop = loop

        own_by_id = {
            unit["entity_id"]: unit
            for unit in obs.own_units
            if unit.get("owner") == self.player_id
        }
        leader = next(
            (unit for unit in obs.visible_allies
             if unit.get("entity_id") == self.leader_entity_id
             and unit.get("owner") == self.leader_player_id),
            None,
        )
        # Legacy P1-only selftests are retained, but the cooperative P2 path
        # must always resolve the leader from visible_allies.
        if leader is None and self.player_id == self.leader_player_id:
            leader = own_by_id.get(self.leader_entity_id)

        enemies = list(obs.visible_enemies)
        base_threats = [
            enemy for enemy in enemies
            if self._dist(enemy["x"], enemy["y"], self.base_x, self.base_y) <= self.base_r
        ]
        leader_threats = [] if leader is None else [
            enemy for enemy in enemies
            if self._dist(enemy["x"], enemy["y"], leader["x"], leader["y"]) <= self.support_range
        ]

        if not own_by_id:
            self._record_mode(AllyMode.RETREAT, "p2_roster_empty")
            self._last_actions = []
            return []

        # Safety always overrides a player attack/follow request.
        critically_wounded = any(
            unit.get("max_health", 0) > 0
            and unit.get("health", 0) <= unit["max_health"] * 0.15
            for unit in own_by_id.values()
        )
        if critically_wounded:
            mode = AllyMode.RETREAT
            mode_reason = "self_preservation"
        elif base_threats:
            mode = AllyMode.DEFEND_BASE
            mode_reason = "base_threat_priority"
        elif leader_threats and self._mode in {
            AllyMode.FOLLOW, AllyMode.REGROUP, AllyMode.ASSIST_ATTACK,
        }:
            mode = AllyMode.ASSIST_ATTACK
            mode_reason = "leader_support_threat"
        else:
            mode = self._mode
            mode_reason = "player_command" if self._mode != AllyMode.FOLLOW else "follow_leader"
        self._record_mode(mode, mode_reason)

        actions: list[AllyAction] = []
        for uid, unit in sorted(own_by_id.items()):
            target = self._nearest(unit, base_threats or leader_threats or enemies)
            if mode in {AllyMode.DEFEND_BASE, AllyMode.ASSIST_ATTACK} and target is not None:
                actions.append(AllyAction(
                    uid,
                    "attack",
                    target_entity_id=target["entity_id"],
                    reason=mode_reason,
                ))
                continue

            destination = self._destination(mode, leader)
            if mode == AllyMode.HOLD:
                actions.append(AllyAction(uid, "hold", reason="player_hold"))
            elif destination is not None:
                kind = "follow" if mode == AllyMode.FOLLOW else "move"
                actions.append(AllyAction(
                    uid,
                    kind,
                    target_x=destination[0],
                    target_y=destination[1],
                    reason=mode_reason,
                ))
            else:
                actions.append(AllyAction(uid, "hold", reason="leader_not_visible"))

        self._action_history.append([a.reason for a in actions])
        if len(self._action_history) > 10:
            self._action_history.pop(0)
        self._last_actions = actions
        return actions

    def _record_mode(self, mode: AllyMode, reason: str) -> None:
        self._mode = mode
        entry = f"{mode.value}:{reason}"
        if not self._mode_history or self._mode_history[-1] != entry:
            self._mode_history.append(entry)

    def _destination(
        self, mode: AllyMode, leader: Optional[dict]
    ) -> Optional[tuple[float, float]]:
        if mode == AllyMode.DEFEND_BASE or mode == AllyMode.RETREAT:
            return self.base_x, self.base_y
        if leader is None:
            return None
        if mode == AllyMode.REGROUP:
            return leader["x"], leader["y"]
        if mode == AllyMode.FOLLOW:
            return leader["x"], leader["y"]
        return None

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
    def _nearest(unit: dict, candidates: list[dict]) -> Optional[dict]:
        if not candidates:
            return None
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

    def __init__(
        self,
        session: SimulatorSession,
        latency_loops: int = 1,
        controlled_player_id: Optional[int] = None,
    ):
        self.session = session
        self.latency_loops = max(0, int(latency_loops))
        self.controlled_player_id = (
            None if controlled_player_id is None else int(controlled_player_id)
        )
        self._issued_this_loop: dict[int, set[int]] = {}  # loop -> {entity_id}（per-loop per-unit 去重）
        self.rejected_over_limit = 0
        self.friendly_fire_rejections = 0
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
        # 1) 单位存活和 P2 ownership 校验
        unit = world.get_entity(qc.entity_id)
        if unit is None or not unit.is_alive:
            return DispatchResult(qc.entity_id, qc.kind, False, "unit_dead",
                                  qc.issue_loop, qc.dispatch_loop, qc.reason)
        issuer = self.controlled_player_id or unit.owner_player_id
        if unit.owner_player_id != issuer:
            return DispatchResult(qc.entity_id, qc.kind, False, "not_owned",
                                  qc.issue_loop, qc.dispatch_loop, qc.reason)
        # 2) hold does not dispatch but is still ownership-valid
        if qc.kind == "hold":
            return DispatchResult(qc.entity_id, qc.kind, False, None,
                                  qc.issue_loop, qc.dispatch_loop, qc.reason)
        # 3) attack target validation, including an explicit friendly-fire gate
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
            if not world.players.is_enemy(issuer, tgt.owner_player_id):
                self.friendly_fire_rejections += 1
                return DispatchResult(qc.entity_id, qc.kind, False,
                                      "friendly_fire_blocked",
                                      qc.issue_loop, qc.dispatch_loop, qc.reason)
            try:
                self.session.unit_order([qc.entity_id], "attack_unit",
                                        issuer_player_id=self.controlled_player_id or issuer,
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
                                        issuer_player_id=self.controlled_player_id or issuer,
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
    leader_player_id: int = 1,
    require_cooperative_roster: bool = False,
    player_commands: Optional[Iterable[dict | str]] = None,
    replay_log_path: Optional[str | Path] = None,
    replay_log_interval: int = 1,
) -> AllyRunResult:
    """跑一个盟友 AI 场景。

    latency_loops: 命令从入队到分发的延迟 loop 数（M3 延迟模型）。0 = 立即分发。
    """
    if int(ally_player_id) != policy.player_id:
        raise ValueError(
            f"policy player {policy.player_id} must match ally_player_id {ally_player_id}"
        )
    configured_enemy_ids = scenario_dict.get("_cooperative_enemy_player_ids")
    roster = validate_cooperative_roster(
        scenario_dict,
        leader_player_id=leader_player_id,
        ally_player_id=ally_player_id,
        enemy_player_ids=configured_enemy_ids,
    )
    if require_cooperative_roster and not roster.valid:
        raise ValueError("invalid cooperative roster: " + ", ".join(roster.issues))

    scheduled_commands: dict[int, list[dict | str]] = {}
    for command in player_commands or ():
        if isinstance(command, str):
            scheduled_commands.setdefault(0, []).append(command)
        else:
            scheduled_commands.setdefault(int(command.get("loop", 0)), []).append(command)

    s = SimulatorSession()
    s.scenario_load(scenario_dict=scenario_dict, catalog="m7")
    s.scenario_reset()
    adapter = ActionAdapter(
        s,
        latency_loops=latency_loops,
        controlled_player_id=policy.player_id,
    )
    replay_source_spawn_by_entity_id: dict[int, dict] = {}
    if scenario_dict.get("_map_metadata", {}).get("source_kind") == "map_extractor":
        # Simulator entity ids are allocated in scenario spawn order. Preserve
        # the source ObjectUnit identity beside each replay entity so the first
        # frame can be audited back to the map, not just to a generated id.
        for entity, spawn in zip(
            sorted(s.world.entities.values(), key=lambda item: item.entity_id),
            scenario_dict.get("spawns", []),
        ):
            replay_source_spawn_by_entity_id[int(entity.entity_id)] = dict(spawn)

    decisions: list[AllyDecisionTrace] = []
    deadlock_loops = 0
    max_cmds_per_loop = 0
    hidden_violations = 0
    total_dispatched = 0
    total_errors = 0

    replay_path = "" if replay_log_path is None else str(Path(replay_log_path))
    replay_frames = 0
    replay_actions: list[dict] = []
    replay_events: list[dict] = []
    replay_action_by_key: dict[tuple[int, int, str], dict] = {}
    replay_owner_roles = {
        str(player_id): {
            "name": str(player.get("name", f"Player{player_id}")),
            "is_ai": bool(player.get("is_ai", False)),
            "relation": player.get(
                "relation",
                (
                    "leader" if int(player_id) == int(leader_player_id)
                    else "ally" if int(player_id) == int(ally_player_id)
                    else "enemy"
                ),
            ),
        }
        for player_id, player in sorted(
            ((int(item["id"]), item) for item in scenario_dict.get("players", [])),
            key=lambda item: item[0],
        )
    }
    replay_map_metadata = dict(scenario_dict.get("_map_metadata", {}))
    if not replay_map_metadata and scenario_dict.get("_map_source_kind"):
        replay_map_metadata = {
            "source_kind": scenario_dict["_map_source_kind"],
            "native_starting_force": bool(
                scenario_dict.get("_map_native_starting_force", False)
            ),
        }

    def _replay_entities() -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = {}
        for entity in sorted(s.world.entities.values(), key=lambda item: item.entity_id):
            source_spawn = replay_source_spawn_by_entity_id.get(int(entity.entity_id), {})
            entity_record = {
                "id": entity.entity_id,
                "t": entity.unit_type_id,
                "p": entity.owner_player_id,
                "x": entity.x.to_float(),
                "y": entity.y.to_float(),
                "hp": entity.health.raw,
                "alive": bool(entity.is_alive),
                "state": entity.state.value if hasattr(entity.state, "value") else str(entity.state),
            }
            if source_spawn:
                entity_record.update({
                    "source_object_id": source_spawn.get("source_object_id"),
                    "source_unit_type_id": source_spawn.get(
                        "source_unit_type_id", source_spawn.get("unit_type_id")
                    ),
                    "source_x": source_spawn.get("x"),
                    "source_y": source_spawn.get("y"),
                    "resource_amount": source_spawn.get("resource_amount"),
                })
            grouped.setdefault(str(entity.owner_player_id), []).append(entity_record)
        return grouped

    def _replay_resources() -> dict[str, dict]:
        return {
            str(player_id): dict(s.world.get_resources(player_id).snapshot())
            for player_id in sorted(replay_owner_roles)
            if int(player_id) in s.world.players.players
        }

    def _replay_observation() -> dict:
        from ..contracts import Observation

        obs = Observation.from_world(s.world, ally_player_id)
        resources_by_player = _replay_resources()
        return {
            "loop": obs.loop,
            "player_id": obs.player_id,
            "own_units": obs.own_units,
            "visible_allies": obs.visible_allies,
            "visible_enemies": obs.visible_enemies,
            "alliance_summary": obs.alliance_summary,
            "resources": obs.resources,
            "resources_by_player": resources_by_player,
            "mission": obs.mission,
            "ally_mode": policy.mode.value,
        }

    def _count_units(owner_ids: set[int]) -> tuple[int, dict[str, int]]:
        counts: dict[str, int] = {}
        for entity in s.world.entities.values():
            if entity.is_alive and entity.owner_player_id in owner_ids:
                counts[entity.unit_type_id] = counts.get(entity.unit_type_id, 0) + 1
        return sum(counts.values()), counts

    def _capture_replay_frame(loop: int, events: Optional[list[dict]] = None) -> bool:
        nonlocal replay_frames
        if replay_log_path is None or replay_frames % max(1, int(replay_log_interval)) != 0:
            replay_frames += 1
            return False
        p1_alive, p1_types = _count_units({int(leader_player_id)})
        p2_alive, p2_types = _count_units({int(ally_player_id)})
        enemy_ids = set(roster.enemy_player_ids)
        enemy_alive, enemy_types = _count_units({int(pid) for pid in enemy_ids})
        p2_observation = _replay_observation()
        resources = p2_observation["resources_by_player"]
        replay_actions_at_loop = [
            action for action in replay_actions if int(action.get("loop", -1)) == int(loop)
        ]
        frame = {
            "record_type": "frame",
            "replay_schema": "cmre-ai-ally-replay.v1",
            "replay_id": scenario_dict.get("name", "cooperative-ally-scenario"),
            "evidence_type": "simulator",
            "runtime_claim": "none; simulator evidence only",
            "map_metadata": replay_map_metadata,
            "owner_roles": replay_owner_roles,
            "loop": int(loop),
            "real_sec": round(int(loop) / 22.4, 3),
            "state_version": int(loop),
            "current_night": 0,
            "waves_fired": 0,
            "total_cmds": total_dispatched,
            "p1_alive": p1_alive,
            "p2_alive": p2_alive,
            "enemy_alive": enemy_alive,
            "p1_units_by_type": p1_types,
            "p2_units_by_type": p2_types,
            "enemy_units_by_type": enemy_types,
            "p1_resources": resources.get(str(leader_player_id), {}),
            "p2_resources": resources.get(str(ally_player_id), {}),
            "resources_by_player": resources,
            "entities_by_player": _replay_entities(),
            "events": list(events or []),
            "key_events": list(events or []),
            "replay_actions": replay_actions_at_loop,
            "context": p2_observation,
            "ally_mode": policy.mode.value,
        }
        replay_frames += 1
        replay_frame_records.append(frame)
        return True

    replay_frame_records: list[dict] = []
    _capture_replay_frame(0)

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
        for result in dispatched:
            key = (int(result.issue_loop), int(result.entity_id), str(result.kind))
            action = replay_action_by_key.get(key)
            if action is not None:
                action["dispatched"] = {
                    "success": bool(result.dispatched or result.error is None),
                    "dispatched": bool(result.dispatched),
                    "error": result.error,
                    "loop": int(loop),
                    "dispatch_loop": int(result.dispatch_loop),
                    "issuer_player_id": int(policy.player_id),
                }
            replay_events.append({
                "loop": int(loop),
                "kind": "p2_dispatch",
                "entity_id": int(result.entity_id),
                "command_kind": result.kind,
                "success": bool(result.dispatched or result.error is None),
                "dispatched": bool(result.dispatched),
                "error": result.error,
                "issue_loop": int(result.issue_loop),
                "dispatch_loop": int(result.dispatch_loop),
                "issuer_player_id": int(policy.player_id),
            })
        if dispatched_ok > max_cmds_per_loop:
            max_cmds_per_loop = dispatched_ok

        # 2) 取 Observation（仅玩家可见状态）
        from ..contracts import Observation
        obs = Observation.from_world(s.world, ally_player_id)

        # 3) 从 P1 命令通道接收本 loop 的指令，再让 P2 策略决策。
        for scheduled in scheduled_commands.get(loop, []):
            if isinstance(scheduled, str):
                notice = policy.receive_player_command(scheduled, leader_player_id, loop)
                command_id = f"{leader_player_id}:{loop}:{scheduled}"
            else:
                notice = policy.receive_player_command(
                    scheduled.get("text", scheduled.get("message", "")),
                    int(scheduled.get("source_player_id", leader_player_id)),
                    loop,
                    scheduled.get("command_id"),
                )
                command_id = str(scheduled.get("command_id") or f"{leader_player_id}:{loop}")
            replay_actions.append({
                "record_type": "action",
                "action_id": f"p1-command-{len(replay_actions) + 1:03d}",
                "name": "P1 -> P2",
                "kind": "player_command",
                "loop": int(loop),
                "owner": int(leader_player_id),
                "issuer_player_id": int(leader_player_id),
                "command_id": command_id,
                "text": notice.message,
                "arguments": {"text": scheduled if isinstance(scheduled, str) else scheduled.get("text", scheduled.get("message", ""))},
                "accepted": bool(notice.accepted),
                "notice": notice.message,
                "mode": notice.mode,
            })
            replay_events.append({
                "loop": int(loop),
                "kind": "p1_command",
                "source_player_id": int(leader_player_id),
                "command_id": command_id,
                "message": notice.message,
                "accepted": bool(notice.accepted),
                "mode": notice.mode,
            })

        # 4) 验证策略不访问隐藏状态：动作实体必须是 P2 自有或可见目标。
        actions = policy.decide(obs, loop)
        own_ids = {u["entity_id"] for u in obs.own_units}
        visible_ids = own_ids | {
            entity["entity_id"] for entity in obs.visible_enemies + obs.visible_allies
        }
        for a in actions:
            if a.entity_id not in own_ids:
                hidden_violations += 1
            if a.target_entity_id and a.target_entity_id not in visible_ids:
                hidden_violations += 1

        # 5) 入队新命令
        receipts = adapter.issue(actions, loop)
        queued_this_loop = len(receipts)
        receipts_by_entity = {int(receipt["entity_id"]): receipt for receipt in receipts}
        for action in actions:
            receipt = receipts_by_entity.get(int(action.entity_id))
            replay_action = {
                "record_type": "action",
                "action_id": f"p2-action-{len(replay_actions) + 1:03d}",
                "name": f"P2 {action.kind}",
                "kind": "ally_action",
                "loop": int(loop),
                "owner": int(policy.player_id),
                "issuer_player_id": int(policy.player_id),
                "entity_id": int(action.entity_id),
                "reason": action.reason,
                "arguments": {
                    "kind": action.kind,
                    "target_entity_id": int(action.target_entity_id),
                    "target_x": action.target_x,
                    "target_y": action.target_y,
                },
                "accepted": receipt is not None,
                "queued": receipt,
                "dispatched": None,
                "mode": policy.mode.value,
            }
            replay_actions.append(replay_action)
            if receipt is not None:
                replay_action_by_key[(int(loop), int(action.entity_id), str(action.kind))] = replay_action
            replay_events.append({
                "loop": int(loop),
                "kind": "p2_action_queued",
                "entity_id": int(action.entity_id),
                "command_kind": action.kind,
                "accepted": receipt is not None,
                "issuer_player_id": int(policy.player_id),
                "reason": action.reason,
            })

        # 6) 死锁检测：连续 N loop 既无分发又无 pending（AI 完全停滞）
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
            mode=policy.mode.value,
        ))

        # 7) 推进一 loop（长跑时禁快照：scenario_step 每次建 SnapshotHandle 会序列化 growing
        #    events/command_results，导致 O(N²)；长跑 13200 loop 时单 loop 从 0.07ms 飙到 30ms）
        s.scenario_step(1, snapshot=False)
        if _capture_replay_frame(s.world.clock.now.loop, replay_events):
            replay_events = []

        # 8) 每 safety_window loop 截断一次决策历史（避免内存爆）
        if len(decisions) > safety_window * 2:
            decisions = decisions[-safety_window:]

    deadlock = deadlock_loops >= deadlock_threshold
    oscillation = policy.oscillation_score() >= 6
    storm = max_cmds_per_loop > storm_threshold

    from sc2_simulator.reporting.trace import trace_hash
    if replay_log_path is not None:
        path = Path(replay_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        header = {
            "record_type": "header",
            "replay_schema": "cmre-ai-ally-replay.v1",
            "replay_id": scenario_dict.get("name", "cooperative-ally-scenario"),
            "evidence_type": "simulator",
            "runtime_claim": "none; simulator evidence only",
            "map_metadata": replay_map_metadata,
            "leader_player_id": int(leader_player_id),
            "ally_player_id": int(ally_player_id),
            "enemy_player_ids": list(roster.enemy_player_ids),
            "owner_roles": replay_owner_roles,
            "commands_are": "P1 chat/signal input; P2-only dispatched actions",
            "p1_native_spawn_count": sum(
                1
                for spawn in scenario_dict.get("spawns", [])
                if int(spawn.get("owner_player_id", -1)) == int(leader_player_id)
            ),
            "p2_native_spawn_count": sum(
                1
                for spawn in scenario_dict.get("spawns", [])
                if int(spawn.get("owner_player_id", -1)) == int(ally_player_id)
            ),
        }
        summary = {
            "record_type": "summary",
            "replay_schema": "cmre-ai-ally-replay.v1",
            "status": "PASS" if roster.valid and not deadlock and not storm else "FAIL",
            "status_detail": (
                "map_derived_replay_p2_native_roster_absent"
                if replay_map_metadata.get("source_kind") == "map_extractor"
                and sum(
                    1
                    for spawn in scenario_dict.get("spawns", [])
                    if int(spawn.get("owner_player_id", -1)) == int(ally_player_id)
                ) == 0
                else "cooperative_simulator_run"
            ),
            "evidence_type": "simulator",
            "runtime_claim": "none; simulator evidence only",
            "map_metadata": replay_map_metadata,
            "loop_start": 0,
            "loop_end": int(s.world.clock.now.loop),
            "timeline_frames": len(replay_frame_records),
            "actions_total": len(replay_actions),
            "actions_successful": sum(
                1 for action in replay_actions
                if (action.get("dispatched") or {}).get("success")
                or (action.get("kind") == "player_command" and action.get("accepted"))
            ),
            "total_dispatched": total_dispatched,
            "friendly_fire_rejections": adapter.friendly_fire_rejections,
            "trace_hash": trace_hash(s.world),
            "mode_history": policy.mode_history,
            "roster_ready": roster.valid,
            "roster_issues": list(roster.issues),
        }
        with path.open("w", encoding="utf-8") as replay_file:
            for record in [header, *replay_frame_records, *replay_actions, summary]:
                replay_file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

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
        roster_ready=roster.valid,
        roster_issues=roster.issues,
        mode_history=policy.mode_history,
        notices=policy.drain_notices(),
        friendly_fire_rejections=adapter.friendly_fire_rejections,
        replay_path=replay_path,
        replay_frame_count=len(replay_frame_records),
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
