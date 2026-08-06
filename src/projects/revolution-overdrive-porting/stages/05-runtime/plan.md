# Stage 05 Plan: Native Runtime Closure

## Objective

Resolve the declared campaign dependency blocker and verify one Revolution Overdrive map,
commander faction selection, and the mission-safe AI ally contract in the native SC2 runtime.
Keep WebUI selection optional and do not convert staging or process startup into runtime evidence.

## Inputs

- Stage 03 owned commander/map package and approved Revolution Overdrive launcher.
- Stage 04 static roster and contract evidence.
- The read-only Revolution Overdrive source package for comparison only.
- An approved installation or owned replacement for `Campaigns/Void.SC2Campaign`.

## Write scope

- `src/projects/revolution-overdrive-porting/project.json`
- `src/projects/revolution-overdrive-porting/stages/05-runtime/**`
- `artifacts/projects/revolution-overdrive-porting/stage05-runtime/**`
- `tools/launchers/launch-revolution-overdrive.ps1` only if a runtime-proven launcher defect is found.

## Tasks

1. Verify the Void Campaign dependency exists and record its source/hash without modifying the
   registered read-only download.
2. Run the approved launcher through `tools/launchers/launch-revolution-overdrive.ps1` for one
   representative mission and one faction preset, with a runtime listener and fresh log window.
3. Require CreateGame/JoinGame or the approved runtime equivalent, advancing frames, listener
   heartbeat, current assertions, and same-window `*ScriptError*.txt` review.
4. Capture faction-specific player-one unit state and mission-owned alliance/owner state; compare
   the observed legal targets with the Stage 04 static contract.
5. Repeat the smallest end-to-end path through WebUI only if the optional UI route is available;
   keep direct launcher evidence authoritative.

## Validation

- `Test-Path` and dependency manifest/hash check for `Void.SC2Campaign`.
- Approved launcher with `-ListenPort`, `-MapName`, and faction selection.
- Runtime listener event/heartbeat and advancing-frame evidence.
- Current-window GameLogs ScriptError scan with no new errors.
- Runtime assertion that P1 owns the selected faction units, P1 is the command source, and no
  ally/neutral/unknown target is accepted.
- `python -m unittest` for Stage 04 and WebUI regressions after any launcher change.

## Stop conditions

- Stop native validation as blocked if the campaign dependency is absent or runtime listener
  evidence cannot be obtained.
- Do not claim native runtime success from launcher exit code, process startup, or staging alone.
- Do not broaden the adapter for unresolved dynamic owners without runtime evidence and a new plan.
