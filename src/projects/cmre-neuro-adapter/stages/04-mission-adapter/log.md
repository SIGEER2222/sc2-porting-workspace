# Stage 04 Log: Dead of Night Mission Adapter

## Progress

Stage 04 is complete within the declared `cmre-neuro-adapter` write scope. The mission layer now
keeps campaign, mission, and runtime state separate, derives public event diffs from the Stage 03
context contract, deduplicates semantic context, and applies a deterministic action lifecycle
policy through `NeuroRuntime`.

## Evidence

- `simulator`: `python -m unittest discover -s tests -p test_dead_of_night_adapter.py -v` -> 4
  focused mission-adapter tests passed. This exercised context deduplication, forced refresh,
  event ordering, action policy transitions, terminal cleanup, and replay equality.
- `simulator`: `python -m unittest discover -s tests -v` -> 39 tests passed under Python 3.13.14,
  including all Stage 01-03 regression tests and Stage 04 mission tests.
- `static`: `python -m compileall -q cmre_neuro_adapter tests` -> pass under Python 3.13.14.
- `static`: Python 3.11 grammar fallback -> 31 project Python files passed
  `ast.parse(..., feature_version=(3,11))`. No Python 3.11 runtime claim is made.
- `static`: `git diff --check -- src/projects/cmre-neuro-adapter` -> pass.

## Gate Results

| Gate | Result | Evidence |
|---|---|---|
| G1-state-separation | PASS | `mission_state.py`, `test_mission_contexts.py`, and simulator lifecycle tests |
| G2-public-events | PASS | `objective_context.py`/`tactical_context.py` diff only Stage 03 public context fields |
| G3-context-dedup | PASS | `test_context_is_semantically_deduplicated_and_forced_refresh_works` |
| G4-action-lifecycle | PASS | `test_action_policy_handles_no_build_pause_block_and_terminal_state` |
| G5-deterministic-replay | PASS | `test_replayed_context_event_trace_is_identical` |
| G6-compatibility | PASS | Python 3.13 tests/compileall plus Python 3.11 grammar fallback |

## Changes

- `cmre_neuro_adapter/mission/mission_state.py`: versioned campaign, mission, runtime, and
  public event records.
- `cmre_neuro_adapter/mission/dead_of_night_adapter.py`: semantic context deduplication,
  forced refresh, event sequence assignment, and action policy/lifecycle integration.
- `cmre_neuro_adapter/mission/objective_context.py`: public objective change events.
- `cmre_neuro_adapter/mission/tactical_context.py`: public wave, phase, building, unit death,
  and mission-end events plus threat/unit summaries.
- `cmre_neuro_adapter/mission/economy_context.py`: public resource summary.
- `cmre_neuro_adapter/mission/production_context.py`: own-unit production counts and public base
  summary.
- `cmre_neuro_adapter/mission/__init__.py`: mission adapter exports.
- `tests/test_dead_of_night_adapter.py`, `tests/test_mission_contexts.py`: Stage 04 regression
  and simulator MVP coverage.
- `stages/04-mission-adapter/result.json`, `issues.json`: gate evidence and limitations.

## Problems and Limitations

- Python 3.11 is not installed on this machine. The compatibility gate is limited to grammar
  parsing plus available Python 3.13 execution.
- This stage intentionally does not connect to a live Neuro WebSocket, SC2 Bank, or real SC2
  process. Real-SC2 runtime evidence remains deferred to the dedicated live adapter stage.
- Base and production summaries are derived from publicly visible own units only; authoritative
  production queues, rewards, objectives, and mission scripting remain in the source simulator.

## Handoff

Stage 05 may consume `MissionSnapshot` and the public event/context contract to add persistent
campaign, mission, and runtime state storage with migration and corruption recovery.
