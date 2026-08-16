# Stage 02 Log: In-Process GSVM Agent

## 2026-08-16

- `static`: The active SC2 binary is `5.0.16.97563`, SHA-256
  `C86A6DD6A9295F300709D84CE0AA15375F8A345E7F7B36493017D78BD32FE01A`.
- `static`: The local `gsvm-research` source is an MIT, 2016 snapshot and
  explicitly describes itself as incomplete; it is retained as a reference
  for opcode terminology only.
- `inference`: A current-version VM entrypoint cannot be selected from the old
  opcode table or string names alone. Stage 02 therefore starts with a disabled
  hook table and a fail-closed agent handshake.

## Implementation and validation

- `static`: `powershell -NoProfile -ExecutionPolicy Bypass -File src/projects/generic-runtime-lab/scripts/build_native_vm.ps1 -Configuration Release` -> Rust GNU target built `gsvm-controller.exe`, `gsvm-fixture-host.exe`, and `gsvm_agent.dll`. The agent now statically links `libunwind.a`, so SC2 does not need to resolve a toolchain DLL during injection.
- `static`: `python -m pytest -q src/projects/generic-runtime-lab/tests/test_native_vm.py` -> `2 passed`.
- `static`: `cargo test --manifest-path tools/runtime-vm/Cargo.toml --target x86_64-pc-windows-gnu -p gsvm-controller` with the isolated LLVM-MinGW linker and `-C link-arg=-lunwind` -> `1 passed`.
- `static`: `python src/projects/generic-runtime-lab/scripts/probe_sc2_binary.py --exe E:\SC2\SC2new\StarCraft II\Versions\Base97563\SC2_x64.exe --profile src/projects/generic-runtime-lab/runtime/native-vm/profiles/sc2-5.0.16.97563.json --out artifacts/projects/generic-runtime-lab/stage02-inprocess-gsvm-agent/static/sc2-binary-probe.json` -> hash match, 54 string matches, no promoted hooks.
- `runtime`: The isolated fixture host was launched with PID `21352`. The controller verified its executable name and SHA-256, injected `gsvm_agent.dll`, and completed `HELLO -> STATUS -> SHUTDOWN`; all responses reported `hook_enabled=false`. Evidence: `artifacts/projects/generic-runtime-lab/stage02-inprocess-gsvm-agent/runtime/fixture-injection.json`.
- `runtime`: `tools/launchers/launch-revolution-overdrive.ps1 -MapName traynor01.SC2Map -Faction Iron -ListenPort 5911 -NoCheats` produced launcher-owned SC2 PID `21212` with `-listen 127.0.0.1 -port 5911 -debug`; the binary SHA matched the locked profile and the listener belonged to PID 21212.
- `runtime`: `gsvm-controller.exe inject --pid 21212 ... --ack-debug-process` completed real SC2 `HELLO -> STATUS -> SHUTDOWN`; every response reported `hook_enabled=false`, `vm_hook=disabled`. Evidence: `artifacts/projects/generic-runtime-lab/stage02-inprocess-gsvm-agent/runtime/sc2-agent-handshake-port5911.json`.
- `runtime`: The same launcher window had zero new `*ScriptError*.txt` files after filtering from `2026-08-16T06:45:41.9121379Z`; PID 21212 was closed after evidence capture.

## Current boundary

This stage proves the native injection and loopback IPC foundation in both a fixture host and a real launcher-owned SC2 process. It does not prove a current-version Galaxy VM entrypoint, executable hook, hot reload, or in-game WYSIWYG behavior. The hook table remains disabled until the next stage independently verifies a current VM signature.
