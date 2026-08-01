# Stage 04 Plan: Dead of Night Mission Adapter

> Start condition: Stage 03 offline simulator transport PASS, with live transport and Python
> 3.11 runtime limitations recorded explicitly.

## Objective

Add mission-owned Dead of Night state and event-aware context/action lifecycle behavior above the
Stage 03 simulator transport. The adapter must consume public observations or `MissionEngine`
results without moving authoritative objectives, rewards, waves, or mission scripting into the
Neuro package.

## Contract

- Campaign, mission, and runtime state remain separate objects with explicit versions.
- Mission context contains only public map identity, phase, night/wave, objectives, resources,
  production/base summaries, visible units, and threat summaries.
- Context updates are deterministic and deduplicated by semantic payload, with an explicit forced
  refresh path for state transitions that must be re-emitted.
- Mission phase changes register and unregister only actions valid for the current phase.
- `no_build`, `paused`, `blocking`, `victory`, and `failure` are represented as lifecycle state,
  not hidden exceptions or implicit action behavior.
- Mission events are derived from public simulator observations or `MissionEngine` results; the
  adapter never reads hidden world state.

## Outputs

```text
cmre_neuro_adapter/mission/mission_state.py
cmre_neuro_adapter/mission/dead_of_night_adapter.py
cmre_neuro_adapter/mission/objective_context.py
cmre_neuro_adapter/mission/tactical_context.py
cmre_neuro_adapter/mission/economy_context.py
cmre_neuro_adapter/mission/production_context.py
tests/test_dead_of_night_adapter.py
tests/test_mission_contexts.py
stages/04-mission-adapter/result.json
stages/04-mission-adapter/issues.json
```

## Work Plan

1. Define versioned campaign, mission, and runtime state records over the Stage 03 public context.
2. Define a small public event diff model for objective changes, wave spawns, building
   completion, unit deaths, and mission termination.
3. Implement deterministic context deduplication and forced-refresh semantics.
4. Implement Dead of Night phase policy for action registration, no-build, pause/blocking, and
   terminal states.
5. Add tests for hidden-state exclusion, event ordering, action lifecycle, and replay stability.
6. Run the offline simulator MVP with two identical traces and record simulator evidence before
   creating the next stage plan.

## Gates

| Gate | Verification | Evidence |
|---|---|---|
| G1-state-separation | Campaign, mission, and runtime state have independent versions | static + simulator |
| G2-public-events | Event diffs derive only from public observations or mission results | simulator |
| G3-context-dedup | Repeated semantic context is suppressed; forced refresh is emitted | simulator |
| G4-action-lifecycle | Phase/no-build/paused/blocking/terminal transitions maintain valid actions | simulator |
| G5-deterministic-replay | Identical observation/event traces produce identical output traces | simulator |
| G6-compatibility | Available-runtime tests, compileall, and Python 3.11 grammar fallback pass | static |

## Non-goals

- Do not connect a live Neuro WebSocket.
- Do not read or write SC2 Banks.
- Do not launch `SC2_x64.exe` or claim real-SC2 completion.
- Do not implement CMRE commander abilities or persistent storage in this stage.
- Do not move mission-owned objectives, rewards, waves, cinematics, or authoritative scripting into
  the adapter.

## Completion Gate

1. All G1-G6 gates pass with simulator evidence separated from static evidence.
2. Repeated observations and events produce a deterministic, deduplicated context/action trace.
3. `result.json`, `issues.json`, and `log.md` contain commands, evidence paths, and limitations.
4. The next stage has a concrete `plan.md` and `project.json.currentStage` is advanced only by a
   later controlled handoff.
