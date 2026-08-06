# Stage 04 Self-Assessment

## Result

The mission-safe AI ally adapter is complete for static and deterministic validation. It
extracts map-owned relationships without editing any source map and refuses to authorize a
generic ally contract for entry-flow maps.

## Proven

- All 31 owned maps were parsed. Twenty-nine are mission maps and two are entry-flow maps.
- No owned map script contains an `AIStart` or `AIMeleeStart` call.
- Explicit P1 ally/enemy edges are converted into a fail-closed contract. P1 is the only
  command source, observations are limited to P1/P2, and targets must be positive owners
  explicitly declared as P1 enemies.
- Low-level `PlayerSetAlliance` calls and `PlayerGroupAdd` calls remain in the roster audit
  record without being over-interpreted as action permissions.
- The source map scripts remained byte-identical during extraction.

## Not Proven

- Native SC2 runtime loading and runtime listener evidence remain blocked by the missing
  `Campaigns/Void.SC2Campaign` dependency recorded in `RO-PKG-001`.
- Dynamic Galaxy expressions are retained as unresolved evidence and do not expand the safe
  target set. Runtime roster capture is required before supporting those dynamically created
  owners.
- The full Stage 25 capability unittest suite did not finish within the bounded 60-second
  command window. The targeted five-test ally capability regression and the 9-test runtime
  matrix both passed.

## Decision

Keep mission initialization, alliance setup, objectives, and scripted AI map-owned. The adapter
is a boundary for observations and commands, not a replacement for mission AI initialization.
