# Stage 03 Plan: Simulator Transport

> Start condition: Stage 02 offline runtime core PASS, with Python 3.11 runtime availability recorded as a limitation rather than a runtime claim.

## Objective

Connect the typed Neuro runtime to the existing simulator-first CMRE observation/action boundary
without introducing WebSocket, SC2 Bank, or real-game dependencies. The simulator path must use
the same `ActionCommand`, `ExecutionResult`, action registry, queue, and context contracts that a
future live adapter will consume.

## Contract

- A simulator adapter owns transport translation, not Neuro protocol construction.
- Observation projection exposes mission-owned public state only: map identity, mission phase,
  night/wave, objectives, resources, visible units, and threat summaries.
- Action execution is deterministic, correlated by `action_id`, and idempotent for duplicate
  commands.
- Transport failures become typed failed `ExecutionResult` values and never advance mission state.
- Context versions increase monotonically and include the source loop/state version used to build
  the projection.
- The implementation remains runnable without an SC2 executable, Bank file, WebSocket service, or
  third-party dependency.

## Outputs

```text
cmre_neuro_adapter/neuro/simulator_transport.py
cmre_neuro_adapter/neuro/mission_projection.py
tests/test_simulator_transport.py
tests/test_mission_projection.py
stages/03-simulator-transport/result.json
stages/03-simulator-transport/issues.json
```

## Work Plan

1. Define the narrow simulator backend protocol for observe, execute, and state version access.
2. Adapt the existing CMRE simulator-first observation/action contracts without modifying the
   source `cmre-porting` project or external repositories.
3. Implement public mission context projection with explicit version and source-loop metadata.
4. Translate registered actions into simulator operations and correlate every result to its
   original Neuro `action_id`.
5. Add duplicate, stale-state, unsupported-action, dispatch-failure, and deterministic replay
   tests.
6. Run the offline simulator scenario and compare projected context, action results, and state
   versions across two identical runs.

## Gates

| Gate | Verification | Evidence |
|---|---|---|
| G1-transport-contract | Backend protocol and state versions are typed | static |
| G2-context-projection | Public Dead of Night context excludes hidden simulator internals | simulator + static |
| G3-action-correlation | Accepted, failed, and duplicate actions preserve `action_id` correlation | simulator |
| G4-idempotency | Duplicate commands cannot execute twice | simulator |
| G5-deterministic-replay | Identical input frames produce identical context/result traces | simulator |
| G6-compatibility | Python 3.11 grammar fallback and available-runtime tests pass | static |

## Non-goals

- Do not connect a live Neuro WebSocket.
- Do not read or write SC2 Banks.
- Do not launch `SC2_x64.exe` or claim real-SC2 completion.
- Do not move mission objectives, rewards, or authoritative state into the Neuro adapter.

## Completion Gate

1. All G1-G6 gates pass with simulator evidence separated from static evidence.
2. The simulator context and action trace are deterministic across repeated runs.
3. `result.json`, `issues.json`, and `log.md` contain commands, evidence paths, and limitations.
4. Stage 04 plan is written only after Stage 03 verification is complete.
