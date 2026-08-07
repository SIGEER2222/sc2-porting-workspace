# Next Stage Plan: Runtime Bootstrap Diagnosis

## Objective

Find a reproducible, approved-launcher path that takes a complete Revolution Overdrive map from
SC2 API `launched` through `CreateGame=init_game` and `JoinGame=in_game`, without weakening the
commander/map boundary or promoting a DirectMapApi listener to runtime success.

## Preconditions and scope

- Keep the read-only download and `assets/` mirror untouched.
- Extend the RO project writeScope to the next stage before editing new implementation files.
- Use a fresh port and a separate artifact directory for every run.
- Require strict response checks: CreateGame must return `init_game`; JoinGame must return
  `in_game`; Observation must advance a nonzero game loop; Catalog and unit observations must be
  nonempty before any AI ally assertion.

## Steps

1. Build a strict RO runtime harness from the existing RealSmoke/RealProfile response-status
   pattern. Record top-level status, nested CreateGame/JoinGame errors, map path form, and map
   dependency resolution for every request.
2. Run the same launcher and harness against a known-good local map, the RO staged directory,
   the RO packed map through `map_data`, and the RO packed map through a Maps-relative path.
   Keep these runs in separate evidence directories and compare the first divergent state.
3. Audit `DocumentHeader`, `DocumentInfo`, and the installed `Mods` names against the packed and
   staged forms. Treat any dependency-path mismatch as a launcher staging issue; do not patch
   map-owned Galaxy initialization to mask it.
4. If the standard API path is proven incompatible with the map's startup graph, test the
   existing CMRE DirectMapApi/`join-existing` topology in an isolated RO run. Require a raw Ping
   and JoinGame response from the attached API before considering it viable; a TCP listener alone
   is blocked evidence.
5. After a playable window exists, run RequestStep/Observation, P1/P2 owner and alliance census,
   `ActionChat("Iron")`, and the dynamic AI ally roster probe. Compare only explicit runtime
   owners with the Stage 04 static contract.
6. Re-run the 5 RO AI ally tests and WebUI tests after any adapter or launcher change. Do not
   widen the 24 dynamic-owner contracts unless the runtime evidence identifies their owners and
   alliances in the same map window.

## Stop conditions

- Stop and record blocked evidence if the response status remains `launched`, the map cannot be
  opened, or the DirectMapApi socket does not answer Ping/JoinGame.
- Do not claim commander, faction, owner, alliance, or AI ally runtime success from listener
  readiness, zero ScriptErrors, MPQ readability, or WebUI staging.
- Do not copy large binary assets into the main repository or modify the read-only source.

## Acceptance

- A current evidence bundle contains the manifest/inputs, launcher output, strict API trace,
  assertion output, same-window ScriptError verdict, and a combined verdict.
- Either the full native MVP passes, or the blocker is reproducible with a concrete next action.
