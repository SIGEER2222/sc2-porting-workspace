# Stage 07 Self-Assessment

## Result

**Commander/runtime bootstrap is proven; the stage remains blocked at the native AI ally gate.**

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
- Approved launcher: staged closure, `CreateGame=init_game`, `JoinGame=in_game`, RequestStep through loop 48, non-empty Catalog, accepted `Iron` chat, and same-window ScriptError count is zero.
- Native bootstrap census: P1-owned units are visible and the runtime reports a Computer P2 slot without P2-owned units through loop 48; the map's later Tychus rescue was not reached.
- Native action probe with the explicit P1/P2 setup: attack-move and move were accepted, but
  Tychus died before Region 24; P2-owned units and P1-visible allied units remained absent.
- Final result schema validation passed; the result contains only canonical claim types and
  integer validation exit codes.
- Final rerun passed: 5/5 AI ally tests, 2/2 WebUI tests, 74-file Galaxy lint with zero
  diagnostics, 4,135 catalog entries with zero parse errors, Python compile, workspace validate,
  and approved launcher `-NoLaunch` with 55/55 staged map files.

## Not Proven

- No native P2-owned or P1-visible allied unit roster was observed in the loop-48 bootstrap window; the later map-owned rescue remains unverified.
- No P2 command acknowledgement or native AI ally action effect was observed.
- The 24 dynamic-owner maps remain fail-closed; static evidence is not enough to widen their
  target contracts.

## Self-critique

The previous RO runtime probe accepted a no-error JoinGame response without requiring the
response status to be `in_game`. The corrected launcher and strict census now close that gap.
The remaining AI ally conclusion is deliberately fail-closed: P2's Computer roster entry and
static shared-vision intent do not prove that P2 was initialized or that owner 16 is an ally.
The native action probe proves that ordinary actions are accepted, but the mission-owned
warehouse objective still did not reach `gt_MidCleanup`; this is a gameplay progression gap, not
evidence for adapter-side unit creation. No generic `AIStart` injection or map-script patch is
introduced because mission-owned initialization and alliances remain outside the commander
adapter boundary.

## Decision

Keep map-owned initialization, objectives, rewards, and alliance setup inside the maps. Keep the
AI ally adapter fail-closed until P2 owner/alliance observations and an acknowledged native
command exist after the map-owned rescue lifecycle. The next stage must repair or clarify the
map-specific progression/initialization contract before widening the shared adapter.
