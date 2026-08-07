# Stage 07 Log: Commander Closure

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
