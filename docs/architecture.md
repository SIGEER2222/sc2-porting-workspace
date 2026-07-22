# Porting Architecture

The workspace separates source evidence, owned porting changes, adapters, tools, orchestration, and
generated artifacts. Existing assets remain in place during the initial phase and are referenced by
registered IDs.

```text
external sources and repositories
          |
          v
static analysis -----> dependency graph
          |                    |
          v                    v
adapter design -----> composition manifest
                               |
                               v
                         runtime analysis
                               |
                               v
                     evidence and next stage
```

## Static analysis

Static analysis discovers declared dependencies, Catalog ownership, Galaxy includes and calls,
initializers, trigger registration, objectives, rewards, Banks, and probable adapter points. Its output
is a dependency graph with explicit evidence and unresolved edges.

## Runtime analysis

Runtime analysis is backend-neutral. Neuro-compatible protocols may be used, but Neuro itself is not a
required dependency. The runtime observer records map load, initialization, triggers, player actions,
unit commands, resources, objectives, rewards, Banks, process state, and ScriptError evidence.

## Adapter ownership

Use the narrowest package that can own the compatibility rule without duplicating behavior:

1. shared runtime mod;
2. commander mod;
3. map-series adapter;
4. map adapter;
5. commander-map adapter;
6. map-local change when the behavior is mission-owned.

The dependency direction is one-way. Canonical commander mods never depend on maps or adapters.
