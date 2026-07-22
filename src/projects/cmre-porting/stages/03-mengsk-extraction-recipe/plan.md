# Stage Plan: Mengsk Extraction Recipe

## Objective

Create a deterministic, reviewable extraction recipe and generated working composition for the
approved 240-entry Mengsk boundary without modifying the CMRE source package.

## Inputs

- `../02-static-boundaries/boundary-decision.json`
- Exact Catalog selector and reverse-reference evidence
- Source Base and Mengsk Mods through `cmre-dev-package`

## Write scope

- `scripts/` and `tooling/` for reusable extraction support
- `src/projects/cmre-porting/stages/03-mengsk-extraction-recipe/**`
- Ignored `artifacts/projects/cmre-porting/**` generated working content

## Tasks

1. Define a machine-readable extraction recipe for whole entries, exceptions, and field moves.
2. Generate owned working copies under `artifacts/` while preserving the source package.
3. Remove moved entries and fields from generated shared Base; merge them into generated Mengsk.
4. Validate exact entry counts, dependency order, Catalog equivalence, and dangling references.
5. Record the source runtime baseline requirement before acceptance.

## Outputs

- `recipe.json`
- Generated shared Base and Mengsk working packages under ignored artifacts
- Static comparison report and unresolved runtime issue

## Validation

- Source file hashes remain unchanged.
- Generated target has 240 whole moves, four retained exceptions, and seven field moves.
- Legacy toolkit validate/compare and workspace checks pass.

## Stop conditions

- Do not edit `cmre-dev-package`.
- Do not accept generated runtime behavior without a real observer run.
- Stop if XML rewriting cannot preserve SC2 merge semantics.
