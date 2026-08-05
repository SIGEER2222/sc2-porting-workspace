# Stage 07 Plan: Runnable Multi-Map Training Entrypoint

## Objective

提供一个用户可以直接运行的基础训练命令：无需手工拼装 env factory、policy、grounder
或 checkpoint 路径，即可在多个 map profile 上执行 PPO，并保存可恢复的 checkpoint 和
JSON report。默认 simulator 模式使用内置最小 `SimulatorSession` 场景；fake 模式用于
快速安装/依赖 smoke。该阶段不宣称真实 SC2 胜率或全地图泛化。

## Outputs

```text
cmre_rl_training/training_cli.py
tools/train_multi_map.py
tests/test_training_cli.py
README.md
stages/07-training-entrypoint/{plan,result,log,issues}.{md,json}
```

## Contracts

- `python tools/train_multi_map.py --help` exits successfully and documents all training controls.
- `--backend simulator` runs actual `SimulatorSession -> SimulatorRlBackend -> CmreRLEnv -> PPO`.
- `--backend fake` runs a dependency-light smoke path with the same shared trainer.
- `--maps` accepts comma-separated map names; one shared policy is updated across all maps.
- A run writes `training-report.json` and `map-aware-policy.pt` under a repo-relative artifact directory.
- `--resume` loads a prior map-aware checkpoint and continues PPO updates.
- Non-finite training metrics, missing checkpoint, or zero collected steps cause a non-zero exit.

## Gates

| Gate | Verification |
|---|---|
| G1-cli-contract | help, argument validation, output paths |
| G2-fake-mvp | command executes end-to-end and emits report/checkpoint |
| G3-simulator-mvp | actual in-memory SimulatorSession completes training steps |
| G4-resume | second command loads the first checkpoint and trains again |
| G5-regression | existing project tests remain green |

## Completion

- [x] G1 CLI help, validation, and repo-relative artifact paths
- [x] G2 fake backend end-to-end report/checkpoint
- [x] G3 actual SimulatorSession end-to-end training
- [x] G4 checkpoint resume
- [x] G5 full regression suite

## Non-goals

- 不直接启动 `SC2_x64.exe`，不替代注册 launcher。
- 不把内置小场景结果当作真实地图胜率证据。
- 不修改 simulator、launcher、canonical commander mod 或 external sources。
