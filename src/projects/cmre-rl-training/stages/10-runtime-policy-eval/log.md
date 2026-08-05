# Stage 10 Log: Runtime Policy Evaluation

**Date**: 2026-08-05
**Stage**: 10-runtime-policy-eval
**Status**: BLOCKED FOR FRESH SC2 LEASE AND TERMINAL EVIDENCE

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
- **Evidence**:
  `artifacts/stage-10-runtime-policy-eval/20260805-bounded-64/evaluation-report.json`,
  `artifacts/stage-10-runtime-policy-eval/blocked-lease-dead-of-night/live-rl-report.json`,
  `artifacts/stage-10-runtime-policy-eval/blocked-lease-dead-of-night/launcher.err.log`。
- **Interpretation**: `sample_count=6`, `terminal_count=0`, and
  `runtime_clean=false`; no win rate is computed. This is a runtime lease block,
  not a policy defeat or victory.

## G5: Validation

- **Focused tests**: 24 passed for terminal parsing, evaluator commands,
  blocked summaries, and terminal-stop rollout behavior.
- **Full project tests**: 171 passed.
- **Compilation**: `py_compile` passed for all changed Python modules.
- **Runtime cleanup**: runner-owned SC2 PID snapshots are used for cleanup; the
  external owner PID `16288` was not touched.

## Outcome

Stage 10 implementation is ready for rerun when the external SC2 runtime lease is
released. The evaluator correctly refuses to turn bounded/no-terminal or
launcher-blocked runs into win-rate evidence. P2 remains native Computer and is
outside the ML-control claim.
