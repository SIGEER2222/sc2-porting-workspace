# Reborn MVP Discovery Plan

## Objective

Resolve the source and effective target dependency boundaries for `zexpedition03 + TerranRaynor`,
record the existing adapter ownership, and decide whether the composition is eligible for runtime validation.

## Inputs

- `reborn-hots-071` read-only local source binding.
- `legacy-project` existing Reborn port and adapter packages.
- `stages/01-manifest-design/result.json` and pilot contracts.

## Write scope

- `src/projects/reborn-zexpedition03-raynor-mvp/project.json`
- `src/projects/reborn-zexpedition03-raynor-mvp/manifests/`
- `src/projects/reborn-zexpedition03-raynor-mvp/stages/01-discovery/`

## Tasks

1. Inspect declared dependencies for the source map and Reborn core mod.
2. Inspect the launcher-effective dependency chain for the existing Raynor port target.
3. Compare the source and port file inventories and classify every changed file by ownership.
4. Record dependency nodes, edges, unresolved packages, analyzer commands, and evidence boundaries.
5. Write an adapter proposal using the narrowest existing ownership layer.
6. Run JSON Schema validation over the project and discovery outputs.

## Outputs

- `evidence/static/dependency-graph.json`
- `evidence/static/analyzer-commands.json`
- `evidence/static/unresolved.json`
- `evidence/static/source-port-diff.json`
- `adapter-proposal.md`
- Completed stage log, result, issues, and next-stage plan.

## Validation

- Legacy toolkit `inspect` succeeds for the source map and core mod.
- Effective toolkit inspection succeeds for `zexpedition03_reborn_port.SC2Map + TerranRaynor`.
- Project, composition, dependency graph, and stage result pass JSON Schema validation.
- Every non-native source path resolves through its registered source ID.

## Stop conditions

- Do not modify the downloaded source or legacy-project content.
- Stop before runtime if a required non-native package is missing.
- Record native campaign packages as unresolved when ownership cannot be proven statically.
- Do not treat existing heartbeat-only RuntimeProbe reports as commander acceptance evidence.
