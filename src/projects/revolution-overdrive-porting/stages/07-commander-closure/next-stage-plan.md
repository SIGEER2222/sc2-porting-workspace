# Next Stage Plan: Native AI Ally Closure

## Objective

Determine whether the map-owned P2 slot is a real controllable AI ally and complete the
mission-safe adapter only from native owner/alliance/action evidence. The commander/bootstrap
MVP is already proven; this stage must not reopen the solved packaging problem.

## Preconditions and scope

- Keep the read-only download and `assets/` mirror untouched.
- Extend the RO project writeScope to the next stage before editing new implementation files.
- Use a fresh port and a separate artifact directory for every run.
- Require strict response checks: CreateGame must return `init_game`; JoinGame must return
  `in_game`; Observation must advance; Catalog and unit observations must be nonempty before any
  AI ally assertion.

## Steps

1. Reproduce `thorner03` through the approved launcher and strict census, retaining the exact
   `init_game`, `in_game`, frame, owner, alliance, chat, and ScriptError evidence fields. The
   current bootstrap and action probes show that ordinary commands are accepted but Tychus dies
   before Region 24; do not treat movement acceptance as rescue progress.
2. Trace `gv_pLAYER_02_USER` and map-owned P2 initialization in `thorner03.SC2Map`, including
   start-unit creation, owner remapping, `PlayerSetAlliance`, and `libNtve_gf_SetAlliance` calls.
   Compare the static calls with the native owner `16` observations and the P2 Computer roster.
3. If P2 is intended to be the ally, first identify a mission-owned, supported way to complete the
   warehouse objective and reach `gt_VictoryWarehouseDudesKilled` at Region 24. Only then repair
   the map-specific initialization or commander-map adapter at its owning boundary. Prove
   P2-owned units, P1-visible allied units, and one acknowledged native P2 command in the same
   window. Do not create units from the shared AI adapter and do not add generic melee AI.
4. If owner 16 is mission-neutral and P2 is intentionally empty, record that contract explicitly
   and keep P2 unavailable to the WebUI ally command path. Do not infer an ally from shared vision.
5. Re-run the five RO AI ally tests, WebUI tests, workspace validation, Galaxy lint, catalog
   analysis, approved launcher `-NoLaunch`, and the full native census after any change.

## Stop conditions

- Stop and record blocked evidence if the mission-owned Region 24 progression cannot be reached
  through supported gameplay or if P2 remains without owned units, allied observations, or an
  acknowledged native command after the trace.
- Do not claim AI ally runtime success from a Computer roster entry, shared vision, zero
  ScriptErrors, MPQ readability, or WebUI staging.
- Do not copy large binary assets into the main repository or modify the read-only source.

## Acceptance

- A current evidence bundle contains the launcher output, strict API trace, owner/alliance census,
  assertion output, same-window ScriptError verdict, combined verdict, and summary.
- Either P2 native ally behavior passes, or the P2 contract is explicitly recorded as unavailable
  with a concrete map-owned next action.
