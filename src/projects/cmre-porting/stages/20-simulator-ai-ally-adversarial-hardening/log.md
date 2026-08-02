# Stage 20 Log

## Scope

Stage 20 hardened the deterministic simulator clearance audit surface after
Stage 19 multi-seed success. The objective predicate and mission-owned startup
semantics were preserved. SC2 was intentionally not launched in this stage.

## Implementation evidence

- `simulator`: `src/projects/cmre-porting/vibe/run_dead_of_night.py` now emits
  `event_summary` with event occurrence counts and payload totals, plus
  `target_allocation_summary` with push-unit filtering, dispatch cycles,
  allocations, stale-target reallocations, unique targets, and peak active
  assignments.
- `simulator`: Controlled push-unit loss is counted only for the configured
  push army; native starting units are not relabeled as push units.
- `simulator`: Real reports for seeds 42, 7, and 99 all reached
  `all_objectives_success` with `0/344` live enemy structures. The runs
  recorded 36 infected spawns, 25-27 daytime infected removals, 297-317
  building reinforcements, and nonzero target reallocations.

## Verification

- `simulator`: `python -m pytest -q src/projects/cmre-porting/stages/20-simulator-ai-ally-adversarial-hardening/test_adversarial_hardening.py src/projects/cmre-porting/stages/19-simulator-ai-ally-clearance/test_simulator_ai_ally_clearance.py` -> `9 passed, 3 subtests passed`.
- `static`: Stage 18/task-loop, registry, launcher, live-adapter regression -> `60 passed`.
- `static`: `python -m py_compile src/projects/cmre-porting/vibe/run_dead_of_night.py src/projects/cmre-porting/stages/20-simulator-ai-ally-adversarial-hardening/test_adversarial_hardening.py src/projects/cmre-porting/stages/19-simulator-ai-ally-clearance/test_simulator_ai_ally_clearance.py` -> pass.
- `static`: `powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/run-all-validation.ps1` -> `52/52` checks passed, zero warnings.

## Evidence paths

- `artifacts/projects/cmre-porting/stage20-simulator-ai-ally-adversarial-hardening/clear-seed-42.json`
- `artifacts/projects/cmre-porting/stage20-simulator-ai-ally-adversarial-hardening/clear-seed-7.json`
- `artifacts/projects/cmre-porting/stage20-simulator-ai-ally-adversarial-hardening/clear-seed-99.json`
- `src/projects/cmre-porting/stages/20-simulator-ai-ally-adversarial-hardening/test_adversarial_hardening.py`

## Handoff

Stage 20 is simulator-only. The next stage must validate the same native-start
and typed Vibe action boundary through the approved SC2 launcher before making
any runtime claim about structure clearance.
