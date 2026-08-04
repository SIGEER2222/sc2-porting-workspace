# Stage 02 Log: Simulator Backend Integration

**Date**: 2026-08-04
**Stage**: 02-simulator-backend
**Status**: PASS

## Summary

将 `SimulatorSessionBackend` 接入 `CmreRLEnv`，验证 ACTION_NAMES 与 BASIC_ACTION_ROUTES 1:1 对齐，验证 encode_rl_observation 与 vibe/ml/encoder 的 49 维特征向量端到端对齐，实现 DomainRandomization 参数采样器。

## Evidence

### G1-backend-protocol (static)
- **Command**: `python -m unittest tests.test_simulator_backend.SimulatorRlBackendProtocolTests -v`
- **Result**: 2 tests, OK
- **Verified**: SimulatorRlBackend 实现 RlBackend Protocol（runtime_checkable isinstance 通过），state_version 属性返回 int

### G2-action-alignment (static)
- **Command**: `python -m unittest tests.test_alignment.ActionAlignmentTests -v`
- **Result**: 2 tests, OK
- **Verified**: `sorted(ACTION_NAMES) == sorted(BASIC_ACTION_ROUTES.keys())`，19 个动作 1:1 对齐

### G3-encoder-integration (static + runtime-local)
- **Command**: `python -m unittest tests.test_alignment.EncoderIntegrationTests -v`
- **Result**: 4 tests, OK
- **Verified**: `vibe.ml.encoder.FEATURE_NAMES` count=49，`encode_rl_observation` 产出 49 维向量，`rl_feature_count()` == `len(FEATURE_NAMES)`，`feature_schema_hash()` 稳定（SHA-256 hex 64 chars）
- **Dependencies**: torch (CPU) installed via pip

### G4-env-loop-sim (runtime-local)
- **Command**: `python -m unittest tests.test_simulator_backend.SimulatorRlBackendLoopTests -v`
- **Result**: 5 tests, OK
- **Verified**: SimulatorRlBackend reset/step 闭环；CmreRLEnv + SimulatorRlBackend 完整 episode 跑通到 terminated；state_version 递增
- **Note**: 使用 MockSimulatorSession + `@patch("vibe.contracts.Observation.from_world")` 绕过 sc2_simulator 依赖。真实 SimulatorSession 集成见 ISSUE-004

### G5-dr-params (runtime-local)
- **Command**: `python -m unittest tests.test_domain_randomization -v`
- **Result**: 10 tests, OK
- **Verified**: DomainRandomization 采样参数在合理范围内（wave_strength [0.8,1.2]、time_scale [0.8,1.2]、fog [10,20]、enemy_damage [0.7,1.0]、structure_health [0.5,1.0]）；seed 可复现；call_count 递增

## Changed Paths

- `src/projects/cmre-rl-training/cmre_rl_training/simulator_backend.py` — SimulatorRlBackend
- `src/projects/cmre-rl-training/cmre_rl_training/domain_randomization.py` — DomainRandomization + ScenarioParams
- `src/projects/cmre-rl-training/tests/test_alignment.py` — G2 + G3 测试
- `src/projects/cmre-rl-training/tests/test_domain_randomization.py` — G5 测试
- `src/projects/cmre-rl-training/tests/test_simulator_backend.py` — G1 + G4 测试

## Test Run

```
PYTHONPATH=.:../cmre-neuro-adapter:../cmre-porting python -m unittest discover -s tests -v
Ran 70 tests in 2.841s
OK
```

## Dependencies Installed

- `numpy` (Stage 01)
- `torch` (CPU, Stage 02 — for vibe.ml.encoder)
