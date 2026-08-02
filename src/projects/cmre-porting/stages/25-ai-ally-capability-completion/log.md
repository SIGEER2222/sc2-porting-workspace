# Stage 25 Log

## Status

In progress. The stage is active because implementation of the requested P1/P2
cooperative AI ally behavior has begun.

## Evidence

- `static`: Stage 25 plan and write scope were reviewed before editing.
- `static`: the simulator already has reciprocal-capable `ScenarioPlayer.allies`
  and `PlayerRegistry.is_ally/is_enemy` primitives; the new contract now keeps
  P1 and P2 ownership separate and exposes P1 to P2 only through visible allies.
- `simulator`: seeds `42`, `7`, and `99` all report reciprocal roster-ready
  P1-human/P2-AI state, P2-only action entity ownership, 62 successful
  dispatches, zero friendly-fire rejections, zero hidden-state violations, and
  no deadlock/oscillation/command storm. The three trace hashes are identical.
  Evidence: `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/simulator-multiseed.json`.
- `runtime`: a pre-existing protected window was observed read-only at
  `127.0.0.1:5151`: GameInfo reported P1 participant/P2 computer and raw
  observation showed four owner=2 units with alliance=2. This is context only,
  not Stage 25 acceptance evidence because no command was sent to that window.
- `blocked`: the fresh approved launcher command on port `5142` was rejected
  with `SC2_RUNTIME_BUSY` for the protected PID `37884`/port `5151`; no fresh
  ScriptError verdict was claimed. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-20260802/runtime-verdict.json`.
- `blocked`: after the first protected process exited, a second fresh launcher
  attempt was rejected by a new protected lease, PID `40408`/port `5152`.
  Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-20260802-pass1/runtime-verdict.json`.

## Changes

- `Observation` now exposes `visible_allies` and an alliance summary filtered by
  vision and reciprocal alliance.
- `AllyPolicy` is a P2-owned state machine with P1 command authorization,
  deduplication, text notices, safety priority, and ally-safe targeting.
- `ActionAdapter` attributes every dispatch to P2 and blocks P1/ally targets.
- The live runner now sends P1 `ActionChat(!ally ...)` commands and records P2
  raw alliance, owner, position deltas, Bank acknowledgements, and chat events;
  it no longer sends P1-owned raw actions as the AI ally.
- The Galaxy kernel and its debug/map mirrors register the P1-only `!ally`
  trigger. It issues orders only to P2 units and writes status/result signals.

## Validation

- `python -m pytest -q src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_ai_ally_capability.py` -> `5 passed`.
- `python -m pytest -q src/projects/cmre-porting/stages/19-simulator-ai-ally-clearance/test_simulator_ai_ally_clearance.py src/projects/cmre-porting/stages/20-simulator-ai-ally-adversarial-hardening/test_adversarial_hardening.py` -> `9 passed, 3 subtests passed`.
- `python -m pytest -q tools/launchers/tests/test_live_runner_unit_adapter.py tools/galaxy-vibe/tests/test_kernel.py tools/launchers/tests/test_launch_cmre_alenger_static.py` -> `58 passed`.
- `powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/run-all-validation.ps1` -> `52/52 passed, 0 warnings`.
- `python -m py_compile src/projects/cmre-porting/vibe/run_dead_of_night_live.py tools/launchers/tests/test_live_runner_unit_adapter.py` -> pass.
- `git diff --check` -> pass; only line-ending normalization warnings were emitted.

## Stop Condition

Simulator and static gates are complete. Stage 25 remains `IN_PROGRESS` until
all protected runtime leases are released and a fresh approved-launcher window
proves P1 ActionChat -> Galaxy P2 order -> RequestStep state change with a
same-window ScriptError check.
