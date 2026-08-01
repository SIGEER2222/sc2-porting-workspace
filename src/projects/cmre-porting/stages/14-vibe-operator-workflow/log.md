# Stage 14 Log: Vibe operator workflow

## Result

- Status: PASS
- Closed: 2026-08-01T07:43:05+08:00
- Workflow status: WARN, with 7 passing lanes and one nonblocking parser warning.
- The warning is `parser.legacy_toolkit`; the registered Galaxy toolkit, project map extractor, and cold static validator pass.

## Runtime evidence

Command:

```text
powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/vibe.ps1 workflow -RunId stage14-live-final3 -Sc2Port 5001 -Live -LiveTimeoutSec 120
```

Runtime evidence:

- `artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/live-attempts/stage14-live-final3/port-5001/runtime-summary.json`
- `artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/live-attempts/stage14-live-final3/port-5001/launcher-stdout.txt`
- `artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/live-attempts/stage14-live-final3/port-5001/launcher-exit.json`
- `artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/live-attempts/stage14-live-final3/port-5001/assert-results.json`
- `artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/live-attempts/stage14-live-final3/port-5001/script-error-verdict.json`
- `artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/live-attempts/stage14-live-final3/port-5001/vibe-verdict.json`

Observed runtime facts:

- `SC2_x64` was launched through `launch-galaxy-vibe.ps1` via the Stage 13 harness.
- API port 5001 opened; `CreateGame` and `JoinGame` succeeded.
- Non-realtime frame advancement was recorded after JoinGame and before assertions.
- Assertions passed: 2/2.
- ScriptError gate: `has_new_errors=false`, count 0.
- The Stage 13 packaging tail exceeded the 120 second operator watchdog after producing the current runtime verdict. Stage 14 marked the attempt PASS only after checking current launcher stdout, current assertions, current ScriptError, and current vibe verdict. This is runtime evidence, not process-start evidence.

## Bundle and status

- Operator bundle: `artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/bundles/bundle-stage14-live-final3/evidence-bundle.json`
- Bundle result: `overall_status=passed`, 19 SHA-256 items, all phase statuses passed.
- Status report: `artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/workflow-status.json`
- Attempt record: `artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/live-attempts.json`

The follow-up non-live command was also verified after the live run:

```text
powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/vibe.ps1 workflow -RunId stage14-workflow-final2
```

It exited 0 and carried forward the latest Stage 14 PASS attempt. Its status is WARN with the parser warning plus a carried-forward evidence warning; it does not relabel that carried-forward bundle as a fresh runtime execution.

## Static verification

```text
PowerShell Parser.ParseFile(tools/galaxy-vibe/vibe.ps1): PASS
python -m py_compile tools/galaxy-vibe/workflow_status.py tools/galaxy-vibe/evidence_bundle.py tools/galaxy-vibe/galaxy_repl.py: PASS
```

## Scope and follow-up

Only the Stage 14 operator surface, project-local skill, status/bundle tooling, and Stage 14 artifacts were advanced. The next stage applies this workflow to AI ally behavior on Dead of Night. The legacy parser warning and optional visual lane remain explicitly recorded in `issues.json`.
