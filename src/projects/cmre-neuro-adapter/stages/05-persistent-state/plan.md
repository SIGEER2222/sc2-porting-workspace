# Stage 05 Plan: Persistent State

> Start condition: Stage 04 mission adapter PASS, with in-memory state and live-runtime
> limitations recorded explicitly.

## Objective

Persist the Stage 04 campaign, mission, and runtime state separately with versioned schemas,
atomic writes, migration support, restart recovery, and deterministic replay participation.

## Contract

- Campaign, mission, and runtime state have independent schemas and version numbers.
- A failed or corrupt write never replaces the last known-good state.
- Load validates the complete envelope before exposing any state to the runtime.
- Migrations are explicit, deterministic, and do not silently discard unknown required fields.
- State snapshots and restored state participate in deterministic simulator traces.
- No SC2 Bank, live Neuro transport, or real-SC2 claim is introduced in this offline stage.

## Outputs

```text
cmre_neuro_adapter/persistence/campaign_state.py
cmre_neuro_adapter/persistence/mission_state.py
cmre_neuro_adapter/persistence/runtime_state.py
cmre_neuro_adapter/persistence/state_store.py
cmre_neuro_adapter/persistence/migrations.py
tests/test_state_store.py
tests/test_state_migrations.py
stages/05-persistent-state/result.json
stages/05-persistent-state/issues.json
```

## Work Plan

1. Define serialized envelopes for the three Stage 04 state domains and their schema versions.
2. Implement deterministic JSON encoding, checksum validation, and atomic replacement using the
   existing project-local artifact/state boundary.
3. Implement forward migrations for the initial schema and reject unsupported future versions.
4. Add corruption, interrupted-write, restart, round-trip, and cross-domain isolation tests.
5. Run a simulator save/load/replay MVP twice and compare state and output traces.
6. Record stage evidence before creating the next stage plan.

## Gates

| Gate | Verification | Evidence |
|---|---|---|
| G1-domain-separation | Campaign, mission, and runtime round-trip independently | simulator + static |
| G2-atomicity | Interrupted/corrupt writes preserve the last good version | simulator |
| G3-migration | Supported schema migrations pass; future schema is rejected | static + simulator |
| G4-restart | Restart restores state without cross-domain leakage | simulator |
| G5-replay | Save/load traces remain deterministic | simulator |
| G6-compatibility | Available-runtime tests, compileall, and Python 3.11 grammar fallback pass | static |

## Non-goals

- Do not read or write StarCraft II Banks.
- Do not connect a live Neuro WebSocket or launch real SC2.
- Do not persist hidden simulator world state.
- Do not add commander ability state before the persistence contract is verified.

## Completion Gate

1. All G1-G6 gates pass with simulator evidence separated from static evidence.
2. Corrupt and interrupted writes leave the last known-good state readable.
3. `result.json`, `issues.json`, and `log.md` contain commands, evidence paths, and limitations.
4. The next stage has a concrete `plan.md` and the project stage pointer is advanced only by a
   controlled handoff.
