# Stage File Contract

`plan.md` defines future work and may not claim results.

`log.md` records chronological execution, evidence, changed paths, failures, and handoff facts.

`result.json` follows `docs/schemas/stage-result.schema.json` and is the machine-readable gate for the
next stage.

`issues.json` contains unresolved problems. Each issue should include an ID, summary, evidence,
impact, and suggested next action.

The next stage may rely only on verified claims in `result.json` and evidence referenced by the log.
It must not inherit informal assumptions from conversation history.
