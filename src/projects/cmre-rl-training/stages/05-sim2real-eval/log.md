# Stage 05 Log: Sim2Real Evaluation

**Date**: 2026-08-04
**Stage**: 05-sim2real-eval
**Status**: PASS

## Summary

实现 `RealSc2BackendAdapter`（python-sc2 BotAI → RlBackend 协议适配器，含 19 个 RL 动作到 SC2 命令的翻译器）和 `evaluate_sim2real` / `generate_sim2real_report`（多策略对比评估工具）。在 FakeBackend + SimulatorRlBackend（MockSimulatorSession）上验证 BC-pretrained、random init、BC+PPO、random+PPO 四种策略的 sim2real 评估流程。

由于 python-sc2 未安装且真 SC2 启动存在已知问题（BankPoll/ChatCommand 不触发），按 plan.md 风险条款退化为 SimulatorRlBackend + Mock 完整场景评估。

## Evidence

### G1-real-backend-protocol (runtime-local)
- **Command**: `python -m unittest tests.test_real_sc2_backend.RealSc2BackendAdapterProtocolTests -v`
- **Result**: 4 tests, OK
- **Verified**:
  - `RealSc2BackendAdapter(MockBotAI)` 实现 `RlBackend` 协议（`isinstance` 检查通过）
  - `state_version` 返回非负 int
  - `reset()` 返回包含 `loop/player_id/own_units/visible_enemies/resources/mission` 的观察字典
  - `step(action_id, args)` 返回 `(obs_dict, terminated_bool, info_dict)` 三元组

### G2-action-translation (runtime-local)
- **Command**: `python -m unittest tests.test_real_sc2_backend.RealSc2BackendActionTranslationTests -v`
- **Result**: 12 tests, OK
- **Verified**:
  - 全部 19 个 RL 动作（`ACTION_NAMES`）在 `_action_translators` 字典中有对应翻译器
  - `move_units` → move 命令（含 target_x/target_y）
  - `attack_move_units` → attack_move 命令
  - `gather_resources` → gather 命令（含 target_tag）
  - `stop_units`/`hold_units` → stop/hold 命令
  - `build_structure` → build 命令（含 unit_type + 位置）
  - `produce_unit` → train 命令（含 unit_type）
  - `cancel_order` → cancel 命令
  - 未知动作抛 `ValueError("unknown_action:...")`
  - 无 `entity_tags` 时默认选取战斗单位
  - 每次 `step` 后 `state_version` 递增

### G3-simulator-full-scenario (runtime-local)
- **Command**: `python -m unittest tests.test_sim2real_eval.SimulatorFullScenarioTests -v`
- **Result**: 2 tests, OK
- **Verified**:
  - BC-pretrained policy 在 `SimulatorRlBackend`（MockSimulatorSession, max_steps=15）上完成完整 15-step rollout
  - 所有观察 finite，无 NaN/Inf
  - random policy 同样完成 10-step rollout

### G4-sim2real-report (runtime-local)
- **Command**: `python tools/evaluate_sim2real.py` → `artifacts/stage-05-sim2real-eval/evaluation-report.json`
- **Result**: all_gates_pass=True
- **Verified**:
  - 4 种策略（random_init/bc_pretrained/random_ppo/bc_ppo）全部完成 10 episodes × 15 steps 评估
  - `mean_reward=16.462`, `mean_steps=15.0`, `survival_rate=100%`（所有策略一致，因 FakeBackend 奖励与动作无关）
  - PPO 训练 loss 全部 finite：
    - random_ppo: total_loss=1.7726, policy_loss=-0.5363, value_loss=4.6731, entropy=2.7595
    - bc_ppo: total_loss=1.5875, policy_loss=-0.7925, value_loss=4.8110, entropy=2.5586
  - **动作分布差异显著**：
    - BC-pretrained: gather_resources(40)、attack_units(20)、patrol_units(20) — 集中偏好
    - random_init: 分布相对均匀（5-16 次/动作）
    - BC+PPO: rally_producer(18)、cast_point_ability(19)、attack_units(17) — PPO 调整后分布
    - random+PPO: rally_producer(16)、attack_units(14)、hold_units(13) — 不同分布模式

### G5-evaluate-helper (runtime-local)
- **Command**: `python -m unittest tests.test_sim2real_eval.EvaluateSim2RealTests -v`
- **Result**: 4 tests, OK
- **Verified**:
  - `evaluate_sim2real(env_factory, policies, n_episodes, n_steps)` 返回 `{policy_name: {mean_reward, std_reward, mean_steps, survival_rate, total_episodes, action_distribution}}`
  - 支持多策略并行评估
  - deterministic 模式两次运行结果完全一致
  - BC vs random 对比产生 finite 指标

### G6-report-generation (runtime-local)
- **Command**: `python -m unittest tests.test_sim2real_eval.Sim2RealReportGenerationTests -v`
- **Result**: 1 test, OK
- **Verified**: `generate_sim2real_report` 生成 JSON 文件包含：
  - `stage`, `env_type`, `n_episodes`, `n_steps`, `ppo_train_steps`
  - `bc_checkpoint`, `bc_checkpoint_available`
  - `ppo_training_metrics`（PPO 训练 loss）
  - `policies`（4 种策略的评估指标）
  - `all_gates_pass`

## Runtime Evidence Report

`artifacts/stage-05-sim2real-eval/evaluation-report.json` 包含：
- 4 种策略的 mean_reward / std_reward / mean_steps / survival_rate / action_distribution
- PPO 训练 loss（random_ppo vs bc_ppo）
- BC checkpoint 可用性检查

## Test Run

```
PYTHONPATH=.;..\cmre-neuro-adapter;..\cmre-porting python -m unittest discover -s tests -v
Ran 142 tests in 2.397s
OK
```

## Changed Paths

- `src/projects/cmre-rl-training/cmre_rl_training/real_sc2_backend.py` — RealSc2BackendAdapter + 19 动作翻译器
- `src/projects/cmre-rl-training/cmre_rl_training/sim2real_eval.py` — evaluate_sim2real + train_policy_with_ppo + generate_sim2real_report
- `src/projects/cmre-rl-training/tests/test_real_sc2_backend.py` — 18 test cases (G1/G2)
- `src/projects/cmre-rl-training/tests/test_sim2real_eval.py` — 7 test cases (G3-G6)
- `src/projects/cmre-rl-training/tools/evaluate_sim2real.py` — runtime evidence 生成工具
- `artifacts/stage-05-sim2real-eval/evaluation-report.json` — runtime 评估报告

## Dependencies

- Stage 01-04 全部产出（P2AllyAC, PPOTrainer, collect_rollout, load_bc_pretrained_ac）
- 真实 BC checkpoint: `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/ml-ally-policy-pytorch-20260804/ally-intent.pt`
- MockBotAI / MockSimulatorSession（测试用，替代 python-sc2 和真实模拟器）

## Limitations

- python-sc2 未安装，RealSc2BackendAdapter 用 MockBotAI 验证协议和动作翻译
- 真 SC2 启动有已知问题（BankPoll/ChatCommand 不触发），sim2real 评估退化为 SimulatorRlBackend + Mock 场景
- FakeBackend 奖励与动作无关，无法验证 BC/PPO 在任务奖励上的实际收益；仅通过动作分布差异间接证明策略行为差异
