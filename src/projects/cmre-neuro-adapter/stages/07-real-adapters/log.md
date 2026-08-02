# Stage 07 Log: Real Transport Adapters

## Progress

The simulator-facing real transport boundaries are implemented within the declared
`cmre-neuro-adapter` write scope. The stage remains blocked at the live probe gate because
the approved launcher found an existing SC2 runtime lease owned by another session.

## Failure-First Diagnostic

- `simulator`: the initial transport test command failed with
  `ModuleNotFoundError: No module named 'tests.test_transport_adapters'` because the declared
  Stage 07 test module and transport package did not yet exist. This failure drove the bounded
  transport implementation and regression tests.
- `simulator`: after implementation, the focused transport suite passed `6/6` and the project
  suite passed `62/62` tests with `22` subtests under Python 3.13.
- `runtime`: an approved launcher preflight with `-NoLaunch` completed staging successfully,
  but it did not count as live evidence.
- `runtime`: the live launcher attempt was rejected before staging with
  `SC2_RUNTIME_BUSY`, owner PID `36840`, port `5121`, and session
  `cmre_alenger-20260802-124748-6ee40c06`. This is an existing session and was not terminated
  or taken over.

## Evidence

- `simulator`: `python -m pytest tests/test_transport_adapters.py --maxfail=20 -q` -> `6 passed`.
- `simulator`: `python -m pytest -q` -> `62 passed, 22 subtests passed`.
- `static`: `python -m compileall -q cmre_neuro_adapter tests` -> pass under Python 3.13.
- `static`: Python 3.11 grammar fallback -> `53` project/test files passed
  `ast.parse(..., feature_version=(3,11))`; no Python 3.11 runtime claim is made.
- `static`: `git diff --check -- src/projects/cmre-neuro-adapter` -> pass before stage metadata
  was added.
- `runtime`: approved preflight command:
  `pwsh -NoProfile -ExecutionPolicy Bypass -File tools/launchers/launch-cmre-alenger.ps1 -MapName 亡者之夜.SC2Map -Commander TerranRaynor -ListenPort 5091 -ApiMinimal -DebugMode -NoLaunch -MapCopySuffix stage07-preflight`
  -> staging completed and lock released.
- `runtime`: live probe command:
  `pwsh -NoProfile -ExecutionPolicy Bypass -File tools/launchers/launch-cmre-alenger.ps1 -MapName 亡者之夜.SC2Map -Commander TerranRaynor -ListenPort 5091 -DebugMode -KeepAlive -MapCopySuffix stage07-runtime`
  -> blocked by `SC2_RUNTIME_BUSY` before API listening. Captured output:
  `artifacts/projects/cmre-neuro-adapter/artifacts/stage07-real-runtime-20260802-125047/launcher-stdout.txt`
  and `artifacts/projects/cmre-neuro-adapter/artifacts/stage07-real-runtime-20260802-125047/launcher-stderr.txt`.
- `runtime`: `python tools/galaxy-vibe/script_error_check.py --since 1785646068 --out src/projects/cmre-neuro-adapter/artifacts/stage07-real-runtime-current-check-script-error-verdict.json` -> no new errors, but this scan is not a same-window successful Stage 07 runtime and is non-qualifying for G4.

## Gate Results

| Gate | Result | Evidence |
|---|---|---|
| G1-contract | PASS | Typed transport boundaries and focused simulator tests |
| G2-reconnect | PASS | Reconnect and idempotency tests with injected fakes |
| G3-failure | PASS | Timeout, stale-state, duplicate, unsupported, and backend-error tests |
| G4-live-probe | BLOCKED | Approved launcher blocked by an unrelated existing SC2 runtime lease |
| G5-packaging | PASS | Python tests, compileall, Python 3.11 grammar fallback, and diff check |

## Changes

- `cmre_neuro_adapter/transports/common.py`: shared typed transport status, execution result,
  error, correlation, state-version, and canonical payload helpers.
- `cmre_neuro_adapter/transports/sc2api_neuro.py`: injected async SC2 API boundary with
  timeout, reconnect, public context projection, stale-state checks, and duplicate results.
- `cmre_neuro_adapter/transports/bank_neuro.py`: injected Bank store boundary with XML Bank
  read/write support, atomic replacement, context publication, action staging, and result polling.
- `cmre_neuro_adapter/transports/input_neuro.py`: explicit input binding fallback with typed
  action results and explicit unsupported observation/context operations.
- `tests/test_transport_adapters.py`: offline transport contract, failure, reconnect,
  idempotency, XML round-trip, and input fallback coverage.

## Problems and Limitations

- Python 3.11 is not installed. Compatibility is limited to grammar parsing plus Python 3.13
  execution; no 3.11 runtime claim is made.
- No live Neuro WebSocket, Bank-in-game, SC2 API action, or Stage 07 runtime heartbeat claim
  is made. The live launcher could not acquire the global runtime lease.
- The current owner session at port `5121` must finish or release its lease before a new live
  probe can be run. It is not safe for this stage to terminate it because it was not created by
  this run.

## Handoff

Stage 07 remains the active stage. Re-run the live probe through the approved launcher after
the existing runtime lease is released, then perform `CreateGame + JoinGame`, collect runtime
listener/heartbeat evidence, and run a same-window `ScriptError` check. Do not mark G4 PASS or
write a next-stage plan from the current evidence.
