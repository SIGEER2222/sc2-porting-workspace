# CMRE RL Training

This project provides a shared map-conditioned PPO loop for cooperative PvE
tactics. One policy is updated across the selected map profiles; the rollout
uses observation-driven action grounding and writes a resumable checkpoint.

## Run Training

From the repository root:

```powershell
python src/projects/cmre-rl-training/tools/train_multi_map.py --backend simulator
```

For a short dependency smoke:

```powershell
python src/projects/cmre-rl-training/tools/train_multi_map.py `
  --backend fake --iterations 2 --rollout-steps 32 --max-episode-steps 32
```

Useful controls:

```text
--maps dead-of-night,void-launch
--iterations 10
--rollout-steps 64
--max-episode-steps 64
--resume artifacts/projects/cmre-rl-training/multi-map-training/map-aware-policy.pt
--bc-checkpoint artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/ml-ally-policy-pytorch-20260804/ally-intent.pt
--device auto|cpu|cuda
```

The default simulator mode uses a small built-in `SimulatorSession` scenario,
so it does not launch SC2. To use an existing simulator scenario JSON:

```powershell
python src/projects/cmre-rl-training/tools/train_multi_map.py `
  --backend simulator --scenario path/to/scenario.json
```

For different scenarios per map, repeat `--scenario-map` with `MAP=PATH`.
Outputs are written under `artifacts/` by default:

```text
training-report.json
map-aware-policy.pt
```

These simulator results establish a runnable training path. They are not
real-SC2 win-rate or all-map generalization evidence; live validation must use
the registered launcher and its runtime evidence gates.
