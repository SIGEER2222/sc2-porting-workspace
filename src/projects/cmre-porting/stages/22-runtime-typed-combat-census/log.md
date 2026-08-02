# Stage 22 Log

## Scope

Stage 22 closed the runtime boundary left by Stage 21: a typed structure census
and a bounded typed combat command were exercised in a real SC2 window. The
probe used a temporary Vibe-created Marine for the valid attack and did not
replace, delete, or rewrite native map initialization.

## Verification

- [simulator] The focused contract suite passed: `3 passed, 3 subtests passed`.
  It covers typed census filtering, missing/neutral/ally/stale target rejection,
  read-only census behavior, and a valid attack with simulator frame advance.
- [static] Kernel, launcher, and Stage 22 regression tests passed: `54 passed,
  3 subtests passed`. Python compilation and `git diff --check` passed.
- [static] `tools/galaxy-vibe/run-all-validation.ps1` passed `52/52` with zero
  warnings.
- [runtime] The approved launcher command was:
  `pwsh -NoProfile -ExecutionPolicy Bypass -File tools/launchers/launch-cmre-alenger.ps1 -MapName 亡者之夜.SC2Map -Commander TerranRaynor -ListenPort 5105 -ApiMinimal -DebugMode -KeepAlive -MapCopySuffix stage22-runtime-final2`.
  Its ready/API gate passed and the runtime listener remained alive.
- [runtime] The staged map was packed with
  `tools/mpq/scripts/pack-sc2map.ps1` into
  `artifacts/projects/cmre-porting/stage22-runtime-typed-combat-census/runtime-20260802-1010/stage22-runtime-final2.packed.SC2Map`.
  The runner now resolves that packed input before `CreateGame` while keeping
  evidence paths repo-relative.
- [runtime] The final runner command used a repo-relative map argument:
  `python src/projects/cmre-porting/stages/22-runtime-typed-combat-census/run_runtime_typed_combat_census.py --port 5105 --map artifacts/projects/cmre-porting/stage22-runtime-typed-combat-census/runtime-20260802-1010/stage22-runtime-final2.packed.SC2Map --output artifacts/projects/cmre-porting/stage22-runtime-typed-combat-census/runtime-20260802-1010/runtime-result-relative-fixed.json`.
  It passed `CreateGame + JoinGame`, initialization, typed census/combat,
  frame advancement, and native preservation.
- [runtime] The final window observed `CommandCenter=1` and `SCV=12` before
  and after the probe. All `CreateStartingUnitsP1/P2`,
  `EnsurePreventDefeatP1/P2`, and `VanillaRemovalCount` flags were `0` before
  and after. The enemy census was nonzero (`194` live structures), all four
  invalid target classes returned `INVALID_ARGS`, valid attack returned `OK`,
  the target disappeared after loop `17 -> 748`, and heartbeat advanced
  `1 -> 19`.
- [runtime] The same-window ScriptError check used launch epoch `1785633903`
  and reported zero new files:
  `artifacts/projects/cmre-porting/stage22-runtime-typed-combat-census/runtime-20260802-1010/script-error-verdict-relative-fixed.json`.

## Runtime Trap Recorded

The first probe passed a staging directory to `CreateGame` and received error
`2`; a packed map is required. A second probe passed the packed file as a
relative path before runner normalization and also received error `2`. After
the runner resolved the input internally, the same repo-relative invocation
passed. This rule is recorded in the project-local `vibe-operator-workflow`
skill and must remain part of future runtime recipes.

## Boundary

This stage proves the typed combat/census boundary, not a runtime victory. The
probe intentionally attacks one target and leaves the remaining enemy
structures in place. Full objective clearance is carried to Stage 23 and is
not inferred from the simulator's zero-structure result.

## Evidence Paths

- The runtime bundle is intentionally retained under the repository-ignored
  `artifacts/projects` tree: it contains generated SC2 output and a packed map.
  The portable stage result and log are tracked; the local runtime paths below
  are the evidence handoff for this workstation.
- `artifacts/projects/cmre-porting/stage22-runtime-typed-combat-census/runtime-20260802-1010/runtime-result-relative-fixed.json`
- `artifacts/projects/cmre-porting/stage22-runtime-typed-combat-census/runtime-20260802-1010/script-error-verdict-relative-fixed.json`
- `artifacts/projects/cmre-porting/stage22-runtime-typed-combat-census/runtime-20260802-1010/stage22-runtime-final2.packed.SC2Map`
- `artifacts/projects/cmre-porting/stage22-runtime-typed-combat-census/runtime-20260802-1010/launcher-stdout.txt`
- `artifacts/galaxy-vibe/static-validation-report.json`

## Next Step

Stage 23 must implement and verify a temporary live clearance controller that
repeatedly censuses valid enemy structures, issues typed attacks, advances
frames, and proves zero remaining objective targets without touching native
initialization.
