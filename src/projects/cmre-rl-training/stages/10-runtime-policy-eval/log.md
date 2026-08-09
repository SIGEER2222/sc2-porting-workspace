# Stage 10 Log: Runtime Policy Evaluation

**Date**: 2026-08-05
**Stage**: 10-runtime-policy-eval
**Status**: BLOCKED FOR MISSION TERMINAL EVIDENCE

## G1: Terminal Contract

- **Result**: PASS offline — raw `ResponseObservation.player_result` is normalized
  into `player_result`, `mission.terminated`, `mission.end_reason`, and
  `mission.win_condition=player_result`.
- **Evidence**: `cmre_rl_training/live_sc2_session.py`,
  `tests/test_live_sc2_session.py::LiveActionSpecTests.test_player_result_becomes_terminal_mission_state`。
- **Details**: victory, defeat, tie, and undecided result names are retained;
  `RawSc2Backend` already terminates on the normalized result.

## G2: Held-Out Map Matrix Contract

- **Command**: `python src/projects/cmre-rl-training/tools/evaluate_live_policy.py ... --map dead-of-night|亡者之夜.SC2Map|... --map void-launch|虚空降临.SC2Map|... --dry-run`
- **Result**: PASS static — generated 2 maps x 3 variants = 6 fresh-run commands,
  with independent ports, checkpoint SHA-256, terminal stop, replay save, and
  report paths.
- **Evidence**: `artifacts/stage-10-runtime-policy-eval/dry-run-2/evaluation-report.json`。

## G3: Baseline And Trace Contract

- **Result**: PASS offline — frozen-stochastic, live-update, and deterministic-
  baseline variants are represented; action trace records decision index, action,
  loop-before/after, grounded target, raw results, and errors.
- **Evidence**: `tools/evaluate_live_policy.py`,
  `cmre_rl_training/live_sc2_session.py`,
  `tests/test_live_policy_eval.py`。
- **Replay**: `LiveRawSc2Session.save_replay()` requests native SC2 replay bytes
  before LeaveGame; the runner writes `live-replay.SC2Replay` under the run directory.

## G4: Fresh Runtime Attempt

- **Command**: `python src/projects/cmre-rl-training/tools/evaluate_live_policy.py ... --max-steps 64 --step-mul 8 --port-start 5960 --output-dir src/projects/cmre-rl-training/artifacts/stage-10-runtime-policy-eval/20260805-bounded-64`
- **Result**: BLOCKED — all 6 subprocess reports were rejected by the approved
  launcher because an external runtime owner held PID `20740` on port `5965`.
  A subsequent isolated retry on port `5967` was rejected by the same launcher
  with external PID `16288`, port `5966`, session `zchar01_reborn_port`.
  After that owner released, a fresh retry on ports `5970-5975` was again rejected
  by external PID `48212`, with unknown port and session
  `cmre_alenger-20260805-205220-7132742a`.
  A further retry on the same ports was rejected by external PID `69888`, a
  `-KeepAlive` `launch-cmre-alenger.ps1` process for `zchar01_reborn_port`; its
  SC2 child was PID `52096` listening on port `6119`, session
  `cmre_alenger-20260805-205731-6abdb4cd`.
- **Evidence**:
  `artifacts/stage-10-runtime-policy-eval/20260805-bounded-64/evaluation-report.json`,
  `artifacts/stage-10-runtime-policy-eval/blocked-lease-dead-of-night/live-rl-report.json`,
  `artifacts/stage-10-runtime-policy-eval/blocked-lease-dead-of-night/launcher.err.log`,
  `artifacts/stage-10-runtime-policy-eval/20260805-bounded-64-retry/evaluation-report.json`,
  `artifacts/stage-10-runtime-policy-eval/20260805-bounded-64-retry-2/evaluation-report.json`,
  `artifacts/stage-10-runtime-policy-eval/20260805-bounded-64-retry-2/dead-of-night-frozen-stochastic/launcher.err.log`。
- **Interpretation**: `sample_count=6`, `terminal_count=0`, and
  `runtime_clean=false`; no win rate is computed. This is a runtime lease block,
  not a policy defeat or victory.

## G5: Validation

- **Focused tests**: 24 passed for terminal parsing, evaluator commands,
  blocked summaries, and terminal-stop rollout behavior.
- **Full project tests**: 171 passed.
- **Compilation**: `py_compile` passed for all changed Python modules.
- **Runtime cleanup**: runner-owned SC2 PID snapshots are used for cleanup; the
  external owner PIDs `16288`, `48212`, and `69888` were not touched. The latest
  owner was still alive after the retry and is a separate `-KeepAlive` session.

## G6: Current-Map Victory-First MVP

- **Simulator**: `train_multi_map.py --backend simulator --maps dead-of-night`
  resumed the existing checkpoint for 10 iterations / 640 steps and emitted
  `artifacts/current-map-victory-20260805/map-aware-policy.pt`; the training
  report status is `passed` with `total_mean_reward=151.2`.
- **Runtime**: a current-map run on port `5991` reached API readiness,
  `CreateGame`, `JoinGame`, frame advancement, 581 successful actions, and
  native replay save over 2048 decisions through loop `16384`; same-window
  ScriptError was clean. No `player_result` arrived before the bounded cutoff,
  so this is runtime bridge evidence, not a victory claim.
- **UI diagnosis**: the launcher log records `commander selection code disabled`
  and `headless startup patch`; the visible frontend was the SC2 API bootstrap
  window. `run_live_rl.py` now passes approved-launcher `-DebugMode`, which
  minimizes that frontend while preserving API `CreateGame+JoinGame` map entry.
- **Headless runtime**: a fresh run with the new flag on port `6001` passed the
  full API bridge: `CreateGame`, `JoinGame`, frame advancement, 578 successful
  actions, 2048 decisions through loop `16384`, native replay save, and clean
  same-window ScriptError verdict. The launcher recorded `commander selection
  code disabled`, `headless startup patch`, `SC2 API mode (ApiMinimal)`, and
  `DebugMode: SC2 窗口已最小化`. No `player_result` arrived before the bounded
  cutoff, so the map-entry/UI issue is resolved but mission victory remains
  unverified.

## Outcome

Stage 10 now has a current-map victory-first path and a verified direct map-entry
surface with the bootstrap window minimized. The runtime bridge is proven through
`CreateGame+JoinGame` and bounded action/replay evidence, while a real mission
victory remains unverified because the 2048-decision run had no `player_result`.
The evaluator correctly refuses to turn bounded/no-terminal or launcher-blocked
runs into a win-rate claim. P2 remains native Computer and is outside the
ML-control claim.

## G7: DirectMapApi Attach Retry

- **Static implementation**: `tools/run_live_rl.py` now launches the approved
  `-DirectMapApi` path and constructs `LiveRawSc2Session(join_existing=True)`,
  so the runner does not issue `CreateGame`. `Sc2ApiClient` reconnects after a
  SC2 WebSocket close, while `JoinGame` retries for the map initialization
  window. Ordinary action/step requests are not replayed automatically.
- **Focused validation**: `test_direct_map_attach_skips_create_game` and the
  transient JoinGame retry test passed; full project suite passed with 173
  tests; changed Python modules compiled.
- **Runtime attempt**: command
  `python src/projects/cmre-rl-training/tools/run_live_rl.py ... --port 6004
  --max-steps 64 --step-mul 8 --stop-on-terminal --save-replay` was rejected
  before API readiness by the approved launcher because external
  `owner_pid=44508` held the SC2 runtime lease for
  `zchar01_reborn_port.SC2Map`. The runner did not terminate that process.
- **Evidence**:
  `artifacts/stage-10-runtime-policy-eval/direct-map-entry-retry-6004/live-rl-report.json`,
  `artifacts/stage-10-runtime-policy-eval/direct-map-entry-retry-6004/launcher.err.log`。
  This is a truthful runtime block (`api_ready=false`), not proof of map entry
  or victory; DirectMapApi still needs a fresh lease-available run.

## Current Outcome

The direct-entry implementation and attach contract are in place, but current
runtime evidence is blocked by an external SC2 process. The previous
ApiMinimal/CreateGame runs remain historical bridge evidence only; they do not
validate the new DirectMapApi path. No mission victory or win rate is claimed.

## G8: PPO Exploration Stabilization

- **Static implementation**: `PPOTrainer` now applies `ent_floor` as a true
  differentiable entropy penalty. The previous form cancelled the entropy
  gradient below the floor, so it recorded an anti-collapse parameter without
  actually pushing low-entropy policies back toward exploration. The GAE docs
  were also corrected to distinguish normalized value targets from advantage
  normalization.
- **Reproducibility**: `train_multi_map.py` reports `ent_coef` and `ent_floor`
  in `training-report.json`, and the checkpoint training metadata records the
  same values. This makes simulator smoke runs reproducible from their report
  and checkpoint alone.
- **Focused validation**: PPO/training/self-training focused tests passed with
  15 tests, including new regression coverage for below-floor entropy gradient,
  above-floor standard entropy bonus behavior, and CLI report propagation of
  the exploration parameters.
- **Simulator evidence**: command
  `python src/projects/cmre-rl-training/tools/train_multi_map.py --backend simulator --maps dead-of-night --iterations 3 --rollout-steps 32 --max-episode-steps 64 --ppo-epochs 2 --batch-size 16 --ent-coef 0.05 --ent-floor 0.5 --step-loops 16 --output-dir src/projects/cmre-rl-training/artifacts/stage-10-runtime-policy-eval/entropy-floor-smoke-20260809`
  completed 96 simulator steps and emitted a passed report plus checkpoint.
  PPO losses were finite and entropy stayed in the 2.37-2.43 range.
- **Full validation**: `PYTHONPATH=src/projects/cmre-rl-training;src/projects/cmre-neuro-adapter;src/projects/cmre-porting python -m unittest discover -s src/projects/cmre-rl-training/tests -v`
  passed 176 tests with 14 expected BC-checkpoint skips.
- **Boundary**: this is offline/simulator training evidence only. No live
  `player_result`, mission victory, or win rate is claimed from this pass.
