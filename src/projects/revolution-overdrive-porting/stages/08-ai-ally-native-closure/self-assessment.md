# Stage 08 Self-Assessment

## Result

**Static P2 contract proven; native AI ally closure remains blocked.**

The map script defines P2 as a time-gated scripted ally. The Odin is pre-placed and hidden, then
handed from the mission-neutral owner to P2 only after the map-owned Region 24 trigger chain. The
admissible debug-free native runs did not reach that gate, so this stage cannot claim native ally
success. The prior debug-assisted handover artifact is explicitly excluded.

## Proven

- P1/P2 alliance and P2 enemy relationships are captured with line citations.
- P2 owns no unit at map start and receives `UnitFromId(2)` only through the map-owned rescue call.
- The Region 24 gate and `gt_MidQ` -> `gt_MidCleanup` chain are guarded by deterministic tests.
- The project-local adapter now models the delayed handover explicitly. It blocks P1-to-P2
  dispatch while P2 owns zero observed units, then permits it only after native ownership is
  observed; unresolved lifecycle paths remain fail-closed.
- The dynamic-owner resolver safely expands 182 concrete PlayerGroupLoop alliance edges across
  24 maps and retains 18 opaque calls as unavailable rather than guessing their membership.
- The capability matrix independently characterizes all 31 owned maps: 26 have at least one
  valid fail-closed pairing, with 414 static and 110 safely dynamic pairings. The remaining 18
  dynamic calls are still unavailable and therefore do not become an accidental authorization
  surface.
- Debug-free 18165 and fresh 18204 runtime probes reached playable games with non-empty Catalogs;
  18204 records `debug_apis_used=[]` and no action errors in its own probe artifact. The 18165
  window has separate same-window ScriptError evidence; 18204 does not independently carry that
  launcher scan after the later fixed-path launcher output was overwritten by port 18220.
- The launcher patch has a stable readiness check; the 18166 follow-up websocket failure remains
  blocked rather than being promoted to a runtime pass.
- A fresh port 18220 launcher attempt also remains blocked: readiness and CreateGame succeeded,
  but JoinGame timed out before a playable observation. It adds no P2 evidence and is explicitly
  excluded from the native closure claim.

## Not proven

- No admissible runtime window has observed P2-owned units after the map-owned rescue.
- No admissible window has shown a P1-visible P2-allied unit or acknowledged native P2 command.
- The 24 dynamic-owner maps remain unresolved and fail-closed.
- Eighteen dynamic alliance calls remain unresolved and require runtime owner/alliance evidence;
  the 182 statically concrete calls are not a blanket runtime guarantee.
- The matrix is static/simulator evidence only; it does not promote any map's observation-gated
  or time-gated ally to native runtime readiness.
- The 18220 window did not reach JoinGame, so it cannot extend the completed 18204 gameplay
  census; this is a launcher/runtime availability gap, not evidence of handover behavior.

## Self-critique

The concurrent Stage 08 closure files incorrectly claimed `PROVEN_STATIC_AND_NATIVE`, used a
non-schema result format, and treated `Debug.game_state.god` as acceptable. They are corrected:
the result now uses canonical claim types, the historical debug-assisted artifact is excluded, and
the 18204 no-debug run is recorded as blocked. The wrapper exit-code propagation gap is also open.
The adapter continuation is intentionally static/simulator-only: it improves dispatch safety
without pretending that the native handover was observed.

## Next action

Use only supported gameplay and native player actions to clear the warehouse objective and enter
Region 24. If that cannot be reproduced, keep thorner03 P2 dispatch unavailable until the
handover is observed and record the map-specific progression limitation. Do not spawn units, enable god mode, inject
generic AI, or edit the map to manufacture the handover.
