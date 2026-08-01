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

## Final AI ally verification

- `static`: `python -m pytest -q tools/launchers/tests/test_launch_cmre_alenger_static.py tools/launchers/tests/test_live_runner_unit_adapter.py` -> `8 passed`.
- `static`: `python -m py_compile src/projects/cmre-porting/vibe/run_dead_of_night_live.py tools/galaxy-vibe/evidence_bundle.py tools/launchers/tests/test_live_runner_unit_adapter.py` -> pass.
- `static`: PowerShell `Parser.ParseFile` over `tools/launchers/lib/cmre-on-demand-overlay.ps1` -> no parse errors.
- `simulator`: Stage 12 manifest identity and Dead of Night deterministic smoke remain passing; no simulator regression was introduced.
- `runtime`: `runtime-summary-custom-adapter-long-v1.json` -> map `[CM] 亡者之夜`, end loop `5504`, player 1 survivors `15`, `827/827` dispatched actions succeeded, and `behavior_verdict=pass`.
- `runtime`: runtime assertions all pass: frames advanced, player units observed, action results correlated, action success observed, and non-neutral action success observed.
- `runtime`: `script-error-verdict.json` -> `has_new_errors=false`, `count=0`.
- `static+runtime`: `workflow_status.py --runtime-artifacts-dir ... --evidence-bundle ...` -> `overall=warn`, `pass=6`, `warn=2`, `fail=0`; warnings are the known legacy parser and carried-forward bundle classification.
- `static+simulator+runtime`: Stage 15 bundle generated at `artifacts/projects/cmre-porting/stage15-ai-ally-vibe-application/evidence-bundles/bundle-stage15-ai-ally-vibe-application-live-20260801-1500`; `21` items. It contains the manifest, launcher stdout, packed map, full runtime summary, replay, ScriptError verdict, static test result, standard runtime wrapper/assertions, and combined verdict.

## Resolved runtime issues

- Empire starting units are now observed as `SCV` (`4382`) and `CommandCenter` (`4390`) through the live adapter.
- Live actions no longer return `NotSupported`: gather uses ability `1`, Empire SCV training uses custom ability `17443`, and all `827` final-run actions returned `Success`.
- Neutral map objects are excluded from threat selection; only `alliance=Enemy` objects enter the policy threat list.

## Scope boundary

Stage 15 is verified. No Stage 16 directory is defined in this project, so no next-stage plan was created outside the active writeScope. The carried-forward parser warning remains recorded rather than being converted into a false PASS.
