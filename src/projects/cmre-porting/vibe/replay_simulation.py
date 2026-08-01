"""Stage 08: Replay Simulation —— 从快照/JSONL 重放 + 策略注入。

核心能力：
- 给定初始快照 + Strategy 插件 → 确定性重放 → 输出 VictoryTimeMetric
- 给定 JSONL 回放日志 + Strategy → 提取初始场景 → 重放
- 多策略并行对比 → 产出 TacticalReport（含胜利时间对比）
"""

from __future__ import annotations

import json
import statistics
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .contracts import Observation, VictoryTimeMetric
from .sim_path import ensure_simulator_on_path
from .consumers.tactical import (
    Strategy,
    TacticalAction,
    SingleRunMetrics,
    AggregatedMetrics,
    TacticalReport,
    _run_single,
    _aggregate,
    run_tactical_ab,
)

ensure_simulator_on_path()

from sc2_simulator.reporting.trace import trace_hash  # noqa: E402
from sc2_simulator.world.snapshot import clone_world  # noqa: E402

from .simulator_session import SimulatorSession


@dataclass
class ReplaySimulationResult:
    """单次重放结果。"""

    scenario_name: str
    strategy_name: str
    seed: int
    victory_metric: VictoryTimeMetric
    trace_hash: str
    decision_count: int
    total_damage_dealt: float
    enemies_killed: int
    friendlies_lost: int


def replay_from_snapshot(
    snapshot_hash: str,
    strategy: Strategy,
    max_loops: int = 15000,
    ally_player_id: int = 1,
    cmd_interval: int = 8,
    session: Optional[SimulatorSession] = None,
) -> ReplaySimulationResult:
    """从已注册快照恢复并运行策略，不修改原始 session。

    ``snapshot_hash`` 必须来自 ``session.snapshot_create()``。快照只保存
    world 状态，因此调用方需要提供仍持有该快照的 session；克隆 session
    保留同一个场景和 catalog，再把快照恢复到克隆 world 上。
    """
    if session is None or session.world is None or session.scenario is None:
        raise ValueError("replay_from_snapshot 需要已加载场景的 session")

    snapshot = next(
        (
            handle
            for handle in session._snapshots.values()
            if handle.hash == snapshot_hash
        ),
        None,
    )
    if snapshot is None:
        raise ValueError(f"session 中不存在快照: {snapshot_hash}")

    replay_session = SimulatorSession()
    replay_session.scenario = session.scenario
    replay_session.catalog = session.catalog
    replay_session._wave_timing = session._wave_timing
    replay_session.world = clone_world(session.world)
    replay_session.world.restore_into(snapshot.data)
    replay_session.terminated = False
    replay_session.paused = False

    result = _run_single_with_strategy(
        scenario_dict={},
        strategy=strategy,
        seed=session.scenario.definition.seed,
        max_loops=max_loops,
        ally_player_id=ally_player_id,
        cmd_interval=cmd_interval,
        session=replay_session,
    )
    return _replay_result_from_metrics(
        result,
        scenario_name=session.scenario.definition.name,
        strategy_name=strategy.name,
        seed=session.scenario.definition.seed,
    )


def replay_from_jsonl(
    jsonl_path: Path,
    strategy: Strategy,
    max_loops: int = 15000,
    ally_player_id: int = 1,
    cmd_interval: int = 8,
    seed: int = 42,
) -> ReplaySimulationResult:
    """从 JSONL 回放日志提取初始场景，注入策略重放。

    1. 读取 JSONL 第 0 帧 → 构造 scenario_dict
    2. 修改 seed（可选）
    3. 跑 _run_single 逻辑，但策略替换为传入的 strategy
    """
    frames = _load_jsonl_frames(jsonl_path)
    if not frames:
        raise ValueError(f"JSONL 为空: {jsonl_path}")

    first_frame = frames[0]
    scenario_dict = _frame_to_scenario_dict(first_frame, jsonl_path.stem)
    scenario_dict["seed"] = seed
    scenario_dict["max_loops"] = max_loops

    # 复用 session runner 但替换策略决策
    result = _run_single_with_strategy(
        scenario_dict=scenario_dict,
        strategy=strategy,
        seed=seed,
        ally_player_id=ally_player_id,
        max_loops=max_loops,
        cmd_interval=cmd_interval,
    )

    return _replay_result_from_metrics(
        result,
        scenario_name=scenario_dict.get("name", jsonl_path.stem),
        strategy_name=strategy.name,
        seed=seed,
    )


def _replay_result_from_metrics(
    result: SingleRunMetrics,
    scenario_name: str,
    strategy_name: str,
    seed: int,
) -> ReplaySimulationResult:
    return ReplaySimulationResult(
        scenario_name=scenario_name,
        strategy_name=strategy_name,
        seed=seed,
        victory_metric=VictoryTimeMetric(
            end_loop=result.end_loop,
            game_time_sec=result.game_time_sec,
            nights_survived=result.nights_survived,
            victory=result.victory,
            end_reason=result.end_reason,
        ),
        trace_hash=result.trace_hash,
        decision_count=result.decision_count,
        total_damage_dealt=result.total_damage_dealt,
        enemies_killed=result.enemies_killed,
        friendlies_lost=result.friendlies_lost,
    )


def _load_jsonl_frames(jsonl_path: Path) -> list[dict]:
    frames = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                frames.append(json.loads(line))
    return frames


def _frame_to_scenario_dict(frame: dict, name: str) -> dict:
    """从 JSONL 第一帧构造 scenario_dict（简化版，仅提取 spawns）。"""
    spawns = []
    for pid_str, ents in frame.get("entities_by_player", {}).items():
        pid = int(pid_str)
        for e in ents:
            if e.get("alive", True):
                spawns.append(
                    {
                        "unit_type_id": e.get("t", "Marine"),
                        "owner_player_id": pid,
                        "x": e.get("x", 0.0),
                        "y": e.get("y", 0.0),
                    }
                )

    # 推断玩家列表
    player_ids = set()
    for pid_str in frame.get("entities_by_player", {}).keys():
        player_ids.add(int(pid_str))
    players = []
    for pid in sorted(player_ids):
        players.append(
            {
                "id": pid,
                "name": f"Player{pid}",
                "race": "terran",
                "allies": [],
                "is_ai": True,
            }
        )

    return {
        "schema_version": "m7",
        "name": name,
        "players": players,
        "spawns": spawns,
        "commands": [],
        "max_loops": 15000,
        "seed": 42,
        "strict": False,
        "win_condition": "annihilation",
    }


def _run_single_with_strategy(
    scenario_dict: dict,
    strategy: Strategy,
    seed: int,
    ally_player_id: int = 1,
    max_loops: int = 1000,
    cmd_interval: int = 8,
    session: Optional[SimulatorSession] = None,
) -> SingleRunMetrics:
    """_run_single 的变体：使用传入的 strategy 而非硬编码。"""
    if session is None:
        sc = dict(scenario_dict)
        sc["seed"] = seed
        s = SimulatorSession()
        s.scenario_load(scenario_dict=sc, catalog="m7")
        s.scenario_reset()
    else:
        s = session

    decisions_made = 0
    initial_friendlies = len(
        [
            e
            for e in s.world.entities.values()
            if e.owner_player_id == ally_player_id and e.is_alive
        ]
    )
    initial_enemies = len(
        [
            e
            for e in s.world.entities.values()
            if e.owner_player_id != ally_player_id and e.is_alive
        ]
    )
    initial_enemy_hp = sum(
        e.health.raw
        for e in s.world.entities.values()
        if e.owner_player_id != ally_player_id and e.is_alive
    )

    last_decide = -10_000
    last_actions: list[TacticalAction] = []
    issued_this_loop: dict[int, set[int]] = {}

    while not s.terminated and s.world.clock.now.loop < max_loops:
        loop = s.world.clock.now.loop
        if loop - last_decide >= cmd_interval:
            obs = Observation.from_world(s.world, ally_player_id)
            last_actions = strategy.decide(obs, loop)
            last_decide = loop
            decisions_made += 1

        issued_set = issued_this_loop.setdefault(loop, set())
        for a in last_actions:
            if a.entity_id in issued_set:
                continue
            if a.kind == "attack" and a.target_entity_id:
                s.unit_order(
                    [a.entity_id],
                    "attack_unit",
                    issuer_player_id=ally_player_id,
                    target_entity_id=a.target_entity_id,
                )
            elif a.kind == "move" and a.target_x != 0.0 and a.target_y != 0.0:
                s.unit_order(
                    [a.entity_id],
                    "move",
                    issuer_player_id=ally_player_id,
                    target_x=a.target_x,
                    target_y=a.target_y,
                )
            elif a.kind == "ability" and a.target_entity_id:
                s.unit_order(
                    [a.entity_id],
                    "cast_unit",
                    issuer_player_id=ally_player_id,
                    target_entity_id=a.target_entity_id,
                    ability_id=a.ability_id,
                )
            issued_set.add(a.entity_id)

        s.scenario_step(1, snapshot=False)

    final_friendlies = [
        e
        for e in s.world.entities.values()
        if e.owner_player_id == ally_player_id and e.is_alive
    ]
    final_enemies = [
        e
        for e in s.world.entities.values()
        if e.owner_player_id != ally_player_id and e.is_alive
    ]
    final_enemy_hp = sum(e.health.raw for e in final_enemies)

    friendlies_lost = initial_friendlies - len(final_friendlies)
    enemies_killed = initial_enemies - len(final_enemies)
    total_dmg = max(0.0, initial_enemy_hp - final_enemy_hp)

    alive = {e.owner_player_id for e in s.world.entities.values() if e.is_alive}
    winner = next(iter(alive)) if len(alive) == 1 else None

    end_loop = s.world.clock.now.loop
    end_reason = getattr(s, "end_reason", "") or "max_loops_reached"
    nights_survived = 0
    if s._wave_timing:
        for night in s._wave_timing.get("nights", []):
            if end_loop >= night.get("end_loop", 0):
                nights_survived += 1
    victory = (winner == ally_player_id) or (
        s.terminated
        and end_reason
        in (
            "all_objectives_success",
            "survive_loops",
            "max_loops_reached",
        )
    )

    return SingleRunMetrics(
        end_loop=end_loop,
        end_reason=end_reason,
        winner=winner,
        survivors={
            pid: sum(1 for e in final_friendlies if e.owner_player_id == pid)
            for pid in {1, 2}
        },
        enemies_killed=enemies_killed,
        friendlies_lost=friendlies_lost,
        total_damage_dealt=total_dmg,
        trace_hash=trace_hash(s.world),
        decision_count=decisions_made,
        game_time_sec=end_loop / 22.4,
        nights_survived=nights_survived,
        victory=victory,
    )


# ---------------------------------------------------------------------------
# 多策略并行对比（进程级并行，避免 GIL）
# ---------------------------------------------------------------------------


@dataclass
class VictoryTimeComparison:
    """多策略胜利时间对比结果。"""

    scenario_name: str
    strategy_results: dict[str, AggregatedMetrics] = field(default_factory=dict)
    fastest_strategy: str = ""
    slowest_strategy: str = ""
    delta_fastest_slowest_sec: float = 0.0
    survival_rates: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "scenario_name": self.scenario_name,
            "strategy_results": {
                k: {
                    "strategy_name": v.strategy_name,
                    "seed_count": v.seed_count,
                    "win_rate": v.win_rate,
                    "survival_rate": v.survival_rate,
                    "avg_victory_time_sec": v.avg_victory_time_sec,
                    "victory_time_p50_sec": v.victory_time_p50_sec,
                    "victory_time_p90_sec": v.victory_time_p90_sec,
                    "avg_exchange_ratio": v.avg_exchange_ratio,
                    "avg_end_loop": v.avg_end_loop,
                }
                for k, v in self.strategy_results.items()
            },
            "fastest_strategy": self.fastest_strategy,
            "slowest_strategy": self.slowest_strategy,
            "delta_fastest_slowest_sec": self.delta_fastest_slowest_sec,
            "survival_rates": self.survival_rates,
        }


def compare_strategies(
    scenario_dict: dict,
    strategies: list[Strategy],
    seeds: list[int],
    ally_player_id: int = 1,
    max_loops: int = 15000,
    max_workers: int = 4,
) -> VictoryTimeComparison:
    """并行跑多策略多种子，聚合胜利时间指标对比。"""
    # 串行跑（避免进程间 pickling 复杂度，种子数少时足够快）
    results = {}
    for strat in strategies:
        agg = _aggregate(strat, scenario_dict, seeds, ally_player_id, max_loops)
        results[strat.name] = agg

    # 找最快/最慢（仅对比有胜利的策略）
    valid = {k: v for k, v in results.items() if v.avg_victory_time_sec > 0}
    if valid:
        fastest = min(valid.items(), key=lambda kv: kv[1].avg_victory_time_sec)
        slowest = max(valid.items(), key=lambda kv: kv[1].avg_victory_time_sec)
        fastest_name = fastest[0]
        slowest_name = slowest[0]
        delta = slowest[1].avg_victory_time_sec - fastest[1].avg_victory_time_sec
    else:
        fastest_name = ""
        slowest_name = ""
        delta = 0.0

    survival_rates = {k: v.survival_rate for k, v in results.items()}

    return VictoryTimeComparison(
        scenario_name=scenario_dict.get("name", "unnamed"),
        strategy_results=results,
        fastest_strategy=fastest_name,
        slowest_strategy=slowest_name,
        delta_fastest_slowest_sec=delta,
        survival_rates=survival_rates,
    )


def run_victory_time_benchmark(
    scenario_dict: dict,
    strategy: Strategy,
    seeds: list[int],
    ally_player_id: int = 1,
    max_loops: int = 15000,
) -> AggregatedMetrics:
    """单策略胜利时间基准测试（用于 G8-victory-time 闸门）。"""
    return _aggregate(strategy, scenario_dict, seeds, ally_player_id, max_loops)
