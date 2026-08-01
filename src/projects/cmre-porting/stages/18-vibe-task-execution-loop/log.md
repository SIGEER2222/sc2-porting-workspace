# Stage 18 Log

## Scope opened

Stage 18 follows the verified Stage 17 typed action/query registry. It owns
the project Vibe task-loop schema, simulator/Host orchestration, tests, and
generated evidence under the declared writeScope. Registered source maps and
external repositories remain read-only.

## Evidence

Implementation and verification entries will be appended as each simulator,
static, and runtime gate completes. Claims must remain classified as
`static`, `simulator`, `runtime`, `blocked`, or `inference`.

## Implementation

- `runtime`: Added a temporary, stage-local preservation runner at
  `artifacts/projects/cmre-porting/stage18-vibe-task-execution-loop/temporary/preserve-native-start.ps1`.
  It invokes the existing compliant launcher unchanged, packs only the staged
  map copy with the existing StormLib tool, runs the Host through
  `python -m vibe.task_loop`, and cleans up only the SC2 PID discovered from
  this run.
- `runtime`: The runner performs read-only census queries for the native and
  historical CMRE starting-unit ids before the action scenario. It does not
  call any creation or removal function for the starting base/workers.

## Verification

- `simulator`: `src/projects/cmre-porting/stages/18-vibe-task-execution-loop/simulator-result.json`
  -> `PASS`, six steps completed.
- `static`: `python -m pytest -q src/projects/cmre-porting/stages/18-vibe-task-execution-loop/test_task_loop.py tools/galaxy-vibe/tests/test_kernel.py tools/launchers/tests/test_launch_cmre_alenger_static.py tools/launchers/tests/test_live_runner_unit_adapter.py`
  -> `60 passed`.
- `static`: PowerShell parser over the temporary runner -> `PASS`.
- `runtime`: `evidence-stage18-preserve-native-runtime/verdict.json` ->
  launcher exit `0`; launch profile recorded
  `CreateStartingUnitsP1/P2=0`, `EnsurePreventDefeatP1/P2=0`, and
  `VanillaRemovalCount=0`; native census recorded `CommandCenter=1` and
  `SCV=12` for player 1.
- `runtime`: The same packed-map window passed the initialization gate with
  all listener/heartbeat/building/unit markers set and
  `world_cover_dialog_visible_p1=0`; `task-loop-runtime.json` completed all
  six observe/invoke/assert steps with state versions `1 -> 3`.
- `runtime`: `script-error-verdict.json` -> `has_new_errors=false`, `count=0`.
- `static+runtime`: Evidence bundle
  `evidence-bundles/bundle-stage18-preserve-native-runtime-20260801-153534`
  -> `overall_status=passed`, 17 items.

## Boundary

The original launcher, overlay, map source, and Galaxy initialization logic were
not changed by this preservation verification. The runtime preservation slice
and the simulator clearance slice remain separately classified.

## Simulator AI ally clearance

- `simulator`: `python -m vibe.run_dead_of_night --mvp-fast --clear-enemy-structures --output src/projects/cmre-porting/stages/18-vibe-task-execution-loop/simulator-clear-structures.json` -> `victory`, `end_reason=all_objectives_success`, loop `1882/2000`, and `remaining_enemy_structures=0` from `initial_enemy_structures=344`.
- `simulator`: The same run recorded six completed nights and all 24 wave triggers. Night buildings generated `infected_spawned=36`; the daytime rule removed `infected_cleared_in_day=27`; building damage generated `building_reinforcements_spawned=306`.
- `simulator`: The clear controller uses persistent global building targets, configurable push units, bounded reinforcement lifetimes, and a reduced duplicate-order interval. It never removes target buildings or changes the clear objective predicate.
- `static`: `python -m py_compile src/projects/cmre-porting/vibe/run_dead_of_night.py` -> pass before the final simulator run.
- `static`: `powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/run-all-validation.ps1` -> `52/52` checks passed, zero warnings; report at `artifacts/galaxy-vibe/static-validation-report.json`.

## Stage closeout

Stage 18 is verified as `PASS`. The next-stage write scope was authorized in
`src/projects/cmre-porting/project.json`, and the concrete plan is
`src/projects/cmre-porting/stages/19-simulator-ai-ally-clearance/plan.md`.
