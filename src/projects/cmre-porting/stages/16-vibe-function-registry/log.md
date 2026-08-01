# Stage 16 Log

## Scope opened

Stage 16 extends the approved write scope to the project-owned Vibe protocol,
the Galaxy Vibe tooling wrapper, the explicit function registry, and the
project map's controlled `LibVibeKernel` mirror. Registered source maps,
external mods, and external repositories remain read-only.

## Evidence

Implementation and verification entries will be appended after each gate. All
claims must remain classified as `static`, `simulator`, `runtime`, `blocked`,
or `inference`.

## Implementation

- `static`: Added the explicit `function.invoke` registry, typed Host/REPL
  request path, simulator dispatch, and Galaxy `vibe.test.ping` handler. The
  project map mirror and standalone debug-mod mirror remain aligned for the
  shared handler; the standalone debug-mod retains its legacy MapCommand
  wrapper.
- `static`: Fixed `libVibeKernel_gf_ArgsGet` in all three Galaxy mirrors. The
  previous inclusive end index included the `;` delimiter, turning
  `operation=function.invoke` into `function.invoke;` and contaminating
  `request_id` values.

## Verification

- `static+simulator`: `python -m pytest tools/galaxy-vibe/tests/test_kernel.py -q --junitxml artifacts/projects/cmre-porting/stage16-vibe-function-registry/live-function-fix-20260801-2124/pytest-kernel.xml` -> 39 passed.
- `static`: `python -m pytest -q tools/galaxy-vibe/tests/test_kernel.py tools/launchers/tests/test_launch_cmre_alenger_static.py tools/launchers/tests/test_live_runner_unit_adapter.py` -> 47 passed.
- `static`: `powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/run-all-validation.ps1` -> 52/52 passed, 0 warnings.
- `runtime`: `launch-cmre-alenger.ps1 -MapName 亡者之夜.SC2Map -Commander TerranRaynor -ListenPort 5074 -ApiMinimal -DebugMode -KeepAlive -MapCopySuffix stage16-function-fix` -> API ready, CreateGame/JoinGame path available, no new ScriptError.
- `runtime`: `pack_stormlib.py` followed by `galaxy_repl.py --port 5074 --map DeadOfNight.stage16.functionfix.packed.SC2Map --cmd 'invoke vibe.test.ping nonce=stage16-function-fix'` -> `OK`, payload `function_id=vibe.test.ping`, `message=pong`, nonce preserved.
- `runtime`: `GalaxyVibe.SC2Bank` contains response key `7f6719bb61f7` with `operation=function.invoke`, `error_code=OK`, and no delimiter contamination.
- `runtime`: `script_error_check.py --since 1785590694` -> `has_new_errors=false`, `count=0`; `summarize_verdict.py` -> PASS, assertions 6/6.
- `runtime`: Evidence bundle `artifacts/projects/cmre-porting/stage16-vibe-function-registry/evidence-bundles/bundle-stage16-function-fix-20260801-2124/evidence-bundle.json` -> 12 items, `overall_status=passed`.

## Closeout

Stage 16 is complete. The known legacy parser/catalog warning remains
carried forward from earlier stages and is not caused by the function
registry. Stage 17 is now the active stage and its plan is recorded at
`src/projects/cmre-porting/stages/17-vibe-action-capabilities/plan.md`.
