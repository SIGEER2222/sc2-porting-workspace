# Stage 23 Log: Runtime Full Structure Clearance

## Status

`PASS`: a fresh approved launcher window completed the typed full-structure
clearance while preserving native initialization and producing a same-window
zero-ScriptError result.

## Scope and safety

- The controller remained project-owned under this stage.
- The source map, canonical commander behavior, and shared Galaxy behavior
  were not modified to force victory.
- The controller used only registered typed census, spawn, attack, and
  RequestStep operations. Neutral, allied, stale, dead, and non-objective
  structures were excluded from the objective projection.
- A no-progress retry may reallocate idle attackers to a still-live target,
  but stale `INVALID_ARGS` responses remain bounded by the allocator retry
  budget. No delete, replacement, debug-victory, or arbitrary ability path was
  added.

## Verification

- `static`: focused Stage 23 contract tests passed: `11 passed`.
- `static`: cross-stage regression passed: `71 passed, 3 subtests passed`.
- `static`: Python compilation and `git diff --check` passed.
- `static`: `pwsh -NoProfile -ExecutionPolicy Bypass -File
  tools/galaxy-vibe/run-all-validation.ps1` passed `52/52` with zero warnings;
  report: `artifacts/galaxy-vibe/static-validation-report.json`.
- `simulator`: `powershell -NoProfile -ExecutionPolicy Bypass -File
  tools/galaxy-vibe/vibe.ps1 manifest -RunId stage23-manifest-preflight`
  passed. This remains simulator preflight evidence, not live clearance.
- `runtime`: approved launcher command:
  `pwsh -NoProfile -ExecutionPolicy Bypass -File tools/launchers/launch-cmre-alenger.ps1 -MapName 亡者之夜.SC2Map -Commander TerranRaynor -ListenPort 5125 -ApiMinimal -DebugMode -KeepAlive -MapCopySuffix stage23-runtime-full-1330`.
  The launcher reported API ready and runtime listener readiness.
- `runtime`: controller command used the packed, repo-relative map input and
  produced `artifacts/projects/cmre-porting/stage23-runtime-full-structure-clearance/runtime-result-pass14.json`.
  CreateGame + JoinGame and the initialization gate passed. The initial typed
  objective census was `206`; the last successful typed census had `8`, after
  which RequestStep closed the completed mission and terminal observation
  verified zero remaining declared tags with player results. The post-close
  API census error is captured and is not used as the zero-target assertion.
  The frame loop advanced `63 -> 7727`; `542` typed attack responses were
  correlated with unique request IDs, `function.invoke` operations, and
  non-negative state versions.
- `runtime`: native preservation passed with `CommandCenter=1` and `SCV=12`
  before and after. `CreateStartingUnitsP1/P2`,
  `EnsurePreventDefeatP1/P2`, and `VanillaRemovalCount` stayed `0`.
- `runtime`: `python tools/galaxy-vibe/script_error_check.py --since
  1785648216 --out artifacts/projects/cmre-porting/stage23-runtime-full-structure-clearance/script-error-verdict-pass14.json`
  reported zero new ScriptError files in the launcher window.
- `runtime`: evidence bundle
  `artifacts/projects/cmre-porting/stage23-runtime-full-structure-clearance/evidence-bundle-pass14.json`
  contains 6 runtime, 2 static, and 1 simulator items; all item hashes are
  present.

## Runtime retries

Earlier attempts are retained as partial/blocked diagnostics. One run left
41 structures because it reserved attackers and stopped at its loop budget;
another reached one final structure but queried the API after the game ended;
the corrected retry path and terminal snapshot handling were verified by the
pass14 window. These attempts are not used as the PASS evidence.

## Changed paths

- `run_runtime_full_structure_clearance.py`: bounded no-progress target
  reallocation and successful terminal census/native snapshot handling.
- `test_full_structure_clearance.py`: allocator and terminal/retry regressions.
- `result.json`, `issues.json`, and this log: verified stage handoff.
- `artifacts/projects/cmre-porting/stage23-runtime-full-structure-clearance/evidence-bundle-pass14.json`:
  categorized evidence manifest.
- `src/projects/cmre-porting/stages/24-final-acceptance/plan.md`: next-stage
  acceptance plan.

## Next Step

Stage 24 consolidates the completed stage evidence and performs final project
acceptance using the explicit runtime/static/simulator artifacts. It must not
rewrite the source map or reinterpret simulator output as runtime evidence.
