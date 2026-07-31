# Stage Plan: Reborn MVP Feasible

## Objective

Integrate 5 Reborn mods into CMRE runtime via `-EnableReborn` switch and verify all 15 commanders' unit replacement on 亡者之夜 map, with black-screen fix.

## Inputs

- `src/projects/reborn-mods-cmre-integration/stages/02-static-boundaries/**`
- Registered source `reborn-hots-071`
- CMRE runtime at `cmre-runtime/`
- `tools/launchers/launch-cmre-alenger.ps1`
- `src/config/reborn-commanders.json`

## Write scope

- `src/projects/reborn-mods-cmre-integration/stages/03-mvp-feasible/**`
- `src/config/cmre-alenger-dependencies.json`
- `tools/launchers/launch-cmre-alenger.ps1`
- `cmre-runtime/Mods/reborn/crys_the_swarm_reborn.SC2Mod/{DocumentInfo,DocumentHeader}`

## Tasks

1. Deploy 5 Reborn mods to `cmre-runtime/Mods/reborn/` with sub-mod paths rewritten.
2. Deploy SwarmStory.SC2Campaign and swarmstoryutil.sc2mod to SC2 install Campaigns/.
3. Add `optionalPackageMods` block to `cmre-alenger-dependencies.json`.
4. Implement `-EnableReborn` switch in `launch-cmre-alenger.ps1`.
5. Implement black-screen fix patch in CMRE Galaxy host overlay.
6. Implement K5Kerrigan spawn patch (direct SwarmSetup trigger).
7. Batch test all 15 commanders via Bank file evidence (CMRERebornDebug.SC2Bank).

## Outputs

- `evidence/CMRERebornDebug.SC2Bank.20260727-final-*` (15 个指挥官的 Bank 证据)
- `evidence/batch-test-summary-20260727.json`
- `result.json`, `issues.json`, and the next stage plan.

## Validation

- All 5 Reborn mods synced to `cmre-runtime/Mods/reborn/`.
- `-EnableReborn` switch loads Reborn mods without ScriptError.
- All 15 commanders' replacement units verified via Bank file.
- Black-screen fix applied (world_cover_dialog_visible_p1=0).

## Stop conditions

- Complete when all 15 commanders pass runtime verification.
- Do not modify Reborn mod source Galaxy/XML.
- Known issues (REBORN-001/002/003) are upstream Reborn mod behavior, non-blocking.
