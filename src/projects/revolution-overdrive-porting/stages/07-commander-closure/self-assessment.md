# Stage 07 Self-Assessment

## Result

**Commander/runtime bootstrap is proven; Stage 07 passes its commander-closure acceptance.**

The eight required Mods are closed against the read-only source through exact owned and asset
hash coverage. All 31 maps remain complete, the representative MPQ is readable, and the
approved launcher stages the effective closure. The extracted commander remains selectable by
the WebUI route and the RO AI ally adapter remains deterministic and fail-closed.

## Proven

- Eight-Mod effective closure: zero missing, changed, or extra files.
- 31-map source/owned closure: zero missing, changed, or extra files.
- 74 owned Galaxy files lint with zero diagnostics.
- Main commander Mod Catalog: 4,135 entries and zero parse errors.
- RO AI ally tests: 5/5 passed.
- WebUI RO tests: 2/2 passed.
- Approved launcher: staged closure, `CreateGame=init_game`, `JoinGame=in_game`, non-empty Catalog, and same-window ScriptError count is zero.
- Native bootstrap census: P1-owned units are visible and the runtime reports a Computer P2 slot without P2-owned units through loop 48; the map's later Tychus rescue was not reached.
- Native action probe with the explicit P1/P2 setup: attack-move and move were accepted, but
  Tychus died before Region 24; P2-owned units and P1-visible allied units remained absent.
- Pure-runtime Iron opening: the owned map still creates `SCV`; the launcher injects only runtime
  Galaxy lifecycle handlers. A fresh secondary session observed 8 `1gangtiegongchengche` workers
  and 1 `1gangtieyaosai` fortress at loops 389 and 405 after native Region 29 progression, with
  `requestStepsSent=0`, no chat command, and a same-window ScriptError count of zero.
- Pure-runtime faction closure: fresh secondary sessions observed `SCVC` plus `CommandCenterC`
  for Coverts, `SCVU` plus `CommandCenterU` for Umojan, `9shougezhe` for Pirate, and
  `3diguozhijian` for Madness. All four sessions reached `init_game`/`in_game`, advanced in
  realtime with `requestStepsSent=0`, required no faction chat, and had zero same-window
  ScriptErrors.
- Generator regression: a single-element JSON replacement list was previously unwrapped by
  PowerShell and omitted from the generated Galaxy function body. The launcher now normalizes
  the list and uses explicit bootstrap markers; the fresh Coverts/Umojan windows prove the
  repaired worker branches in the real VM.
- Runtime isolation regression: when the previous packed map was still held open, the launcher
  selected `thanson01.stage07.5967.packed.SC2Map` and reached ready without terminating the
  external SC2 process.
- Final result schema validation passed; the result contains only canonical claim types and
  integer validation exit codes.
- Final rerun passed: 5/5 AI ally tests, 2/2 WebUI tests, 74-file Galaxy lint with zero
  diagnostics, 4,135 catalog entries with zero parse errors, Python compile, workspace validate,
  and approved launcher `-NoLaunch` with 55/55 staged map files.

## Remaining Scope

- The 24 dynamic-owner maps remain fail-closed; static evidence is not enough to widen their
  target contracts.
- The old thorner03 loop-48 blocker is superseded by the Stage 09 no-debug handover evidence;
  the current unresolved item is the general RO-AI-001 dynamic-owner population, not the Iron
  commander replacement.

## Self-critique

The previous RO runtime probe accepted a no-error JoinGame response without requiring the
response status to be `in_game`. The corrected launcher and strict census now close that gap.
The earlier thanson01 conclusion was limited by a short probe window, not by a replacement failure.
The final run used the map-owned Escort transition and removed the launcher's static SCV and
rescue patches before proving the target units. No generic `AIStart` injection or artificial base
creation is introduced; mission-owned initialization and alliances remain outside the commander
adapter boundary.

## Decision

Keep map-owned initialization, objectives, rewards, and alliance setup inside the maps. Keep the
general AI ally adapter fail-closed for the 24 unresolved dynamic-owner maps, while treating all
five Revolution Overdrive commander runtime replacement paths as proven on thanson01. The next
stage remains responsible for any broader AI ally contract changes.
