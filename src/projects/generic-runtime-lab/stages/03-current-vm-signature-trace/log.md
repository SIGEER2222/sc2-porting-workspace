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
