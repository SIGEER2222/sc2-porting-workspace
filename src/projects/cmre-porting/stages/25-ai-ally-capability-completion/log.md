# Stage 25 Log

## Status

In progress. The stage is active because implementation of the requested P1/P2
cooperative AI ally behavior has begun.

> Older verification-loop entries (2026-08-02 through 2026-08-05) rotated to
> archive/log-20260806.md per AGENTS.md 'Stage evidence rotation'.

## Verification Loop 2026-08-06 ZChar01 Enemy Target Diagnosis

- `static`: the ZChar01 startup gate previously tested P1's ally group before
  the adapter created the P1/P2 alliance. In the Computer-ally topology that
  condition was false, so the map fell through to `cai_startall()` and kept
  P2 in the original enemy-wave role. The project glue now detects
  `PlayerType(2) == c_playerTypeComputer`, runs the existing native P2
  initializer first, disables P2's original enemy-wave triggers, sets
  reciprocal P1/P2 alliances, and retargets campaign waves to both players.
- `static`: staged-map idempotence now replaces the generated CMRE and
  ZChar01 blocks between stable markers, so reusing a previous staged map
  cannot silently retain old glue. ZChar01 StartAI and wave hooks also have
  forward declarations before the generated map functions that call them.
- `static`: 57 launcher/live-runner tests passed, both relevant PowerShell
  files parsed, and the updated Galaxy glue reported zero diagnostics.
- `runtime`: the v4 standard API probe completed 2000 loops and emitted a
  native replay, but observed `p2_unit_count=0`, no P2 alliance values, and no
  enemy survivors; it is `INCONCLUSIVE` because map-side initialization did not
  run in that API window.
- `blocked`: the v5 DirectMapApi probe loaded the map and the launcher sent
  the Reborn confirmation input. The same window produced no non-empty
  ScriptError, but the runtime listener heartbeat stayed at zero and the
  join-existing WebSocket did not reach Ping/Observation. No runtime claim
  about enemy target distribution is promoted.

Evidence:
`tools/launchers/overlays/cmre-alenger/map-glue.reborn-zchar01.galaxy`,
`tools/launchers/lib/cmre-on-demand-overlay.ps1`,
`tools/launchers/launch-cmre-alenger.ps1`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-reborn-ally-target-v4-p2init-20260806/runtime-report.json`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-reborn-ally-target-v5-p2init-direct-20260806/launcher.stdout.log`.
