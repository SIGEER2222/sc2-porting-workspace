# Stage 04 Plan: BC Pretrain Checkpoint Loading

> Start condition: Stage 03 PASS (102 tests OK, P2AllyAC + PPOTrainer + collect_rollout verified).

## 1. 目标

从 `vibe.ml.training` 已训练的 BC checkpoint 加载 trunk + 4 BC 头到 `P2AllyAC`，验证 BC 预训练权重与 RL action/value 头的协同性。验证 BC-pretrained policy 在 SimulatorRlBackend 上 rollout 比 random init policy 表现更好（reward 基线提升）。

## 2. 输出

```text
cmre_rl_training/bc_pretrain.py    # load_bc_pretrained_ac(path, hidden_dim, seed) → P2AllyAC
tests/test_bc_pretrain.py          # BC checkpoint 加载 + rollout 对比测试
stages/04-bc-pretrain/{plan,result,log,issues}.{md,json}
```

## 3. 契约

- `load_bc_pretrained_ac(bc_checkpoint_path, *, hidden_dim=128, seed=7, num_actions=NUM_ACTIONS) -> P2AllyAC`
  - 内部调用 `load_bc_checkpoint_into_ac`
  - 验证加载后 `trunk`/`heads` 与 BC checkpoint 完全一致
  - `action_head`/`value_head` 保持随机初始化（Xavier-like）
- `evaluate_policy_rollout(env, policy, n_episodes, n_steps) -> dict`
  - 返回 `{mean_reward, std_reward, mean_steps, total_episodes}`
  - 用于 BC vs random init 对比

## 4. Gates

| Gate | 验证内容 |
|---|---|
| G1-bc-load-end-to-end | 从真实 BC checkpoint（vibe.ml.training 产出）加载到 P2AllyAC，forward_bc 输出与原 BC 模型一致 |
| G2-rl-head-intact | 加载后 action_head/value_head 仍可正常 PPO 训练，loss 收敛 |
| G3-bc-vs-random-baseline | BC-pretrained policy 在 FakeBackend 上 mean reward ≥ random init policy 的 mean reward |
| G4-bc-rollout-stability | BC-pretrained policy 在 100-step rollout 上不产生 NaN/Inf，动作分布合理（不退化到单一动作） |

## 5. 非目标

- 不实现 BC 训练本身（已在 `vibe.ml.training` 中实现）
- 不接入真 SC2（Stage 05）
- 不验证 BC 训练数据集质量

## 6. 依赖

- `vibe.ml.model.save_checkpoint`（已在 Stage 03 测试中验证可用）
- `vibe.ml.training`（如果存在已训练 checkpoint，使用之；否则用 `vibe.ml.model.P2AllyPolicyNet` 随机初始化一个 fake BC checkpoint 供测试）
- Stage 03 的 `P2AllyAC`、`load_bc_checkpoint_into_ac`、`collect_rollout`、`PPOTrainer`

## 7. 测试策略

- 真实 BC checkpoint：检查 `artifacts/` 或 `vibe/ml/training.py` 是否有训练入口，若有则训练一个 mini BC checkpoint（≤10 epochs）作为测试夹具
- 若无训练数据，使用 `P2AllyPolicyNet(seed=N)` 保存为 fake BC checkpoint，验证加载机制正确性（不验证 BC 训练效果）
- 对比测试：BC-pretrained vs random init 在 FakeBackend 上各跑 10 episodes，比较 mean reward
