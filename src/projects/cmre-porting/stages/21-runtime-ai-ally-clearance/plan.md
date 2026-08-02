# Stage 21 Plan: Runtime AI Ally Clearance

## Objective

Validate the simulator-hardened AI ally control path in a real Dead of Night
SC2 window. Enter the map directly through the approved launcher, preserve the
map's original initialization, and execute a bounded Vibe observe/action loop
against native game state before making any runtime clearance claim.

## Contract

- Launch only through `tools/launchers/`; never invoke `SC2_x64.exe` directly.
- The staged map must enter the mission without the commander-selection screen.
- The initialization gate must observe native `CommandCenter=1` and `SCV=12`
  (or an explicitly recorded native variation), with replacement/removal flags
  all zero.
- Runtime actions must use the existing typed Vibe function/task boundary or
  the project-owned live adapter. No debug building replacement, mass deletion,
  arbitrary Galaxy reflection, or source-map modification is allowed.
- Runtime evidence is separate from simulator evidence and requires launcher
  ready/API, CreateGame/JoinGame, advancing frame loops, action results,
  assertions, and same-window ScriptError verification.

## Work Scope

1. Add a temporary, project-owned runtime recipe/runner under this stage or
   `artifacts/projects/cmre-porting/stage21-runtime-ai-ally-clearance/` that
   observes native startup state and records a building census before actions.
2. Run the typed Vibe observe/invoke/assert loop against the fresh packed map,
   using real state queries and bounded attack/move commands where the runtime
   adapter supports them.
3. Advance non-realtime frames through the runtime listener; record heartbeat,
   state versions, command results, and target/death observations.
4. Verify the native initialization gate and the absence of replacement/removal
   behavior before and after the action loop.
5. Run the same-window ScriptError check, package launcher/API/assertion/state
   evidence, and compare runtime outcomes with the Stage 20 simulator reports.

## Completion Gate

- A fresh approved-launcher window reaches the map and passes the native start
  gate without selection UI.
- The typed Vibe action loop reaches its real target, receives correlated
  responses, advances frames, and records at least one truthful action result
  plus a resulting observable state change.
- Building identity/count remains native and no replacement/removal flag is
  observed; any inability to clear all buildings is recorded as blocked or
  incomplete rather than converted to a pass.
- Same-window ScriptError verdict is clean, and all runtime claims have runtime
  evidence paths in `log.md`.
- `result.json`, `log.md`, `issues.json`, and the next-stage plan agree.

## Non-goals

- Do not edit the registered source map, canonical commander mod, or original
  mission initialization to make the probe easier.
- Do not treat the Stage 20 simulator victory as proof of SC2 runtime victory.
