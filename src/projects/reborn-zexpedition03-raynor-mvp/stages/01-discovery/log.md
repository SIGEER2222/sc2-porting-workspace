# Reborn MVP Discovery Log

## Progress

- 2026-07-16: Created the project around the read-only Reborn 0.71 binding and existing port target.
- 2026-07-16: Captured declared source and core-mod dependency inspections.
- 2026-07-16: Captured effective target inspection for `TerranRaynor`.
- 2026-07-16: Compared source and target inventories; found five changed/added files.
- 2026-07-16: Ran direct Galaxy CI checking with zero blocking issues.

## Evidence

- Static: source map declares SwarmStory campaign and Reborn core; core declares four local Reborn packages plus native campaign parents.
- Static: effective target resolves the Reborn integrated profile and Raynor, but also loads 17 unselected commander packages.
- Static: target retains both scoped and stale unscoped Reborn adapter references.
- Static: Galaxy checker reports two non-blocking undeclared event functions and 42 non-blocking catalog diagnostics.
- Inference: the existing adapter boundary is structurally correct, but the generated dependency closure is not yet MVP-minimal.

## Changes

- Added only files under this project directory; no source map, Mod, or legacy-project content was edited.

## Problems

- `SwarmStoryUtil.SC2Mod`, `VoidMulti.SC2Mod`, and `StarCoop.SC2Mod` remain unresolved by static inspection.
- Current target composition is broader than the selected Raynor MVP.
- Runtime probe evidence is not accepted as commander correctness proof because its assertions are empty/unknown.

## Handoff

The next stage must repair composition/dependency generation before runtime validation. It should not
edit the canonical Raynor package or copy the Reborn source.
