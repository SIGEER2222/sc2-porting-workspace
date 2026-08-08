# Stage 08 Log: Native AI Ally Closure

## Scope and decision

- Stage plan: `src/projects/revolution-overdrive-porting/stages/08-ai-ally-native-closure/plan.md`.
- The read-only Revolution Overdrive download and `assets/` mirror were not modified.
- No map script, Catalog XML, commander adapter, unit spawn, generic melee AI, or debug API was
  added by this stage.
- The project-local RO AI ally adapter was extended only after the write scope was explicitly
  expanded to `src/projects/revolution-overdrive-porting/vibe/**`; it remains read-only against
  map scripts and does not create units or initialize generic AI.
- Stage status is `blocked`: the map-owned P2 contract is statically identified, but no admissible
  native run has reached the handover precondition.

## Phase-aware adapter continuation

- `static`: `vibe/ai_ally.py` now extracts resolved `RescueUnit` handovers into an
  `AllyActivation` record. For `thorner03`, the record is linked to `TychusCommando` entering
  `RegionFromId(24)` and the `UnitFromId(2)` handover.
- `static/simulator`: `AllyContract.can_dispatch_ally_action` preserves P1-only command
  authorization but rejects dispatch while the observed P2-owned unit count is zero. It allows
  dispatch only after native ownership is observed; ambiguous or unresolved lifecycle paths stay
  fail-closed.
- `static`: Stage 08 contract tests increased from 10 to 12 and cover both pre-handover rejection
  and post-observation readiness. The Stage 04 5-test adapter regression remains green.
- `runtime`: this adapter improvement does not promote the native verdict. The latest native
  probe still lost Tychus before Region 24, so P2 handover remains runtime-blocked.
- `static`: the concurrent RO-AI-001 resolver was reviewed and bounded to the iterator's actual
  group symbol. The corrected aggregate is 182 resolved and 18 unresolved calls across 24 maps;
  the earlier 138/62 count came from a global group-member scan and was not retained.
- `static`: `test_ro_ai_001_dynamic_alliance.py` pins the 31-map inventory, 24 dynamic maps,
  concrete positive edges, opaque-edge visibility, and source preservation.
- `static`: `vibe/ally_matrix.py` and `test_ally_capability_matrix.py` characterize the full
  owned-map surface without widening unresolved calls: 31 maps, 26 supported maps, 414 static
  pairings, 110 dynamic pairings, and 18 unresolved dynamic calls. The report is stored at
  `artifacts/projects/revolution-overdrive-porting/ro-ai-001-generalization/ally-capability-matrix.json`.

## Static P2 contract

- `static`: `artifacts/projects/revolution-overdrive-porting/stage08-ai-ally-native-closure/p2-contract-trace.json`
  cites the P1 -> P2 shared-vision alliance, P2 enemy relationships, the single
  `RescueUnit(UnitFromId(2), gv_p02_TYCHUS, true)` call, the `TychusCommando` -> Region 24 gate,
  the `gt_MidQ` -> `gt_MidCleanup` chain, and map-owned `AIAttackWave*` control.
- `static`: `test_p2_ally_contract.py` guards the source hash, alliance, single handover,
  hidden/revealed Odin lifecycle, gate chain, map-owned AI waves, and no-debug probe source.
- The static result is definite: P2 is a time-gated scripted ally and owns no unit at map start.
  Static evidence does not authorize a runtime P2 command before rescue.

## Admissible native evidence

- `runtime`: 18165 reached `Ping=launched`, `CreateGame=init_game`, `JoinGame=in_game`, P1 id 1,
  Catalog `3786/12225`, 53 observations, and zero action errors. It used no debug injection,
  cheats, or map edits. Tychus died before Region 24; P2-owned and P1-visible P2-allied counts
  were zero, P2 acknowledgement was absent, owner 16 remained Neutral, and ScriptError count was 0.
- `runtime`: fresh no-debug 18204 native probe reached `CreateGame=init_game`,
  `JoinGame=in_game`, Catalog `3786/12225`, baseline loop 86, and final observation after Tychus
  died at loop 469. The probe artifact records `debug_apis_used=[]`, `gate_reached=false`,
  `handover_observed=false`, and P2-owned count 0. This probe artifact does not independently
  contain a same-window launcher ScriptError scan, so no such claim is made for port 18204.
- `runtime/blocked`: patched-launcher port 18166 reached stable ready and a clean ScriptError
  scan, but the raw websocket closed before probe completion. It is not a gameplay pass.
- `runtime/blocked`: fresh port 18220 approved-launcher run reached `ready=true`,
  `CreateGame=init_game`, and a clean launcher ScriptError scan, but `JoinGame` timed out after
  120 seconds. The probe wrote `verdict=error` without gameplay observations; it is retained as
  `RO-RUN-009` and is not a native ally assertion.

## Excluded runtime evidence

- The historical `runtime-20260808-p2-handover/p2-handover-probe.json` reports an owner 16 -> 2
  transition, but its own `debug_apis_used` records `Debug.game_state.god`. It is retained for
  audit history and excluded because the repository forbids cheat/debug-assisted progression.
- The first 18203 wrapper attempt used a relative packed-map path and produced `MissingMap`; it
  is not part of the runtime verdict. The corrected 18204 run used an absolute packed-map path.
- The outer PowerShell wrapper did not propagate the probe's expected blocked exit code, so the
  structured artifact assertion is authoritative for 18204. The next probe should invoke the
  probe directly or explicitly propagate `$LASTEXITCODE`.

## Validation

- Stage result schema: pass.
- Workspace validate: `ok=true`, only pre-existing registered-path warnings.
- Stage 08 contract test: 12 passed; RO AI ally adapter: 5 passed; WebUI: 2 passed.
- Continuation adapter MVP: P2=0 dispatch rejected, observed P2 ownership dispatch allowed, and
  non-P1 command source rejected; these cases are covered by the 12-test Stage 08 run.
- Dynamic-owner regression: 6 passed; 182 concrete PlayerGroupLoop edges resolved and 18 remain
  fail-closed across 24 maps.
- Capability matrix regression: 8 passed; 31 maps covered, 26 supported, 18 unresolved dynamic
  calls retained fail-closed, and the thorner03 P1 -> P2 time-gated pairing matches Stage 08.
- WebUI rerun after one transient HTTP 500: 2 passed; an independent same-request staging probe
  also returned HTTP 200 and staged `traynor01.SC2Map`.
- Galaxy lint: 74 files, 0 diagnostics; Catalog: 36 XML files, 4,135 entries, 0 parse errors.
- Python compile, launcher PowerShell parser, approved launcher `-NoLaunch` 55/55 staging, and
  `git diff --check`: pass.
- The fresh 18220 native attempt is blocked at JoinGame and does not change the prior completed
  18204 no-debug gameplay census; its launcher output is kept separate as the current fixed-path
  18220 record.

## Handoff

Keep the commander and map bootstrap accepted for their proven P1/runtime surface. Keep thorner03
P2 command selection unavailable until supported, non-debug gameplay reaches Region 24 and proves
P2 ownership, P1-visible alliance, and an acknowledged native P2 command in one window. Do not
generalize this map contract to the 24 dynamic-owner maps.
