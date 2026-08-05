# Stage 07 Log: Runnable Multi-Map Training Entrypoint

**Date**: 2026-08-05
**Stage**: 07-training-entrypoint
**Status**: PASSED

## Outcome

提供了用户可直接运行的训练入口：

```text
python src/projects/cmre-rl-training/tools/train_multi_map.py --backend simulator
```

入口默认使用真实 `SimulatorSession`，不启动 SC2；它创建两个 map profile 的环境，
复用 `MultiMapSelfTrainer`、地图条件 policy、strict action mask 和 ActionGrounder，
训练结束后写出 `training-report.json` 与 `map-aware-policy.pt`。`--backend fake` 提供
快速依赖 smoke，`--resume` 支持从既有 map-aware checkpoint 继续训练，`--scenario` 和
`--scenario-map MAP=PATH` 支持替换 simulator 场景。

## Evidence

### G1-cli-contract (runtime-local)

- **Command**: `python src/projects/cmre-rl-training/tools/train_multi_map.py --help`
- **Result**: PASS — 参数帮助正常输出并退出 0。
- **Verified**: backend/maps/iterations/rollout/checkpoint/resume/BC/device/scenario 参数均可见。

### G2-fake-mvp (runtime-local)

- **Command**: `python src/projects/cmre-rl-training/tools/train_multi_map.py --backend fake --maps dead-of-night,void-launch --iterations 1 --rollout-steps 4 --max-episode-steps 4 --hidden-dim 16 --ppo-epochs 1 --batch-size 4 --output-dir artifacts/stage-07-training-entrypoint/fake-smoke`
- **Result**: PASS — two maps, 8 total steps, report and checkpoint emitted。

### G3-simulator-mvp (simulator)

- **Command**: `python src/projects/cmre-rl-training/tools/train_multi_map.py --backend simulator --maps dead-of-night,void-launch --iterations 1 --rollout-steps 4 --max-episode-steps 4 --hidden-dim 16 --ppo-epochs 1 --batch-size 4 --output-dir artifacts/stage-07-training-entrypoint/mvp`
- **Result**: PASS — actual `SimulatorSession -> SimulatorRlBackend -> CmreRLEnv -> PPO` path completed 8 steps。
- **Evidence**: `artifacts/stage-07-training-entrypoint/mvp/training-report.json`，
  `artifacts/stage-07-training-entrypoint/mvp/map-aware-policy.pt`。

### G4-resume (simulator)

- **Command**: `python src/projects/cmre-rl-training/tools/train_multi_map.py --backend simulator --maps dead-of-night,void-launch --iterations 1 --rollout-steps 2 --max-episode-steps 2 --hidden-dim 16 --ppo-epochs 1 --batch-size 2 --resume artifacts/stage-07-training-entrypoint/mvp/map-aware-policy.pt --output-dir artifacts/stage-07-training-entrypoint/resume-smoke`
- **Result**: PASS — prior map-aware checkpoint loaded and a further 4 steps completed。

### G5-regression

- **Command**: `PYTHONPATH=.;..\\cmre-neuro-adapter;..\\cmre-porting python -m unittest discover -s tests -v`
- **Result**: PASS — 157 tests, 0 failures。
- **Command**: `python -m json.tool src/projects/cmre-rl-training/project.json`
- **Result**: PASS。

## Changed Paths

- `cmre_rl_training/training_cli.py` — CLI orchestration, built-in scenario, resume and scenario overrides
- `tools/train_multi_map.py` — repository-facing executable wrapper
- `tests/test_training_cli.py` — CLI/fake/simulator/resume coverage
- `README.md` — user commands and runtime boundary
- `.gitignore` — keep generated project-local training outputs out of source control
- `stages/07-training-entrypoint/{plan,log,result,issues}`

## Limitations

- 内置 simulator 场景是可运行训练 harness，不是实际 SC2 地图复刻，也不提供真实地图胜率证据。
- 当前 report 的 reward 仍依赖现有 observation-derived reward；动作因果收益需要更完整任务场景验证。
- 真实 SC2 训练仍需后续把 raw session 连接到注册 launcher，并记录 runtime/API/GameLogs 证据。
