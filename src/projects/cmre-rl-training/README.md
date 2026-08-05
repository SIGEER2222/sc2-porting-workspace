# CMRE RL Training

This project provides a shared map-conditioned PPO loop for cooperative PvE
tactics. One policy is updated across the selected map profiles; the rollout
uses observation-driven action grounding and writes a resumable checkpoint.

The current MVP is victory-first training on `dead-of-night`. Multi-map
generalization and adversarial opponents are optional follow-up work; they are
not required to run the current-map loop.

## Current Map Victory-First Run

Continue training on the current map only:

```powershell
python src/projects/cmre-rl-training/tools/train_multi_map.py `
  --backend simulator --maps dead-of-night --iterations 10 `
  --rollout-steps 64 --max-episode-steps 64 --device cpu `
  --resume artifacts/projects/cmre-rl-training/multi-map-training/map-aware-policy.pt `
  --output-dir src/projects/cmre-rl-training/artifacts/current-map-victory
```

Run the policy through the approved launcher and stop only on a real mission
`player_result` or the explicit bounded cutoff:

```powershell
python src/projects/cmre-rl-training/tools/run_live_rl.py `
  --checkpoint src/projects/cmre-rl-training/artifacts/current-map-victory/map-aware-policy.pt `
  --map-name dead-of-night --launcher-map-name 亡者之夜.SC2Map `
  --map-path artifacts/live-maps/亡者之夜_live_packed.SC2Map `
  --port 5992 --max-steps 2048 --step-mul 8 `
  --stop-on-terminal --save-replay --variant current-map-victory
```

The live runner starts the approved launcher in minimized Debug/API mode, so
the native commander-selection frontend is not the visible control surface.
The runtime gate still requires API readiness, `CreateGame`, `JoinGame`, frame
progress, successful actions, and clean same-window ScriptError evidence.

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

## Run A Live Rollout

After producing a checkpoint, run a bounded participant-side rollout through the
approved launcher:

```powershell
python src/projects/cmre-rl-training/tools/run_live_rl.py `
  --checkpoint artifacts/projects/cmre-rl-training/multi-map-training/map-aware-policy.pt `
  --map-path artifacts/live-maps/亡者之夜_live_packed.SC2Map `
  --max-steps 8 --step-mul 8 --train
```

The report is written under `artifacts/stage-09-live-rl-bridge/`. A runtime PASS
requires API readiness, CreateGame/JoinGame, frame advancement, at least one
successful action result, and a clean same-window ScriptError scan. The bounded
reward is an observation-derived runtime proxy; it is not a mission win-rate
claim. The ML-controlled participant is P1; a native Computer P2 remains the
environment opponent.

## Evaluate Across Maps

The Stage 10 evaluator runs frozen-stochastic, live-update, and deterministic
variants for every supplied map. Each run uses a fresh approved launcher,
stops only on a real `player_result` or the bounded step limit, and saves the
native replay when the runtime is reachable:

```powershell
python src/projects/cmre-rl-training/tools/evaluate_live_policy.py `
  --checkpoint artifacts/projects/cmre-rl-training/multi-map-training/map-aware-policy.pt `
  --map 'dead-of-night|亡者之夜.SC2Map|artifacts/live-maps/亡者之夜_live_packed.SC2Map' `
  --map 'void-launch|虚空降临.SC2Map|src/projects/cmre-rl-training/artifacts/live-maps/void-launch_live_packed.SC2Map' `
  --max-steps 64 --step-mul 8
```

The map-aware policy is evaluated as P1. P2 remains a native Computer, and a
bounded run without `player_result` is reported as inconclusive rather than a
win or loss.
