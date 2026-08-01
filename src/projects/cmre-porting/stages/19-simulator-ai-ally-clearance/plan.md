# Stage 19 Plan: Simulator AI Ally Clearance

## Objective

Continue the CMRE AI ally work in the deterministic simulator. Prove that the
ally can clear every enemy structure while the Dead of Night day/night rules
remain active: buildings create infected units at night, daytime removes those
infected units, and damaging a building summons local enemy troops.

## Contract

- Victory is only `destroy_all_enemy_structures` with zero live enemy buildings.
- Simulator acceleration may reduce structure health and bound summoned-unit
  lifetimes, but may not remove objective entities or bypass damage events.
- The push controller must retain explicit orders, deterministic target
  allocation, bounded retries/intervals, and command result accounting.
- Simulator evidence must stay classified separately from SC2 runtime evidence;
  this stage does not launch SC2.

## Work Scope

1. Add deterministic multi-seed clearance checks around the verified
   `run_dead_of_night` clear mode.
2. Exercise hostile cases: late-night infection, reinforcement pressure,
   dead push units, stale targets, and wall-clock exhaustion.
3. Preserve the existing task-loop and registry regression suite while adding
   only focused simulator assertions.
4. Record simulator reports, event counts, and unresolved behavior in this
   stage directory.

## Completion Gate

- Each declared seed either reaches `all_objectives_success` with zero enemy
  structures or records a reproducible issue with its exact remaining count.
- Infection spawn, daytime cleanup, and building reinforcement evidence is
  present in every passing scenario.
- Task-loop, static validation, and focused simulator tests pass.
- `result.json`, `log.md`, and `issues.json` contain classified evidence and
  the next-stage plan is written only after verification.
