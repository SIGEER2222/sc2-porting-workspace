# Stage 20 Log

## Scope opened

Stage 20 starts adversarial hardening on the pure deterministic simulator
controller after the Stage 19 multi-seed clearance baseline. SC2 remains out
of scope. Existing maps, mods, external repositories, and parallel untracked
work remain untouched.

## Verified so far

- `simulator`: `python -m pytest -q src/projects/cmre-porting/stages/20-simulator-ai-ally-adversarial-hardening/test_adversarial_hardening.py` -> 3 passed in 0.33s.
- `simulator`: The focused tests verify stale-target reallocation counts, dead push-unit filtering, and separate event occurrence counts from event payload totals.
- `static`: `python -m py_compile src/projects/cmre-porting/vibe/run_dead_of_night.py src/projects/cmre-porting/stages/20-simulator-ai-ally-adversarial-hardening/test_adversarial_hardening.py` -> pass.
- `static`: `git diff --check` -> pass.
- `simulator`: Stage 19 seed 42/7/99 reports remain the real-map clearance baseline; they were generated before the audit-only fields were finalized.

## Open work

Rerun the three real-map seeds after the audit fields settle, inspect
`event_summary` and `target_allocation_summary`, then either close the stage or
record a reproducible regression. Do not promote the focused synthetic result
to a fresh real-map claim.
