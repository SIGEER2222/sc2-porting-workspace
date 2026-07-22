# Manifest Design Log

## Progress

- 2026-07-16: Selected Reborn HotS 0.71, `zexpedition03`, and `TerranRaynor` as the first bounded composition.
- Added package, composition, static request, runtime scenario, and runtime verdict contracts.
- Added a local-binding source ID so machine-specific Downloads paths remain uncommitted.
- 2026-07-16: Bound `reborn-hots-071` to the user-provided Reborn 0.71 directory through ignored local configuration.
- 2026-07-16: JSON Schema validation passed for all six pilot examples; source IDs and package paths resolved.

## Evidence

- Static: the user-provided package identifies itself as The Swarm Reborn 0.71 in `metadata.txt`.
- Static: the legacy toolkit resolves the five Reborn packages and reports `SwarmStoryUtil.SC2Mod` as unresolved.
- Runtime: the legacy project phase-0 report records a successful `zexpedition03` baseline with no ScriptError.
- Runtime: the phase-3 report records a successful Raynor smoke launch and a manually observed build-panel defect.
- Static: `node tools/workspace.mjs validate` returned `ok: true` after the new contracts were added.
- Static: Python `Draft202012Validator` accepted all pilot examples and their schemas.
- Static: source/path validation accepted all non-native package paths and all composition references.

## Changes

- Added schema contracts under `docs/schemas/` and pilot examples under this stage's `evidence/pilot/` directory.
- Registered `reborn-hots-071` as a read-only local-binding source without committing its absolute path.
- Expanded this stage's write scope to include the registration and validation files required by its original objective.

## Problems

- `file:Campaigns/SwarmStoryUtil.SC2Mod` still requires an authoritative external dependency mapping.
- Runtime and manual acceptance remain project-stage work; this contract stage does not claim them.
- The user-provided Reborn source is read-only; the existing port target is treated as a separate legacy-project comparison input.

## Handoff

The pilot project may rely on these contracts after schema validation passes.
