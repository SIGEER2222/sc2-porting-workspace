# Stage 03 Plan: PPO Loop and Policy Network

> Start condition: Stage 02 PASS (70 tests OK).

## 1. 目标

实现 P2AllyAC 策略网络（子类化 P2AllyPolicyNet 加 value/action 头）和自研 PPO 训练循环，在模拟器上验证收敛性。

## 2. 输出

```text
cmre_rl_training/network.py        # P2AllyAC: trunk + 4 BC 头 + value + action 头
cmre_rl_training/ppo.py            # RolloutBuffer + GAE + PPO trainer
cmre_rl_training/rollout.py        # VecEnv 并行 rollout 收集
tests/test_network.py
tests/test_ppo.py
tests/test_rollout.py
stages/03-ppo-loop/{plan,result,log,issues}.{md,json}
```

## 3. 契约

- `P2AllyAC(P2AllyPolicyNet)`: `forward(obs, mask)→(logits, value)`，`load_bc_checkpoint(path)`
- `RolloutBuffer`: 存储 `(obs, action, logprob, value, reward, done, mask)`，`compute_gae()→(advantages, returns)`
- `PPOTrainer`: `train(env, policy, epochs)`，clipped surrogate + value loss + entropy

## 4. Gates

| Gate | 验证内容 |
|---|---|
| G1-network | P2AllyAC forward 产出 (logits[19], value[1])，mask 正确应用 |
| G2-bc-load | BC checkpoint 可加载到 trunk + 4 头 |
| G3-gae | GAE 优势计算正确（lambda=0.95） |
| G4-ppo-converge | PPO 在 FakeBackend mini 场景上 reward 上升（≥100 step） |
| G5-checkpoint | save/load checkpoint 往返一致 |

## 5. 非目标

- 不接入真 SC2（Stage 05）
- 不做 BC 预训练本身（Stage 04）
