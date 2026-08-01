# Stage 17 Plan: Vibe Action Capabilities

## Objective

Extend the explicit typed function registry from the side-effect-free ping
probe to a small, useful set of game actions and queries. Prove that a Vibe
caller can dynamically select a registered function, apply a state change, and
observe the resulting state through the same simulator, Host, Galaxy, and
runtime contracts.

## Contract

- All callable functions remain declared in
  `tools/galaxy-vibe/kernel/function-registry.json`.
- Dispatch remains an explicit function-id mapping. No reflection, `eval`,
  arbitrary Galaxy names, or `TriggerExecuteByName` is allowed.
- The first action/query slice is:
  - `vibe.player.set_resource`
  - `vibe.unit.spawn`
  - `vibe.query.units`
  - `vibe.unit.kill`
- Function arguments use the existing typed nested Host API and typed
  `arg_<name>` Galaxy wire fields.
- Invalid function IDs, missing arguments, out-of-range values, and invalid
  catalog IDs must return structured errors without applying a side effect.
- Existing operation-level handlers remain compatible while function-level
  handlers become the preferred Vibe surface.

## Work Scope

1. Add the four function definitions and their explicit handler mappings.
2. Implement shared Python registry validation and simulator behavior for the
   action/query sequence.
3. Implement the matching explicit Galaxy handlers in the canonical kernel,
   project map mirror, and debug-mod mirror.
4. Extend Host/REPL invocation ergonomics and contract tests.
5. Run simulator/static validation, then use the approved CMRE launcher to
   verify a real action followed by a real query and capture Bank/ScriptError
   evidence.

## Completion Gate

- Registry/schema/whitelist are mutually consistent.
- Simulator tests prove set-resource, spawn, query, kill, and invalid-input
  behavior with no unintended state changes.
- Galaxy mirrors pass static checks and remain aligned for shared code.
- A real packed-map runtime invocation changes/query state through the typed
  function registry and returns the expected payloads.
- The same-window ScriptError gate is clean, and result/log/issues plus the
  next-stage plan contain classified evidence.
