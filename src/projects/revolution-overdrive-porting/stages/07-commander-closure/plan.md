# Stage 07 Plan: Commander Mod Closure

## Objective

Close the owned Revolution Overdrive commander and its explicit Mod dependency chain so the
approved launcher stages the same effective files as the read-only source. Preserve map-owned
initialization, objectives, rewards, and alliances. The existing `assets/` repository is an input
asset mirror and must not be modified.

## Write scope

- `src/projects/revolution-overdrive-porting/project.json`
- `src/projects/revolution-overdrive-porting/stages/06-map-closure/**`
- `src/projects/revolution-overdrive-porting/stages/07-commander-closure/**`
- `artifacts/projects/revolution-overdrive-porting/stage06-map-closure/**`
- `artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/**`
- `src/projects/revolution-overdrive-porting/packages/Commander/**`
- `tools/launchers/launch-revolution-overdrive.ps1`

## Inputs and boundary

- Read-only source: `C:/Users/22448/Downloads/RevolutionOverdrive缝合版/RevolutionOverdrive缝合版`.
- Effective owned binary asset mirror: `assets/src/projects/revolution-overdrive-porting/packages/`.
- Owned commander package: `src/projects/revolution-overdrive-porting/packages/Commander/`.
- Existing MPQ extractor/verifier under `tools/mpq/scripts/`.

## Steps

1. Extract the seven source `.SC2Mod` archives into ignored Stage 07 artifacts and compare all
   eight source Mods against owned package directories plus the asset mirror.
2. Record source, owned, asset-only, missing, changed, and extra paths. Stop before copying if a
   common source/owned or source/asset hash differs.
3. Keep the large binary files in the existing `assets/` repository and treat exact-hash asset
   coverage as part of the effective owned package; do not duplicate them into the main repository
   and never modify the read-only source or `assets/` repository.
4. Update the approved launcher to merge the owned package and asset mirror into the live staging
   directories, fail clearly when a declared asset mirror is absent, and record effective closure
   manifests under Stage 07 artifacts.
5. Run workspace validation, Mod/catalog/Galaxy static checks, the RO AI ally tests, the WebUI
   tests, and the launcher `-NoLaunch` MVP. Verify the real SC2 staging directory contains every
   declared source path and matching hash.
6. Run one fresh native API session through the approved launcher: CreateGame, JoinGame,
   RequestStep, Observation, P1 owner/alliance census, `ActionChat("Iron")`, and same-window
   ScriptError scan. Do not promote listener readiness to runtime success.
7. Self-assess the native result. Only after a playable session exists may the next stage widen or
   change the AI ally adapter for unresolved dynamic owners.

## Stop conditions

- Never modify the read-only download or the existing `assets/` repository.
- Stop on any common hash change or missing source file not covered by an exact local asset.
- Do not claim runtime success from MPQ readability, staging, WebUI, process startup, or API Ping.
- If SC2 still returns `MissingMap`/`CannotOpenMap`, record the exact response and leave native
  commander/AI claims blocked.

## Validation

- Source archive extraction and full eight-Mod closure manifest.
- MPQ readability for extracted source archives and the packed representative map.
- Workspace validation and owned Mod catalog/Galaxy static checks.
- `python -m unittest src/projects/revolution-overdrive-porting/stages/04-ai-ally/test_ai_ally_adapter.py -v`.
- `python -m unittest tools/cmre-webui/test_revolution_overdrive.py -v`.
- Approved launcher `-NoLaunch` plus effective staging hash comparison.
- Native SC2 API MVP and same-window ScriptError evidence.
