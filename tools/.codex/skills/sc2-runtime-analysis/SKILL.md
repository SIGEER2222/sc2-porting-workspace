---
name: sc2-runtime-analysis
description: Run backend-neutral dynamic analysis of an SC2 map/mod composition using Banks, game logs, process state, event streams, screenshots, or Neuro-compatible services. Use after static validation, when proving initializers/triggers/objectives/rewards/actions execute, when comparing static predictions with observed behavior, or when diagnosing runtime-only failures.
---

# SC2 Runtime Analysis

Collect real game evidence. Neuro and Gary are optional backends, not required architecture dependencies.

## Preconditions

1. Read the active project, stage plan, static dependency graph, and composition manifest.
2. Confirm static validation passed or record the explicitly accepted static gap.
3. Use the registered launcher and test lock for the target map type.
4. Confirm only one runtime observer and one selected backend own each action channel.

## Observation workflow

1. Record launch command, map, mods, adapters, commander, run ID, and pre-launch process state.
2. Launch SC2 through the target-specific launcher.
3. Wait for the complete readiness procedure; process startup alone is not success.
4. Capture initialization, trigger, objective, reward, Bank, selection, command, resource, and unit events.
5. Capture ScriptError and process exit state.
6. Exercise the stage's declared scenarios.
7. Compare observed events with static predictions and acceptance criteria.
8. Store raw evidence and write a stage result.

## Required evidence

- map and composition identity;
- SC2 PID and observed runtime;
- readiness result;
- ScriptError status;
- initializer and trigger observations relevant to the stage;
- player action and resulting game state for action tests;
- objective/reward progression for mission tests;
- observer/backend process state;
- exact evidence paths.

Never use mock-only evidence when the stage requires a real service or game process.

Read [runtime-contract.md](references/runtime-contract.md) before launching.
