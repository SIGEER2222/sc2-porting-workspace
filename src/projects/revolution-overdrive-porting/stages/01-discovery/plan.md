# Stage 01 Plan: Revolution Overdrive Discovery

## Objective

Produce a reproducible, source-only inventory of the Revolution Overdrive package. The inventory
must identify all maps, all mod packages, component manifests, declared dependencies, trigger/Galaxy
entry points, and the likely ownership split between commander, shared, map, and commander-map
adapters. No source asset may be modified.

## Inputs

- Registered source `revolution-overdrive-download`, bound through ignored `src/config/local.sources.json`.
- Registered reference project `cmre-porting` for launcher, WebUI, and AI-ally contracts.
- `tools/mpq/` and `tools/analysis/` existing extract/catalog tooling.
- Project-local SC2 skills: `vibe-operator-workflow`, `galaxy-code-organization`,
  `galaxy-ai-and-techtree`, `galaxy-triggers-and-functions`, and `galaxy-units-and-groups`.

## Write scope

- `src/projects/revolution-overdrive-porting/project.json`
- `src/projects/revolution-overdrive-porting/stages/01-discovery/**`

Generated reports belong under `artifacts/projects/revolution-overdrive-porting/` and are not source
packages. The bound download directory is read-only.

## Tasks

1. Validate workspace registration and resolve the source binding without embedding a machine path
   in committed files.
2. Inventory every `.SC2Map`, `.SC2Mod`, component file, catalog XML, Galaxy script, trigger file,
   and declared dependency. Hash source files needed for later change detection.
3. Run the existing catalog analyzer against the editable Revolution Overdrive mod and each map's
   `Base.SC2Data` where catalog XML exists. Record parser errors instead of treating missing data as
   success.
4. Inspect the source launch script and initializer/trigger references to classify the five faction
   mods, the main Revolution Overdrive mod, maps, and shared dependencies.
5. Self-assess whether the inventory is sufficient to start extraction. Any unknown dependency,
   parser error, or ambiguous ownership becomes an explicit issue and blocks the next stage.

## Outputs

- `evidence/static/source-inventory.json`
- `evidence/static/dependency-boundary.json`
- `evidence/static/catalog-summary.json`
- `evidence/static/catalog-map-summary.json` and `evidence/static/catalog-maps/*.json`
- `evidence/static/ai-ally-discovery.json`
- `evidence/static/source-hashes.json`
- `self-assessment.md`
- Updated `log.md`, `result.json`, and `issues.json`.

## Validation

- `node tools/utils/workspace.mjs validate`
- `node tools/utils/workspace.mjs status`
- `node tools/analysis/analyze-catalog.mjs revolution-overdrive-download RevolutionOverdrive.SC2Mod " .* " <repo-relative-output>`
- A source-inventory command that reports nonzero map/mod counts, dependency declarations, and
  stable hashes; its output must be checked as JSON.
- No runtime launch in this stage. Runtime is intentionally deferred until a target package and
  approved launcher recipe exist; this is recorded as an `inference`/`blocked` boundary, not a pass.

## Stop conditions

- Complete: all source assets are accounted for, catalog/trigger limits are explicit, the ownership
  boundary is reviewable, and the next-stage plan can name exact inputs and write scope.
- Blocked: source binding is unavailable, source files cannot be read, catalog analysis has unexplained
  parser failures, or the faction/commander boundary cannot be determined.
- Failure: any command mutates the download source or emits an absolute source path into committed
  project files.
