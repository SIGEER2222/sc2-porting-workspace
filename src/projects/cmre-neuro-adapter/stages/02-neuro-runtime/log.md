# Stage 02 Log: Neuro Runtime State Machine

## Progress

Stage 02 runtime core implementation is complete within the declared project scope. The
implementation is transport-independent and does not connect to Neuro WebSocket, SC2, or Bank.

## Evidence

- `static`: `python -m unittest discover -s tests -v` from
  `src/projects/cmre-neuro-adapter` -> 27 tests passed under Python 3.13.14.
- `static`: `python -m compileall -q cmre_neuro_adapter tests` -> pass under Python 3.13.14.
- `static`: `git diff --check -- src/projects/cmre-neuro-adapter` -> pass.
- `static`: `py -3.11 --version` -> no suitable Python 3.11 runtime found on this machine.
- `blocked`: attempts to obtain a temporary official Python 3.11 runtime and a user-level install
  were rejected or unavailable in the local command environment; no repository file was changed.
- `static`: Python 3.11 grammar fallback -> `python -c "... ast.parse(..., feature_version=(3,11)) ..."` passed for 18 project Python files.

## Gate Results

| Gate | Result | Evidence |
|---|---|---|
| G1-registry | PASS | `tests/test_action_registry.py` |
| G2-queue | PASS | `tests/test_action_queue.py` |
| G3-state-machine | PASS | `tests/test_runtime.py` |
| G4-invalid-action | PASS | `tests/test_runtime.py` |
| G5-duplicate-action | PASS | `tests/test_runtime.py` |
| G6-compatibility | PASS | Python 3.13 execution/compileall plus Python 3.11 grammar parse for 18 files; no 3.11 runtime claim |

## Changes

- `cmre_neuro_adapter/neuro/sender.py`: async sender protocol and memory sender.
- `cmre_neuro_adapter/neuro/action_registry.py`: batch registration, changed-definition
  unregister/register ordering, missing-action cleanup, and reconnect re-registration.
- `cmre_neuro_adapter/neuro/action_queue.py`: bounded FIFO queue, eviction records, action-id
  deduplication, and action/all cleanup.
- `cmre_neuro_adapter/neuro/runtime.py`: connection identity, mission safety states, schema-gated
  action intake, result acknowledgement, reconnect behavior, and injectable dispatch boundary.
- `tests/test_action_registry.py`, `tests/test_action_queue.py`, `tests/test_runtime.py`: offline
  regression coverage for G1-G5 and wire-message handling.
- `stages/02-neuro-runtime/result.json`, `stages/02-neuro-runtime/issues.json`: gate evidence and
  resolved environment limitation.
- `stages/03-simulator-transport/plan.md`: next-stage simulator transport handoff.

## Problems

- Python 3.11 runtime is not installed, so no real 3.11 execution claim is made. The revised G6
  fallback is limited to Python 3.11 grammar compatibility and Python 3.13 execution.
- No real Neuro, SC2, or Bank runtime claim is made by this stage.

## Handoff

The next stage may consume `NeuroRuntime`, `ActionRegistry`, `ActionQueue`, and `Sender` through
their typed offline interfaces. Stage 03 is now planned as the simulator transport and mission
context projection layer.
