# Stage 21 Log

## Scope

Stage 21 validated the project-owned Vibe control path in real SC2 windows.
The approved CMRE launcher entered the staged Dead of Night map directly; the
original map initialization remained intact and no source map or canonical
commander behavior was edited.

## Runtime evidence

- `runtime`: Native-start window launched with
  `artifacts/projects/cmre-porting/stage18-vibe-task-execution-loop/temporary/preserve-native-start.ps1 -ListenPort 5094 -MapCopySuffix stage21-runtime-native -Commander TerranRaynor` and was archived at
  `artifacts/projects/cmre-porting/stage21-runtime-ai-ally-clearance/runtime-native-20260802-001145/`.
- `runtime`: Launcher exit was `0`; native census observed
  `CommandCenter=1` and `SCV=12`. `CreateStartingUnitsP1/P2`,
  `EnsurePreventDefeatP1/P2`, and `VanillaRemovalCount` were all `0`.
- `runtime`: The same window completed the typed Vibe task loop `6/6` with
  correlated function responses and initialization gate success.
- `runtime`: A separate `stage21-runtime-live` launcher window ran
  `vibe.run_dead_of_night_live` to loop `1500`. It observed 17 surviving P1
  units, dispatched 21 actions, and received 21 successful results: 15 gather
  and 6 train. Runtime assertions for frame advance, observed units,
  correlation, action success, and non-neutral action success were all true.
- `runtime`: ScriptError checks using the actual launch epochs for both windows
  found zero new files.

## Boundary

The live adapter run is a real defensive/economic control slice, not a full
structure-clear controller. Its report has no all-344-building census and must
not be promoted to a runtime `destroy_all_enemy_structures` victory. The next
stage must add or validate a typed combat/census boundary before claiming that
runtime objective.

## Evidence paths

- `artifacts/projects/cmre-porting/stage21-runtime-ai-ally-clearance/runtime-native-20260802-001145/verdict.json`
- `artifacts/projects/cmre-porting/stage21-runtime-ai-ally-clearance/runtime-native-20260802-001145/task-loop-runtime.json`
- `artifacts/projects/cmre-porting/stage21-runtime-ai-ally-clearance/runtime-native-20260802-001145/script-error-verdict.json`
- `artifacts/projects/cmre-porting/stage21-runtime-ai-ally-clearance/live-ai-ally-20260802-0016/live-runtime-summary.json`
- `artifacts/projects/cmre-porting/stage21-runtime-ai-ally-clearance/live-ai-ally-20260802-0016/script-error-verdict.json`
