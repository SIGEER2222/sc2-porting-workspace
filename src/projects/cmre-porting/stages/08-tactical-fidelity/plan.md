# Stage Plan: 战术保真度 MVP —— 胜利时间框架 + Replay Simulation

> **目标**：最小可行交付，核心指标 **Victory Time**（end_loop / 游戏秒数），支持 Replay Simulation 与多策略 A/B 对比。

## 1. 范围与约束

- **仅 Dead of Night Normal** 地图；真实地图默认使用项目内 `packages/Maps/亡者之夜.SC2Map`
- **仅现有 DefendBasePolicy** 策略（不新增技能、不重写敌方 AI、不做升级系统）
- **复用现有代码**：map_extractor、mission_engine、simulator_session、tactical、replay_generator/player
- **新增最小接口**：标准化胜利时间字段、从快照/JSONL 重放、多策略并行对比

## 2. 交付物

| 产出 | 文件 | 说明 |
|------|------|------|
| 胜利时间标准化字段 | `vibe/contracts.py`、`vibe/consumers/tactical.py`、`vibe/mission_engine.py` | `end_loop`、`game_time_sec`、`nights_survived`、`victory: bool` |
| Replay Simulation 入口 | `vibe/replay_simulation.py` | `replay_from_snapshot()`、`replay_from_jsonl()`、`compare_strategies()` |
| 多策略胜利时间对比 | `vibe/victory_time_comparison.py`、`vibe/replay_simulation.py` | 多策略 seeds → 统计聚合 → 报告 |
| 闸门验证 | `vibe/gate_verification.py` 新增 G8-victory-time、G8-replay-sim | 自动化验证 |

## 3. 实施步骤

### 3.1 标准化胜利时间字段（contracts.py + tactical.py + mission_engine.py）
- `Observation` / `MissionResult` / `TacticalReport` / `SingleRunMetrics` 增加：
  - `end_loop: int`
  - `game_time_sec: float` (= end_loop / 22.4)
  - `nights_survived: int`
  - `victory: bool` (player1_survivors > 0 且 terminated)
- `TacticalReport` 新增聚合字段：
  - `avg_victory_time_sec: float`
  - `victory_time_p50_sec: float`
  - `victory_time_p90_sec: float`
  - `survival_rate: float`

### 3.2 Replay Simulation 核心（replay_simulation.py）
```python
def replay_from_snapshot(snapshot_hash: str, strategy: Strategy, max_loops: int) -> TacticalReport
def replay_from_jsonl(jsonl_path: Path, strategy: Strategy, max_loops: int) -> TacticalReport
def compare_strategies(scenario_dict: dict, strategies: list[Strategy], seeds: list[int]) -> VictoryTimeComparison
```
- 复用 `SimulatorSession.scenario_load` + `scenario_reset` + `scenario_step(snapshot=False)`
- 从 JSONL 取初始帧构造 scenario_dict（复用 map_extractor 逻辑）
- 策略注入：每 N loops（默认 8）调用 `strategy.decide(obs)` → `unit_order`

### 3.3 多策略并行对比（victory_time_comparison.py）
- `run_strategy_seeds(strategy, scenario_dict, seeds, max_loops) -> AggregatedMetrics`
- 并行（ProcessPoolExecutor）跑多策略
- 输出 `VictoryTimeComparison`：策略名、胜率、平均/中位/90分位胜利时间、生存率、换损比

### 3.4 闸门验证（gate_verification.py）
- **G8-victory-time**：合成 fallback 验证指标链路；真实地图使用 `--mvp-fast` 在一分钟内完成六夜 smoke，后续再跑多 seed/A-B 基准
- **G8-replay-sim**：同一场景、策略和 seed 重复运行 → trace_hash、end_loop、victory_time 完全一致；同时产出多策略可比较报告

## 4. writeScope

```
src/projects/cmre-porting/stages/08-tactical-fidelity/**
src/projects/cmre-porting/vibe/contracts.py
src/projects/cmre-porting/vibe/consumers/tactical.py
src/projects/cmre-porting/vibe/mission_engine.py
src/projects/cmre-porting/vibe/replay_simulation.py        # NEW
src/projects/cmre-porting/vibe/victory_time_comparison.py   # NEW
src/projects/cmre-porting/vibe/gate_verification.py         # 修改：新增 G8 闸门
```

## 5. 验收标准

| 闸门 | 通过标准 |
|------|----------|
| G8-victory-time | 合成 fallback 10 seeds 指标通过；真实地图 `--mvp-fast` 六夜在 60s 内完成 |
| G8-replay-sim | 同一输入重复运行结果一致，并输出多策略 TacticalReport |
| 回归 | P1-P9 12/12 PASS，sc2_simulator tests 全过 |

## 6. 非目标

- ❌ 新增技能/敌方 AI/升级系统
- ❌ 多地图支持
- ❌ 真机 .SC2Replay 解析
- ❌ 可视化渲染
