# Manifest Contracts

The workspace uses five small contracts instead of copying launcher-specific plans into every
project.

- `package-manifest.schema.json` identifies maps, mods, commanders, adapters, ownership, and source
  references.
- `composition-manifest.schema.json` records effective load order, selected map and commander,
  adapters, runtime entry, and acceptance criteria.
- `static-analysis-request.schema.json` declares analyzer capabilities and required coverage. Its
  result is `dependency-graph.schema.json`.
- `runtime-scenario.schema.json` defines the launcher, readiness gate, actions, expectations, and
  evidence root.
- `runtime-verdict.schema.json` maps each acceptance criterion to observed evidence.

Committed source references always use a registered `sourceId` plus a relative package path.
Machine-specific roots belong only in ignored `src/config/local.sources.json` bindings.

Package manifests describe ownership. They do not grant write permission. The active stage's
`writeScope` remains authoritative.
