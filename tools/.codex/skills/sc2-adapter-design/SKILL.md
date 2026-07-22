---
name: sc2-adapter-design
description: Design the smallest SC2 compatibility layer between a source map, target map family, commander mod, shared runtime, and external dependencies. Use after dependency and gap analysis, when deciding whether behavior belongs in a shared mod, commander mod, series adapter, map adapter, commander-map adapter, or map-local implementation.
---

# SC2 Adapter Design

Choose ownership before writing code.

## Inputs

- static dependency graph;
- target composition;
- source and target behavior differences;
- runtime evidence when available;
- active project's acceptance criteria.

## Ownership order

Evaluate each behavior in this order:

1. Map-local: mission-owned initialization, objectives, rewards, cinematics, terrain, or scripting.
2. Canonical commander mod: behavior valid for that commander in every supported environment.
3. Shared runtime mod: behavior required by multiple proven consumers.
4. Map-series adapter: compatibility shared by every map in one series.
5. Map adapter: compatibility shared by commanders on one map.
6. Commander-map adapter: behavior unique to one pairing.

Select the narrowest layer that avoids duplication without polluting canonical packages.

## Design output

Write an adapter proposal containing:

- behavior gap and evidence;
- selected ownership layer;
- rejected broader and narrower layers;
- dependencies and load order;
- Catalog IDs, Galaxy symbols, triggers, and Banks involved;
- exact write scope;
- static and runtime validation scenarios;
- removal condition if the adapter becomes obsolete.

Do not implement during the design stage unless the plan explicitly combines design and implementation.

Read [boundaries.md](references/boundaries.md) before finalizing ownership.
