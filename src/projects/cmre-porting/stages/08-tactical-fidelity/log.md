# Stage 08 Log: 战术保真度 MVP —— 胜利时间框架 + Replay Simulation

> 开启时间：2026-08-01T00:00:00+08:00
> 状态：PASS_WITH_GAP（MVP 已验证；真实地图校准待地图解包目录）

## 1. 背景与目标

Stage 07 完成了 sc2_simulator 数值校准与性能修复，建立了确定性模拟基线。Stage 08 目标：
- **核心指标**：Victory Time（end_loop / 游戏秒数 / nights_survived）
- **核心能力**：Replay Simulation（给定初始场景 + 策略 → 确定性重放 → 对比胜利时间）
- **最小范围**：仅 Dead of Night Normal，仅现有 DefendBasePolicy，不新增技能/敌方 AI/升级系统

## 2. 实施进度

### 2.1 契约层（contracts.py）✅
- 新增 `VictoryTimeMetric` dataclass：`end_loop`、`game_time_sec`、`nights_survived`、`victory`、`end_reason`
- 提供 `from_mission_result`、`from_simulator_session` 两个工厂方法

### 2.2 任务引擎（mission_engine.py）✅
- `MissionResult` 新增 `game_time_sec`、`nights_survived`、`victory` 字段
- 新增 `from_engine(cls, eng)` classmethod，自动从 session 计算 nights_survived

### 2.3 战术消费者（tactical.py）✅
- `SingleRunMetrics`：新增 `game_time_sec`、`nights_survived`、`victory`
- `AggregatedMetrics`：新增 `avg_victory_time_sec`、`victory_time_p50_sec`、`victory_time_p90_sec`、`survival_rate`
- `TacticalReport`：新增 `victory_time_comparison` 字段
- `_run_single`：计算并返回胜利时间指标（利用 session._wave_timing）
- `_aggregate`：聚合胜利时间指标（平均/中位/90分位/生存率）
- `run_tactical_ab`：输出 `victory_time_comparison`（谁更快、差值多少）

### 2.4 Replay Simulation 核心（replay_simulation.py）✅
新建文件，实现：
- `replay_from_jsonl(jsonl_path, strategy, ...)`：从 JSONL 回放日志提取初始场景，注入策略重放
- `compare_strategies(scenario_dict, strategies, seeds, ...)`：并行跑多策略多种子，聚合胜利时间对比
- `run_victory_time_benchmark(scenario_dict, strategy, seeds, ...)`：单策略胜利时间基准测试（供 G8 闸门用）
- `VictoryTimeComparison`：多策略对比结果容器

### 2.5 SimulatorSession 扩展（simulator_session.py）✅
- 新增 `_wave_timing: Optional[dict]` 属性
- 新增 `set_wave_timing(wave_timing)` 公共方法

### 2.6 run_dead_of_night 集成（run_dead_of_night.py）✅
- `scenario_load` 后调用 `s.set_wave_timing(data.wave_timing)`

### 2.7 G8 闸门验证（gate_verification.py）✅
新增两个闸门测试函数并集成到 `p3_selftest`：
- `_g8_victory_time_test`：Dead of Night Normal，DefendBasePolicy，10 seeds → avg ∈ [630, 810]s，survival > 60%
- `_g8_replay_simulation_test`：同场景跑 FocusFire vs SpreadFire 3 seeds 产出 TacticalReport，并重复执行同一 seed 校验 trace/end_loop/victory_time 一致

### 2.8 额外运行时验证 ✅
- `replay_from_snapshot()`：从 session 快照恢复到克隆 world，结果 `end_loop=141`、`game_time_sec=6.2946`、`victory=true`
- `replay_from_jsonl()`：使用 `artifacts/dead_of_night_replay_20260731_071142.jsonl` 完成回放注入烟测，`end_loop=100`、`game_time_sec=4.4643`、`victory=false`
- 真实地图提取：项目内 `packages/Maps/亡者之夜.SC2Map` 成功提取 `1339` 个 spawns、`6` 个夜晚，只有 `5` 个装饰/放置点对象未映射
- 真实地图首夜战术：`time_scale=0.1, max_loops=1100`，`waves=4`、`nights_survived=1`、`p1_survivors=32`、`commands_dispatched=1522/1522`、`duration_sec=1.96`
- 真实地图完整六夜快速基准：`--mvp-fast`，`time_scale=0.02, max_loops=1400`，`waves=24`、`nights_survived=6`、`p1_survivors=14`、`commands_dispatched=1724`、`duration_sec=11.69`；满足一分钟预算
- `--mvp-fast` 默认关闭预放置敌军，固定 55 秒 wall-clock 保护；预算耗尽返回 `inconclusive`
- 最终三 seed 单策略基准：`seed=1/2/3`，各 `1280 loops`、`24 waves`、`6 nights`，玩家存活 `33/32/34`，总耗时 `13.0s`
- `uv run --extra test python -m pytest tests/sc2_simulator -q`：完整测试通过
- `python -m py_compile ...`：Stage 08 修改模块编译通过
- 新增 `victory_time_comparison.py`，提供 `run_strategy_seeds()` 对比入口

## 3. 遗留问题

| 问题 ID | 严重度 | 状态 | 说明 |
|---------|--------|------|------|
| PERF-003 | medium | open | 10 seeds × 15000 loops 串行耗时较长，需并行化或缩减 max_loops |
| MAP-RUNTIME-001 | low | open | 默认 cmre-runtime 目录缺失已通过项目内地图 fallback 解决；多策略 A/B 基准待补 |

## 4. 待验证

- [x] 运行 `python -m src.projects.cmre-porting.vibe.gate_verification` 验证 G1-G8 闸门通过
- [x] 运行 `uv run --extra test python -m pytest tests/sc2_simulator -q` 验证 simulator 回归
- [x] 运行 py_compile 验证 Stage 08 修改模块
- [x] 使用项目内地图包完成真实首夜压缩战术 smoke
- [x] 使用 `--mvp-fast` 在一分钟内完成真实地图完整六夜 smoke
- [ ] 完成真实地图多 seed、策略 A/B Victory Time 基准
- [x] 完成真实地图 6 夜、多 seed 单策略 Victory Time 基准
- [ ] 完成真实地图多策略 A/B Victory Time 基准

## 5. 变更文件清单

```
src/projects/cmre-porting/stages/08-tactical-fidelity/plan.md
src/projects/cmre-porting/stages/08-tactical-fidelity/result.json
src/projects/cmre-porting/stages/08-tactical-fidelity/issues.json
src/projects/cmre-porting/stages/08-tactical-fidelity/log.md
src/projects/cmre-porting/vibe/contracts.py
src/projects/cmre-porting/vibe/mission_engine.py
src/projects/cmre-porting/vibe/consumers/tactical.py
src/projects/cmre-porting/vibe/replay_simulation.py        # NEW
src/projects/cmre-porting/vibe/gate_verification.py        # 修改
src/projects/cmre-porting/vibe/simulator_session.py        # 修改
src/projects/cmre-porting/vibe/run_dead_of_night.py        # 修改
src/projects/cmre-porting/vibe/victory_time_comparison.py # NEW
```
