# Stage Plan: Neuro Adapter Contracts and Architecture Baseline

> 本阶段把 `SC2-Neuro-API-Integration` 与 `SC2-Neuro-WoL-Integration` 中已经验证过的架构模式，整理为 CMRE 的独立适配器计划。目标是冻结上层契约，不复制 WoL 地图、Galaxy 库或具体能力数值。

## 1. 目标

建立以下分层：

```text
Neuro WebSocket API
        |
        v
Neuro Host Runtime
  - session/reconnect
  - action registry
  - bounded action queue
  - context publisher
  - result publisher
        |
        +------------------+
        |                  |
        v                  v
Simulator Adapter      SC2 Runtime Adapters
        |                - SC2 API
        |                - Bank
        |                - input fallback
        v
CMRE Mission Adapter
        |
        v
Observation / MissionState / Policy
```

CMRE 的 `SimulatorTransport` 是第一传输路径。真实 SC2 通道只能作为后续适配器，不能成为本地开发和回归的前置依赖。

## 2. 参考架构结论

### 2.1 通用 Neuro API 层

参考 `reference/SC2-Neuro-API-Integration` 的以下消息：

- `startup`
- `context`
- `actions/register`
- `actions/unregister`
- `actions/force`
- `action/result`
- `action`
- `actions/reregister_all`

该层不得依赖 WoL、CMRE、Ares 或某张地图。

### 2.2 状态桥接层

参考作者的 Bank 状态面，但将 Bank 视为一种可替换 transport，而不是核心状态模型：

```text
SC2/Galaxy -> game_context / possible_actions / game_state
SC2/Galaxy <- do_action / force_action
```

需要保留的机制：

- 安全写入窗口。
- 串行写入和原子替换。
- action 消费后的 flag 清理。
- action queue 与 blocking/cutscene 状态协同。
- 重连后重新注册 active actions。

### 2.3 Mission Adapter 层

Dead of Night 适配器负责：

- objective 和 victory 状态。
- 波次、夜晚、基地和经济摘要。
- 可见单位和威胁摘要。
- 任务状态变化时的 context。
- 当前任务可用 action 的生命周期。

任务规则、目标、波次、奖励和权威状态仍归 CMRE 所有，不转移到 Neuro host。

### 2.4 Action 生命周期

```text
MissionState 发布 possible actions
        |
        v
动态注册/注销 action
        |
        v
Neuro action -> schema 校验 -> action/result
        |
        v
有界队列 -> 安全窗口 -> dispatcher
        |
        v
执行结果 -> uses/cooldown/state 更新 -> context
```

必须处理：

- required、enum、range、regex 参数校验。
- 未知 action 拒绝。
- action 定义变化时 unregister 后 register。
- queue 满时丢弃最旧动作并发布 context。
- action 失效时从 queue 清除。
- 任务结束时注销 active actions。
- 断线重连后重新注册 active actions。

## 3. 计划阶段

### Stage 01 - Contracts

**输出：**

```text
src/projects/cmre-neuro-adapter/
  project.json
  stages/01-contracts/plan.md
  cmre_neuro_adapter/neuro/messages.py
  cmre_neuro_adapter/neuro/schemas.py
  cmre_neuro_adapter/neuro/session.py
  cmre_neuro_adapter/neuro/actions.py
  cmre_neuro_adapter/neuro/context.py
  cmre_neuro_adapter/neuro/errors.py
  cmre_neuro_adapter/neuro/evidence.py
```

**工作内容：**

- 冻结 Neuro message、ActionDefinition、ActionCommand、ContextEnvelope、ExecutionResult。
- 明确 Neuro `action_id` 与 CMRE RPC `request_id` 的边界。
- 复用 `vibe.protocol` 的 session/checksum/idempotency 原则，但不混淆两套 ID 生命周期。
- 建立错误码和证据记录格式。

**Gate：**

- 消息构造和解析 round-trip 通过。
- 非法 JSON、未知 command、缺失 data 显式失败。
- action schema 支持 required、unexpected、string、integer、number、boolean、enum、min/max、regex。
- 不启动 SC2，不读取 Bank，不依赖 Neuro 在线服务。

### Stage 02 - Neuro Runtime

**输出：**

```text
neuro/websocket_runtime.py
neuro/action_registry.py
neuro/action_queue.py
neuro/context_publisher.py
neuro/result_publisher.py
```

**工作内容：**

- startup 握手、session、display name、character id。
- WebSocket 断线重连。
- action 动态注册、注销、更新和全量重注册。
- 有界 action queue、blocking/paused 等待和失败结果。
- action uses 消耗和 action 生命周期清理。

**Gate：**

- 重连后 active actions 完整恢复。
- 重复 action 不重复执行。
- 非法 action 不进入 queue。
- queue 上限固定且行为确定。
- 任务结束后无残留 action。

### Stage 03 - Simulator Neuro Transport

**输出：**

```text
transports/simulator_neuro.py
transports/action_dispatch.py
transports/context_projection.py
```

**工作内容：**

- 将 `Observation.from_world()` 投影为 Neuro context。
- 只暴露配置好的玩家可见视图，不暴露 hidden world。
- 首批支持 `move_units`、`attack_unit`、`attack_move`、`retreat_units`、`hold_position`、`produce_unit`、`research_upgrade`、`set_rally`、`use_ability`。
- 将 action 转换为 `SimulatorSession`/`SimulatorTransport` 操作。
- 将 command result 转换为 `ExecutionResult`。

**Gate：**

- simulator 中 startup -> context -> register -> action -> dispatch -> result 闭环通过。
- 死亡目标、不可见目标、错误 owner、非法参数被拒绝且无状态副作用。
- 相同 snapshot、action 序列和 seed 产生相同 trace hash。

### Stage 04 - Dead of Night Mission Adapter

**输出：**

```text
mission/mission_state.py
mission/dead_of_night_adapter.py
mission/objective_context.py
mission/tactical_context.py
mission/economy_context.py
mission/production_context.py
```

**工作内容：**

- 发布当前夜晚、波次、基地、资源、生产和 objective 状态。
- 对 objective changed、wave spawned、building completed、unit died、mission ended 等事件发送 context。
- 对周期性 combat/economy context 做节流和去重。
- 根据 mission state 注册和注销 action。
- 正确处理 no-build、paused、blocking、victory、failure。

**Gate：**

- context 只能追溯到 Observation 或 MissionEngine。
- 不泄漏 hidden enemy state。
- 任务状态转换不会留下不适用 action。
- 相同 context 默认去重，但支持显式 forced refresh。

### Stage 05 - Persistent State

**输出：**

```text
persistence/campaign_state.py
persistence/mission_state.py
persistence/runtime_state.py
persistence/state_store.py
persistence/migrations.py
```

**工作内容：**

分离三类状态：

- `campaign state`：跨任务能力和任务进度。
- `mission state`：当前任务目标、波次、资源、冷却和单位状态。
- `runtime state`：session、active actions、queue 和 transport 状态。

**Gate：**

- round-trip、重启恢复和 schema migration 通过。
- 损坏状态不会覆盖旧版本。
- 跨任务状态与当前任务状态不串扰。
- 状态参与 snapshot/replay 后结果可重复。

### Stage 06 - CMRE Ability Slice

**输出：**

```text
abilities/definitions.py
abilities/registry.py
abilities/executor.py
abilities/state.py
```

首批只实现四个能力：

- `heal_allies`
- `temporary_shields`
- `call_backup`
- `nuke_visible_target`

每个能力必须有 definition、schema、requirements、energy cost、cooldown、effect、result 和 context。暂不复制 WoL 的 14 能力和具体数值。

**Gate：**

- 能量不足、冷却未完成、目标不可见时拒绝且无错误副作用。
- 成功时一次性扣能量并设置冷却。
- snapshot/replay 能恢复能力状态。
- 相同输入产生相同效果和 trace。

### Stage 07 - Real SC2 Adapters

**输出：**

```text
transports/sc2api_neuro.py
transports/bank_neuro.py
transports/input_neuro.py
```

**工作内容：**

- 优先接入 SC2 API。
- 在确认 SC2 能消费外部变化后再接 Bank。
- 输入回退只作为最后兼容通道。
- 所有启动必须使用 `tools/launchers/` 下的 launcher。
- 每次启动后检查新增 `ScriptError.*.txt`。

**Gate：**

- 真实 startup、context、action register、action result 和 reconnect 通过。
- 真实游戏中的 action 有可观察效果。
- 没有新增 Neuro 相关 ScriptError。
- Bank 通道必须单独生成 runtime verdict，不能以 simulator 结果代替。

### Stage 08 - Runtime Acceptance

**输出：**

```text
stages/08-runtime-acceptance/result.json
stages/08-runtime-acceptance/issues.json
stages/08-runtime-acceptance/log.md
artifacts/cmre-neuro-adapter/
```

**完整链路：**

```text
launcher -> Dead of Night -> startup -> context -> actions
-> Neuro action -> queue -> CMRE dispatch -> SC2 result
-> wave/objective context -> victory/failure -> state save
```

**Gate：**

- 3500 loop 任务运行有完整 runtime evidence。
- objective、wave、victory/failure context 正确。
- 无 command storm、无限 no-op 或 hidden state 访问。
- 任务结束后 action、queue、Bank 写入全部清理。
- launcher、进程状态、GameLogs、action/context 日志和结果文件齐全。

## 4. 推荐目录结构

```text
src/projects/cmre-neuro-adapter/
  project.json
  cmre_neuro_adapter/neuro/
    messages.py
    schemas.py
    session.py
    action_registry.py
    action_queue.py
    context_publisher.py
    result_publisher.py
  transports/
    simulator_neuro.py
    sc2api_neuro.py
    bank_neuro.py
    input_neuro.py
  mission/
    mission_state.py
    dead_of_night_adapter.py
    objective_context.py
    tactical_context.py
    economy_context.py
    production_context.py
  abilities/
    definitions.py
    registry.py
    executor.py
    state.py
  persistence/
    campaign_state.py
    mission_state.py
    runtime_state.py
    state_store.py
    migrations.py
  tests/
  stages/
```

## 5. 与 `cmre-ai-enhancement` 的边界

`cmre-neuro-adapter` 只依赖稳定的：

- `Observation`
- `MissionState`
- `ActionDefinition`
- `ActionCommand`
- `ExecutionResult`

不得直接依赖 Ares 的 manager、`BuildOrderRunner` 或内部 bot state。`EnhancedPolicy` 可以作为 action consumer，但不能成为 Neuro adapter 的必要依赖。

## 6. 非目标

- 不复制 WoL 的 30 张地图。
- 不直接移植 WoL 的 14 个能力。
- 不修改两个 Neuro 外部仓库的 canonical 内容。
- 不修改 `sc2_simulator` 外部源码。
- 不以 Bank 作为 simulator 本地路径的前置依赖。
- 不让 Neuro 访问全知 world。
- 不允许 LLM 或 Neuro 调用任意 Galaxy 函数。
- 不在缺少 launcher、GameLogs 和运行时证据时宣称真实 SC2 完成。

## 7. 证据规则

- `static`：架构、schema、代码依赖、Catalog/银河脚本分析。
- `simulator`：本地 simulator action/context、snapshot、trace 和 replay 结果。
- `runtime`：launcher、SC2 事件、Bank、截图、进程状态和 GameLogs。
- `inference`：尚未验证的跨项目兼容性或作者报告之外的结论。

## 8. Completion Gate

1. 每个阶段的声明输出存在。
2. 当前阶段的 validation commands 通过。
3. `result.json`、`issues.json`、`log.md` 含证据路径和未解决问题。
4. 真实 SC2 结果只使用 launcher 和新增 GameLogs 作为 runtime 证据。
5. 当前阶段验证后才创建下一阶段的 `plan.md`。
