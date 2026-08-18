# SC2 模拟器宏观战术验证路线图

> 来源：`sc2-simulator-macro-tactics-questionnaire-20260818.md` 的用户回答。
>
> 核心结论：当前模拟器不应围绕帧级保真或 SC2 实机校准展开；它应定位为 **PvE AI 战术评估沙盘 / CI 回归验证器**，重点回答 AI 策略是否有效、完成时间是否更优、不同 AI 策略之间谁更适合任务场景。

## 1. 产品定位

### 主定位

模拟器的核心目标是验证 **AI 决策质量**，尤其是 PvE / 合作任务中的宏观战术表现。

优先服务对象：

1. **CI regression 防退化**
2. AI agent 策略评估
3. 后续才是人类调参/读报告

当前不把重点放在：

- SC2 实机校准
- 帧级战斗保真
- 弹道、动画、武器 backswing 等微观细节
- 完整复刻 SC2 engine

## 2. 成功标准

### 主要判断指标

第一优先指标：

- **完成时间 / 清图时间**

同时报告应保留完整指标集合：

- 胜负 / 任务完成
- 完成时间
- 资源曲线
- 单位损失
- 损失交换比
- DPS / 承伤
- 扩张时机
- 科技完成时间
- 失败原因标签

### 当前阶段失败解释深度

用户当前选择：暂时只要胜负和指标，不要求自动生成完整“为什么失败”的自然语言结论。

因此 MVP 中：

- 必须输出结构化指标
- 可以输出失败标签
- 不要求自动写复杂战术建议

## 3. 场景模型

### 场景关注方向

优先 PvE / 合作任务。

场景组织方式：

- 按敌人
- 按波次
- 按任务目标

场景时间尺度采用三层：

1. **单次事件**：一次进攻、防守、护送、守点、清营地
2. **战术窗口**：5-10 分钟局部战术区间
3. **完整对局**：端到端任务验证

MVP 可以先做事件与战术窗口，完整对局作为后续扩展。

### 场景来源

优先从 **地图 / 任务定义抽取** 初始状态，而不是完全手写。

但为了快速落地，建议采用两阶段：

1. 手写最小 tactical scenario，验证 runner / report / CI 链路
2. 再从地图/任务定义抽取波次、目标、敌人配置

### 敌方策略

MVP 中敌人只需要固定波次 / 固定行为，不需要复杂敌方 AI。

## 4. AI 接口

### Observation / Action 抽象

要求：同一套 AI 必须能接模拟器 Observation/Action 接口，并为未来真实 SC2 接口保留适配空间。

这意味着应尽早定义统一接口：

```text
Observation -> AI Policy -> Action
```

Observation 应可配置信息层级：

- 完整全图信息
- 玩家视野信息
- 抽象战术状态

Action 应支持三层粒度：

1. 高层战术意图：expand / attack / defend / tech / regroup
2. 中层编队目标：army_group attack area / defend point / escort unit
3. 低层单位命令：move / attack / build / cast

MVP 建议先支持高层与中层，低层命令保持 adapter 能力即可。

## 5. 实验框架

### A/B 测试

A/B 测试是核心功能。

优先比较对象：

- 不同 AI 策略

典型问题：

```text
同一场景下，AI 策略 A 是否比 AI 策略 B 更快完成目标？
```

### Sweep

参数 sweep 是必需功能。

优先 sweep 参数：

- 敌人数量
- 敌人出现时间
- 资源倍率
- AI aggressiveness
- 波次强度
- 目标时间限制

### Compare

用户当前不要求独立 compare 功能作为 MVP。

建议处理方式：

- MVP 先做 `run` 和 `sweep`
- A/B 可以作为 sweep 的一种特殊维度
- 后续再独立做 `compare` 报告

## 6. 报告设计

### 报告受众

报告同时服务：

- 结构化 JSON：给 AI / CI 使用
- Markdown / 图表：给人类快速读

### 必须输出时间序列

每次战术实验应输出时间序列：

- 资源
- 人口
- 军力
- 单位损失
- 地图控制 / 目标进度
- 关键事件

### 可信度

每个报告必须输出 confidence / reliability。

unsupported 或近似机制必须显式降级。

建议字段：

```json
{
  "confidence": "high|medium|low",
  "unsupported_mechanics": [],
  "approximated_mechanics": [],
  "result_reliability": "usable|degraded|not_reliable"
}
```

## 7. 近似与不可近似边界

### 可以近似

用户允许所有机制近似，但必须标注。

包括：

- 地图距离 / 路径
- 战斗细节
- 经济采集曲线
- 技能效果
- 敌方 AI

### 不能近似

用户明确选择：

- **任务目标完成** 不能近似

建议扩展为硬约束：

- 任务目标完成必须准确记录
- 完成时间必须准确记录
- A/B 比较时必须使用同一近似等级，避免不公平比较

## 8. MVP 范围

### MVP 完成标准

用户选择：

- 能跑固定场景并输出稳定报告

因此 MVP 不要求一开始就做到：

- 自动解释失败
- 自动改策略
- 完整 compare UI
- 完整地图抽取
- 完整多 race / 多 commander 覆盖

### 推荐 MVP Golden Scenarios

用户未填写第 29 题，结合其他答案，建议 MVP 先选这些：

1. **Timing Push 有效性测试**
   - 这是用户第 32 题明确选择的首个宏观战术。
   - 指标：完成时间、损失交换比、目标完成率、失败标签。

2. **防守固定第一波 / 第二波**
   - PvE 合作任务最常见验证场景。
   - 指标：是否 hold、损失、剩余军力、恢复时间。

3. **AI Ally 协同进攻**
   - 对应核心目标：AI 决策质量。
   - 指标：集结延迟、进攻同步率、目标完成时间、无效移动次数。

4. **经济扩张窗口**
   - 不是当前首选，但对完成时间影响大。
   - 指标：扩张时机、资源曲线、军力真空期。

## 9. 下一阶段优先级

用户第 31 题选择：

- 战术报告与失败解释

但第 5 / 16 题又表示暂时不需要完整失败解释和自动战术结论。

因此解释为：

> 下一阶段应先做“结构化战术报告与失败标签”，而不是自然语言教练式分析。

推荐 Stage50 后续拆解：

### Stage50A：Tactical Report Schema

产出：

- `tactical_report.v1` schema
- run summary
- time series
- metrics
- confidence / reliability
- failure tags

### Stage50B：Experiment Runner MVP

产出：

- `run_scenario`
- `run_batch`
- `sweep`
- deterministic output directory
- JSON + Markdown report

### Stage50C：Observation / Action Interface

产出：

- Observation schema
- Action schema
- AI policy adapter interface
- dummy AI / scripted policy

### Stage50D：Timing Push Golden Scenario

产出：

- 首个 MVP tactical scenario
- 两个 AI 策略 A/B
- 完成时间对比
- reliability 标注

### Stage50E：CI Regression Gate

产出：

- 固定场景稳定运行
- 指标阈值
- regression diff
- artifacts 可复现

## 10. 失败标签体系初稿

AI 输掉时，用户最关心：

- 战术选择错误
- 模拟器能力不足

建议 MVP failure tags：

```text
TACTIC_BAD_TIMING
TACTIC_UNSUITABLE_TARGET
TACTIC_INSUFFICIENT_ARMY
TACTIC_ECONOMIC_DELAY
TACTIC_TECH_DELAY
TACTIC_POOR_GROUPING
EXECUTION_LATE_ATTACK
EXECUTION_IDLE_ARMY
EXECUTION_BAD_RETREAT
SCENARIO_UNSUPPORTED_MECHANIC
SIM_APPROXIMATION_LOW_CONFIDENCE
SIM_CAPABILITY_GAP
```

其中最重要的是区分：

```text
AI 策略确实不好
vs
模拟器能力不足，不能可信判断
```

## 11. 建议立即推进的实现任务

1. 定义 `tactical_report.v1` JSON schema。
2. 在 CMRE `vibe` 层新增 experiment runner，而不是先改底层规则。
3. 建立 timing-push MVP scenario。
4. 实现两个 scripted AI policy：
   - aggressive timing push
   - delayed / defensive baseline
5. 输出 run report：完成时间、任务目标、损失、资源时间序列、failure tags、confidence。
6. 加 focused tests，验证 report schema 和 stable output。
7. 再接入 sweep：敌人数量、波次时间、资源倍率。

## 12. 非目标

下一阶段不做：

- SC2 实机校准
- VM debugger / hook 推进
- 帧级战斗还原
- 自动生成完整自然语言战术建议
- 大规模 commander/race 全覆盖
- 复杂敌方 AI

## 13. 一句话方向

> 先把模拟器做成能稳定回答“这个 AI 战术在 PvE 场景里是否更快完成目标，并且结果有多可信”的实验框架；规则细节只服务于这个宏观问题，不反过来绑架路线。

## 14. Ares-SC2 与 M7 能力矩阵补充

本地 `E:/Code/sc2-rts-reference/ares-sc2` 应作为战术决策层参考，而不是底层规则保真来源。优先借鉴：

- `ManagerMediator`：统一战术查询 / 行动请求接口
- `MacroPlan` / `CombatManeuver`：策略行为组合方式
- `UnitRole` / `SquadManager`：战术分工与失败标签词汇
- `BuildOrderRunner`：timing push / build order 策略描述
- `EngagementResult`：战斗结果分级

历史 M7 能力矩阵应作为 `confidence / reliability` 的输入。即使某些单位的 combat / ability / buff 仍是 partial，战术实验也可以继续运行，但报告必须显式标注：

```text
result_reliability = usable | degraded | not_reliable
unsupported_mechanics = [...]
approximated_mechanics = [...]
capability_coverage = {...}
```

Stage50 现在应优先推进 **Ares-inspired tactical layer + M7-backed reliability reporting**，而不是继续追逐 SC2 微观规则完全复刻。

## 15. Qdrant 历史结论落点

结合 `sc2模拟器计划评审.md` 与 `sc2模拟器m7能力矩阵.md`，Stage50 的落点应是：

1. 用 Ares-SC2 的 `Mediator / Behavior / UnitRole / EngagementResult` 抽象搭建战术决策层。
2. 用 M7 能力矩阵把底层机制覆盖情况暴露到 `tactical_report.v1`。
3. 对微观能力缺口做 `confidence / reliability` 降级，而不是阻塞宏观战术实验。
4. 把首个 MVP 聚焦在 `timing push` 和 AI 策略 A/B，而不是完整复刻 SC2 战斗规则。

这也解释了为什么当前路线不再把 VM debugger、SC2 实机校准或底层帧级保真作为 Stage50 主任务。

