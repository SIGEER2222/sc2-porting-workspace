# Stage 22 Plan: Runtime Typed Combat and Structure Census

## Objective

Close the remaining gap from Stage 21: expose a bounded, explicit Vibe combat
command and a read-only structure census that can be exercised in the real SC2
window. Prove the runtime objective boundary without replacing or deleting map
buildings through debug shortcuts.

## Contract

- New calls must be explicit registry entries with typed arguments and fixed
  action kinds; no arbitrary ability IDs, Galaxy reflection, or free-form
  command strings.
- The structure census is observational. It must report owner, type, tag, and
  live count from real state and must not mutate the world.
- Combat commands must target a real enemy tag and return correlated action
  results. Invalid, neutral, ally, stale, or missing targets must fail without
  a side effect.
- Native initialization remains unchanged: CommandCenter/SCV counts and
  replacement/removal flags are checked before and after the probe.
- Simulator, Host, Galaxy, and SC2 runtime evidence stay separately classified.

## Work Scope

1. Extend the explicit function registry with a typed combat order and a
   structure-census query, implementing simulator and Host validation first.
2. Add matching explicit Galaxy handlers in the canonical kernel, debug mirror,
   and project map mirror only where the existing Vibe wire contract requires.
3. Add stale-target, neutral-target, ally-target, and successful attack tests;
   preserve Stage 18 task-loop and Stage 21 runtime initialization regressions.
4. Run the approved launcher against a fresh staged map, query the native
   structure census, issue a bounded attack sequence, and observe target state
   changes through frame advancement.
5. Re-run the same-window ScriptError gate and record whether all objective
   buildings were cleared. A partial attack slice remains partial evidence.

## Completion Gate

- Registry/schema/whitelist consistency and simulator/Host tests pass.
- A fresh runtime window observes native startup and a nonzero enemy structure
  census, then accepts at least one valid typed combat command against an enemy
  target and rejects invalid target classes without side effects.
- Runtime action responses are correlated, frames advance, the before/after
  census is recorded, and ScriptError has no new files.
- Full `destroy_all_enemy_structures` runtime victory is claimed only when the
  census reaches zero with a matching objective/result artifact; otherwise the
  remaining count is recorded as an open issue.
