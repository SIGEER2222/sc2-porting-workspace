# Stage 51: P2 Ally Usability Closure

## Objective

Close the last two lanes between the verified P2 ally execution spine and a usable
co-op AI ally:

1. runtime evidence that map combat events drive automatic behavior rules
   (clears stage 27 `DOUQUQU-RUNTIME-PENDING`);
2. a first end-to-end runtime experiment where a simulator-validated policy drives
   the native P2 Computer player through the existing Model-P2 bridge
   (advances stage 25 `ML-NATIVE-P2-COMPUTER-BRIDGE-20260803`).

The "usable" bar is defined up front as the `ally_usable.v1` acceptance contract
(multi-seed majority vote, methodology adapted from the Vibecraft evaluation), so
completion is measured, not asserted.

Driver: `docs/evaluations/vibecraft-vs-inhouse-ai-ally-20260822.md`. Both primary
blockers recorded in issues are environmental (stale SC2 session ownership), not
architectural failures; the fastest path to a usable ally is closing the strategy
loop on the existing launcher + Galaxy kernel spine.

## Inputs

- `docs/evaluations/vibecraft-vs-inhouse-ai-ally-20260822.md`
- `src/projects/cmre-porting/stages/27-dou-ququ-behavior-plugin/issues.json` (DOUQUQU-RUNTIME-PENDING)
- `src/projects/cmre-porting/stages/25-ai-ally-capability-completion/issues.json` (ML-NATIVE-P2-COMPUTER-BRIDGE-20260803, MAP-DERIVED-P2-NATIVE-ROSTER-ABSENT)
- `src/projects/cmre-porting/stages/21-runtime-ai-ally-clearance/result.json` (verified 21/21 live action slice, TerranRaynor)
- `src/projects/cmre-porting/stages/25-ai-ally-capability-completion/result.json` (P1+P2 topology, Model-P2 bridge function pair)
- `tools/galaxy-vibe/kernel/LibVibeKernel.galaxy` (WriteModelP2Snapshot / ApplyModelP2Intent)
- `tools/cmre-webui/server.py`, `tools/cmre-webui/runtime_script.py`, `tools/galaxy-vibe/galaxy_repl.py`
- `tools/launchers/launch-cmre-alenger.ps1` (dou-ququ overlay flags are dou-ququ-map-restricted)
- `reference/vibecraft` (development base per user decision 2026-08-22, see evaluation doc §9; baseline bring-up verified: `pytest -m "not e2e"` 3704 passed — `artifacts/projects/cmre-porting/stage51-p2-ally-usability-closure/vibecraft-baseline-bringup-20260822.md`)
- `reference/vibecraft/scripts/build_acceptance.py` (majority-vote acceptance methodology reference)

## Work packages

### WP-A: Event-lane unlock (clears DOUQUQU-RUNTIME-PENDING)

- Pre-flight ownership check: confirm no stale SC2 / dq-webui session holds the
  single game instance (the original blocker was an unrelated session occupying the
  SC2 window). Record the check result in the stage log before any launch.
- Rerun the dou-ququ behavior retest through the launcher with the dou-ququ runtime
  and behavior overlays enabled on the runtime-only dou-ququ map card. Required
  evidence: Wait-GameReady signal, runtime listener heartbeat, combat events
  reaching runtime VM rules (GalaxyVibeEvents → RuntimeConsole dispatch with
  correlation ids), zero new `*ScriptError*.txt` in GameLogs.
- Update stage 27 `issues.json` from observed evidence only.

### WP-B: Usability acceptance contract (`ally_usable.v1`)

- Define the contract: map (CMRE 亡者之夜), commander (TerranRaynor), difficulty,
  seed batch size (N ≥ 5), majority threshold (≥ 4/5), and measurable per-run
  criteria (ally base survives to a named wave / worker floor / army value growth /
  zero new ScriptError / heartbeat alive for the run duration).
- Implement an offline runner harness for the contract against the simulator first,
  reusing Stage 50 tactical runner surfaces (`run_tactical_batch`,
  `verify_tactical_determinism`) where they fit. Runtime application of the contract
  happens in WP-C.
- Artifacts land under `artifacts/projects/cmre-porting/stage51-p2-ally-usability-closure/`.

### WP-C: Native P2 policy bridge (advances ML-NATIVE-P2-COMPUTER-BRIDGE-20260803)

- Drive native P2 on 亡者之夜 via the existing `WriteModelP2Snapshot` /
  `ApplyModelP2Intent` bridge using the simulator-validated policy artifacts from
  Stage 25. No new ML training in this stage.
- Sequence: static bridge verification → single-run runtime smoke → seed-batch runs
  evaluated against `ally_usable.v1`.
- Known dependency: the map Objects carry no native P1/P2 roster
  (MAP-DERIVED-P2-NATIVE-ROSTER-ABSENT); P2 units come from launcher/commander
  initialization, so each run must verify the P2 roster before policy attach.
- Outcome is either contract-evaluated PASS or a documented blocker with the exact
  gap; a blocker does not fail the stage if the evidence pack is complete.

## Deliverables

- WP-A runtime evidence pack (unblocks the stage 27 issue).
- `ally_usable.v1` contract + simulator-passing runner harness (WP-B).
- First end-to-end native P2 policy runtime evidence, contract-evaluated (WP-C).
- Updated `issues.json` files; `result.json` per stage schema; `log.md` with
  evidence paths and commands for every verified claim.

## Verification

```text
# static
py -3.13 -m json.tool src/projects/cmre-porting/stages/51-p2-ally-usability-closure/result.json
py -3.13 -m json.tool src/projects/cmre-porting/stages/27-dou-ququ-behavior-plugin/issues.json

# simulator (WP-B harness)
PYTHONPATH=src/projects/cmre-porting py -3.13 -m pytest -q src/projects/cmre-porting/stages/51-p2-ally-usability-closure/

# runtime (WP-A / WP-C) — launcher only, never SC2_x64.exe directly
# tools/launchers/launch-cmre-alenger.ps1 <dou-ququ retest flags>
# tools/launchers/launch-cmre-alenger.ps1 -MapName 亡者之夜 -Commander TerranRaynor -ListenPort <port>
# acceptance requires: Wait-GameReady, runtime listener heartbeat, GameLogs
# ScriptError review, bank/call-log evidence. Launcher exit 0 alone is not acceptance.
```

## Boundaries

- vibecraft is a development base (user decision 2026-08-22, evaluation doc §9), not
  a read-only reference. Stage 51 itself does not modify vibecraft source; adaptation
  work (attach layer, P2 control seam, custom-unit knowledge) is the next stage's
  scope and happens on a fork branch (`workspace-ally`), with `reference/vibecraft`
  master kept upstream-pristine.
- No new directive/DSL design in this stage (deferred per evaluation §6 path A step 4).
- No ML training or parameter tuning (stays in Stage 6x per Stage 50 next_actions).
- Native differential remains BLOCKED; simulator evidence is never reported as native.
- Reborn CreateGame timeout lane (MAP-COMMANDER-Reborn-RUNTIME-BLOCKED) is out of scope.
- Every SC2 launch goes through `tools/launchers/` with post-launch ScriptError
  review; no fixed-sleep blind waits.
