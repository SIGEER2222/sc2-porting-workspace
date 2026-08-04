# Stage 02 Plan: Simulator Backend Integration

> Start condition: Stage 01 PASS (47 tests OK).

## 1. 目标

将 `SimulatorSession` + `SimulatorSessionBackend`（来自 `cmre-neuro-adapter`）接入 `CmreRLEnv`，使 RL 环境能在真实确定性模拟器上跑 reset/step/action_mask 闭环，并启用 Domain Randomization。验证 `observation.py` 与 `vibe/ml/encoder` 的端到端对齐。

## 2. 输出

```text
cmre_rl_training/simulator_backend.py   # SimulatorRlBackend: 包装 SimulatorSessionBackend
cmre_rl_training/domain_randomization.py # DR 参数采样器
tests/test_simulator_backend.py          # 模拟器后端集成测试
tests/test_domain_randomization.py       # DR 参数测试
stages/02-simulator-backend/plan.md
stages/02-simulator-backend/result.json
stages/02-simulator-backend/log.md
stages/02-simulator-backend/issues.json
```

## 3. 契约

- `SimulatorRlBackend(RlBackend)`: 内部持有 `SimulatorSessionBackend`，`reset()` 重置场景 + DR，`step(action_id, args)` 走 `route_basic_action` → `SimulatorTransport.dispatch`，`state_version` 从 backend 读取
- `DomainRandomization`: 采样 `(seed, wave_strength_scale, time_scale, fog_range)` 参数
- 验证 `ACTION_NAMES` 与 `BASIC_ACTION_ROUTES` 1:1 对齐
- 验证 `encode_rl_observation` 在 PYTHONPATH 含 `vibe` 时产出与 `FEATURE_NAMES` 长度一致的向量

## 4. Gates

| Gate | 验证内容 | 证据类型 |
|---|---|---|
| G1-backend-protocol | SimulatorRlBackend 实现 RlBackend Protocol | static |
| G2-action-alignment | ACTION_NAMES 与 BASIC_ACTION_ROUTES 1:1 对齐 | static |
| G3-encoder-integration | encode_rl_observation 产出向量长度 = len(FEATURE_NAMES) | static + runtime-local |
| G4-env-loop-sim | CmreRLEnv(SimulatorRlBackend) reset/step/action_mask 闭环 ≥ 10 step | runtime-local |
| G5-dr-params | DomainRandomization 采样参数在合理范围内 | runtime-local |

## 5. 非目标

- 不接入 python-sc2 BotAI（Stage 05）
- 不实现 PPO 循环（Stage 03）
- 不启动 SC2 进程

## 6. Completion Gate

1. G1-G5 全部 PASS。
2. `result.json`、`issues.json`、`log.md` 记录验证命令和结果。
3. 完成后创建 `03-ppo-loop/plan.md`。
