# Stage 03 Log: Current VM Signature Trace

## 2026-08-16

- `static`: Stage 02 proved the native agent can load into a launcher-owned
  `5.0.16.97563` debug process, but the agent deliberately exposes no VM hook.
- `static`: The optimized PE probe is the only current-version candidate source
  so far. It records strings and RIP-relative xref candidates without promoting
  an address to executable configuration.
- `inference`: The 2016 GSVM research cannot identify a safe current-version
  entrypoint by itself; a stable signature and a dynamic observation boundary
  are still required.

## Probe v2 and observation recipe

- `static`: Updated `probe_sc2_binary.py` to decode common x64 RIP-relative
  ModRM forms using the displacement after the ModRM byte. The report now
  records section ownership, byte windows, instruction bytes, and disassembler
  availability. A synthetic `48 8D 0D disp32` test prevents regression.
- `static`: Re-ran the locked probe. SHA-256 matches; 54 target-string matches,
  6,643 file-backed RIP-relative instruction candidates, and zero direct xrefs
  to the exact starts of those target strings. This is consistent with table or
  offset-based diagnostic resources, but does not identify a VM boundary.
  Evidence: `artifacts/projects/generic-runtime-lab/stage03-current-vm-signature-trace/static/sc2-binary-probe.json`.
- `static`: No `llvm-objdump`, `objdump`, or Capstone installation is available
  in the local toolchain. The report explicitly records this gap and retains
  machine-code context as the reproducible fallback.
- `static`: Added the non-invasive three-layer observation contract and
  promotion gate in `trace-recipe.md`. It keeps script load, trigger dispatch,
  and VM execution evidence separate and leaves the hook disabled.

## Initial validation

- `static`: `python src/projects/generic-runtime-lab/scripts/probe_sc2_binary.py --exe E:\SC2\SC2new\StarCraft II\Versions\Base97563\SC2_x64.exe --profile src/projects/generic-runtime-lab/runtime/native-vm/profiles/sc2-5.0.16.97563.json --out artifacts/projects/generic-runtime-lab/stage03-current-vm-signature-trace/static/sc2-binary-probe.json` -> SHA match, 54 string matches, and zero promoted hooks.

## Boundary

No hook, patch, bytecode replacement, or WYSIWYG runtime behavior is enabled in
this stage until a candidate survives independent static and debug-window
verification. The dynamic trace remains blocked at the VM execution layer
because the agent reports `vm_hook=disabled` and no event-source observer is
currently installed.

## 2026-08-16 trace protocol and breakpoint fixture

- `static`: Added explicit `TRACE_ARM`, `TRACE_STATUS`, `TRACE_DISARM`,
  `TRACE_TEST_BREAK`, and `TRACE_TEST_INT3` commands to the native agent. The
  handler is a VEH observer only; `hook_enabled=false` and `vm_hook=disabled`
  remain hard-coded in the handshake/status contract.
- `static`: Native agent test `trace_protocol_captures_int3_and_disarms` passed
  on `x86_64-pc-windows-gnu`. It installed the VEH, captured
  `0x80000003` (`last_exception=2147483651`), observed a non-zero instruction
  pointer, counted one event, and rejected a second test after disarm.
  Evidence: `tools/runtime-vm/agent/src/lib.rs`.
- `static`: `build_native_vm.ps1` now regenerates `fixture-profile.json` from
  the freshly copied fixture SHA, so injection no longer depends on a stale
  manually maintained profile.
- `runtime`: A release fixture completed
  `inject -> HELLO -> STATUS -> TRACE_ARM -> TRACE_TEST_INT3 -> TRACE_STATUS -> SHUTDOWN`.
  The target SHA matched the generated profile
  `1291E2F968623D0E52E4B8D457B694AB842DF2B80EB71F0CDFC3DF373FD8988D`,
  the fixture stayed alive, and the trace reported one `0x80000003` event with
  `last_ip=0x00007FFB8F80933A`. Evidence:
  `artifacts/projects/generic-runtime-lab/stage03-current-vm-signature-trace/runtime/fixture-veh-breakpoint-trace.json`.
- `static`: Added a reusable `--breakpoint-trace` map build. Its delayed
  five-second trigger writes `trace_before`, executes Galaxy `breakpoint;`,
  then writes `trace_after`. The packed map SHA is
  `7778fad557b256b7fc1abe1d3cec5c59adc2b1e3cd0d0220bbf6c03400dfd803` and
  both Galaxy files lint with zero errors/warnings. Evidence:
  `artifacts/projects/generic-runtime-lab/stage03-current-vm-signature-trace/maps/breakpoint-trace-build-report.json`.
- `runtime`: A previous session window on launcher-owned SC2 PID `20852`, port
  `5981`, recorded the locked SHA, zero ScriptErrors, and one VEH
  `0x80000003` event. The preserved record is explicitly historical because
  its original controller stdout was not persisted and the mutable launcher
  JSON was later overwritten; it does not prove Galaxy-to-VEH correlation.
  Evidence:
  `artifacts/projects/generic-runtime-lab/stage03-current-vm-signature-trace/runtime/sc2-veh-breakpoint-trace-port5981-historical.json`.
- `blocked`: A fresh compliant launcher attempt on port `5983` timed out after
  180 seconds because an unrelated SC2 process (PID `8516`, port `5943`) was
  already present. The launcher did not take ownership or terminate it, so no
  fresh breakpoint-map runtime evidence was claimed.

## Current boundary

The native VEH path is now reproducible in a fixture and has historical real
SC2 evidence, but it still does not show that Galaxy `breakpoint;` dispatches
through the same boundary or that Bank `trace_before/trace_after` survive the
event. Keep the version profile disabled until a fresh launcher-owned window
captures all three records in one run.

## 2026-08-16 fresh launcher-owned trace attempts

- `runtime`: Three fresh `pwsh tools/galaxy-vibe/launch-galaxy-vibe.ps1` windows
  reached launcher/API readiness and completed `CreateGame + JoinGame` for
  `BreakpointTrace.SC2Map` on ports `5993`, `5994`, and `5995`. Each controller
  handshake matched the locked SHA
  `C86A6DD6A9295F300709D84CE0AA15375F8A345E7F7B36493017D78BD32FE01A` and
  reported `hook_enabled=false`.
- `runtime`: Port `5993` failed on one `step 2000` request after successful
  Create/Join. Its agent trace reached `breakpoint_count=24782341`,
  `last_exception=0x80000003`, and a non-zero IP, but the event is not
  attributable to the Galaxy fixture. Evidence:
  `artifacts/projects/generic-runtime-lab/stage03-current-vm-signature-trace/runtime/sc2-breakpoint-trace-runtime-attempts-20260816.json`.
- `runtime`: Port `5994` completed 25 `step 100` requests. The trace reached
  `breakpoint_count=88046484` with the same generic `0x80000003` signature;
  the pre-seeded Bank remained an empty shell and contained neither
  `trace_before` nor `trace_after`.
- `blocked`: Port `5995` completed eight `step 100` requests, then the `obs`
  request timed out near the delayed trigger. Its Bank was still an empty
  shell and the trace reached `breakpoint_count=77048074`; no causal link was
  claimed. Port `5996` reached only the launcher's short-lived API marker and
  refused the first websocket connection.
- `runtime`: The same-window ScriptError gates for ports `5993`, `5994`, and
  `5995` each reported no new ScriptError files. Evidence:
  `runtime/scripterror-port5993.json`, `runtime/scripterror-port5994.json`, and
  `runtime/scripterror-port5995.json`.
- `inference`: The current debug build emits high-volume `0x80000003` traffic
  through the VEH observer, and the breakpoint fixture did not produce a
  durable Bank marker. This is insufficient to identify a VM boundary or to
  promote an executable hook. The profile remains `hook_enabled=false`.

## Updated boundary

The stage now has fresh launcher-owned negative evidence in addition to the
fixture PASS: API readiness and Create/Join are reproducible, but Galaxy
breakpoint-to-VEH-to-Bank correlation remains unproven. Do not use the current
VEH counter as a VM event source; the next attempt needs a filtered event
observer or an explicitly instrumented map startup marker before promotion.

## 2026-08-16 map-only Bank check

- `runtime`: A no-agent launcher-owned window on port `5997` completed
  `CreateGame + JoinGame` and `step 600` for `BreakpointTrace.SC2Map`.
  `Banks\\1\\GalaxyVibe.SC2Bank` was still absent immediately afterward; no
  Bank marker was claimed. Evidence:
  `artifacts/projects/generic-runtime-lab/stage03-current-vm-signature-trace/runtime/sc2-breakpoint-trace-map-only-port5997.json`.
- `runtime`: The port `5997` same-window ScriptError gate reported no new
  ScriptError files (`runtime/scripterror-port5997.json`).
- `inference`: The map/API path is reachable, but the fixture does not yet
  provide a durable writable Bank in this runtime recipe. This blocks causal
  Bank correlation independently of the high-volume VEH breakpoint stream.
- `runtime`: After the port `5997` observation, a separate SC2 process on port
  `5948` repopulated `Banks\\1\\GalaxyVibe.SC2Bank` with unrelated session
  requests. That external process and Bank were identified by command line and
  left untouched; the map-only evidence above records the file state at the
  observation time.

## 2026-08-16 filtered observation preparation

- `static`: Extended the VEH observer with a fixed 32-slot instruction-pointer
  histogram. `TRACE_STATUS` now retains the high-volume total plus per-IP
  counts, so a future window can distinguish one generic debug stream from a
  candidate event source without treating the counter as VM evidence. The
  profile and handshake remain `hook_enabled=false`.
- `static`: Rebuilt `BreakpointTrace.SC2Map` to use the isolated
  `GalaxyVibeTrace` Bank and to persist `startup`, `trace_before`, and
  `trace_after` around Galaxy `breakpoint;`. The trigger delay is now five game
  seconds. The packed map SHA remains reproducible in the build report.
- `static`: Generated the seed Bank artifact
  `artifacts/projects/generic-runtime-lab/stage03-current-vm-signature-trace/runtime/galaxy-vibe-trace-bank-seed.xml`.
  The recipe now requires copying this seed to the root and existing numeric
  author directories before `CreateGame`; it intentionally leaves the
  unrelated `GalaxyVibe.SC2Bank` RPC channel untouched.
- `static`: `python -m pytest -q src/projects/generic-runtime-lab/tests` ->
  `14 passed`; both breakpoint fixture Galaxy files linted with zero errors and
  zero warnings; `cargo check` for `gsvm-agent` and `gsvm-controller` on the
  MSVC target passed.
- `blocked`: A fresh runtime attempt was not started because unrelated SC2
  owners were present at ports `5949` (PID `9424`) and `5965` (PID `30644`).
  The approved launcher can perform a global SC2 restart, so this session did
  not terminate or attach to either process. Evidence is the process command
  line snapshot from the current shell; the next runtime attempt requires an
  empty owner window and the new seed procedure.

## Updated boundary

The observer and map fixture are now prepared for a clean causal attempt, but
no new runtime correlation was claimed in this session. Keep
`hook_enabled=false` and `trace_status=VEH_BREAKPOINT_HIGH_VOLUME_UNCORRELATED`
until a fresh launcher-owned window records `startup -> trace_before ->
attributable VEH IP -> trace_after` in the isolated Bank with zero new
ScriptErrors.

## 2026-08-16 fresh seed attempts

- `runtime`: A compliant launcher-owned window on port `6001` (launcher PID
  `29844`, SC2 PID `8312`) completed `CreateGame + JoinGame + step 400` for
  the first seeded fixture build. `GalaxyVibeTrace.SC2Bank` remained exactly
  at `seed_marker`; `startup`, `trace_before`, and `trace_after` were absent.
  The same-window ScriptError gate reported no new errors.
- `runtime`: The fixture was rebuilt without the copied `Triggers` payload and
  rerun on port `6002` (launcher PID `18868`, SC2 PID `14836`). Both a
  non-realtime `step 400` run and a realtime retry reaching game loop `183`
  completed `CreateGame + JoinGame`; the seeded Bank again remained unchanged
  and the same-window ScriptError gate reported no new errors. Evidence:
  `runtime/sc2-breakpoint-trace-bank-seed-attempts-20260816.json`,
  `runtime/scripterror-port6001.json`,
  `runtime/scripterror-port6002.json`, and
  `runtime/scripterror-port6002-realtime.json`.
- `inference`: The first result is consistent with the copied compiled
  `Triggers` payload overriding the source fixture. The second result shows
  that removing `Triggers` alone is insufficient; it does not yet prove the
  source compiler is unavailable because the map retained `Triggers.version`.
- `static`: The next build now removes both `Triggers` and `Triggers.version`,
  reports the new packed SHA
  `2426968320eee7444f9c838c447387a6ffb51c386ffdb52ecdffe4e69e3a9071`, and
  remains covered by 14 project tests, zero-error Galaxy lint, and the seed
  artifact.
- `blocked`: Before the third runtime attempt, an unrelated SC2 owner appeared
  on port `5971` (PID `4812`). The launcher restart path is global, so the
  attempt was skipped and the owner was left untouched. A later clean window
  must run the SHA `242696...` fixture before any VM correlation claim.

## Current boundary

The map/API transport is runtime-proven, but the map-owned trace trigger has
not yet rewritten its seeded Bank in either fresh window. This is a fixture
dispatch problem, separate from VM event attribution. Keep
`hook_enabled=false`; do not interpret the zero-error gates or unchanged seed
as evidence that `breakpoint;` executed.

## 2026-08-16 self-restarted verification

- `runtime`: The approved `tools/galaxy-vibe/launch-galaxy-vibe.ps1` was
  rerun with `pwsh -NoProfile ... -Port 6003 -ForceRestart`. It terminated the
  prior SC2 owner through the launcher's forced restart path, started Switcher
  PID `16624` and SC2 PID `20288`, and opened API port `6003`. Evidence:
  `runtime/launcher-port6003-20260816-pwsh.log`.
- `runtime`: With the current packed fixture SHA
  `2426968320eee7444f9c838c447387a6ffb51c386ffdb52ecdffe4e69e3a9071`, the
  same window completed `CreateGame + JoinGame + realtime step 600` after an
  eight-second join wait. Every seeded root/numeric `GalaxyVibeTrace` Bank
  remained at `seed_marker`; no `startup`, `trace_before`, or `trace_after`
  key appeared. Evidence:
  `runtime/repl-port6003-20260816.jsonl`,
  `runtime/bank-pre6003-20260816T121617Z`, and
  `runtime/sc2-breakpoint-trace-bank-seed-attempts-20260816.json`.
- `runtime`: The same-window ScriptError gate for launch epoch `1786882618`
  reported no new errors. Evidence: `runtime/scripterror-port6003.json`.
- `runtime`: A second forced restart on port `6004` tested a `LocalMap.map_path`
  pointing at the unpacked build directory. SC2 API rejected it before
  `JoinGame` with `map_path ... file doesn't exist`; the directory experiment
  is not execution evidence. The same-window ScriptError gate was empty.
  Evidence: `runtime/repl-port6004-20260816.jsonl`,
  `runtime/scripterror-port6004.json`.
- `inference`: The requested fresh-window retry removes the prior owner
  blocker, but it still cannot distinguish a source-compilation boundary from
  a map fixture dispatch defect because the current packed map produces no
  Bank marker. The native observer remains uncorrelated and
  `hook_enabled=false` is retained.

## Updated boundary

The current fixture has fresh launcher/API/runtime evidence but no automatic
Galaxy trigger marker. Do not inject or promote a VM hook from this window;
the next bounded action is to establish a compliant source-compilation or
trigger-dispatch path, then repeat the observer only after
`startup -> trace_before -> attributable VEH/IP -> trace_after` is visible.

## 2026-08-16 InitMap direct-dispatch probe

- `static`: Added a separate `BreakpointTraceDirect.SC2Map` build target. It
  removes both `Triggers` and `Triggers.version`, then executes
  `TriggerExecute(TriggerCreate("BreakpointTrace_Probe"), false, true)` from
  `InitMap()`. The delayed `BreakpointTrace.SC2Map` remains unchanged for the
  later automatic-dispatch test. Build SHA:
  `726263ed97679d428592efc4182e3c2583fbd25f76f9b25140d0251974293336`.
- `static`: Project tests now pass `15/15`; direct fixture Galaxy lint reports
  zero errors and zero warnings (known include/undeclared diagnostics remain
  suppressed by the linter). Native release artifacts were rebuilt after the
  IP-histogram observer change.
- `runtime`: Port `6009` was a first direct probe with the pre-histogram DLL.
  `CreateGame` reached the map and the root `GalaxyVibeTrace` Bank contained
  `startup`, `trace_before`, and `trace_after`; JoinGame remained at
  `game_loop=0` because the Galaxy `breakpoint;` probe pauses the debug game.
  The same-window ScriptError gate reported zero new errors.
- `runtime`: Fresh port `6012` repeated the direct probe with the rebuilt
  agent. The launcher-owned SC2 PID was `3632`, the locked executable SHA
  matched, and the observer was armed before `CreateGame`. The root Bank again
  contained all three markers. The observer reported one high-volume IP
  (`0x00007FF6D878B586`, `33,975,012` breakpoint events, exception
  `0x80000003`) and zero ScriptErrors. Raw evidence:
  `artifacts/projects/generic-runtime-lab/stage03-current-vm-signature-trace/runtime/direct-initmap-evidence-20260816.json`.
- `inference`: This proves current source compilation, `InitMap` direct
  trigger execution, and Bank persistence in a real SC2 window. The VEH IP is
  still uncorrelated to a trigger/program id; it is not a promoted VM
  boundary. `hook_enabled=false` remains required.

## Updated boundary

The direct path is now runtime-verifiable and can be used as the fixture gate
for future observer work. Automatic time-event dispatch is still a separate
blocked behavior, and the current VEH stream remains only a debug-break
observation. The next bounded experiment is a direct probe without
`breakpoint;` to isolate the JoinGame pause, followed by a filtered observer
that can carry a trigger correlation id before any hook promotion.

## 2026-08-16 direct control runtime

- `static`: Added `BreakpointTraceDirectControl.SC2Map`, reusing the exact
  `InitMap -> TriggerExecute` and Bank probe while removing only `breakpoint;`.
  The control map SHA is
  `d89104959b8ed38c6484a09db34e11a04d1ed17122a4ac7fd87311c81fa9425b`.
- `static`: Refactored the two direct variants through one builder helper;
  project tests pass `16/16`, and the control Galaxy files lint with zero
  errors and zero warnings.
- `runtime`: Port `6013` launched through the approved launcher and completed
  `CreateGame`, `JoinGame` (`player_id=1`, `game_loop=1`), realtime
  initialization, and `step 100`. The root `GalaxyVibeTrace` Bank contained
  `startup=1`, `trace_before=1`, and `trace_after=1`; the same-window
  ScriptError gate reported zero new errors.
- `runtime`: The control pass isolates the previous direct probe's
  `JoinGame/game_loop=0` result to the deliberate Galaxy `breakpoint;` pause.
  It does not add VM-boundary attribution; the generic VEH observer remains
  uncorrelated and the profile remains disabled. Evidence:
  `artifacts/projects/generic-runtime-lab/stage03-current-vm-signature-trace/runtime/direct-control-evidence-20260816.json`.

## Updated boundary

The source/dispatch path now has both a breakpoint probe and a no-break
runtime control, with the expected Bank effects and stable game-loop evidence.
The remaining gap is specifically automatic time-event dispatch and a filtered,
trigger-correlated VM observer; no executable hook is promoted.

## 2026-08-17 offline continuation

- `static`: Added a `TRACE_RESET` protocol command that only succeeds while
  the VEH observer is disarmed. It clears the breakpoint count, last exception,
  last IP, and all 32 histogram slots. An armed observer returns
  `trace_must_be_disarmed`. The controller now records the raw reset response
  before `TRACE_ARM` for every `--arm-trace` window, ensuring future evidence
  has a zero-counter baseline without enabling a VM hook.
- `static`: The runtime-lab configuration and all control/trace builders now
  reference the existing read-only test-arena map source rather than the absent
  `src/lib/_testmap_src` skeleton. The source map itself was not modified.
- `static`: `python -m pytest -q src/projects/generic-runtime-lab/tests` ->
  `18 passed`; Windows GNU-target `cargo check --tests` completed for both
  `gsvm-agent` and `gsvm-controller`; and `rustfmt --check` passed for both
  changed Rust sources. Evidence:
  `artifacts/projects/generic-runtime-lab/stage03-current-vm-signature-trace/static/offline-validation-20260817.json`.
- `blocked`: The new base-source configuration let
  `python src/projects/generic-runtime-lab/scripts/build_runtime_lab.py --breakpoint-trace`
  reach `pack_map`, but it cannot produce a fresh packed fixture because
  `artifacts/stormlib-v9.40/x64/StormLib.dll` is absent. No fixture SHA or
  Galaxy-lint result was claimed from this attempt.
- `blocked`: Native Rust unit tests cannot link in this shell: the GNU target
  lacks `dlltool.exe`, and the MSVC target/linker is not installed. Their code
  compiles through `cargo check --tests`; the runnable native-test claim remains
  deferred.
- `blocked`: No local SC2 environment is available, so no launcher, API,
  ScriptError, Bank, or VM-observation step was attempted in this continuation.
- `static`: The offline evidence JSON remains under the workspace-wide ignored
  `artifacts/**` tree by design. Its commands and outcomes are mirrored in this
  log and `result.json`, so the ignored artifact is intentionally not staged.

## Updated boundary

The next future runtime window will start with a controller-recorded reset
baseline, but this is static preparation only. It does not correlate VEH events
to a Galaxy trigger, exercise delayed automatic dispatch, identify a VM entry
point, or permit `hook_enabled=true`.
