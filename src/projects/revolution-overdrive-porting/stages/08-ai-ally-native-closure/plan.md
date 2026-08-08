# Stage 08 Plan: Native AI Ally Closure

## Objective

Decide the `thorner03` P2 contract from map-owned evidence only, and close the last open
acceptance criterion of the project: *"AI ally behavior is covered by deterministic simulator
evidence and a bounded native runtime probe, or is recorded as blocked with the next action."*

This continuation also closes the adapter lifecycle gap found during the native probe: the
project-local AI ally adapter must represent a map-owned, delayed P2 handover explicitly and
must reject P2 dispatch while the ally has no observed owned unit.

It also closes the safe subset of RO-AI-001: PlayerGroupLoop alliance edges are resolved only
when the iterator's bound group has explicit concrete members; opaque groups remain unresolved.

Stage 07 recorded P2 as `blocked` because no P2-owned unit ever appeared through loop 48. That
observation is real, but the conclusion drawn from it was framed against the wrong expectation.
This stage must first establish *what the map actually promises for P2*, then verify that promise.

## Hypothesis under test

`thorner03` P2 (`gv_p02_TYCHUS`) is a **time-gated scripted AI ally**, not an ally that owns units
at map start. If true, Stage 07's "no P2 units at loop 48" is the correct and expected behavior,
not a defect, and the fail-closed adapter contract must be restated rather than repaired.

## Preconditions and scope

- The read-only download at `local-binding/revolution-overdrive-download` stays untouched.
- No map script, Catalog, or Galaxy source is edited. This stage may update the project-local
  read-only AI ally adapter and its tests, but the adapter must not mutate map sources.
- `project.json` writeScope is extended to Stage 08 before any new file is written.
- Every runtime run uses a fresh port and its own artifact subdirectory.
- Strict response gates: CreateGame must return `init_game`, JoinGame must return `in_game`,
  observations must advance, and Catalog plus unit observations must be non-empty before any
  AI ally assertion is recorded.

## Steps

1. **Regression baseline.** Re-run workspace validate, Galaxy lint, Catalog analysis, the RO AI
   ally tests, the WebUI RO tests, and the approved launcher `-NoLaunch`, so the Stage 08 verdict
   sits on a currently-true foundation rather than on Stage 07 history.
2. **Static P2 contract trace.** Extract, with file and line citations from
   `packages/Maps/thorner03.SC2Map/MapScript.galaxy`, the complete P2 lifecycle: the alliance
   setup, the unit-handover call, the trigger chain that reaches it, and the AI wave calls that
   drive P2 after handover. Emit a machine-readable trace artifact.
3. **Codify the contract as a test.** Add a deterministic test that asserts the traced contract
   directly against the shipped map script, so the finding cannot silently rot. The test must fail
   if the handover call, its trigger chain, or the alliance setup changes.
4. **Close the adapter lifecycle boundary.** Teach the RO adapter to expose a time-gated
   activation contract from the static RescueUnit/Region 24 evidence. P1 command authorization
   remains static, but dispatch to P2 stays closed until a runtime census observes an owned P2
   unit. Also fold safely resolved PlayerGroupLoop alliance edges into the per-map contract while
   retaining opaque edges as fail-closed audit records. Add regression tests for both
   pre-activation rejection/post-handover readiness, the 24-map dynamic-owner aggregate, and
   the full 31-map capability matrix.
5. **Bounded native runtime probe.** Through the approved launcher, reach `in_game` on
   `thorner03`, then use only supported SC2 debug/observation APIs to satisfy the map's own
   documented precondition for the P2 handover. Record the owner census before and after. Do not
   create units for P2 from the adapter, and do not inject generic melee AI.
6. **Verdict and closure.** Record either a `passed` P2 ally contract with native evidence, or an
   explicit, evidence-backed contract statement plus the next action. Update issues, write the
   self-assessment, and update `project.json`.

## Stop conditions

- Do not claim AI ally success from a Computer roster entry, shared vision, zero ScriptErrors,
  MPQ readability, or WebUI staging.
- Do not widen the shared adapter's target contract for the 24 dynamic-owner maps on static
  evidence alone.
- If the native handover cannot be reached through supported APIs, record it as bounded-blocked
  with the exact precondition that was not met, and keep the adapter fail-closed.

## Acceptance

- The P2 contract is stated as a definite engineering fact with line-level citations, replacing
  Stage 07's open-ended "blocked" framing.
- A deterministic test guards that contract.
- The regression suite is green in the same session as the verdict.
- Either native P2 ownership is observed, or the unmet precondition is named precisely.

## Continuation evidence

The capability matrix is now an explicit static output of this stage: 31 maps are covered,
26 expose at least one valid fail-closed pairing, 414 pairings are authorized by literal/static
edges and 110 by safely expanded PlayerGroupLoop edges, while 18 dynamic calls remain unresolved.
Those unresolved calls stay unavailable until runtime owner evidence exists.

## Current Execution Outcome

- The no-debug probe now filters the map's own invulnerable `OdinBuild` staging actor from
  escort targets. The exclusion is narrowly tied to `UnitFromId(2)` and the static contract;
  it does not suppress ordinary hostile units.
- Port 18302 reached `in_game`, Catalog `3786/12225`, and advanced from loop 88 to loop 2768
  while clearing hostile units, but the pre-fix probe repeatedly attacked that staging actor and
  the websocket later closed. It did not reach Region 24 or observe P2 ownership.
- Fresh post-fix ports 18303 and 18304 both reached launcher ready and `CreateGame=init_game`,
  then closed their websocket before `JoinGame=in_game`. Both same-window ScriptError scans were
  clean. These are runtime availability failures, not gameplay or P2 evidence.
- The bounded verdict remains `blocked`: rerun the unchanged, debug-free probe only after a
  stable JoinGame runtime window is available. P2 dispatch stays fail-closed.
