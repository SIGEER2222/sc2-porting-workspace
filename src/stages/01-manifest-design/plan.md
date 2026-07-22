# Manifest Design Plan

## Objective

Define machine-readable composition, map, mod, adapter, tool, and runtime test manifests before
creating or migrating any SC2 content package.

## Inputs

- Bootstrap constraints and schemas.
- One proposed pilot map and commander.
- Static analyzer and runtime observer capabilities.

## Write scope

- `src/config/workspace.json`
- `docs/schemas/`
- `templates/`
- `docs/`
- `tools/workspace.mjs`
- `stages/01-manifest-design/`

## Tasks

1. Define map, mod, adapter, and composition IDs and ownership fields.
2. Define dependency edges and load-order representation.
3. Define static analysis request and result contracts.
4. Define runtime scenario and verdict contracts.
5. Validate the contracts against one real pilot composition without moving its assets.
6. Register machine-local source roots by ID without committing absolute paths.

## Outputs

- Approved manifest schemas and examples.
- Pilot composition registered by source references.
- Next-stage discovery plan.

## Validation

- Parse every JSON example.
- Validate every example against its declared JSON Schema.
- Validate required IDs and registered source paths.
- Confirm the pilot can be described without absolute paths.

## Stop conditions

- Do not move or modify the pilot map or mods in this stage.
