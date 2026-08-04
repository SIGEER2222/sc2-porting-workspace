# Stage 05 Plan: Sim2Real Evaluation on Real SC2

> Start condition: Stage 04 PASS (117 tests OK, BC checkpoint loaded into P2AllyAC, runtime evidence report generated).

## 1. 目标

在真实 SC2（或 SimulatorRlBackend 完整场景）上评估 BC-pretrained P2AllyAC + PPO 训练后的策略表现，验证 sim2real 迁移效果。对比 BC-only、BC+PPO、random+PPO 三种策略在 Dead-of-Night 任务上的表现。

## 2. 输出

```text
cmre_rl_training/sim2real_eval.py        # 真实场景评估入口
cmre_rl_training/real_sc2_backend.py     # python-sc2 BotAI 适配器（RlBackend 协议）
tests/test_real_sc2_backend.py           # 适配器单元测试（mock BotAI）
tests/test_sim2real_eval.py              # 评估流程集成测试
stages/05-sim2real-eval/{plan,result,log,issues}.{md,json}
artifacts/stage-05-sim2real-eval/evaluation-report.json
```

## 3. 契约

- `RealSc2Backend(RlBackend)`:
  - `reset() -> obs_dict`
  - `step(action_id, args) -> (obs_dict, terminated, info)`
  - `state_version -> int`
  - 包装 `python-sc2.BotAI`，将 RL 动作翻译为 SC2 命令
- `evaluate_sim2real(env_factory, policies, n_episodes) -> dict`:
  - 对比多种策略（BC-only, BC+PPO, random+PPO）的 mean_reward / mean_steps / survival_rate
  - 输出 JSON 报告到 `artifacts/stage-05-sim2real-eval/`

## 4. Gates

| Gate | 验证内容 |
|---|---|
| G1-real-backend-protocol | RealSc2Backend 实现 RlBackend 协议（reset/step/state_version） |
| G2-action-translation | 19 个 RL 动作正确翻译为 SC2 命令（move/attack/build/train 等） |
| G3-simulator-full-scenario | BC-pretrained policy 在 SimulatorRlBackend（完整 Dead-of-Night）上完成 1 个 night 循环 |
| G4-sim2real-report | 生成对比报告，BC+PPO 在 simulator 上 mean_reward ≥ random+PPO |

## 5. 非目标

- 不实现真 SC2 启动（需 launcher 配合，推迟到独立 stage）
- 不训练到收敛（仅验证评估流程跑通）
- 不实现多 episode 并行评估

## 6. 依赖

- Stage 01-04 全部产出
- `python-sc2`（若可用；否则用 SimulatorRlBackend 替代）
- `cmre_neuro_adapter.neuro.simulator_transport.SimulatorSessionBackend`
- 真实 BC checkpoint + Stage 03 PPO 训练后的 RL checkpoint

## 7. 风险

- 真 SC2 启动需 launcher 配合，可能受 SC2 API 限制（参考 topics.md 中 BankPoll/ChatCommand 不触发的问题）
- 若真 SC2 不可用，退化为 SimulatorRlBackend 完整场景评估，在 issues.json 记录
