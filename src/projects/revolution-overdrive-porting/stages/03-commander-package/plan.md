# Stage 03 Plan: Owned Commander, Map Packages, And Selectors

## Objective

Create an owned Revolution Overdrive package from the verified Stage 02 extraction and the
read-only map source. Preserve mission-owned map behavior, expose the five native faction presets,
and connect the package to a compliant launcher and the existing WebUI without changing CMRE
selection behavior.

## Inputs

- Stage 02 extraction and ownership evidence.
- Read-only source binding `revolution-overdrive-download`.
- Existing `tools/cmre-webui` API and launcher conventions.
- Existing MPQ packing/verification tools and workspace validation.

## Write scope

- `src/config/workspace.json`
- `src/projects/revolution-overdrive-porting/project.json`
- `src/projects/revolution-overdrive-porting/stages/03-commander-package/**`
- `artifacts/projects/revolution-overdrive-porting/stage03-commander-package/**`
- `src/projects/revolution-overdrive-porting/packages/Commander/**`
- `src/projects/revolution-overdrive-porting/packages/Maps/**`
- `tools/launchers/launch-revolution-overdrive.ps1`
- `tools/cmre-webui/server.py`
- `tools/cmre-webui/webui/app.js`
- `tools/cmre-webui/test_revolution_overdrive.py`

The bound download remains read-only. Stage artifacts are analysis evidence, not the owned package.

## Tasks

1. Record a source hash baseline for every copied Mod and map, then copy the seven verified Mods
   and all 31 source maps into the owned package tree.
2. Write package metadata that names the commander root, faction presets, map inventory, dependency
   paths, and the rule that map scripts/alliances/objectives remain mission-owned.
3. Add a launcher that stages the selected owned map and explicit dependency closure, uses the
   approved SC2 Switcher/launcher path, waits on ready signals, and records ScriptError/runtime
   listener evidence. It must not embed Galaxy behavior.
4. Extend WebUI discovery and launch routing with an opt-in `revolution-overdrive` package
   selector. Existing CMRE maps and commanders must remain unchanged.
5. Run static package/catalog validation, launcher static tests, WebUI MVP dry-run tests, and a
   source immutability comparison.
6. Self-assess package/runtime confidence and record the Stage 04 AI ally plan only after this
   stage's result is verified.

## Outputs

- `packages/Commander/revolution-overdrive-commander.json`
- `packages/Commander/Mods/**`
- `packages/Maps/**`
- `packages/maps.json`
- `stages/03-commander-package/evidence/static/**`
- `stages/03-commander-package/self-assessment.md`
- `stages/03-commander-package/log.md`
- `stages/03-commander-package/result.json`
- `stages/03-commander-package/issues.json`
- `stages/04-ai-ally/plan.md` after Stage 03 passes

## Validation

- `node tools/utils/workspace.mjs validate`
- Verify every copied source package and map hash against the read-only source.
- `python tools/mpq/scripts/verify_mpq.py` for every packed output, where packing is used.
- Catalog parse/lint for every owned Mod and map dependency manifest.
- `python -m pytest tools/cmre-webui/test_revolution_overdrive.py`
- `powershell -NoProfile -ExecutionPolicy Bypass -File tools/launchers/launch-revolution-overdrive.ps1 -NoLaunch ...`
- MVP WebUI request must reach the real Revolution Overdrive launcher and produce a staged map,
  not only return a mocked response.

## Stop conditions

- Complete only when all 31 maps and the explicit commander closure are owned, selectors route to
  the correct launcher, static/MVP checks pass, and the source remains unchanged.
- Blocked when SC2 installation/launcher/API evidence is unavailable; record the exact command and
  continue with static and dry-run evidence without calling it runtime pass.
- Failure if a map script, objective, reward, or alliance initializer is rewritten in this stage.
