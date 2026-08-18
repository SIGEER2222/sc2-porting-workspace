# Ares-SC2 战术决策层集成说明

> 目的：把本地 `E:/Code/sc2-rts-reference/ares-sc2` 作为 SC2 模拟器宏观战术验证层的参考，而不是作为底层规则保真来源。
>
> 结论：Ares-SC2 对 Stage50 最有价值的部分是 **战术决策抽象、行为组合、角色/编队管理、路径/影响力网格、build runner 与 combat result 分级**。这些可以帮助我们设计模拟器的 AI policy / Observation / Action / report schema。

## 1. 为什么 Ares-SC2 有帮助

Ares-SC2 的定位与当前模拟器路线高度一致：

- 它强调让用户掌控战略决策，而不是替用户做固定策略选择。
- 它有 `ManagerMediator`，可作为统一信息查询/动作请求接口参考。
- 它有 `MacroPlan` / `CombatManeuver`，可作为高层行为组合模型参考。
- 它有 `UnitRole` / `SquadManager`，可作为模拟器中“AI 意图”和“战术分工”的标签体系参考。
- 它有 `BuildOrderRunner`，可作为 build order / timing push 脚本化策略参考。
- 它有 `EngagementResult` 与 `can_win_fight`，可作为战斗结果分级与战术报告指标参考。

这正好补上当前 Stage50 路线图里的核心缺口：

```text
Observation -> AI Policy -> Action -> Tactical Report
```

Ares-SC2 不是要直接塞进模拟器底层，而是用来设计：

```text
模拟器战术层 API
模拟器策略行为组合方式
模拟器战术报告字段
模拟器 CI regression benchmark
```

## 2. 建议复用的 Ares 概念

### 2.1 Mediator Pattern

Ares 的 `ManagerMediator` 通过 `self.mediator` 暴露战术查询，例如：

- ground / air grid
- path next point
- units in range
- worker selection
- role assignment
- combat sim result
- enemy/own cached army
- expansion positions

模拟器可借鉴为：

```text
TacticalMediator
  get_observation_summary()
  get_units_by_role(role)
  get_threats_near_objective(objective_id)
  get_path_cost(start, target, layer)
  can_win_engagement(own_group, enemy_group)
  assign_role(entity_ids, role)
  issue_group_action(group_id, action)
```

不要一开始复制 Ares 全部 API；先抽最小战术接口。

### 2.2 Behavior / MacroPlan / CombatManeuver

Ares 的行为模型是：

```text
Behavior.execute(ai, config, mediator) -> bool
MacroPlan: 按优先级执行 macro behaviors
CombatManeuver: 顺序执行 combat behaviors
```

模拟器可借鉴为：

```text
TacticalBehavior.evaluate(observation, mediator) -> Action | None
TacticalPlan: 多个 behavior 按优先级评估
CombatManeuverPlan: 组合 move / attack / regroup / retreat / focus 等动作
```

这比硬编码 if/else 策略更适合 A/B 测试。

### 2.3 UnitRole

Ares 的 `UnitRole` 很适合转成模拟器战术标签，例如：

- `ATTACKING`
- `ATTACKING_MAIN_SQUAD`
- `BASE_DEFENDER`
- `DEFENDING`
- `HARASSING`
- `MAP_CONTROL`
- `SCOUTING`
- `GATHERING`
- `REPAIRING`
- `CONTROL_GROUP_*`

模拟器不需要完整照搬，但 MVP 应至少有：

```text
GATHERING
SCOUTING
MAIN_ARMY
DEFENDING
ATTACKING
HARASSING
MAP_CONTROL
IDLE
```

这些角色能让失败标签更有解释性：

```text
EXECUTION_IDLE_ARMY
TACTIC_INSUFFICIENT_DEFENSE
TACTIC_BAD_ATTACK_TIMING
TACTIC_NO_MAP_CONTROL
```

### 2.4 EngagementResult

Ares 的结果分级：

```text
VICTORY_EMPHATIC
VICTORY_OVERWHELMING
VICTORY_DECISIVE
VICTORY_CLOSE
VICTORY_MARGINAL
TIE
LOSS_MARGINAL
LOSS_CLOSE
LOSS_DECISIVE
LOSS_OVERWHELMING
LOSS_EMPHATIC
```

这非常适合作为模拟器战术报告中的 `engagement_outcome` 字段。

建议放进 `tactical_report.v1`：

```json
{
  "engagement_outcome": "VICTORY_DECISIVE",
  "objective_completed": true,
  "completion_loop": 4200,
  "loss_exchange_ratio": 1.8,
  "confidence": "medium"
}
```

### 2.5 Build Runner

Ares 的 build runner / build order parser 可以启发 timing push 策略描述。

模拟器 MVP 可以先定义简化格式：

```yaml
strategy_id: timing_push_aggressive
steps:
  - at: 0
    action: train_workers
  - at: 900
    action: tech_to
    target: barracks
  - at: 1800
    action: assemble_army
  - at: 2400
    action: attack_objective
    target: enemy_wave_spawn
```

这不要求模拟器完整生产细节保真，只要求策略能驱动战术实验。

## 3. 不建议直接复用的部分

短期不要直接绑定：

- `python-sc2` runtime 对象
- SC2 实机 API loop
- Ares 的所有 manager 实现
- cython 扩展细节
- sc2_helper combat sim 的内部结果作为唯一真相

原因：当前目标是模拟器战术层，而不是运行真实 SC2 bot。

应采用：

```text
借鉴接口与概念 -> 在模拟器里定义轻量版本 -> 后续可选 adapter 到 Ares/python-sc2
```

## 4. 对 Stage50 路线图的影响

原路线图里下一步是：

```text
Tactical Report Schema
Experiment Runner MVP
Observation / Action Interface
Timing Push Golden Scenario
CI Regression Gate
```

加入 Ares-SC2 后，建议调整为：

### Stage50A：Ares-Inspired Tactical Interface

产出：

- `TacticalObservation`
- `TacticalAction`
- `TacticalMediator`
- `TacticalBehavior`
- `TacticalPlan`
- `UnitRole` 最小集合
- `EngagementOutcome` 分级

### Stage50B：Tactical Report Schema

产出：

- `tactical_report.v1`
- 时间序列
- strategy id
- role distribution
- engagement outcome
- objective completion
- confidence / reliability
- failure tags

### Stage50C：Experiment Runner MVP

产出：

- `run`
- `batch`
- `sweep`
- A/B 作为 sweep 特例
- JSON + Markdown artifacts

### Stage50D：Timing Push Golden Scenario

产出：

- aggressive timing push policy
- delayed/defensive baseline policy
- fixed enemy wave script
- completion-time comparison
- regression threshold

### Stage50E：CI Regression Gate

产出：

- fixed tactical benchmark suite
- stable output report
- threshold diff
- confidence downgrade on unsupported mechanics

## 5. MVP 实现建议

第一步不要改底层 simulator rule engine。

先新增 project-local tactical layer：

```text
src/projects/cmre-porting/vibe/tactics/
  __init__.py
  roles.py
  outcomes.py
  observation.py
  actions.py
  mediator.py
  behavior.py
  report.py
  runner.py
  policies.py
```

优先实现：

1. `UnitRole` 最小枚举
2. `EngagementOutcome` 分级
3. `TacticalAction`：attack_objective / defend_objective / regroup / expand / tech / wait
4. `TacticalReport` schema
5. `ScriptedTimingPushPolicy`
6. `ScriptedDefensiveBaselinePolicy`
7. 一个 fixed-wave timing push scenario
8. focused tests 验证 stable report

## 6. 与历史计划评审的一致性

历史上下文也支持这个方向：

- 模拟器适合测试 AI 指令、策略和优先级回归。
- 经济、建造、生产与补给可以逐步覆盖。
- 底层生命、护甲、攻速、范围伤害、技能、Buff 等细节当前不是宏观战术 MVP 的核心。
- 寻路、碰撞、目标选择、地图触发器等微观/实机细节不应阻塞战术验证层推进。

因此 Stage50 应避免再次滑回“SC2 细节保真”路线。

## 7. 一句话结论

> Ares-SC2 最大价值不是给我们一个更准确的 SC2 模拟器，而是给我们一套成熟的 bot 战术决策词汇表：Mediator、Behavior、MacroPlan、CombatManeuver、UnitRole、EngagementResult。Stage50 应先把这些抽象转成模拟器自己的战术实验接口。

## 8. 与 M7 能力矩阵的关系

历史 M7 能力矩阵说明：99 个 Catalog 单位已经按创建、生产、命令、战斗、死亡五类能力记录机器可读覆盖度，并且运行报告会按 `unit.<id>.<capability>` 标记实际触发状态。

Stage50 应把这类能力矩阵作为战术报告的可信度输入，而不是把所有底层能力缺口都当作战术验证阻塞项：

```text
M7 capability matrix
  -> capability_coverage
  -> unsupported_mechanics / approximated_mechanics
  -> confidence / reliability downgrade
```

推荐关系：

```text
Ares-SC2 concepts -> 战术决策接口与策略组合
M7 capability matrix -> 机制覆盖度与可信度标注
CMRE simulator session -> 可执行 world / event / scenario backend
Tactical report -> CI regression 与 AI 策略评估输出
```

这能避免两种偏差：

- 不把 Ares 当成底层模拟器实现来源。
- 不把微观能力缺口当成宏观战术验证的全部阻塞项。

## 9. Qdrant 来源对齐

本节吸收了两份历史材料的结论：

- `sc2模拟器计划评审.md`：当前模拟器路线适合测试 AI 指令、策略和优先级回归；经济、建造、生产与补给可逐步覆盖；生命、护甲、攻速、射程、范围伤害、技能、Buff、升级、维修、寻路、碰撞、目标选择、地图触发器等不应作为宏观战术 MVP 的前置条件。
- `sc2模拟器m7能力矩阵.md`：99 个 Catalog 单位已有创建、生产、命令、战斗、死亡五类机器可读能力矩阵，运行报告会按 `unit.<id>.<capability>` 标记本次实际触发状态。

因此 Stage50 的技术决策是：Ares-SC2 提供战术决策词汇和接口形态，M7 能力矩阵提供覆盖度与可信度输入，CMRE simulator backend 负责实际运行场景。

