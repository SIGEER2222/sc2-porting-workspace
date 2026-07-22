---
name: sc2-ai-development-loop
description: Execute staged AI-assisted SC2 map/mod development with bounded plans, logs, write scopes, static analysis, adapter design, implementation, static validation, runtime validation, and acceptance handoffs. Use for multi-stage porting, compatibility work, commander integration, map adaptation, or autonomous iteration that must remain auditable and avoid repository noise.
---

# SC2 AI Development Loop

Advance one verified stage at a time.

## Stage protocol

1. Read `AGENTS.md`, `src/config/workspace.json`, the project manifest, current plan, log, result, and issues.
2. Confirm the stage objective, inputs, write scope, outputs, validation, and stop conditions.
3. Load only the Skills required by the stage.
4. Execute bounded work. Do not absorb unrelated findings.
5. Validate the smallest claim first, then broader composition behavior.
6. Update the stage log continuously with evidence and failures.
7. Write the machine-readable result and unresolved issues.
8. Create the next stage plan only when the current result is verified.

## Loop routing

- Discovery or dependency uncertainty: use `$sc2-static-analysis`.
- Ownership or compatibility uncertainty: use `$sc2-adapter-design`.
- Runtime behavior or acceptance: use `$sc2-runtime-analysis`.
- Implementation: follow the active write scope and existing package patterns.

## Failure handling

- Static failure: repair the model or implementation before runtime testing.
- Runtime failure: preserve raw evidence, classify static mismatch versus runtime-only behavior, and
  create a narrower retry stage.
- Scope expansion: record an issue and stop; do not silently widen write scope.
- Missing tool or source: mark blocked with the missing registered ID and expected capability.

## Noise control

- No speculative utilities, duplicate manifests, temporary docs, or unregistered scripts.
- No generated content outside `artifacts/` and stage evidence.
- No stage closes without changed paths, evidence, commands, and remaining risks.
- Delete failed generated drafts before handoff; preserve only evidence needed to explain the failure.

Read [stage-protocol.md](references/stage-protocol.md) for file contracts.
