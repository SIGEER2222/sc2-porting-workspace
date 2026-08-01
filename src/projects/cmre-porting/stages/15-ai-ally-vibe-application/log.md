# Stage 15 Log

## Scope update

The Dead of Night startup policy is now map-specific at the staged code level. The registered source map remains read-only. The compliant launcher copies the map into an isolated staged runtime directory, patches the staged `LibCOOC.galaxy` startup branch, and rejects `-ShowSelectionUI` for `亡者之夜.SC2Map`.

## Verification

- `static`: `python -m pytest -q tools/launchers/tests/test_launch_cmre_alenger_static.py` -> 6 passed.
- `static`: PowerShell `Parser.ParseFile` over `tools/launchers/lib/cmre-on-demand-overlay.ps1` -> no parse errors.
- `static`: staged `LibCOOC.galaxy` and `MapScript.galaxy` scan -> no `CommanderSelectionScreen` token.
- `runtime`: `launch-cmre-alenger.ps1 -MapName 亡者之夜.SC2Map -Commander Empire -ListenPort 5011 -MapCopySuffix stage15-selection-final` -> launcher exit 0, API ready, no new ScriptError.
- `runtime`: `vibe.run_dead_of_night_live` against the packed map generated from that staged copy -> `CreateGame` OK, `JoinGame` OK, loop advanced to 300, map reported `[CM] 亡者之夜`, and no new ScriptError in the launch window.
- `blocked`: passing an unpacked staged directory directly to SC2 API `CreateGame` failed; the successful runtime attempt used `DeadOfNight.launcher.packed.SC2Map` produced by `tools/mpq/scripts/pack_stormlib.py`.
- `simulator`: `python -m vibe.run_dead_of_night --max-loops 300 --output artifacts/projects/cmre-porting/stage15-ai-ally-vibe-application/simulator-300.json` -> victory, 32 player survivors, 424 dispatched commands, no deadlock.
- `simulator+static`: `powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/vibe.ps1 workflow -RunId stage15-workflow-final1` -> operator exit 0; workflow status warn only for the carried-forward parser/evidence lanes.

## Runtime limits

The selection-free startup assertion is verified, but the AI ally application is not complete. The runtime observation remained at one `ACHeroSpawnPlacement` unit with zero resources, and all 13 runner actions returned `sc2:NotSupported`. The current evidence proves map entry and frame advancement only; it does not prove custom starting-unit creation or successful AI actions.

## Evidence paths

- `artifacts/projects/cmre-porting/stage15-ai-ally-vibe-application/live-selection-free-final/launcher-stdout.txt`
- `artifacts/projects/cmre-porting/stage15-ai-ally-vibe-application/live-selection-free-final/runtime-summary-launcher-packed.json`
- `artifacts/projects/cmre-porting/stage15-ai-ally-vibe-application/live-selection-free-final/script-error-verdict.json`
- `artifacts/projects/cmre-porting/stage15-ai-ally-vibe-application/live-selection-free-final/DeadOfNight.launcher.packed.SC2Map`
- `src/projects/cmre-porting/artifacts/live_replay_20260801_084514.jsonl`
- `artifacts/projects/cmre-porting/stage15-ai-ally-vibe-application/simulator-300.json`
- `artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/workflow-status.json`
- `artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/bundles/bundle-stage15-workflow-final1/evidence-bundle.json`

## Changed paths

- `tools/launchers/launch-cmre-alenger.ps1`
- `tools/launchers/lib/cmre-on-demand-overlay.ps1`
- `tools/launchers/overlays/cmre-alenger/startup/tail.headless.galaxy`
- `tools/launchers/tests/test_launch_cmre_alenger_static.py`
- `src/projects/cmre-porting/stages/15-ai-ally-vibe-application/plan.md`
