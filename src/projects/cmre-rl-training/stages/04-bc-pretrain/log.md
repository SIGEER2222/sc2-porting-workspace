# Stage 04 Log: BC Pretrain Checkpoint Loading

**Date**: 2026-08-04
**Stage**: 04-bc-pretrain
**Status**: PASS

## Summary

从真实 BC checkpoint（`ally-intent.pt`，48 epochs，holdout acc 95.28%）加载 trunk + 4 BC heads 到 `P2AllyAC`，验证 BC 预训练权重与 RL action/value 头的协同性。实现 `load_bc_pretrained_ac` 和 `evaluate_policy_rollout` 工具，生成 runtime evidence 报告。

## Evidence

### G1-bc-load-end-to-end (runtime-local)
- **Command**: `python -m unittest tests.test_bc_pretrain.BCLoadEndToEndTests -v`
- **Result**: 4 tests, OK
- **Verified**:
  - 真实 BC checkpoint 加载成功：schema=`cmre-ally-intent-pytorch.v2`, hidden_dim=128, input_dim=49
  - `load_bc_pretrained_ac` 返回 `P2AllyAC` 实例
  - `action_head`/`value_head` 权重与同 seed 的 random init AC 完全一致（BC 加载未触及 RL 头）
  - `forward(obs, mask)` 返回 `(logits[3,19], value[3,1])`

### G2-rl-head-intact (runtime-local)
- **Command**: `python -m unittest tests.test_bc_pretrain.BCRolloutStabilityTests.test_bc_pretrained_policy_can_run_ppo_training`
- **Result**: 1 test, OK
- **Verified**: BC-loaded AC 在 20-step rollout + PPO 训练后：
  - total_loss=1.0278, policy_loss=-0.0735, value_loss=2.2532, entropy=2.5320
  - 所有 loss 指标 finite，PPO 训练机制未受 BC 加载影响

### G3-trunk-feature-transfer (runtime-local)
- **Command**: `python -m unittest tests.test_bc_pretrain.TrunkFeatureTransferTests -v`
- **Result**: 3 tests, OK
- **Verified**:
  - BC-pretrained trunk 输出与原 BC 模型 trunk 输出完全一致（max_abs_diff=0.0）
  - 4 个 BC heads（economy/production/tactical/command）输出完全一致（max_abs_diff=0.0）
  - BC trunk 权重与 random init 显著不同（`torch.allclose` 返回 False），证明加载生效
- **Meaning**: BC 训练的特征提取能力完整迁移到 RL policy，PPO 可在此暖启动 trunk 上训练

### G4-rollout-stability (runtime-local)
- **Command**: `python -m unittest tests.test_bc_pretrain.BCRolloutStabilityTests -v`
- **Result**: 3 tests, OK
- **Verified**:
  - 100-step rollout: `obs_finite=True`, `logprobs_finite=True`, `actions_in_range=True`
  - 15/19 个动作被采样（action_entropy=2.481），动作分布健康，未退化到单一动作
  - PPO 训练 loss 全部 finite

### G5-evaluate-helper (runtime-local)
- **Command**: `python -m unittest tests.test_bc_pretrain.EvaluatePolicyRolloutTests -v`
- **Result**: 4 tests, OK
- **Verified**: `evaluate_policy_rollout(env_factory, policy, n_episodes, n_steps)` 返回：
  - `mean_reward`, `std_reward`, `mean_steps`, `total_episodes`, `action_distribution`
  - deterministic 模式两次运行结果完全一致
  - `action_distribution` 总和 = episodes × steps

### G6-bc-vs-random-consistency (runtime-local)
- **Command**: `python tools/evaluate_bc_pretrain.py` → `artifacts/stage-04-bc-pretrain/evaluation-report.json`
- **Result**: all_gates_pass=True
- **Key findings**:
  - FakeBackend 奖励与动作无关，BC 与 random 的 mean_reward 相同（17.32，预期）
  - **动作分布显著不同**：
    - Random init: 分布相对均匀（4-21 次/动作）
    - BC-pretrained: 分布更集中（gather_resources 43 次, attack_units 32 次, hold_units 20 次）
  - 这证明 BC trunk 的特征表示改变了 action_head 的响应分布，即使 action_head 是随机初始化的

## Runtime Evidence Report

`artifacts/stage-04-bc-pretrain/evaluation-report.json` 包含：
- BC checkpoint metadata（epochs, accuracy, loss）
- Trunk + heads parity 验证（max_abs_diff=0.0）
- 100-step rollout stability（15/19 actions, entropy=2.481）
- PPO training compatibility（total_loss=1.0278）
- BC vs random action distribution 对比

## Test Run

```
PYTHONPATH=.;..\cmre-neuro-adapter;..\cmre-porting python -m unittest discover -s tests -v
Ran 117 tests in 2.333s
OK
```

## Changed Paths

- `src/projects/cmre-rl-training/cmre_rl_training/bc_pretrain.py` — load_bc_pretrained_ac + evaluate_policy_rollout
- `src/projects/cmre-rl-training/tests/test_bc_pretrain.py` — 15 test cases (G1-G6)
- `src/projects/cmre-rl-training/tools/evaluate_bc_pretrain.py` — runtime evidence 生成工具
- `artifacts/stage-04-bc-pretrain/evaluation-report.json` — runtime 评估报告

## Dependencies

- Stage 03 的 `P2AllyAC`、`load_bc_checkpoint_into_ac`、`collect_rollout`、`PPOTrainer`
- `vibe.ml.model.load_checkpoint`（BC checkpoint 加载）
- 真实 BC checkpoint: `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/ml-ally-policy-pytorch-20260804/ally-intent.pt`
