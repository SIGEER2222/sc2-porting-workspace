# Stage 03 Log: Simulator Transport

## Progress

Stage 03 is complete within the declared `cmre-neuro-adapter` write scope. The adapter now
connects the existing transport-neutral Neuro runtime contract to a narrow offline simulator
backend contract. No WebSocket, Bank, SC2 executable, or live-game dependency was introduced.

## Evidence

- `simulator`: `python -m unittest discover -s tests -p test_simulator_transport.py -v` -> 4
  simulator transport tests passed. This exercised NeuroRuntime action intake, simulator
  dispatch, backend side effects, action/result correlation, duplicate suppression, stale-state
  rejection, unsupported-action rejection, backend failure conversion, and deterministic replay.
- `simulator`: `python -m unittest discover -s tests -v` -> 33 tests passed under Python 3.13.14,
  including the Stage 02 regression suite and Stage 03 simulator/projection tests.
- `static`: `python -m compileall -q cmre_neuro_adapter tests` -> pass under Python 3.13.14.
- `static`: Python 3.11 grammar fallback -> 22 project Python files passed
  `ast.parse(..., feature_version=(3,11))`. No Python 3.11 runtime claim is made.
- `static`: `git diff --check -- src/projects/cmre-neuro-adapter` -> pass.

## Gate Results

| Gate | Result | Evidence |
|---|---|---|
| G1-transport-contract | PASS | `SimulatorBackend`, explicit action-operation map, typed `SimulatorExecutionResult`; static review and transport tests |
| G2-context-projection | PASS | `tests/test_mission_projection.py`; public unit/resource/objective/threat allowlist and hidden-field exclusion |
| G3-action-correlation | PASS | `test_runtime_dispatch_preserves_action_correlation` |
| G4-idempotency | PASS | `test_action_is_translated_and_duplicate_is_idempotent` |
| G5-deterministic-replay | PASS | `test_repeated_input_trace_is_deterministic` |
| G6-compatibility | PASS | Python 3.13 tests/compileall plus Python 3.11 grammar fallback |

## Changes

- `cmre_neuro_adapter/neuro/simulator_transport.py`: narrow backend protocol, explicit action
  translation, state-version preconditions, typed failures, duplicate result cache, and the
  public `SimulatorSession` wrapper.
- `cmre_neuro_adapter/neuro/mission_projection.py`: immutable public observation projection,
  deterministic JSON serialization, monotonic context versions, source loop/state metadata,
  and hidden simulator field exclusion.
- `cmre_neuro_adapter/neuro/__init__.py`: exports the Stage 03 adapter contracts.
- `tests/test_simulator_transport.py`: simulator MVP and runtime integration regression tests.
- `tests/test_mission_projection.py`: public-state, versioning, stale-state, and privacy tests.
- `stages/03-simulator-transport/result.json`, `issues.json`: gate evidence and limitations.

## Problems and Limitations

- Python 3.11 is not installed on this machine. The compatibility gate is limited to grammar
  parsing plus available Python 3.13 execution.
- This stage intentionally does not connect to a live Neuro WebSocket, SC2 Bank, or real SC2
  process. Real-SC2 runtime evidence remains deferred to the dedicated live adapter stage.
- The simulator MVP uses a deterministic in-memory backend fixture. The existing
  `SimulatorSessionBackend` remains transport-boundary code and is not a real-SC2 claim.

## Handoff

Stage 04 may consume the public `PublicMissionContext`, `MissionContextProjector`,
`SimulatorTransport`, and `SimulatorSessionBackend` contracts to add mission-owned Dead of Night
state and event-driven context/action lifecycle behavior.
