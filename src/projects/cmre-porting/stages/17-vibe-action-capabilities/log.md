# Stage 17 Log

## Scope opened

Stage 17 follows the verified Stage 16 function registry. It owns only the
project Vibe protocol, registry-backed Host/simulator behavior, controlled
Galaxy kernel mirrors, tests, and generated evidence under the declared
writeScope. Registered source maps and external repositories remain read-only.

## Evidence

Implementation and verification entries will be appended as each simulator,
static, and runtime gate completes. Claims must remain classified as
`static`, `simulator`, `runtime`, `blocked`, or `inference`.

## Implementation

- `static`: Registered `vibe.player.set_resource`, `vibe.unit.spawn`,
  `vibe.query.units`, and `vibe.unit.kill` with typed arguments and explicit
  handler mappings. Host and SimulatorTransport use the same registry
  validation contract.
- `static`: Aligned the canonical kernel, debug-mod mirror, and project map
  mirror. Query handlers validate live unit life/type/owner; kill resolves the
  runtime `UnitGetTag` before calling `UnitKill`, avoiding static editor-id
  tombstones.
- `static`: Extended `evidence_bundle.py` to collect stage-root combined
  verdict, Bank, host logs, request log, and packed-map evidence.

## Verification

- `simulator+static`: `python -m pytest -q tools/galaxy-vibe/tests/test_kernel.py
  tools/launchers/tests/test_launch_cmre_alenger_static.py
  tools/launchers/tests/test_live_runner_unit_adapter.py` -> `51 passed`.
- `static`: `powershell -NoProfile -ExecutionPolicy Bypass -File
  tools/galaxy-vibe/run-all-validation.ps1` -> `52/52 PASS`, 0 warnings.
- `runtime`: `launch-cmre-alenger.ps1` with `-ApiMinimal -DebugMode -KeepAlive`
  reached API ready on port 5081 and entered the packed map through
  CreateGame/JoinGame. The launcher exited 0 and its runtime listener was
  present.
- `runtime`: Run `stage17-action-runtime-pass5-20260801-2214` completed six
  `function.invoke` requests. `set_resource` returned 4321; Marine query
  counts changed `0 -> 2 -> 1`; `unit.kill` returned `OK`.
- `runtime`: `script_error_check.py --since 1785593749` -> no new
  `ScriptError*.txt` files.
- `runtime`: `summarize_verdict.py` -> `PASS`, assertions `5/5`, ScriptError
  count `0`.
- `static+runtime`: Evidence bundle
  `bundle-stage17-action-runtime-pass5-20260801-2214/evidence-bundle.json`
  -> `17` items, `overall_status=passed`.

## Closeout

Stage 17 is complete. The next stage plan is recorded at
`src/projects/cmre-porting/stages/18-vibe-task-execution-loop/plan.md`.
The carried-forward legacy parser warning remains explicit and does not
invalidate the verified action/query runtime path.
