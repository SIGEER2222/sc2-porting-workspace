# Stage Plan: Decision Control — Contracts, Action Registry, and Mission Phases

## Objective

Deliver a deterministic, auditable decision-control layer for the Dead of Night AI ally. The
layer must separate observation, intent selection, action validation, phase gating, execution
result, and trace recording while remaining runnable without the optional Ares/SC2 runtime.

This stage absorbs the useful Neuro integration patterns (explicit action schemas, forced
high-priority decisions, blocking gates, and action results) without exposing raw unit commands
to a language model or pretending that Stage 01's Ares runtime gates have passed.

## Inputs

- `src/projects/cmre-ai-enhancement/project.json`
- `src/projects/cmre-ai-enhancement/stages/01-foundation/{plan,log,result,issues}.json|md`
- `src/projects/cmre-ai-enhancement/vibe/{macro_plan,combat_maneuver,enhanced_policy}.py`
- `src/projects/cmre-porting/vibe/contracts.py` observation shape and `DefendBasePolicy` action semantics
- `reference/SC2-Neuro-API-Integration/Documentation/Documentation.md` action/context/force-action protocol
- `reference/SC2-Neuro-API-Integration/neuro_integration_runtime.py` action schema and queue behavior

## Write scope

```
src/projects/cmre-ai-enhancement/stages/02-decision-control/**
src/projects/cmre-ai-enhancement/vibe/decision_contracts.py
src/projects/cmre-ai-enhancement/vibe/action_registry.py
src/projects/cmre-ai-enhancement/vibe/mission_phase.py
src/projects/cmre-ai-enhancement/vibe/decision_trace.py
src/projects/cmre-ai-enhancement/vibe/decision_controller.py
src/projects/cmre-ai-enhancement/vibe/__init__.py
src/projects/cmre-ai-enhancement/tests/test_decision_control.py
```

## Tasks

1. Define typed, JSON-safe contracts for `DecisionObservation`, `ActionSpec`, `DecisionRequest`,
   `ActionResult`, `DecisionBatch`, and phase snapshots.
2. Implement an `ActionRegistry` with explicit argument validation, precondition checks, phase
   allow-lists, priority ordering, and bounded action timeouts.
3. Implement a Dead of Night `MissionPhaseArbiter` with deterministic transitions for startup,
   buildup, night defense, stabilization, expansion, objective push, retreat, and terminal states.
4. Implement `DecisionTrace` so each decision records observation summary, selected phase, request,
   rejected candidates, executor outcome, and a stable trace hash.
5. Implement `DecisionController` that produces bounded high-level intents for the existing Ares
   macro/combat executors. It must not emit raw SC2 protocol actions.
6. Add focused standard-library tests covering phase priority, forced decisions, action validation,
   blocking gates, timeout results, deterministic request IDs, and trace hashing.

## Outputs

- New decision-control modules listed in the write scope.
- `tests/test_decision_control.py`.
- `stages/02-decision-control/{result,issues,log}.json|md`.
- No Ares dependency installation, live SC2 launch, or LLM integration in this stage.

## Validation

- Static: `python -m py_compile src/projects/cmre-ai-enhancement/vibe/decision_*.py src/projects/cmre-ai-enhancement/vibe/action_registry.py src/projects/cmre-ai-enhancement/vibe/mission_phase.py`.
- Unit: `python -m unittest discover -s src/projects/cmre-ai-enhancement/tests -p 'test_decision_control.py'`.
- Contract: JSON serialize representative observations, decisions, results, and traces; verify a
  repeated input produces the same request ID and trace hash.
- Runtime boundary: Ares import and live 3500-loop validation remain Stage 01 open issues and are
  not claimed by this stage.

## Stop conditions

- Stop and record an issue if the implementation requires importing Ares or SC2 to validate pure
  contracts.
- Stop and record an issue if a proposed action can bypass registry validation or phase gates.
- Stage passes only when static compilation, focused unit tests, deterministic hashing, and result
  artifact validation pass. Stage 01 remains open until its own Ares/runtime gates pass.

## Completion gate

1. All declared Stage 02 outputs exist.
2. Focused tests pass in the available Python environment.
3. `result.json`, `issues.json`, and `log.md` contain evidence and unresolved Stage 01 dependency
   gaps.
4. `project.json.currentStage` is not advanced until Stage 01 is closed.
