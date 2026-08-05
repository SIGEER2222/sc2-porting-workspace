# Stage 09 Log: Live RL Bridge

**Date**: 2026-08-05
**Stage**: 09-live-rl-bridge
**Status**: PASS WITH EXPLICIT TOPOLOGY AND REWARD BOUNDARIES

## G1: Protocol And Action Contract

- **Command**: `PYTHONPATH=.;..\cmre-neuro-adapter;..\cmre-porting python -m unittest tests.test_live_sc2_session -v`
- **Result**: PASS — 8 focused tests passed.
- **Evidence**: `cmre_rl_training/live_sc2_session.py`, `tests/test_live_sc2_session.py`。
- **Details**: all 19 policy actions resolve to raw action specs; canonical entity IDs,
  point targets, unit targets, standard Catalog IDs (`SCV=45`, `Marine=48`,
  `Medivac=54`, `Barracks=21`), and the `ActionRaw -> sc2api.Action(action_raw=...)`
  envelope are covered.

## G2: Offline Bridge MVP

- **Result**: PASS — fake raw session completed
  `RawSc2Backend -> CmreRLEnv -> MapAwareEnv -> MapAwareP2AllyAC` rollout with finite
  observations, strict target mask, grounded action dispatch, and loop advancement.
- **Evidence**: `tests/test_live_sc2_session.py::OfflineLiveBridgeTests`。

## G3: Fresh Approved-Launcher Runtime Rollout

- **Command**: `python src/projects/cmre-rl-training/tools/run_live_rl.py --checkpoint artifacts/projects/cmre-rl-training/multi-map-training/map-aware-policy.pt --map-path artifacts/live-maps/亡者之夜_live_packed.SC2Map --port 5953 --max-steps 8 --step-mul 8 --launcher-suffix rl-bridge-20260805-verified-2 --output src/projects/cmre-rl-training/artifacts/stage-09-live-rl-bridge/20260805-dead-of-night-6/live-rl-report.json --train`
- **Result**: PASS — the runner returned exit code 0 and the fresh launcher produced
  an empty `launcher.err.log`.
- **Evidence**: `artifacts/stage-09-live-rl-bridge/20260805-dead-of-night-6/live-rl-report.json`,
  `artifacts/stage-09-live-rl-bridge/20260805-dead-of-night-6/launcher.log`,
  `artifacts/stage-09-live-rl-bridge/20260805-dead-of-night-6/launcher.err.log`。
- **Runtime facts**: `api_ready=true`, `create_game=true`, `join_game=true`,
  `steps_collected=8`, `loop_start=0`, `loop_end=64`, `request_steps=8`,
  `requested_step_loops=64`, `action_requests=8`, `action_successes=3`,
  `action_results_observed=true`, `training_update_applied=true`。
- **Reward boundary**: `reward_sum=4.921875` is an observation-derived runtime
  proxy only; it is not a mission win-rate or tactical-improvement claim.

## G4: ScriptError Gate

- **Result**: PASS — the same runtime window reported `checked=true`,
  `has_new_errors=false`, `count=0`。
- **Evidence**: `artifacts/stage-09-live-rl-bridge/20260805-dead-of-night-6/live-rl-report.json`。

## G5: Evidence Consistency

- The final report has `runtime_gate=true`, `status=passed`, and no runner error.
- The launcher log records API listening on port `5953` with a fresh SC2 process;
  the launcher error log is zero bytes.
- An earlier stale-port false positive was rejected and not used as final evidence.
  The runner now preflights the requested port unless `--skip-launch` is explicit.
- The raw action envelope bug found during the first fresh attempt was fixed and
  locked by `test_raw_action_is_wrapped_in_sc2api_action_envelope`。

## Outcome

Stage 09 is verified for P1 participant control: a map-aware PPO checkpoint can be
loaded, grounded through the shared 19-action contract, dispatched to real SC2, and
updated once from a bounded live rollout. P2 remains a native Computer and is not an
external ML action issuer. Mission terminal reward and held-out-map tactical uplift
remain the next stage's responsibility.
