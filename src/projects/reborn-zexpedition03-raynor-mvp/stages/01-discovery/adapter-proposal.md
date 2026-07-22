# Adapter Proposal

## Boundary

Keep Reborn definitions in the source Reborn packages and keep Raynor behavior in the canonical
Raynor commander package. Use `RebornBridge.SC2Mod` as the series compatibility layer and
`RebornMapAdapter.SC2Mod` for map initialization and victory/defeat bridging.

## Evidence

- `MapScript.galaxy` adds `RebornMapAdapter`, initializes the bridge, and calls after-technology,
  after-player, and after-unit hooks.
- The map disables restricted campaign data and story-tech calls, which is runtime behavior owned by
  the map adapter boundary rather than by the Raynor package.
- The target `DocumentInfo` contains all commander packages, not only Raynor; this is a launcher and
  composition-generation defect, not a reason to modify the canonical commander mod.

## Decision

1. Retain `reborn.bridge` as the series adapter.
2. Retain `reborn.map-adapter` as the map/runtime adapter.
3. Generate a Raynor-only composition and dependency document for the MVP.
4. Do not copy Reborn Galaxy or Catalog data into the commander package.

## Rejected layers

- Shared runtime: too broad; the callbacks and campaign restrictions are Reborn-specific.
- Canonical commander mod: wrong owner; the behavior is not Raynor-canonical.
- Map-local rewrite: would duplicate reusable Reborn compatibility behavior.

## Validation

- Static: resolve the native campaign utility and stale adapter paths.
- Static: validate the Raynor-only dependency closure and Galaxy checker output.
- Runtime: load the map, verify no new ScriptError, inspect the Raynor build panel, and observe the
  first mission objective.

## Removal condition

Remove the map adapter only when the Reborn campaign can load through a stable shared runtime and the
launcher no longer needs map-specific initialization or restricted-native bypasses.
