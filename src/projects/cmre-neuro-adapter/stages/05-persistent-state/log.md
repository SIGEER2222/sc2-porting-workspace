# Stage 05 Log: Persistent State

## Progress

Stage 05 is complete within the declared `cmre-neuro-adapter` write scope. Campaign, mission,
and runtime state now use independent versioned envelopes with deterministic JSON, checksums,
atomic replacement, backup recovery, explicit v0-to-v1 migration, and typed restart loading.
Mission persistence stores the complete Stage 04 public context and validates the derived economy,
production, and tactical summaries before exposing the state.

## Evidence

- `simulator`: `python -m unittest discover -s tests -p 'test_state*.py' -v` -> 10 Stage 05
  tests passed. This exercised three-domain round-trip, checksum recovery, interrupted writes,
  cross-domain isolation, corruption rejection, v0 migration, future-schema rejection, and
  deterministic save/load replay.
- `simulator`: `python -m unittest discover -s tests -v` -> 49 tests passed under Python
  3.13.14, including all Stage 01-04 regression tests.
- `static`: `python -m compileall -q cmre_neuro_adapter tests` -> pass under Python 3.13.14.
- `static`: Python 3.11 grammar fallback -> 39 project Python files passed
  `ast.parse(..., feature_version=(3,11))`. No Python 3.11 runtime claim is made.
- `static`: `git diff --check -- src/projects/cmre-neuro-adapter` -> pass.

## Gate Results

| Gate | Result | Evidence |
|---|---|---|
| G1-domain-separation | PASS | Independent campaign, mission, and runtime files plus round-trip tests |
| G2-atomicity | PASS | Interrupted replacement and backup recovery simulator tests |
| G3-migration | PASS | Explicit v0 aliases migrate; future schema and missing fields reject |
| G4-restart | PASS | New `StateStore` instance restores a complete `MissionSnapshot` |
| G5-replay | PASS | Two independent save/load traces and file envelopes are identical |
| G6-compatibility | PASS | Python 3.13 tests/compileall plus Python 3.11 grammar fallback |

## Changes

- `cmre_neuro_adapter/persistence/campaign_state.py`: strict campaign-domain codec.
- `cmre_neuro_adapter/persistence/mission_state.py`: public-context mission codec and summary
  consistency validation.
- `cmre_neuro_adapter/persistence/runtime_state.py`: strict runtime-domain codec.
- `cmre_neuro_adapter/persistence/migrations.py`: canonical envelopes, checksums, and explicit
  schema migrations.
- `cmre_neuro_adapter/persistence/state_store.py`: per-domain atomic writes, `.bak` recovery,
  complete-envelope validation, and typed snapshot load/save.
- `cmre_neuro_adapter/persistence/__init__.py`: persistence package exports.
- `tests/test_state_store.py`, `tests/test_state_migrations.py`: Stage 05 simulator coverage.
- `project.json`: controlled handoff to `06-ability-slice` after Stage 05 verification.

## Problems and Limitations

- Python 3.11 is not installed on this machine. Compatibility is limited to grammar parsing plus
  Python 3.13 execution.
- This stage intentionally does not connect to a live Neuro WebSocket, SC2 Bank, or real SC2
  process. Runtime evidence remains deferred to the real-adapter stage.
- Persistence is intentionally file-based and transport-neutral. The SC2 Bank adapter remains a
  later integration concern.

## Handoff

Stage 06 may consume the verified state store and add the first four CMRE ability contracts:
`heal_allies`, `temporary_shields`, `call_backup`, and `nuke_visible_target`.
