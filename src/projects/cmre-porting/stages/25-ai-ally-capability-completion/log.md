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
- `runtime`: fresh approved launcher epoch `2026-08-02T14:50:24+08:00` on
  port `5152` passed `CreateGame + JoinGame`, and the same-window native task
  reached loop `5504` with victory. Native action success counts were
  `gather=17`, `train=6`, `move=442`, `attack=35`; strategy audit was PASS
  with empty debug/injection operation lists. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-native-task-pass6/runtime-native-strategy-pass7.json`.
- `runtime`: the current staged map was repacked with the existing StormLib
  tool and passed a fresh `CreateGame + JoinGame`; same-websocket
  `function.invoke` returned `vibe.test.ping -> pong` and
  `vibe.query.units(SCV) -> count=12`. The typed client rejected the unknown
  function locally as `FUNCTION_NOT_FOUND`. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-native-task-pass6/debug-function-probe-pass7.txt`.
- `runtime`: the same launcher epoch has no new non-empty ScriptError files.
  Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-native-task-pass6/script-error-verdict.json`.
- `blocked`: P1 `ActionChat(!ally ...)` messages are visible in SC2
  observations, but the fresh runtime report still has empty `bank_after` and
  `p2_command_ack_observed=false`; P2 alliance/owner observation is valid, but
  Galaxy command acknowledgement and resulting order cannot be claimed.

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
- Removed the stray `+` before the cooperative ally section in the project map
  Galaxy mirror before repacking the current runtime map.

## Validation

- `python -m pytest -q src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_ai_ally_capability.py` -> `6 passed`.
- Stage 25 + Stage 19 + Stage 20 regression -> `15 passed, 3 subtests passed`.
- Stage 22 + Stage 23 typed combat regression -> `16 passed, 3 subtests passed`.
- `python -m pytest -q tools/launchers/tests/test_live_runner_unit_adapter.py tools/galaxy-vibe/tests/test_kernel.py tools/launchers/tests/test_launch_cmre_alenger_static.py` -> `58 passed`.
- `powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/run-all-validation.ps1` -> `52/52 passed, 0 warnings`.
- `python -m py_compile` over Stage 25 runtime/policy modules and focused tests -> pass.
- `git diff --check` -> pass.
- `python tools/mpq/scripts/pack_stormlib.py ...` -> packed 76 files; the
  existing `verify_mpq.py` cannot inspect this StormLib archive because its
  reader does not support encryption, so SC2 `CreateGame + JoinGame` is the
  runtime packaging evidence.

## Stop Condition

Simulator, static, native-task, and typed debug-function gates are complete.
Stage 25 remains `IN_PROGRESS` with issue `RUNTIME-P2-ALLIANCE-UNVERIFIED`
until a fresh approved-launcher window proves P1 ActionChat -> Galaxy P2 order
-> RequestStep state change and a same-window ScriptError check. Do not promote
the P2 command lane from `BLOCKED` based on P2 visibility or position deltas.
