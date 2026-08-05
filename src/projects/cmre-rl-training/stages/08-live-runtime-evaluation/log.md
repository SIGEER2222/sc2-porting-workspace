# Stage 08 Log: Live Runtime Evaluation

**Date**: 2026-08-05
**Stage**: 08-live-runtime-evaluation
**Status**: BLOCKED FOR LIVE RL ACCEPTANCE

## Run 1: Native Live Baseline

- **Launcher command**: `pwsh -NoProfile -ExecutionPolicy Bypass -File tools/launchers/launch-cmre-alenger.ps1 -MapName 亡者之夜.SC2Map -Commander TerranRaynor -ListenPort 5940 -ApiMinimal -DebugMode -KeepAlive -MapCopySuffix rl-live-20260805`
- **Runner command**: `PYTHONPATH=src/projects/cmre-porting;reference/SC2-Neuro-API-Integration python -m vibe.run_dead_of_night_live --port 5940 --map <SC2_INSTALL>/Maps/亡者之夜_p0_default_packed.SC2Map --max-loops 1500 --step-size 4 --decision-interval 22 --output src/projects/cmre-rl-training/artifacts/stage-08-live-smoke/20260805-dead-of-night/live-runtime-report.json`
- **Runtime result**: CreateGame/JoinGame reached P1, frames advanced to loop 1501, P2 Computer roster and 13 P2-owned visible units were observed, and 4/4 dispatched actions succeeded.
- **Verdict**: `INCONCLUSIVE`; P2 is a native Computer, not an externally controlled participant, and the bounded run did not reach the full build/train/attack/victory contract.
- **ScriptError**: PASS, `has_new_errors=false`, `count=0`.
- **Evidence**: `artifacts/stage-08-live-smoke/20260805-dead-of-night/live-runtime-report.json`, `live-replay.SC2Replay`, `live-replay.jsonl`, `script-error-verdict.json`.

## Run 2: P1 PyTorch Runtime Probe

- **Launcher command**: same approved launcher shape on port `5941`, with map copy suffix `rl-p1-ml-20260805-retry`.
- **Runner command**: same live runner with `--p1-model artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/ml-p1-action-pytorch-20260804/p1-action.pt` and output under `artifacts/stage-08-live-smoke/20260805-dead-of-night-p1-ml/`.
- **Runtime result**: CreateGame/JoinGame reached P1, frames advanced to loop 1501, 4/4 dispatched actions succeeded, `p1_ml_model_loaded=true`, `p1_ml_decision_observed=true`, and `p1_ml_dispatch_label_observed=true`.
- **Verdict**: `INCONCLUSIVE`; the loaded checkpoint is P1 imitation learning, not Stage 07 map-aware PPO, and native P2 topology remains unavailable for external ML control.
- **ScriptError**: PASS, `has_new_errors=false`, `count=0`.
- **Evidence**: `artifacts/stage-08-live-smoke/20260805-dead-of-night-p1-ml/p1-ml-runtime-report.json`, `p1-ml-replay.SC2Replay`, `p1-ml-replay.jsonl`, `script-error-verdict.json`.

## Outcome

真实 SC2 安装、approved launcher、SC2 API、CreateGame/JoinGame、frame stepping、动作结果和
ScriptError gate 均已验证。当前没有足够证据声称 `cmre-rl-training` 的多地图 PPO 已在真实
SC2 中训练或提升战术收益；该边界转入下一阶段。
