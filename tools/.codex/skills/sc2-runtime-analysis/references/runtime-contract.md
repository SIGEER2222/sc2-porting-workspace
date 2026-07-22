# Runtime Evidence Contract

Use one run directory:

```text
evidence/runtime/<run-id>/
  run.json
  events.jsonl
  process.json
  script-errors/
  screenshots/
  verdict.json
```

`run.json` identifies the composition and commands. `events.jsonl` preserves ordered raw events.
`verdict.json` maps acceptance criteria to evidence and must distinguish passed, failed, and not
observed.

Runtime observation is backend-neutral. A Neuro-compatible WebSocket is one transport option. Bank
watchers, game logs, replay analysis, or a purpose-built observer are valid when they provide equivalent
evidence.
