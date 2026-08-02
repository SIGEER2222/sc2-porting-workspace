# Stage 23 Plan: Runtime Full Structure Clearance

## Objective

Use the Stage 22 typed census and combat boundary to prove a real SC2
structure-clearance slice through the approved launcher. The controller must
operate on native map state, preserve the original initialization, and claim
runtime victory only when its declared objective census reaches zero.

## Contract

- Launch only through `tools/launchers/`; use a packed `.SC2Map` input and let
  the runner resolve the path before `CreateGame`.
- Keep the controller temporary and project-owned under this stage or its
  artifact directory. Do not edit the registered source map or canonical
  commander behavior to make the test pass.
- Use only explicit typed Vibe registry functions for census, attack, and any
  movement or support action added for this stage. No arbitrary ability IDs,
  Galaxy reflection, mass deletion, building replacement, or debug victory.
- Define the target set from live observations and typed census results. Reject
  neutral and allied structures, handle stale tags and reinforcements, and
  keep mission-owned structures outside the target set unless their ownership
  and objective role are proven.
- Verify native `CommandCenter=1`, `SCV=12`, and zero replacement/removal
  flags before and after the controller. Non-realtime runs must advance through
  `RequestStep`, not wall-clock sleeps.

## Work Scope

1. Build a temporary runtime clearance runner that repeatedly queries the typed
   structure census, selects valid enemy targets, issues bounded combat work,
   advances frames, and records correlated results and state versions.
2. Reconcile the live structure census with the mission objective definition;
   distinguish enemy objective structures from ally, neutral, decorative, and
   dynamically spawned non-objective structures.
3. Add simulator or host regressions for target reallocation, stale tags,
   target death, reinforcements, bounded retry, and no-side-effect rejection.
4. Run a fresh approved-launcher window until either the declared target set is
   empty or a truthful runtime blocker is reached. Capture heartbeat, loop
   progress, census deltas, native initialization, and the same-window
   ScriptError verdict.
5. Close the stage only with a zero-target runtime assertion; otherwise record
   the blocker and keep the full-clearance claim open.

## Completion Gate

- A fresh launcher window reaches the map directly and passes the native
  initialization gate without commander-selection UI or building replacement.
- The controller produces correlated typed action results and advances frames
  while reducing the declared enemy objective census.
- The final runtime census reaches zero for the declared objective target set,
  or the result is explicitly `BLOCKED`/`PARTIAL` with the remaining target
  identities and next action recorded.
- Same-window ScriptError count is zero, all evidence paths are repo-relative,
  and simulator/static/runtime evidence remains separately classified.
- `result.json`, `log.md`, `issues.json`, and the next plan agree with the
  runtime verdict.

## Non-goals

- Do not replace or delete the CommandCenter/SCV initialization.
- Do not claim the simulator's 344-building clearance as SC2 runtime evidence.
- Do not alter the source map, commander mod, or shared canonical behavior for
  a one-off runtime probe.
