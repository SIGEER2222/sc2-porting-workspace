# Stage 02 Plan: Static Mod Extraction And Ownership

## Objective

Extract the archive-based Mod dependency closure into generated artifacts, analyze every extracted
Catalog and Galaxy component, and freeze a reviewable ownership boundary for the independent
`revolution-overdrive-commander`. This stage must prove source immutability and must not yet alter
the source download or launch it through an unapproved path.

## Inputs

- Stage 01 outputs under `stages/01-discovery/evidence/static/`.
- Bound source `revolution-overdrive-download` resolved by `node tools/utils/workspace.mjs resolve`.
- Existing `tools/mpq/scripts/extract_mpq.py`, `tools/mpq/scripts/verify_mpq.py`,
  `tools/analysis/analyze-catalog.mjs`, and registered Galaxy toolkit.
- Galaxy skills for Catalog ownership, triggers, units/abilities, and function organization.

## Write scope

- `src/projects/revolution-overdrive-porting/project.json`
- `src/config/workspace.json` (registers the generated extraction root for the existing catalog analyzer)
- `src/projects/revolution-overdrive-porting/stages/02-static-extraction/**`
- `artifacts/projects/revolution-overdrive-porting/stage02-extraction/**`

The source download remains read-only. Extracted artifacts are analysis inputs only; owned packages
will be created in a later implementation stage after this boundary is verified.

## Tasks

1. Resolve the source binding and record the Stage 01 hash baseline before extraction.
2. Extract each file-based `.SC2Mod` into the stage02 artifact directory with the existing MPQ
   tool, and verify every archive before/after extraction.
3. Run Catalog analysis over the main directory Mod and every extracted archive Mod; record XML
   parse errors, duplicate IDs, parent chains, and cross-package references.
4. Parse component manifests, `DocumentInfo`, localized data, Galaxy headers/functions/triggers,
   and the launch script mapping. Identify what is commander behavior, reusable dependency, map
   initialization, or external campaign content.
5. Compare extracted hashes to the read-only source and prove the source tree is unchanged.
6. Produce a self-assessment. The stage passes only when the commander dependency closure is
   explicit enough to name the next package files and the AI ally contract remains map-owned.

## Outputs

- `evidence/static/archive-extraction-manifest.json`
- `evidence/static/mod-catalog-summary.json`
- `evidence/static/galaxy-symbol-catalog.json`
- `evidence/static/ownership-boundary.json`
- `evidence/static/source-unchanged.json`
- `self-assessment.md`
- Updated `log.md`, `result.json`, and `issues.json`.

Generated extracted packages and bulky reports belong under
`artifacts/projects/revolution-overdrive-porting/stage02-extraction/`.

## Validation

- `node tools/utils/workspace.mjs validate`
- `node tools/utils/workspace.mjs resolve revolution-overdrive-download`
- `python tools/mpq/scripts/verify_mpq.py <each file-based source *.SC2Mod>`
- `python tools/mpq/scripts/extract_mpq.py <resolved-source>/<archive> artifacts/projects/revolution-overdrive-porting/stage02-extraction/<archive>/`
- `node tools/analysis/analyze-catalog.mjs revolution-overdrive-download RevolutionOverdrive.SC2Mod .* <stage02 catalog report>`
- `node tools/analysis/analyze-catalog.mjs <stage02 extracted package source> . .* <stage02 catalog report>`
- Registered Galaxy parser/static validation over extracted `.galaxy` files.
- Recompute Stage 01 source hashes and require exact equality in
  `evidence/static/source-unchanged.json`.
- JSON schema/parsing validation for every declared Stage 02 output.
- No runtime launch is allowed until this stage passes and the next package plan exists.

## Stop conditions

- Complete: all archives are extracted and verified, catalog/Galaxy reports have no unexplained
  parser failures, ownership and dependency closure are explicit, and source hashes are unchanged.
- Blocked: an archive cannot be read, a Catalog collision cannot be classified, or Galaxy parser
  errors prevent a safe ownership decision.
- Failure: any command writes into the bound source, or the extracted package is treated as a
  commander without preserving a dependency or map-initialization boundary.
