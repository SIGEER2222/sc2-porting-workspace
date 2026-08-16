# Stage 02: In-Process GSVM Agent

## Objective

Implement the first document-aligned native runtime layer for offline SC2 mod
development. The stage owns a version-locked controller, an in-process agent
loaded into an approved debug SC2 process, and a loopback named-pipe protocol.
It must prove process identity and agent handshake before any Galaxy VM hook is
enabled.

This stage is intentionally narrower than arbitrary code injection. It does
not bypass Warden, patch the retail client, attach to a non-debug process, or
guess a VM function address. The hook profile remains disabled until a current
binary signature is statically and dynamically verified.

## Inputs

- `E:/SC2/SC2new/StarCraft II/Versions/Base97563/SC2_x64.exe` (read-only local
  debug binary, version `5.0.16.97563`).
- `artifacts/galaxy-vibe/research/gsvm-research` (MIT, 2016 GSVM research;
  reference only, not a current-version signature source).
- `src/projects/generic-runtime-lab/stages/01-foundation` RuntimeLab map and
  its existing runtime evidence.

## Deliverables

- Version profile with executable SHA-256, required debug flags, and an empty
  hook table until a real signature is verified.
- Native controller and agent sources under the project-owned runtime tree.
- A Windows fixture host used for deterministic injection/IPC regression tests.
- A PE/GSVM static probe that reports relevant strings and candidate xrefs but
  never promotes a candidate to an executable hook automatically.
- Stage evidence quartet and a runtime probe result. A real SC2 handshake is a
  required gate; if the current session cannot be safely isolated, record a
  `blocked` result instead of reusing or terminating it.

## Verification

```text
python -m pytest -q src/projects/generic-runtime-lab/tests/test_native_vm.py
powershell -NoProfile -ExecutionPolicy Bypass -File src/projects/generic-runtime-lab/scripts/build_native_vm.ps1 -Configuration Release
python src/projects/generic-runtime-lab/scripts/probe_sc2_binary.py --profile src/projects/generic-runtime-lab/runtime/native-vm/profiles/sc2-5.0.16.97563.json
```

The fixture test must show `inject -> pipe handshake -> status -> shutdown`.
The SC2 gate must use an approved launcher-created `-debug -listen 127.0.0.1`
window and record PID, command line, binary hash, agent handshake, and the
same-window ScriptError verdict.

## Write scope

- `src/projects/generic-runtime-lab/**`
- `tools/runtime-vm/**`
- `artifacts/projects/generic-runtime-lab/**`
