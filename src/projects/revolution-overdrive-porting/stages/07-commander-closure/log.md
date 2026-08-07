# Stage 07 Log: Commander Closure

## Scope and decision

- Stage plan: `src/projects/revolution-overdrive-porting/stages/07-commander-closure/plan.md`.
- The read-only source `C:/Users/22448/Downloads/RevolutionOverdrive缝合版/RevolutionOverdrive缝合版` was not modified.
- The existing `assets/` mirror was not modified and remains the source of large binary asset coverage.
- The workspace `activeProject` remains `cmre-porting` by the prior project decision; this RO stage is governed by its explicit project manifest.
- Stage status is `blocked`: commander/map closure and static checks pass, but the native SC2 session does not reach `in_game`.

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

## Native runtime diagnosis

1. Port `18130`: the existing API probe reached the listener, but `ActionChat`, `RequestStep`, and `Observation` returned `Not in game`; observation stayed `launched`, loop `0`, Catalog units/abilities `0`. Evidence: `artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/runtime-probe/`.
2. Port `18131`: strict `Sc2Api.RealSmoke` with `map_data` recorded `CreateGame=init_game`, then `JoinGame=LaunchError` with `无法打开地图`. Evidence: `artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/runtime-diagnosis-18131/realsmoke/`.
3. Port `18132`: path-based API probe returned no explicit Create/Join error, but all observations remained `status=launched`, `game_loop=0`, and Catalog units/abilities `0`; no worker was found. Evidence: `artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/runtime-diagnosis-18132/sc2api_runtime_probe.json`.
4. Port `18133`: the existing profile runner rejected directory-form input because its directory adapter appends `MapInfo`; this is a harness input-shape failure, not a RO closure claim. Evidence: `artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/runtime-diagnosis-18133/realprofile/result.json`.
5. Port `18134`: the same packed map was temporarily placed under the SC2 `Maps` directory and exercised with path-only CreateGame. `CreateGame` passed, but after the runner's JoinGame retries the final state was `Launched` with `Must first start a game with CreateGame or specify ports to join another client's game`. Evidence: `artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/runtime-diagnosis-18134/realprofile/result.json`.
6. Port `18134` same-window ScriptError scan: `has_new_errors=false`, count `0`. Evidence: `artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/runtime-diagnosis-18134/script-error-verdict.json`.

The reproducible blocker is therefore the `init_game -> in_game` transition after the map has been closed and staged. No native faction, unit owner/alliance, `ActionChat("Iron")`, or native AI ally roster claim is made.

## AI ally boundary

The RO adapter remains fail-closed. Its five deterministic tests pass, and the 24 maps with dynamically resolved owners remain unresolved rather than being widened by inference. Native owner/alliance capture is deferred until a playable window exists.

## Handoff

The next diagnosis must compare the standard API bootstrap with a controlled direct-map/`join-existing` candidate and a known-good map under the same SC2 installation. See `next-stage-plan.md`. The direct-map candidate is not promoted: the existing CMRE evidence shows it can listen without answering the API handshake.
