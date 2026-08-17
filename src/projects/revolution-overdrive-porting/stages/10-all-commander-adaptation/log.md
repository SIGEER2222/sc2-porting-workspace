# Stage 10 Log: All Commander Runtime Adaptation

## Status

In progress. This stage begins with the existing Stage 07 evidence: seven native map/commander
cells have realtime evidence, and no other cell is treated as runtime-passed.

## Evidence Rules

- `static`: generated manifest/matrix, source Mod Catalog checks, template syntax checks, and
  staged-map assertions.
- `runtime`: only an approved launcher window with `CreateGame`, `JoinGame`, advancing frames,
  target-unit observation, and same-window ScriptError scan.
- `blocked`: missing dependency, catalog, launcher slot, or entry-flow mismatch.

Validation commands and their observed results are appended after implementation.

## 2026-08-18 Generic Realtime Probe and Alenger3 Pilot

- `static`: Added `realtime_commander_probe.py`. It reads the selected commander from
  `vibe/commander_map_patches.json`, creates the game with `realtime=True`, never sends a manual
  step request, and requires strict CreateGame/JoinGame status, advancing raw observations,
  manifest target structure/worker observations, and same-window non-empty ScriptError absence.
  The implementation is not a runtime claim by itself.
- `static`: The launcher now uses .NET streaming SHA-256 instead of `Get-FileHash` so the approved
  `powershell.exe -NoProfile` runtime path can stage files on Windows PowerShell 5.1. A previous
  port-5992 attempt failed before SC2 launch because that command was unresolved; it is retained
  only in `runtime-pilot-5992/launcher.stdout.log` and is not runtime evidence.
- `static`: Added a staged Galaxy fallback for maps whose P1 opening has no replaceable base or
  worker. It creates exactly the manifest starting structure and worker count at the first P1
  mission-unit anchor, after ordinary replacement scanning. The source map and canonical commander
  Mods remain unchanged.
- `static`: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File
  tools/launchers/launch-revolution-overdrive.ps1 -MapName thanson01.SC2Map -Commander
  TerranAlenger3 -ListenPort 5995 -NoLaunch` staged successfully. The resulting MapScript had no
  unresolved template token and declared one `3diguoqianshaojidi` plus 12 `3diguolaogong` units.
- `runtime`: The approved launcher on port 5996 staged and packed `thanson01.SC2Map` with the
  three Alenger3 dependencies, reached API ready, and found no same-window ScriptError. Evidence:
  `artifacts/projects/revolution-overdrive-porting/stage10-all-commander-adaptation/runtime-pilot-5996/launcher-runtime.json`
  and `runtime-pilot-5996/launcher.stdout.log`.
- `runtime`: The matching generic probe reached `CreateGame=init_game` and `JoinGame=in_game`,
  observed realtime game loop `3 -> 11` with `requestStepsSent=0`, and observed P1 with exactly one
  `3diguoqianshaojidi` and 12 `3diguolaogong`. Its same-window ScriptError scan was empty. Verdict:
  `passed_realtime_starting_structure_and_worker_observed`. Evidence:
  `artifacts/projects/revolution-overdrive-porting/stage10-all-commander-adaptation/runtime-pilot-5996/realtime-probe.json`.
- `static`: Rebuilt `artifacts/projects/revolution-overdrive-porting/stage10-all-commander-adaptation/commander-map-matrix.json`
  from the runtime evidence index. Counts are 8 `runtime_pass`, 50 `unsupported`, and 1,492
  `runtime_pending`; only `thanson01.SC2Map` x `TerranAlenger3` was added by this stage.
- `static`: `python -m pytest -q
  src/projects/revolution-overdrive-porting/stages/10-all-commander-adaptation/test_commander_rollout.py
  tools/cmre-webui/test_revolution_overdrive.py tools/cmre-webui/test_launch_async_contract.py`
  -> `45 passed`. `python -m py_compile` for the generator/probe and PowerShell parser validation
  for the launcher also passed.

## Changed Paths

- `src/projects/revolution-overdrive-porting/vibe/build_commander_rollout.py`
- `src/projects/revolution-overdrive-porting/vibe/runtime_commander_overlay.galaxy.tpl`
- `src/projects/revolution-overdrive-porting/stages/10-all-commander-adaptation/realtime_commander_probe.py`
- `src/projects/revolution-overdrive-porting/stages/10-all-commander-adaptation/test_commander_rollout.py`
- `tools/launchers/launch-revolution-overdrive.ps1`
- `artifacts/projects/revolution-overdrive-porting/stage10-all-commander-adaptation/`
