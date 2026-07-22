# Composition Remediation Plan

## Objective

Verify that the current launcher can generate a Raynor-selected Reborn composition independently of
the broad target template, then decide whether runtime smoke is safe and meaningful.

## Inputs

- Passed discovery result and dependency graph.
- Desired composition manifest.
- Existing Reborn launcher, composer, map profile, and generated plan contract.

## Write scope

- `src/projects/reborn-zexpedition03-raynor-mvp/project.json`
- `src/projects/reborn-zexpedition03-raynor-mvp/manifests/`
- `src/projects/reborn-zexpedition03-raynor-mvp/stages/02-composition-remediation/`
- `legacy-project:out/compositions/reborn.zexpedition03_reborn_port__p1-TerranRaynor.launcher-plan.json`
- `legacy-project:out/verification/reborn.zexpedition03_reborn_port__p1-TerranRaynor/`

## Tasks

1. Run the Reborn launcher in `-CheckOnly` mode to refresh the selected composition plan.
2. Validate the generated plan and Raynor commander package.
3. Run composer verification against the refreshed launcher plan.
4. Compare generated dependency layers with the desired MVP composition.
5. Record whether stale paths, unselected commanders, Galaxy diagnostics, and document roundtrip remain.
6. Write a runtime eligibility verdict and the next bounded stage plan.

## Outputs

- `evidence/static/generated-plan-summary.json`
- `evidence/static/composer-verification-summary.json`
- `runtime-eligibility.json`
- Completed stage log, result, issues, and next-stage plan.

## Validation

- Launcher `-CheckOnly` exits 0.
- Generated launcher plan validation exits 0.
- Raynor commander package validation exits 0.
- Composer verification produces a machine-readable report.
- Project and stage outputs pass JSON Schema validation.

## Stop conditions

- Do not use `-NoLaunch`; it mutates live SC2 content despite its name.
- Do not edit map, Mod, launcher, or shared configuration source in this stage.
- Stop before runtime if the generated plan still contains unselected commander packages, blocking
  Galaxy errors, or an unclassified document mismatch.
