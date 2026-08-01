# Stage 18 Plan: Vibe Task Execution Loop

## Objective

Turn the typed `function.invoke` surface into a reusable Vibe workflow that
can execute a declarative task as an observe -> invoke -> assert loop. The
same task identity and expected state predicates must run through the
deterministic simulator first and the approved SC2 runtime afterward.

## Contract

- A task scenario declares ordered observations, registered function calls,
  response predicates, and bounded retry/timeout policy.
- Every side effect remains an explicit function id from
  `tools/galaxy-vibe/kernel/function-registry.json`; no reflection, `eval`,
  arbitrary Galaxy names, or free-form command execution is allowed.
- Simulator, Host, and live runtime use the same normalized task/scenario
  representation and produce correlated request, response, assertion, and
  state-version traces.
- A failed response, timeout, stale state version, or assertion stops the task
  with a structured failure; it must not be reported as a successful loop.
- The runner must support a deterministic callback/planner boundary so a
  future Vibe model can choose a registered function without coupling model
  output to Galaxy symbols.

## Work Scope

1. Add the task-loop scenario schema and parser under the project-owned Vibe
   tooling, reusing the existing manifest identity and registry validator.
2. Implement simulator execution with observe, invoke, assert, bounded retry,
   and trace emission. Add invalid/stale/timeout cases.
3. Implement the Host runner against BankPoll with frame advancement and
   request/response correlation; preserve the current function API.
4. Add a small Dead of Night scenario that sets resources, spawns units,
   observes count, kills one unit, and asserts the final count through the
   generic runner rather than hand-written request sequencing.
5. Run simulator and static validation, then use the compliant launcher to
   verify the same scenario in a fresh packed-map runtime window.

## Completion Gate

- Scenario schema, registry, and protocol validation pass.
- Simulator tests cover success, invalid function, failed predicate, stale
  response, timeout, and retry behavior.
- Host tests prove non-realtime frame advancement and exact request/response
  correlation for a multi-step task.
- A real packed-map run executes the same scenario and records all loop steps,
  state versions, Bank responses, and final assertions.
- The same-window ScriptError gate is clean and the evidence bundle contains
  the manifest, scenario, simulator result, runtime trace, assertions, Bank,
  launcher output, and combined verdict.
- `result.json`, `log.md`, `issues.json`, and the next-stage plan are updated
  only after the current stage is verified.
