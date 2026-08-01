# Stage 20 Plan: Simulator AI Ally Adversarial Hardening

## Objective

Harden the deterministic AI ally controller after multi-seed structure
clearance. Preserve the Dead of Night contract while making target allocation,
push-unit loss, reinforcement pressure, and event accounting easier to audit.

## Contract

- Victory remains `destroy_all_enemy_structures` with zero live enemy buildings.
- Night buildings still spawn infected units, daytime still removes those
  infected units, and building damage still summons local enemy troops.
- Controller changes must retain explicit orders, deterministic allocation,
  bounded retries/intervals, and truthful command result accounting.
- Simulator evidence remains separate from SC2 runtime evidence; this stage
  should not launch SC2 unless a future plan explicitly authorizes it.

## Work Scope

1. Add stable event and target-allocation summaries for post-run audit.
2. Exercise push-army size variants and controlled unit-loss cases without
   weakening the structure-clear objective.
3. Keep the three-seed clearance matrix and stage 18/task-loop regressions
   green.
4. Record any performance or determinism regressions before changing the
   controller.

## Completion Gate

- At least three deterministic seeds still reach zero live enemy structures.
- Infection, daytime cleanup, reinforcement, death, stale-target, and timeout
  evidence is present and classified as simulator evidence.
- Focused tests, static validation, and Python compilation pass.
- `result.json`, `log.md`, and `issues.json` agree with the evidence, and no
  runtime claim is promoted from simulator output.
