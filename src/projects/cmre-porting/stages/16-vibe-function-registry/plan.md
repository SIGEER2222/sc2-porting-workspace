# Stage 16 Plan: Explicit Vibe Function Registry

## Objective

Add a safe, typed function-level RPC surface on top of the existing operation
transport. The first registered function is the side-effect-free
`vibe.test.ping`, which must return a structured payload on the simulator,
Host, and Galaxy Kernel paths.

## Contract

- `function.invoke` is the only function-level operation.
- Every callable function is present in `tools/galaxy-vibe/kernel/function-registry.json`.
- Dispatch is an explicit function-id-to-handler mapping. No arbitrary Galaxy
  function names, reflection, `eval`, or `TriggerExecuteByName` are allowed.
- The wire form carries `function_id` and typed `arg_<name>` values. The Host
  API carries the same values as a nested typed `args` object.
- Unknown function IDs return `FUNCTION_NOT_FOUND`.
- Missing, unknown, or incorrectly typed arguments return `INVALID_ARGS`.
- `vibe.test.ping` accepts optional string `nonce` (max 64 characters) and
  returns `function_id`, `message=pong`, and the supplied `nonce`.

## Work Scope

1. Extend the request/response schemas and operation whitelist.
2. Add a shared Python registry validator used by Host and Simulator.
3. Add `function.invoke` to the deterministic SimulatorTransport.
4. Add `VibeHost.invoke_function` and make the REPL expose `invoke` only.
5. Add the explicit Galaxy handler. The project map mirrors the canonical
   Kernel; the standalone debug-mod keeps its existing MapCommand wrapper but
   shares the same explicit function handler.
6. Run static tests and simulator invocation tests before live validation.
7. Use the approved CMRE launcher to run a real `vibe.test.ping` request and
   capture the Bank response plus the same-window ScriptError verdict.

## Completion Gate

- Registry JSON, schemas, and whitelist are valid and mutually consistent.
- Existing kernel tests plus new registry tests pass.
- Simulator returns the expected ping payload and rejects unknown/invalid calls
  without side effects.
- Galaxy source and header pass static checks and the two mirrors are aligned.
- A real launcher/API run returns `OK` with `message=pong`, and there are no
  new ScriptErrors.
- `result.json`, `log.md`, and `issues.json` contain classified evidence and a
  concrete next-stage note.
