# Stage 01 Plan: RL Environment Contracts

> Start condition: project.json created, design spec approved.

## 1. 目标

定义 RL 环境的统一接口、动作空间、动作掩码、奖励函数和观测编码，使其能同时消费模拟器后端和真 SC2 后端，且与现有 `vibe/ml/encoder` 和 `neuro/basic_actions` 契约对齐。本阶段用 fake backend 离线验证，不依赖真实模拟器或 SC2 进程。

## 2. 输出

```text
cmre_rl_training/__init__.py
cmre_rl_training/env.py              # CmreRLEnv: reset/step/action_mask
cmre_rl_training/backends.py         # RlBackend Protocol + FakeBackend
cmre_rl_training/action_space.py     # ACTION_NAMES + compute_action_mask
cmre_rl_training/reward.py           # compute_reward + RewardNormalizer
cmre_rl_training/observation.py      # encode_rl_observation (桥接 backend obs → encoder 向量)
tests/__init__.py
tests/test_action_space.py
tests/test_reward.py
tests/test_observation.py
tests/test_env.py
stages/01-env-contracts/result.json
stages/01-env-contracts/issues.json
stages/01-env-contracts/log.md
```

## 3. 契约

- `RlBackend` Protocol: `reset()→observation dict`, `step(action_id, args)→(observation dict, terminated, info)`, `state_version→int`
- `CmreRLEnv`: `reset()→obs_vector`, `step(action_id, args)→(obs_vector, reward, terminated, info)`, `action_mask()→ndarray[bool]`
- 观测向量复用 `vibe/ml/encoder.encode_observation`，schema hash 稳定
- 动作空间 = `BASIC_ACTION_ROUTES` 的 20 种，action_id = route name
- 动作掩码根据 observation 的 own_units/resources 计算
- 奖励从 observation 的 mission/resources/own_units/visible_enemies 变化导出

## 4. Gates

| Gate | 验证内容 | 证据类型 |
|---|---|---|
| G1-action-space | 20 种动作 + mask 逻辑正确（无兵掩 attack/move，无资源掩 build） | static + runtime-local |
| G2-reward | 密集 + 终止奖励从 observation 导出，归一化器 running mean/std 正确 | runtime-local |
| G3-observation | encode_rl_observation 产出向量与 FEATURE_NAMES 长度一致，schema hash 稳定 | static |
| G4-env-loop | FakeBackend reset/step/action_mask 闭环，reward 非零，terminated 可触发 | runtime-local |
| G5-compatibility | Python 3.11 grammar + 可用 runtime unittest 通过 | static |

## 5. 非目标

- 不接入真实 SimulatorSession（Stage 02）
- 不接入 python-sc2 BotAI（Stage 05）
- 不实现 PPO 循环（Stage 03）
- 不做 BC 预训练（Stage 04）
- 不启动 SC2 进程

## 6. Completion Gate

1. G1-G5 全部 PASS。
2. `result.json`、`issues.json`、`log.md` 记录验证命令和结果。
3. 完成后创建 `02-simulator-transport/plan.md`。
