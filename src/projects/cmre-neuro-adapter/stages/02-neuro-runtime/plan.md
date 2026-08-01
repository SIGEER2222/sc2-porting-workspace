# Stage Plan: Neuro Runtime State Machine

> Stage 01 已冻结并验证消息、action、context、session、错误和证据契约。本阶段实现不依赖真实 WebSocket 的 runtime core；网络客户端只作为可替换边界，确保 registry、queue 和 reconnect 行为可离线测试。

## 1. 目标

- 管理 startup identity 和连接生命周期。
- 管理 active action 的注册、更新、注销和重注册。
- 管理容量固定的 action queue。
- 在 mission、paused、blocking 和 update-in-progress 状态下正确调度。
- 保证同一 Neuro `action_id` 不重复入队或执行。
- 通过可注入 sender/dispatcher 离线验证全部状态转换。

## 2. 输出

```text
cmre_neuro_adapter/neuro/runtime.py
cmre_neuro_adapter/neuro/action_registry.py
cmre_neuro_adapter/neuro/action_queue.py
cmre_neuro_adapter/neuro/sender.py
tests/test_runtime.py
tests/test_action_registry.py
tests/test_action_queue.py
```

## 3. 任务分解

### 3.1 Sender Boundary

- 定义最小异步 sender protocol，只负责发送已经构造好的 payload。
- 提供 memory sender 用于离线测试。
- 不在本阶段引入 `aiohttp` 或具体 WebSocket 客户端。

### 3.2 Action Registry

- 以 action name 为稳定 key。
- 新 action 批量 register。
- 缺失 action unregister。
- 定义变化时先 unregister 再 register。
- reconnect/reregister_all 时发送完整 active set。
- action 移除时通知 queue 清理对应命令。

### 3.3 Bounded Action Queue

- 默认容量 3，可配置但必须大于 0。
- queue 满时移除最旧命令并返回 eviction 记录。
- 以 `action_id` 去重。
- 支持按 action name 清理和全部清理。
- 保持 FIFO 执行顺序。

### 3.4 Runtime State Machine

状态至少包含：

```text
connected
identified
in_mission
paused
blocking
update_in_progress
active_actions
queued_action_ids
```

- 仅在 connected + identified 时发送注册和 context。
- action 接收后先验证 active definition 和 schema。
- 合法 action 发送 accepted result 后入队。
- 非法 action 发送 failed result，不入队。
- 只有在任务中且未 paused/blocking/update 时出队执行。
- 任务结束时注销 actions 并清空 queue。
- reconnect 后重发 startup，并在 identity 恢复后重新注册 actions。

## 4. Gate

| Gate | 验证内容 | 证据类型 |
|---|---|---|
| G1-registry | new/missing/changed/reregister 行为确定 | static/runtime-local |
| G2-queue | FIFO、容量、eviction、去重、清理正确 | runtime-local |
| G3-state-machine | paused/blocking/mission/reconnect 状态转换正确 | runtime-local |
| G4-invalid-action | unknown/schema-invalid action 不入队且返回失败 | runtime-local |
| G5-duplicate-action | 同一 action_id 只接受一次 | runtime-local |
| G6-compatibility | Python 3.11/3.13 unittest 和 compileall 通过 | static |

## 5. 非目标

- 不连接真实 Neuro WebSocket。
- 不读取或写入 SC2 Bank。
- 不调用 `SimulatorTransport`。
- 不实现 Dead of Night context projection。
- 不实现能力、能量或 cooldown。
- 不修改外部 Neuro 仓库。

## 6. Completion Gate

1. G1-G6 全部 PASS。
2. 所有状态转换有测试覆盖和可读 failure message。
3. `result.json`、`issues.json`、`log.md` 记录验证命令和结果。
4. 完成后创建 `03-simulator-transport/plan.md`。
