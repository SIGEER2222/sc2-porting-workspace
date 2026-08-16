# Non-invasive VM Boundary Observation Recipe

This recipe is an observation contract for a fresh, launcher-owned SC2 debug
window. It does not patch code, set breakpoints, or enable the native VM hook.
The current agent can only prove injection and transport readiness; the VM
execution row remains `NOT_OBSERVED` until a current-version boundary is
independently verified.

## Window ownership

1. Start the approved launcher with a unique listen port and `-debug`.
2. Record the launcher evidence path, SC2 PID, listener owner, executable SHA,
   and a UTC start marker.
3. Reject the run if the listener belongs to another PID, the SHA differs from
   the locked profile, or the process was not created by the launcher.
4. Inject the release agent with the profile. Require `HELLO` and `STATUS` to
   report `hook_enabled=false`; do not pass a hook address in the profile.

## Three observation layers

| Layer | Observable | Required correlation | Current status |
| --- | --- | --- | --- |
| Script load | launcher map-load event plus a map-owned `runtime.ready` Bank record | run id and map hash | available through launcher/Bank evidence |
| Trigger dispatch | a normal map event writes `trace.trigger.<id>` and the agent records the same event window | run id, trigger id, frame | blocked until an event-source observer exists |
| VM execution | the agent records a VM boundary entry/return around that trigger, including bytecode/program id | run id, trigger id, frame, program id | `NOT_OBSERVED`; `vm_hook=disabled` |

The Bank record alone is not VM evidence: it proves only that Galaxy code
produced an observable side effect. A direct `function.invoke` request is API
validation and must be reported separately from automatic gameplay dispatch.

## Evidence sequence

1. Clear stale assertion, Bank, and ScriptError outputs under the run artifact
   directory. Keep the UTC marker for the same window.
2. Before `CreateGame`, seed the map-owned `GalaxyVibeTrace` Bank from
   `artifacts/projects/generic-runtime-lab/stage03-current-vm-signature-trace/runtime/galaxy-vibe-trace-bank-seed.xml`
   into the root and every existing numeric author directory under the local
   SC2 `Documents/StarCraft II/Banks` directory. Do not touch the unrelated
   `GalaxyVibe.SC2Bank` RPC channel.
3. Launch the map through the approved launcher and wait for its ready signal.
4. Capture the runtime listener and launcher JSON before injecting the agent.
5. Inject the agent and save raw `HELLO`, `STATUS`, and `SHUTDOWN` responses.
6. Exercise one map-owned trigger using a unique correlation id. Capture the
   raw event, frame, Bank value, and any agent trace record.
7. Scan only ScriptError files newer than the UTC marker. Any new file fails the
   window; process startup or a zero-error scan alone is not a VM pass.
8. Close the launcher-owned process and write a bundle that classifies each
   artifact as `static`, `runtime`, `blocked`, or `inference`.

## Direct dispatch gate

Use `BreakpointTraceDirect.SC2Map` before testing the delayed fixture when
source compilation or trigger dispatch is in doubt. Its `InitMap()` executes
`TriggerExecute(TriggerCreate("BreakpointTrace_Probe"), false, true)` directly,
so `startup`, `trace_before`, and `trace_after` in the isolated
`GalaxyVibeTrace` Bank prove the map-owned function ran. This is a runtime
source/dispatch check only; it does not prove automatic time-event dispatch or
the VM boundary. The direct probe intentionally includes `breakpoint;`, so a
`JoinGame`/`game_loop=0` result is expected while the debug observer is armed.
Record the direct run separately from the delayed behavior verdict.

Use `BreakpointTraceDirectControl.SC2Map` as the no-break control. It keeps the
same `InitMap` and Bank writes but removes only `breakpoint;`; a successful
`JoinGame` with an advancing `game_loop` confirms that a direct probe's paused
window is caused by the debug-break instruction rather than by source loading
or Bank persistence.

## Promotion gate

A profile may set `hook_enabled=true` only when two independent fresh windows
show the same current-version signature, the trigger-to-VM correlation is
complete, the process remains stable, and both windows have zero new
ScriptErrors. A string match, a guessed RVA, a single crash-free injection, or
the 2016 research snapshot is insufficient. Until then keep `hooks=[]` and
record `promoted_hooks=[]`.
