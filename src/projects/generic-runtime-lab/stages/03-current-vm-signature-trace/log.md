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
