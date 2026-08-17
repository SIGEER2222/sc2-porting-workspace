# Stage 30 Log: Differential Validation Layer

## 2026-08-17

- `static`: Opened Stage 30 after Stage 29 produced a PASS `normal-start-contract.v1` simulator artifact.
- `scope`: Stage 30 targets `differential-report.v1`, comparing simulator and native observations for entity creation, resources, stats, build time, cost, abilities, upgrades, and trigger outputs.
- `scope`: Native mission completion remains out of scope until Stage 31; Stage 30 must keep simulator, native runtime, and inference evidence separate.

## Initial evidence paths

- `src/projects/cmre-porting/stages/30-differential-validation-layer/plan.md`
- `src/projects/cmre-porting/stages/30-differential-validation-layer/result.json`
- `src/projects/cmre-porting/stages/30-differential-validation-layer/issues.json`
- `artifacts/projects/cmre-porting/stage29-normal-start-contract/normal-start-contract-20260817.json`

## Implementation and verification

- `static`: Added `src/projects/cmre-porting/vibe/differential_validation.py` with `differential-observation.v1` input validation and `differential-report.v1` output. The comparator covers entity creation, resource changes, unit stats, build time, cost, ability execution, upgrade state, and trigger result.
- `static`: Native observations are accepted only with `source=native` and `evidence_type=runtime`. Inference, static, missing, unsupported, and blocked inputs cannot produce a PASS report; fidelity labels remain `EXACT`, `APPROXIMATE`, `PARTIAL`, `UNSUPPORTED`, or `BLOCKED`.
- `simulator`: Added `src/projects/cmre-porting/stages/30-differential-validation-layer/test_differential_validation.py`; 6 focused tests passed. They cover exact runtime match, value mismatch, inference rejection, native-missing blocking, Stage 29 fixture coverage, and artifact writing.
- `simulator`: Generated `artifacts/projects/cmre-porting/stage30-differential-validation-layer/differential-report-20260817.json`. Stage 29 supplied exact simulator observations for entity creation and resource changes; six other scopes remain blocked because the normal-start fixture did not exercise them.
- `blocked`: The generated report status is `BLOCKED` with counts `NATIVE_MISSING=2` and `BLOCKED=6`; `native_runtime_present=false` and `native_claim=false`. This is expected and is not promoted to a runtime PASS.
- `validation`: `py -3.13 -m py_compile ...` passed; focused unittest ran 6 tests in 2.594s; `json.tool` and explicit eight-scope/blocked-native assertions passed.
- `transition`: Stage 30 implementation is complete. Stage 31 owns the fresh launcher-owned native runtime window and mission-result evidence needed to fill the native side of the comparator.
