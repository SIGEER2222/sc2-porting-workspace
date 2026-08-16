# Stage 07 Log: Commander Closure

## 2026-08-15 WebUI thanson01 direct-map startup race

- `static`: `tools/launchers/launch-revolution-overdrive.ps1` previously exited on
  the first poll when `SC2Switcher_x64.exe` had not yet exposed its `SC2_x64`
  child. The launcher then wrote `ready=false` within seconds, while SC2
  continued loading in the background and the WebUI reported a misleading
  180-second ready timeout.
- `static`: The direct-map wait now allows a bounded 30-second SC2 child startup
  window, still exits early after an observed child disappears, and preserves
  the existing Alert and same-window ScriptError gates.
- `runtime`: `pwsh -NoProfile -ExecutionPolicy Bypass -File
  tools/launchers/launch-revolution-overdrive.ps1 -MapName thanson01.SC2Map
  -Faction Coverts -ReadyTimeoutSeconds 90 -NoCheats` -> exit `0`; the launcher
  emitted `Revolution Overdrive ready: thanson01.SC2Map / Coverts`.
- `runtime`: `artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/launcher-runtime.json`
  records `ready=true`, `scriptErrors=[]`, and `scriptErrorFree=true`; SC2
  remained running after the check. The WebUI itself remained reachable at
  `http://127.0.0.1:8767/` with HTTP `200`, 45 commander records, and 15 maps.
- `validation`: PowerShell parser passed; `python -m pytest -q
  tools/launchers/tests/test_launch_cmre_alenger_static.py` passed `62`; the
  focused WebUI/RO contract tests passed `26`.

## Scope and decision

- Stage plan: `src/projects/revolution-overdrive-porting/stages/07-commander-closure/plan.md`.
- The read-only source `C:/Users/22448/Downloads/RevolutionOverdrive缝合版/RevolutionOverdrive缝合版` was not modified.
- The existing `assets/` mirror was not modified and remains the source of large binary asset coverage.
- The workspace `activeProject` remains `cmre-porting` by the prior project decision; this RO stage is governed by its explicit project manifest.
- Stage status is `blocked` only at the native AI ally gate: commander/map closure, native RO bootstrap, and static checks pass, but P2 has not produced a native ally roster.

## Closure evidence

- `static`: `artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/source-owned-asset-closure.json` records exact source/owned/asset coverage for all eight required Mods. Missing, changed, and extra effective files are zero.
- `static`: `artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/staged-effective-closure.json` records a complete live staging closure for all eight Mods and `traynor01.SC2Map`.
- `static`: `src/projects/revolution-overdrive-porting/stages/06-map-closure/result.json` records all 31 maps complete and `traynor01` MPQ readback `50/50`.
- `runtime`: `artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/launcher-runtime.json` records the approved launcher staging, campaign dependencies present, `ready=true`, and zero same-window ScriptErrors for the latest launch.

## Static and deterministic validation

- `node tools/utils/workspace.mjs validate` -> `ok=true`; only pre-existing registered-path warnings remain.
- `node tools/utils/workspace.mjs lint src/projects/revolution-overdrive-porting/packages --format json --no-type-check` -> 74 files, 0 diagnostics.
- `node tools/analysis/analyze-catalog.mjs revolution-overdrive-owned-package Commander/Mods/RevolutionOverdrive.SC2Mod '.*' artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/owned-main-catalog.json` -> 36 XML files, 4,135 entries, 0 parse errors.
- `python -m unittest src/projects/revolution-overdrive-porting/stages/04-ai-ally/test_ai_ally_adapter.py -v` -> 5 passed.
- `python -m unittest tools/cmre-webui/test_revolution_overdrive.py -v` -> 2 passed.
- `python -m py_compile tools/runtime-bridge/sc2api_runtime_probe.py src/projects/revolution-overdrive-porting/vibe/ai_ally.py` -> pass.
- PowerShell parser for `tools/launchers/launch-revolution-overdrive.ps1` -> no errors.
- `launch-revolution-overdrive.ps1 -MapName thorner03.SC2Map -Faction Iron -ListenPort 18149 -NoLaunch` -> staging pass; source/staged file count `55/55`.
- Supplementary `node tools/analysis/static-validate.mjs revolution-overdrive-porting --stage
  src/projects/revolution-overdrive-porting/stages/07-commander-closure` was not runnable because
  this project has no `manifests/composition.json`; this is a tooling precondition gap, not a
  failed stage validation. The declared workspace validation and all stage-specific checks above
  remain passing.

## Native runtime diagnosis and reassessment

The earlier diagnosis bundles remain historical blocked evidence. The launcher was then corrected to pack through StormLib directly and the strict native census was rerun.

1. `runtime-bootstrap-20260807-ro-native-census` on port `18148` reached `CreateGame=init_game` and `JoinGame=in_game`; `RequestStep` advanced observations through loop `48`. Evidence: `artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/runtime-bootstrap-20260807-ro-native-census/native-census.json`.
2. The same window observed non-empty Catalog data (`units=3786`, `abilities=12225`) and P1-owned units (`owner=1`, `20` units after the first step). `ActionChat("Iron")` was accepted with no response errors and appeared in the observation chat. Evidence: the same native census bundle.
3. The same window recorded `has_new_errors=false`, `count=0` in the GameLogs scan. Evidence: `artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/runtime-bootstrap-20260807-ro-native-census/script-error-verdict.json`.
4. The P2 slot is present as a Computer roster entry, but no unit is owned by P2 and no P2 unit is visible as a P1 ally. The nine additional observed units have `owner=16` and `owner_alliance=Neutral`. Evidence: the native census `observations` and `ai_ally_contract` fields.

The runtime bootstrap blocker is resolved. The AI ally blocker is now narrower and reproducible: static shared-vision intent does not result in a native P2-owned roster or acknowledged P2 command in this map window.

## Long native AI ally observation

- `runtime-bootstrap-20260808-ro-ai-ally-long/long-census.json` records a fresh approved-launcher session on port `18150`: `CreateGame` was confirmed, `JoinGame` reached `in_game`, the map received a 45-second initialization wait, and the probe issued only native `RequestStep(300)` plus observations.
- Across 12 step batches, the query output remained the P1 initial roster (`3720 x5`, `LABBOT x2`, `HERC x2`, `TYCHUSCOMMANDO x1`). No P2-owned units, owner-16 units, or P2 command acknowledgement appeared. No debug injection, unit creation, cheats, or action commands were used.
- The bounded REPL wrapper exited nonzero after completing the scripted queries, so this is recorded as `blocked`, not as a clean full-run pass. The separate ScriptError gate passed with `count=0`: `runtime-bootstrap-20260808-ro-ai-ally-long/script-error-verdict.json`.
- The later map-owned `RescueUnit(UnitFromId(2), gv_p02_TYCHUS, true)` lifecycle was not reached; no permanent P2 absence is inferred from this window.

## Native action probe with P2 Computer setup

- `runtime-bootstrap-20260808-ro-ai-ally-actions/strict-action-census.json` records a fresh
  approved-launcher session on port `18156` with an explicit P1 participant plus P2 Computer
  setup. Strict responses were `CreateGame=init_game` and `JoinGame=in_game`.
- Native `attack-move` for the nine non-Tychus P1 units and native `move` for the P1 roster were
  both accepted with `ActionResult=1`, targeting the static Region 24 center `(89.1628, 41.6557)`.
  Tychus reached `(86.53, 31.34)` but died before entering the `Tychus Destination` region.
- Across the observation window, P2-owned units remained `0`; no P1-visible P2 ally appeared;
  the observed owner `16` units remained Neutral; and no P2 command acknowledgement appeared.
  The same launcher window had zero new ScriptErrors. No debug injection, unit creation, cheats,
  or map edits were used.
- This is stronger runtime blocked evidence, not an AI ally pass. Ordinary native actions are
  available, but they do not reach the map-owned `gt_VictoryWarehouseDudesKilled` -> `gt_MidQ`
  -> `gt_MidCleanup` rescue chain. The adapter remains fail-closed.

## AI ally boundary

The RO adapter remains fail-closed. Its five deterministic tests pass, and the 24 maps with dynamically resolved owners remain unresolved rather than being widened by inference. The native census now exists, but it does not authorize P2: P2-owned units, P1-visible allied units, and P2 command acknowledgement are all absent. No adapter widening or generic AI injection is justified by the current evidence.

## Handoff

The next stage must either provide a mission-safe way to progress `thorner03` through its
warehouse objective and `gt_MidCleanup`, or explicitly keep P2 unavailable for this map. See
`next-stage-plan.md`. The commander runtime is accepted only for the proven P1/bootstrap surface;
AI ally behavior remains blocked.

## Final Plan D verification

- `node tools/analysis/validate-schema.mjs src/projects/revolution-overdrive-porting/stages/07-commander-closure/result.json docs/schemas/stage-result.schema.json` -> pass. The result now uses only canonical claim types and integer validation exit codes; the supplementary validator with a missing `manifests/composition.json` precondition remains documented above rather than represented with an invalid `null` exit code.
- `python -m unittest src/projects/revolution-overdrive-porting/stages/04-ai-ally/test_ai_ally_adapter.py -v` -> 5/5 passed.
- `python -m unittest tools/cmre-webui/test_revolution_overdrive.py -v` -> 2/2 passed.
- `python -m py_compile tools/runtime-bridge/sc2api_runtime_probe.py src/projects/revolution-overdrive-porting/vibe/ai_ally.py` -> pass.
- `node tools/utils/workspace.mjs lint src/projects/revolution-overdrive-porting/packages --format json --no-type-check` -> 74 files, zero diagnostics.
- `node tools/analysis/analyze-catalog.mjs revolution-overdrive-owned-package Commander/Mods/RevolutionOverdrive.SC2Mod '.*' artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/final-owned-main-catalog.json` -> 36 XML files, 4,135 entries, zero parse errors.
- `powershell -NoProfile -ExecutionPolicy Bypass -File tools/launchers/launch-revolution-overdrive.ps1 -MapName thorner03.SC2Map -Faction Iron -ListenPort 18149 -NoLaunch` -> staging pass; source/staged file count remains 55/55.
- `node tools/utils/workspace.mjs validate` -> `ok=true`; the same ten pre-existing registered-path warnings remain and no errors were introduced.
- `git diff --check` -> no whitespace errors. The command reports only normal LF/CRLF conversion warnings for modified text files.
- `node tools/utils/workspace.mjs check-writescope --simulate` is not a valid invocation for this older utility: its `--simulate` parser expects a path and throws a type error. The real changed-path report separately identifies only the pre-existing `assets/` and `map-glue.reborn-zchar01.galaxy` changes outside this stage; no out-of-scope Stage 07 file is staged.

## 2026-08-16 Iron opening realtime retry

- `static`: `iron_opening_runtime_probe.py` now matches the installed protobuf schema (`raw_pb2.Unit` exposes `is_blip`, not `is_snapshot`), records the full P1 raw-unit census, and can issue a finite number of delayed native moves based on game loop. `python -m py_compile .../iron_opening_runtime_probe.py` passed.
- `runtime`: The approved launcher command on port `5963` staged `thanson01.SC2Map` from 57 files, applied `thanson01-iron-opening`, injected `runtime_galaxy_bootstrap`, reached `ready=true`, and sent no faction chat. Evidence: `runtime-bootstrap-20260816-ro-iron-thanson01/launcher-5963-default-data.log`.
- `runtime`: The same 5963 realtime probe reached `CreateGame=init_game`, `JoinGame=in_game`, P1, Catalog IDs for `1gangtiegongchengche`/`1gangtieyaosai`, and game loop `3 -> 545` with `requestStepsSent=0`. The native move to Region 29 returned `ActionResult=1`, but no target unit appeared; verdict is `blocked_target_units_not_observed`. Evidence: `runtime-bootstrap-20260816-ro-iron-thanson01/runtime-progressed-default-data.json`.
- `runtime`: A follow-up isolated 5964 launch with `-DataDirOverride` failed its 90-second ready gate while the user's external SC2 instance was active. No external process was terminated. Evidence: `runtime-bootstrap-20260816-ro-iron-thanson01/launcher-5964-isolated.log`; the current mutable `stage07-commander-closure/launcher-runtime.json` records this failed attempt and must not be used as a pass artifact.
- `inference`: The missing Iron worker/fortress is consistent with the map-owned `gt_StartHansonEscortPhase` waiting for `gv_missionPhase == Escort`; a single early move of the initial cinematic units is insufficient proof of reaching that transition. No commander adapter widening or artificial base creation was made.

## 2026-08-16 Pure runtime Iron replacement closure

- `static`: Removed the launcher's direct SCV and rescue-site text rewrites. The owned map still
  contains `libNtve_gf_UnitCreateFacingPoint(1, "SCV", ...)`; the adapter now records the declared
  replacement and injects only a runtime Galaxy bootstrap. Regression coverage is in
  `stages/07-commander-closure/test_iron_runtime_adapter.py`.
- `static`: The runtime bootstrap registers `UnitCreated`, `UnitChangeOwner`, and `TimePeriodic`
  events, scans P1 units, applies Iron tech, and calls `libNtve_gf_ReplaceUnit` for SCV and
  CommandCenter/OrbitalCommand/PlanetaryFortress. It requires no chat command or UI selection.
- `runtime`: The approved launcher on port `5967` reached `ready=true` in a secondary client,
  selected the unique packed path `thanson01.stage07.5967.packed.SC2Map`, and left the external
  SC2 process untouched. Evidence: `launcher-runtime.json` and the launcher output.
- `runtime`: The same realtime probe reached `CreateGame=init_game`, `JoinGame=in_game`, and
  advanced game loop `3 -> 405` with `requestStepsSent=0`. Three native moves reached Region 29;
  the map-owned Escort/rescue lifecycle then exposed 8 `1gangtiegongchengche` workers and 1
  `1gangtieyaosai` fortress at loops 389 and 405. Evidence:
  `runtime-bootstrap-20260816-ro-iron-thanson01/runtime-pure-runtime-secondary-5967.json`.
- `runtime`: The same launcher window has `ready=true`, `apiStable=true`, and zero new
  `*ScriptError*.txt` files. Evidence:
  `runtime-bootstrap-20260816-ro-iron-thanson01/script-error-verdict-pure-runtime-5967.json`.
- `validation`: The four pure-runtime adapter regression tests, Python compilation, and
  PowerShell parsing all pass. Stage 07 is now `passed` for commander closure; the general
  RO-AI-001 dynamic-owner population remains explicitly open and fail-closed.

## 2026-08-16 All-faction runtime replacement closure

- `static`: The first Coverts retry exposed a generator defect rather than a game failure:
  the JSON evidence declared `SCV -> SCVC`, but PowerShell unwrapped the one-element property
  before the count-based Galaxy generation loop, leaving the generated replacement function
  empty. The launcher now normalizes `runtimeReplacementList` and substitutes explicit
  bootstrap markers. The generated staged script contains the real `if (lv_type == "SCV")`
  and `libNtve_gf_ReplaceUnit(..., "SCVC", ...)` branch.
- `runtime/blocked historical`: Coverts port `5982` reached `init_game/in_game` and observed
  `CommandCenterC`, but the pre-fix probe failed on a stale `TARGET_TYPES` name. Coverts port
  `5983` then observed `CommandCenterC` while the generator defect still left map SCVs native;
  neither is promoted as the final pass. These artifacts remain under
  `runtime-bootstrap-20260816-ro-coverts-thanson01/` for diagnosis.
- `runtime`: The repaired Coverts window on port `5984` reached `CreateGame=init_game`,
  `JoinGame=in_game`, and realtime observations without `RequestStep`. The map-owned escort
  progression exposed `SCVC` workers and `CommandCenterC`; the probe verdict is
  `passed_realtime_coverts_replacement_observed`. Same-window ScriptError count is zero.
  Evidence: `runtime-bootstrap-20260816-ro-coverts-thanson01/runtime-coverts-secondary-5984.json`
  and `script-error-verdict-coverts-5984.json`.
- `runtime`: The repaired Umojan window on port `5985` reached the same strict lifecycle and
  observed `SCVU` plus `CommandCenterU`; `requestStepsSent=0`, no faction chat, and same-window
  ScriptError count is zero. Evidence: `runtime-bootstrap-20260816-ro-umojan-thanson01/`.
- `runtime`: The Pirate bridge window on port `5986` observed `9shougezhe` from the native
  Revolution Overdrive trigger bridge; `requestStepsSent=0` and ScriptError count is zero.
  Evidence: `runtime-bootstrap-20260816-ro-pirate-thanson01/`.
- `runtime`: The Madness bridge window on port `5987` observed `3diguozhijian`; realtime
  progression, no faction chat, and same-window ScriptError count zero are recorded in
  `runtime-bootstrap-20260816-ro-madness-thanson01/`.
- `runtime`: A post-generator-fix Iron regression on port `5988` observed
  `1gangtiegongchengche` and `1gangtieyaosai` with `requestStepsSent=0` and zero same-window
  ScriptErrors. Evidence: `runtime-bootstrap-20260816-ro-iron-thanson01/runtime-Iron-secondary-5988.json`
  and `script-error-verdict-Iron-5988.json`.
- `validation`: `python -m unittest src/projects/revolution-overdrive-porting/stages/07-commander-closure/test_iron_runtime_adapter.py -v` passed 8/8; PowerShell parsing and Python compilation passed; all five fresh approved launcher windows returned exit 0 and all five probes returned exit 0.
- `validation`: After the live clients exited, a clean sequential approved launcher `-NoLaunch`
  smoke for `Iron`, `Coverts`, `Umojan`, `Pirate`, and `Madness` all returned exit 0. The earlier
  second-faction staging failure was a live-client directory lock and is not promoted as a
  product failure.

## 2026-08-16 Commander x map rollout matrix

- `static`: Added `map-commander-adaptation-plan.md` as the execution contract for 30 eligible
  maps x 5 commanders = 150 cells. `tarcade.SC2Map` is excluded as the Stage 04 entry-flow
  arcade map; `tstory01.SC2Map` remains explicitly pending because it is also entry-flow.
- `static`: Added `artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/map-commander-matrix.json`.
  It joins every cell to the preserved MapScript, Stage 04 roster, adapter rule, target Catalog
  IDs, protected players, and a dedicated runtime evidence directory.
- `static`: The matrix guard passed 3/3. It reports 7 current runtime-pass cells
  (`thanson01` x 5, `thanson02/Iron`, `thanson03a/Iron`) and 143 `runtime_pending` cells.
- `blocked`: The first new `thanson02/Iron` launcher attempt without `-SecondaryClient` was
  correctly rejected because an external SC2 PID 31752 was already running. A retry through the
  approved `-SecondaryClient` path on port 5991 staged 50 files but did not produce the requested
  ready signal within 90 seconds; no existing SC2 process was terminated and no runtime pass was
  inferred. Evidence: `artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/launcher-runtime-blocked.json`
  and the current `launcher-runtime.json`.
- `next`: Keep the four remaining `thanson02` cells pending until a fresh independent API window
  is available, then proceed map-by-map in the order recorded by the rollout plan.
