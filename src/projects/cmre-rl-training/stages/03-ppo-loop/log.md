# Stage 03 Log: PPO Loop and Policy Network

**Date**: 2026-08-04
**Stage**: 03-ppo-loop
**Status**: PASS

## Summary

实现 P2AllyAC actor-critic 策略网络（子类化 `P2AllyPolicyNet` 复用 BC 预训练 trunk + 4 头，新增 `action_head`/`value_head`）、`RolloutBuffer` + GAE-λ、`PPOTrainer`（clipped surrogate + value loss + entropy bonus）和 `collect_rollout` 并行数据收集。在 FakeBackend 与可学习 mini 场景上验证 PPO 收敛性（≥100 step）。

## Evidence

### G1-network (static + runtime-local)
- **Command**: `python -m unittest tests.test_network.P2AllyACContractTests -v`
- **Result**: 8 tests, OK
- **Verified**:
  - `P2AllyAC.forward(obs, mask)` 返回 `(logits[B,19], value[B,1])`
  - mask 应用 `masked_fill(~mask, -inf)` 使非法动作产生 0 概率
  - 单条输入自动 unsqueeze 到 batch 维度
  - 继承自 `P2AllyPolicyNet`，保留 4 个 BC 头（economy/production/tactical/command）
  - `forward_bc(features)` 仍可调用原始 BC 头路径，供 Stage 04 BC 加载使用

### G2-bc-load (runtime-local)
- **Command**: `python -m unittest tests.test_network.P2AllyACBCLoadTests -v`
- **Result**: 2 tests, OK
- **Verified**:
  - `load_bc_checkpoint_into_ac(ac, path)` 仅复制 trunk + 4 BC heads 状态
  - `action_head`/`value_head` 保持当前初始化（随机或 RL 训练后）
  - hidden_dim 不匹配时抛 `ValueError("bc_hidden_dim_mismatch:...")`

### G3-gae (runtime-local)
- **Command**: `python -m unittest tests.test_ppo.RolloutBufferGAETests -v`
- **Result**: 6 tests, OK
- **Verified**: GAE-λ 公式正确实现
  - `lam=1, gamma=1`: 优势 = 累积回报 [5,4,3,2,1]
  - `lam=0`: 优势 = TD 误差
  - `lam=0.95, gamma=0.99`: 手算匹配 `[2.373067625, 1.46525, 0.5]`
  - `normalize=True` 默认开启，产出零均值单位方差优势
  - `clear()` 重置后 buffer 长度为 0

### G4-ppo-converge (runtime-local)
- **Command**: `python -m unittest tests.test_ppo.PPOTrainerConvergenceTests -v`
- **Result**: 2 tests, OK
- **Verified**:
  - 100-step 训练循环（20 rollouts × 5 steps），所有 loss 有限
  - 50-rollout × 1-step 训练在 2-action 可学习 mini backend 上：
    - action_a 给 +1 reward，action_b 给 -1 reward
    - 训练后 action_a 选择次数显著高于随机基线，且 >50% 评估 episode 都选 action_a
- **Note**: 测试关闭 advantage 归一化与 entropy bonus，因为 1-step episode 中归一化会消除信号

### G5-checkpoint (runtime-local)
- **Command**: `python -m unittest tests.test_network.P2AllyACCheckpointTests -v`
- **Result**: 3 tests, OK
- **Verified**:
  - `save_rl_checkpoint(policy, path)` 写入 schema=`cmre-rl-ac.v1`、`policy_config`、`num_actions`、`state_dict`
  - `load_rl_checkpoint(path)` 严格加载 state_dict，forward 输出与原 policy 完全一致（`torch.testing.assert_close`）
  - state_dict 包含 trunk、4 BC heads、action_head、value_head 全部权重

### G6-rollout-integration (runtime-local)
- **Command**: `python -m unittest tests.test_rollout -v`
- **Result**: 10 tests, OK
- **Verified**:
  - `collect_rollout(env, policy, n_steps)` 返回 length==n_steps 的 buffer
  - 终止时自动 reset，跨 episode 收集
  - mask 形状 (n, 19)，dtype bool
  - deterministic=True 时两次相同 seed rollout 产出相同动作序列
  - 端到端：rollout → PPOTrainer.train 返回 finite metrics

## Implementation Notes

- P2AllyAC forward 与 BC parent forward 签名不同（返回 tuple 而非 dict），这是有意的：RL 训练需要 (logits, value) 配对，BC 推理保持 dict 格式供现有 P2Intent 流水线使用
- `forward_bc` 方法保留对原 BC 路径的访问，避免子类破坏 BC 推理
- PPO 训练器对 `-inf` logits（来自 mask）做 `torch.where(isfinite, logits, -1e9)` 替换，保证 `Categorical` 不产生 NaN
- 优势归一化默认开启（PPO 标准做法），但短 episode + 单一奖励信号时需禁用（G4 测试已演示此问题）

## Test Run

```
PYTHONPATH=.;..\cmre-neuro-adapter;..\cmre-porting python -m unittest discover -s tests -v
Ran 102 tests in 3.262s
OK
```

## Changed Paths

- `src/projects/cmre-rl-training/cmre_rl_training/network.py` — P2AllyAC + save/load RL checkpoint + BC load helper
- `src/projects/cmre-rl-training/cmre_rl_training/ppo.py` — RolloutBuffer + GAE-λ + PPOTrainer
- `src/projects/cmre-rl-training/cmre_rl_training/rollout.py` — collect_rollout 并行收集
- `src/projects/cmre-rl-training/tests/test_network.py` — G1 + G2 + G5 测试（14 cases）
- `src/projects/cmre-rl-training/tests/test_ppo.py` — G3 + G4 测试（8 cases）
- `src/projects/cmre-rl-training/tests/test_rollout.py` — G6 rollout 集成测试（10 cases）

## Dependencies

- 复用 Stage 01/02 的 `numpy`、`torch`（CPU）
- 复用 `vibe.ml.model.P2AllyPolicyNet` 作为 BC trunk 基类
- 复用 `cmre_rl_training.action_space.NUM_ACTIONS`（19）与 `ACTION_NAMES`
