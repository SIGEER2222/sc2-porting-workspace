# Stage 32 Log: Simulator Fidelity Matrix

## 2026-08-17 start

- `scope`: Opened as the primary Simulation-First workstream after Stage 31 native preflight remained blocked by the absent SC2 installation.
- `scope`: This stage is simulator-only. It may report deterministic support and fidelity boundaries, but it cannot claim native parity or mission completion.
- `static`: The roadmap table requires 27 explicit rows across Unit, Weapon, Movement, Combat, Economy, Production, Upgrade, Ability, Vision, Terrain, Pathing, Trigger, and Mission.
- `static`: Stage 30 already provides the native-evidence rule: missing runtime-labelled native observations remain `BLOCKED` rather than becoming matches.

## Planned implementation

- Build one project-local matrix generator from the existing m7 CatalogSnapshot, simulator contracts, and read-only simulator source provenance.
- Keep `UNSUPPORTED` rows visible, mark every row tested by a focused contract check, and set every native differential field to `BLOCKED` with one explicit reason.
- Generate the report under `artifacts/projects/cmre-porting/stage32-simulator-fidelity-matrix/`.

## Completion 2026-08-17

- `static`: Corrected an initial row-count misread: the supplied table has 27 rows because `HP/Shield` is one row. No synthetic feature was added merely to reach 28.
- `static`: Added `src/projects/cmre-porting/vibe/simulator_fidelity_matrix.py` and its focused Stage 32 tests. Each row records its domain, feature, static support probe, fidelity label, probe id, native-differential status, reason, and source provenance.
- `simulator`: `PYTHONPATH=src/projects/cmre-porting py -3.13 -m unittest discover -s src/projects/cmre-porting/stages/32-simulator-fidelity-matrix -p test_simulator_fidelity_matrix.py -v` passed: 4 tests in 5.391s.
- `simulator`: `PYTHONPATH=src/projects/cmre-porting py -3.13 -m pytest -q src/projects/cmre-porting/stages/28-simulator-baseline-hardening/test_simulator_baseline_hardening.py src/projects/cmre-porting/stages/29-normal-start-contract/test_normal_start_contract.py --tb=short` passed: 8 tests in 2.94s.
- `simulator`: Generated `artifacts/projects/cmre-porting/stage32-simulator-fidelity-matrix/fidelity-matrix-20260817.json`; it reports 27 rows, 26 supported, 11 `APPROXIMATE`, 15 `PARTIAL`, 1 `UNSUPPORTED`, and 27 `BLOCKED` native-differential entries.
- `static`: JSON parsing and artifact assertions passed: schema `simulator-fidelity-matrix.v1`, `status=PASS`, `native_claim=false`, 27 tested rows, explicit unsupported acceleration, and PASS catalog/normal-start baseline inputs.
- `blocked`: Native differential comparison remains unavailable because the Stage 31 compliant-SC2 prerequisite is still absent. This status is recorded per row and is not converted into a simulator or native PASS.
- `scope`: The verified next plan is `src/projects/cmre-porting/stages/33-world-state-observability-contract/plan.md`, which standardizes observable simulator world state before new behavior breadth.
