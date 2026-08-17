# Stage 31: Native Runtime Evidence Lane

## Objective

Produce a fresh, launcher-owned native SC2 evidence chain for one declared CMRE mission fixture. Stage 31 is the only stage in this roadmap allowed to claim native mission completion, and only when every runtime gate passes in the same launch window.

## Fixture

- Fixture id: `stage31-native-dead-of-night-baseline`.
- Map: `亡者之夜.SC2Map` from the registered CMRE package.
- Commander: `TerranRaynor` unless the launcher/map contract requires another registered commander.
- Runtime topology: P1 Participant, P2 native Computer ally; no simulator victory, replay-only, or adapter-clearance substitution.
- Input map must be packed before `CreateGame`; the SC2 executable must be started only through `tools/launchers/launch-cmre-alenger.ps1`.

## Required same-window evidence

1. Fresh UTC launch epoch and clean output directory.
2. Approved launcher output proving process readiness and runtime-listener heartbeat.
3. Successful `CreateGame`/`JoinGame` and advancing `RequestStep` frames.
4. API/runtime assertions for native initialization, player topology, mission state, and terminal player result.
5. Mission result verification from the live API/runtime observation, not only a replay.
6. Same-window `ScriptError` scan with zero new non-empty error files.
7. A normalized `differential-observation.v1` native record with `source=native` and `evidence_type=runtime`.
8. Evidence bundle containing all paths, commands, classifications, hashes, and any blocked/inference warnings.

## Runtime procedure

```text
1. Stage/pack 亡者之夜.SC2Map into artifacts/projects/cmre-porting/stage31-native-runtime-evidence-lane/.
2. Record a fresh UTC epoch and clear stale assertion/verdict files.
3. Start tools/launchers/launch-cmre-alenger.ps1 with -MapName, -Commander, -ListenPort, -ApiMinimal, -DebugMode, -KeepAlive, and a unique -MapCopySuffix.
4. Wait for launcher readiness/runtime listener; do not use fixed blind sleeps.
5. Run the approved native controller against the packed map, issuing RequestStep calls until the declared mission terminal result or a truthful blocked outcome.
6. Run the same-window ScriptError gate using the recorded epoch.
7. Normalize only runtime-observed fields and feed them to the Stage 30 comparator.
8. Write result.json/log.md/issues.json and the evidence bundle before changing currentStage.
```

## Completion gate

Stage 31 is `COMPLETE` only if the fresh window has launcher/API/runtime-listener evidence, advancing frames, valid assertions, terminal mission result, zero same-window ScriptErrors, and a native observation record. If any dependency cannot be reached, status remains `BLOCKED` and Stage 32 must not be promoted.

## Deliverables

- `native-observation.v1`.
- Fresh packed-map/runtime/controller output under `artifacts/projects/cmre-porting/stage31-native-runtime-evidence-lane/`.
- Same-window ScriptError verdict and evidence bundle.
- Updated Stage 30 differential report using the native record, without changing `native_claim=false` in the comparator layer.
- Stage 31 `result.json`, `log.md`, and `issues.json` with evidence classification.

## Verification commands

The exact port, packed-map path, and fresh epoch are recorded after the launcher run. The required command shapes are:

```text
py -3.13 tools/mpq/scripts/pack_stormlib.py --stormlib <StormLib.dll> <staged-map-directory> <packed-map>
pwsh -NoProfile -ExecutionPolicy Bypass -File tools/launchers/launch-cmre-alenger.ps1 -MapName 亡者之夜.SC2Map -Commander TerranRaynor -ListenPort <port> -ApiMinimal -DebugMode -KeepAlive -MapCopySuffix stage31-native-baseline
py -3.13 -m json.tool <runtime-result.json>
py -3.13 tools/galaxy-vibe/script_error_check.py --since <fresh-utc-epoch> --out <script-error-verdict.json>
```

## Write scope

- `src/projects/cmre-porting/project.json`
- `src/projects/cmre-porting/stages/30-differential-validation-layer/**`
- `src/projects/cmre-porting/stages/31-native-runtime-evidence-lane/**`
- `src/projects/cmre-porting/vibe/**`
- `artifacts/projects/cmre-porting/stage30-differential-validation-layer/**`
- `artifacts/projects/cmre-porting/stage31-native-runtime-evidence-lane/**`
