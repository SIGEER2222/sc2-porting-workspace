# Stage 03: Current VM Signature Trace

## Objective

Identify a current-version SC2 Galaxy VM execution boundary for the locked
`5.0.16.97563` binary without guessing from the 2016 research snapshot. The
stage may collect static candidates and non-invasive debug observations, but it
must not enable an executable hook until one candidate is independently
validated in a launcher-owned debug process.

## Inputs

- `src/projects/generic-runtime-lab/runtime/native-vm/profiles/sc2-5.0.16.97563.json`
- `artifacts/projects/generic-runtime-lab/stage02-inprocess-gsvm-agent/static/sc2-binary-probe.json`
- `tools/runtime-vm/` controller/agent handshake foundation
- `artifacts/galaxy-vibe/research/gsvm-research` as terminology-only reference

## Deliverables

- A reproducible candidate-signature report with file offsets, RVAs, and
  disassembly context.
- A debug-window observation recipe that distinguishes script load, trigger
  dispatch, and VM execution without patching code.
- A reusable `BreakpointTrace.SC2Map` fixture with a delayed Galaxy
  `breakpoint;` and `trace_before`/`trace_after` Bank markers for same-window
  correlation.
- An updated version profile that remains `hook_enabled=false` unless the
  signature passes the stage's independent verification gate.
- Stage evidence quartet and a concrete decision on whether a hook can be
  promoted or must remain deferred.

## Verification

```text
python src/projects/generic-runtime-lab/scripts/probe_sc2_binary.py --exe E:\SC2\SC2new\StarCraft II\Versions\Base97563\SC2_x64.exe --profile src/projects/generic-runtime-lab/runtime/native-vm/profiles/sc2-5.0.16.97563.json --out artifacts/projects/generic-runtime-lab/stage03-current-vm-signature-trace/static/sc2-binary-probe.json
```

Any dynamic trace must use a fresh compliant launcher-owned `-debug -listen`
window, capture runtime listener and same-window ScriptError evidence, and leave
the profile disabled when the trace cannot prove a stable current signature.

## Write scope

- `src/projects/generic-runtime-lab/**`
- `tools/runtime-vm/**`
- `artifacts/projects/generic-runtime-lab/**`
