# Stage 01 Log: RL Environment Contracts

**Date**: 2026-08-04
**Stage**: 01-env-contracts
**Status**: PASS

## Summary

定义了 RL 环境的统一接口、动作空间、动作掩码、奖励函数和观测编码，全部用 FakeBackend 离线验证通过。

## Evidence

### G1-action-space (static + runtime-local)
- **Command**: `python -m unittest tests.test_action_space -v`
- **Result**: 14 tests, OK
- **Verified**: 19 个动作匹配 BASIC_ACTION_ROUTES；action_mask 正确过滤无兵/无资源/无结构的非法动作

### G2-reward (runtime-local)
- **Command**: `python -m unittest tests.test_reward -v`
- **Result**: 15 tests, OK
- **Verified**: 基地受损惩罚、supply 增长奖励、杀敌奖励、任务进度奖励、夜晚存活奖励、worker 增长奖励、终止胜利/失败奖励；RewardNormalizer running mean/std 正确

### G3-observation (static)
- **Command**: `python -m unittest tests.test_observation -v`
- **Result**: 8 tests, OK
- **Verified**: normalize_observation 填充缺失字段（mineral_fields/tech/visible_allies）；encode_rl_observation 产出 float list，fallback 模式长度匹配 rl_feature_count()；编码确定性

### G4-env-loop (runtime-local)
- **Command**: `python -m unittest tests.test_env -v`
- **Result**: 10 tests, OK
- **Verified**: CmreRLEnv reset/step/action_mask 闭环；FakeBackend 完整 episode 跑通到 terminated；reward 非零；state_version 递增；自定义 encoder 注入正常

### G5-compatibility (static)
- **Command**: `python -m unittest discover -s tests -v`
- **Result**: 47 tests, OK
- **Environment**: Python 3.11, numpy installed via pip

## Changed Paths

- `src/projects/cmre-rl-training/project.json` — 项目定义
- `src/projects/cmre-rl-training/stages/01-env-contracts/plan.md` — 阶段计划
- `src/projects/cmre-rl-training/cmre_rl_training/__init__.py`
- `src/projects/cmre-rl-training/cmre_rl_training/action_space.py` — 19 动作 + compute_action_mask
- `src/projects/cmre-rl-training/cmre_rl_training/reward.py` — RewardTracker + RewardNormalizer
- `src/projects/cmre-rl-training/cmre_rl_training/observation.py` — normalize + encode_rl_observation + fallback
- `src/projects/cmre-rl-training/cmre_rl_training/backends.py` — RlBackend Protocol + FakeBackend
- `src/projects/cmre-rl-training/cmre_rl_training/env.py` — CmreRLEnv
- `src/projects/cmre-rl-training/tests/test_action_space.py`
- `src/projects/cmre-rl-training/tests/test_reward.py`
- `src/projects/cmre-rl-training/tests/test_observation.py`
- `src/projects/cmre-rl-training/tests/test_env.py`

## Design Decisions

1. **observation.py 用 fallback 编码**：当 `vibe/ml/encoder` 不可 import 时，使用 8 维 fallback 向量。Stage 02 接入真实模拟器时会设置 PYTHONPATH 使 vibe 可用。
2. **action_space.py 本地定义 ACTION_NAMES**：避免 Stage 01 跨项目 import 依赖。Stage 02 会验证与 `BASIC_ACTION_ROUTES` 的 1:1 对齐。
3. **reward.py 从 observation delta 导出**：不依赖模拟器内部状态，所有信号来自 `own_units`/`visible_enemies`/`resources`/`mission` 公开字段。
4. **env.py 支持自定义 encoder**：便于测试注入和后续 Stage 03 PPO 策略直接消费。
