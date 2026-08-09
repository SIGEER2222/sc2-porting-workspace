# RuntimeLab Reference Feature Inventory

## Source

Static reference only:

- Supplied map: map-debug-battle (complete feature edition).
- Supplied description: map-debug-battle documentation (complete feature edition).
- Extracted inspection: artifacts/galaxy-vibe/reference-inspection/map-debug-battle.

The reference map requires Mods/WarCoop/WarClassicSystem.SC2Mod, which is not
available in this workspace. It is not a RuntimeLab dependency or runtime baseline.

## Reference Capabilities

The supplied tool exposes these areas:

- Unit creation/search with owner and count selection.
- Ability, behavior, item, weapon, and technology adjustments.
- Unit and damage statistics, resource editing, alliance/control changes, and no-attack mode.
- Effect-unit query plus unit property changes.
- Production, research, upgrade, and game-speed acceleration.
- Unit animation, model preview, attachment, transform, and projectile tooling.
- Formation editing and a manual battle start workflow.

## Stage 01 Adoption

RuntimeLab deliberately implements the subset required to validate generic runtime
behavior without mission or commander coupling:

- A deterministic P1-versus-P2 arena: 6 Marines and 2 Marauders versus 12 Zerglings.
- Reset, clear, add-unit, fight, and status actions in a small map-owned dialog.
- Symmetric enemy relation, shared vision, and resource setup through CMLib.
- Managed-unit, team-count, death, reset, fight, readiness, and control-panel markers
written to the runtime VM Bank.
- A direct group attack order that gives the tactical fixture a real combat transition.

## Deferred

Catalog browsers, arbitrary unit/property editors, visual/model tooling, formation
authoring, and damage-stat dashboards are intentionally deferred. They need a
separate interaction and validation design; adding them now would expand this
foundation stage beyond proving VM, CMLib, and a deterministic tactical scenario.
