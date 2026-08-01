# Stage 19 Log

## Scope

Stage 19 verified the pure deterministic simulator AI ally clearance lane. SC2
was intentionally not launched. Registered maps, mods, external repositories,
and the parallel untracked `test_simulator_clearance.py` file were left
untouched.

## Simulator evidence

- `simulator`: `python -m vibe.run_dead_of_night --mvp-fast --clear-enemy-structures --seed 42 --output stages/19-simulator-ai-ally-clearance/simulator-seed-42.json` reached `all_objectives_success` at loop 1882 with `0/344` enemy structures, 36 infected spawns, 27 daytime removals, 306 building reinforcements, and 2754/2754 successful push commands.
- `simulator`: The same command with seed 7 reached `all_objectives_success` at loop 1930 with `0/344` structures, 36 infected spawns, 27 daytime removals, 297 building reinforcements, and 2750/2750 successful push commands.
- `simulator`: The same command with seed 99 reached `all_objectives_success` at loop 1945 with `0/344` structures, 36 infected spawns, 25 daytime removals, 317 building reinforcements, and 2898/2898 successful push commands.
- `simulator`: The original 90-second seed 7 probe stopped inconclusively at loop 1784 with two structures remaining. The clear probe budget was raised to 120 seconds; the rerun passed without changing the objective predicate or removing buildings.

## Focused regression

- `simulator`: `python -m pytest -q src/projects/cmre-porting/stages/19-simulator-ai-ally-clearance/test_simulator_ai_ally_clearance.py` -> 5 passed in 0.43s.
- `simulator`: The focused cases cover night infection, daytime cleanup, building reinforcement on damage, stale target reallocation, dead push-unit filtering, wall-clock exhaustion, and deterministic wave seeding.
- `static`: The combined stage 18/19, kernel, launcher, and live adapter regression command -> 65 passed.
- `static`: `python -m py_compile src/projects/cmre-porting/vibe/run_dead_of_night.py src/projects/cmre-porting/stages/19-simulator-ai-ally-clearance/test_simulator_ai_ally_clearance.py` -> pass.
- `static`: `git diff --check` -> pass.
- `static`: `powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/run-all-validation.ps1` -> 52/52 checks passed, 0 warnings.

## Changed paths

- `src/projects/cmre-porting/vibe/run_dead_of_night.py`
- `src/projects/cmre-porting/stages/19-simulator-ai-ally-clearance/test_simulator_ai_ally_clearance.py`
- `src/projects/cmre-porting/stages/19-simulator-ai-ally-clearance/simulator-seed-{42,7,99}.json`
- `src/projects/cmre-porting/stages/19-simulator-ai-ally-clearance/{result,log,issues}.json`
- `src/projects/cmre-porting/project.json`
- `src/projects/cmre-porting/stages/20-simulator-ai-ally-adversarial-hardening/plan.md`

## Handoff

Stage 19 is PASS. The active project now points to
`20-simulator-ai-ally-adversarial-hardening`; its plan is written only after
the current simulator result passed.
