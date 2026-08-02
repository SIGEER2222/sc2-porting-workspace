# Stage 06 Log: CMRE Ability Slice

## Progress

Stage 06 is complete within the declared `cmre-neuro-adapter` write scope. The four-ability
slice is simulator-first and transport-neutral. It validates public mission context and returns
deterministic effect requests without mutating simulator authority. Successful uses return a new
versioned ability state; rejected uses return the original state unchanged.

## Failure-First Diagnostic

- `simulator`: the initial command
  `python -m unittest tests.test_abilities tests.test_ability_replay -v` failed because the
  declared Stage 06 test modules did not exist. This was the pre-fix failure that drove the
  implementation.
- `static`: `py -3.11 --version` still reports no suitable runtime after a user-scope
  `winget install --id Python.Python.3.11 --exact --scope user ...` attempt timed out after
  184 seconds. No 3.11 runtime claim is made.

## Evidence

- `simulator`: `python -m unittest discover -s tests -p 'test_ability*.py' -v` -> 7 tests
  passed. This covers definition/registration, success effect creation, energy and cooldown
  requirements, invalid/invisible target rejection, public readiness projection, snapshot
  recovery, and deterministic replay.
- `simulator`: `python -m unittest discover -s tests -v` -> 56 tests passed under Python
  3.13.14, including all Stage 01-05 regressions.
- `simulator`: `python -m unittest discover -s tests -p 'test_state*.py' -v` -> 10 Stage 05
  persistence tests passed after adding the optional ability state domain.
- `static`: `python -m compileall -q cmre_neuro_adapter tests` -> pass under Python 3.13.14.
- `static`: Python 3.11 grammar fallback -> 47 project Python files passed
  `ast.parse(..., feature_version=(3,11))`.
- `static`: `git diff --check -- src/projects/cmre-neuro-adapter` -> pass.

## Gate Results

| Gate | Result | Evidence |
|---|---|---|
| G1-definitions | PASS | `tests/test_abilities.py`; four stable definitions and action schemas |
| G2-requirements | PASS | `tests/test_abilities.py`; failures preserve state and effect absence |
| G3-effects | PASS | `tests/test_abilities.py`; one deterministic request and one state update |
| G4-persistence | PASS | `tests/test_ability_replay.py`; `abilities.json` snapshot round-trip |
| G5-replay | PASS | `tests/test_ability_replay.py`; repeated traces compare equal |
| G6-compatibility | PASS | Python 3.13 tests/compileall plus Python 3.11 grammar fallback |

## Changes

- `cmre_neuro_adapter/abilities/definitions.py`: four stable definitions, schemas, costs,
  cooldowns, and simulator operation names.
- `cmre_neuro_adapter/abilities/registry.py`: deterministic registration and public readiness
  context projection.
- `cmre_neuro_adapter/abilities/executor.py`: side-effect-free requirement checks and typed
  effect requests/results.
- `cmre_neuro_adapter/abilities/state.py`: versioned energy, cooldown, and use-sequence state.
- `cmre_neuro_adapter/persistence/ability_state.py`: strict ability state codec.
- `cmre_neuro_adapter/persistence/state_store.py`, `persistence/migrations.py`: optional
  `abilities.json` snapshot domain and schema handling.
- `cmre_neuro_adapter/mission/mission_state.py`: optional ability state on `MissionSnapshot`.
- `tests/test_abilities.py`, `tests/test_ability_replay.py`: Stage 06 regression and replay MVP.

## Problems and Limitations

- Python 3.11 is not installed. Compatibility is limited to grammar parsing plus Python 3.13
  execution; the timed installation attempt did not change that state.
- This stage intentionally does not connect to a live Neuro WebSocket, SC2 Bank, or real SC2
  process. Effect requests are not real-SC2 effects.
- The ability costs, cooldowns, and operation identifiers are adapter contract values until a
  later authoritative transport stage maps them to mission-owned behavior.

## Handoff

Stage 07 is planned for real transport adapters. It must preserve the simulator-first contracts
and collect launcher/GameLogs/runtime-listener evidence before making any real-SC2 claim.
