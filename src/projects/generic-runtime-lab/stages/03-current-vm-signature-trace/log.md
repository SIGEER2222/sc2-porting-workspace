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

## Initial validation

- `static`: `python src/projects/generic-runtime-lab/scripts/probe_sc2_binary.py --exe E:\SC2\SC2new\StarCraft II\Versions\Base97563\SC2_x64.exe --profile src/projects/generic-runtime-lab/runtime/native-vm/profiles/sc2-5.0.16.97563.json --out artifacts/projects/generic-runtime-lab/stage03-current-vm-signature-trace/static/sc2-binary-probe.json` -> SHA match, 54 string matches, and zero promoted hooks.

## Boundary

No hook, patch, bytecode replacement, or WYSIWYG runtime behavior is enabled in
this stage until a candidate survives independent static and debug-window
verification.
