# Stage 06 Plan: CMRE Ability Slice

> Start condition: Stage 05 persistent state PASS, with file-store recovery and migration
> limitations recorded explicitly.

## Objective

Add a simulator-first, transport-neutral ability layer for the first four CMRE abilities while
keeping effect authority in the mission simulator and keeping ability state persistable through
the verified Stage 05 snapshot boundary.

## Contract

- Each ability has a stable definition, argument schema, requirement checks, energy cost,
  cooldown, deterministic effect request, result, and public context projection.
- `heal_allies`, `temporary_shields`, `call_backup`, and `nuke_visible_target` are the only
  abilities in this stage.
- Insufficient energy, active cooldown, invalid arguments, or an invisible target reject without
  mutating mission or ability state.
- Successful execution applies one deterministic effect request, deducts energy once, and starts
  the declared cooldown.
- Ability state is separate from mission authority and can be included in snapshot/replay without
  exposing hidden simulator state.
- The same ability trace is reproducible across repeated simulator runs and restored snapshots.

## Outputs

```text
cmre_neuro_adapter/abilities/__init__.py
cmre_neuro_adapter/abilities/definitions.py
cmre_neuro_adapter/abilities/registry.py
cmre_neuro_adapter/abilities/executor.py
cmre_neuro_adapter/abilities/state.py
tests/test_abilities.py
tests/test_ability_replay.py
stages/06-ability-slice/result.json
stages/06-ability-slice/issues.json
```

## Work Plan

1. Define immutable ability definitions and schemas for the four named abilities.
2. Define versioned ability runtime state for energy, cooldowns, and deterministic use sequence.
3. Implement registry and executor boundaries that accept only public mission context and return
   typed effect requests or typed failures.
4. Integrate ability state with the Stage 04 mission snapshot and Stage 05 persistence without
   persisting hidden simulator world state.
5. Add rejection, success, cooldown, visibility, snapshot/restart, and deterministic replay tests.
6. Run the offline ability MVP twice, then record evidence before any live-adapter planning.

## Gates

| Gate | Verification | Evidence |
|---|---|---|
| G1-definitions | Four definitions expose stable schemas and costs | static + simulator |
| G2-requirements | Invalid, insufficient-energy, cooldown, and visibility failures are side-effect free | simulator |
| G3-effects | Successful use emits one deterministic effect request and updates state once | simulator |
| G4-persistence | Ability state survives snapshot/load without hidden world state | simulator |
| G5-replay | Identical inputs produce identical results and traces | simulator |
| G6-compatibility | Available-runtime tests, compileall, and Python 3.11 grammar fallback pass | static |

## Non-goals

- Do not implement the remaining WoL ability set.
- Do not hard-code SC2 catalog effects or commander-specific authoritative mission scripting.
- Do not connect a live Neuro WebSocket, SC2 Bank, or real SC2 process.
- Do not claim real-SC2 ability effects from simulator evidence.

## Completion Gate

1. All G1-G6 gates pass with simulator evidence separated from static evidence.
2. Ability failures leave energy, cooldown, mission state, and replay trace unchanged.
3. `result.json`, `issues.json`, and `log.md` contain commands, evidence paths, and limitations.
4. The next stage has a concrete plan and the project pointer advances only by a controlled
   handoff after verification.
