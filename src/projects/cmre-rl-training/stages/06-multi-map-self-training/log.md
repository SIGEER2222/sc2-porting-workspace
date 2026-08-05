# Stage 06 Log: Multi-Map Adaptive Self-Training

**Date**: 2026-08-05
**Stage**: 06-multi-map-self-training
**Status**: PASSED

## Outcome

实现了一个共享的地图条件策略训练闭环：基础 49 维 BC observation 保持不变，
环境追加固定 8 维 map context；同一个 `MapAwareP2AllyAC` 在多个地图 factory
之间轮换，通过 strict target mask 和 `ActionGrounder` 生成 observation-driven
的 canonical action arguments，再由 PPO 更新共享 trunk、地图投影、action/value heads。

真实 SC2 的边界是注入式 `RawSc2Session`：session 负责 raw protocol 的 Create/Join、
Observation、RequestAction、RequestStep、Leave 生命周期，RL backend 只做状态归一化和
终止/动作结果传播，不伪造 loop 或 mission progression。

## Evidence

### G1-map-context (runtime-local)

- **Command**: `python -m unittest tests.test_map_profiles tests.test_map_aware -v`
- **Result**: PASS — 6 tests
- **Verified**: known map、`.SC2Map` 文件名和 unknown fallback 均确定性解析；context
  宽度固定为 8，schema hash 稳定；地图 profile 会优先使用当前可见敌人质心作为攻击点。

### G2-action-grounding (runtime-local)

- **Command**: `python -m unittest tests.test_action_grounding -v`
- **Result**: PASS — 3 tests
- **Verified**: attack/gather/load/point actions 使用 observation 中的 entity/tag 和坐标；
  缺失目标抛出 `ActionGroundingError`；transport-specific ability ID 不进入策略层。

### G3-map-aware-policy (runtime-local)

- **Command**: `python -m unittest tests.test_map_aware -v`
- **Result**: PASS — 3 tests
- **Verified**: map context appended 后 input 为 57 维；masked logits/value 输出形状正确；
  现有 BC checkpoint 可 warm-start shared trunk；map-aware checkpoint roundtrip 保持输出一致。

### G4-raw-backend (runtime-local contract)

- **Command**: `python -m unittest tests.test_raw_sc2_backend -v`
- **Result**: PASS — 1 test
- **Verified**: injected raw session 的 loop、visible enemies、dispatch result、action
  arguments、monotonic state_version 和 mission termination 均被保留；`close()` 调用 Leave。

### G5-self-training (runtime-local MVP)

- **Command**: `python -m unittest tests.test_self_training -v`
- **Result**: PASS — 1 test
- **Verified**: 一个共享 policy 在 `Dead of Night` 和 `Void Launch` 两个 profile 上各完成
  4 步 rollout + PPO update，共 8 steps；返回 per-map metrics、total metrics，并生成可加载
  的 map-aware checkpoint。

### G6-regression

- **Command**: `PYTHONPATH=.;..\\cmre-neuro-adapter;..\\cmre-porting python -m unittest discover -s tests -v`
- **Result**: PASS — 153 tests, 0 failures
- **Command**: `python -m json.tool project.json`
- **Result**: PASS — project manifest is valid JSON

## Changed Paths

- `cmre_rl_training/map_profiles.py` — profile registry, fallback, fixed context schema
- `cmre_rl_training/map_aware.py` — context environment, contextual AC, checkpoint helpers
- `cmre_rl_training/action_grounding.py` — canonical actor/target/point grounding
- `cmre_rl_training/raw_sc2_backend.py` — raw session adapter contract and normalization
- `cmre_rl_training/self_training.py` — multi-map shared PPO trainer and metrics
- `cmre_rl_training/action_space.py` — optional strict target-aware masks
- `cmre_rl_training/rollout.py` — optional action-builder callback
- `cmre_rl_training/ppo.py` — policy-device-aware minibatch tensors
- `tests/test_map_profiles.py`, `test_map_aware.py`, `test_action_grounding.py`,
  `test_raw_sc2_backend.py`, `test_self_training.py`
- `project.json`, `stages/06-multi-map-self-training/plan.md`, `result.json`, `issues.json`

## Limitations

- 本阶段验证的是 runtime-local fake/simulator 环境的自训练闭环，不是所有真实地图的胜率泛化证明。
- 真实 SC2 全地图矩阵、跨地图任务奖励与动作的因果收益、以及自动从 Catalog/地图元数据发现
  完整战略 profile 仍需后续 runtime gate。
- `FakeBackend` 的奖励仍非动作相关，因此本阶段不声称 PPO 已提升真实任务胜率。
