# Stage 01 Plan: Isolated Runtime Lab Foundation

## Objective

Create a packed SC2 map that verifies the runtime VM, CMLib, and a controlled
two-player tactical arena without loading a CMRE mission or commander package.

## Inputs

- `src/lib/_testmap_src`: minimal map skeleton.
- `tools/galaxy-vibe/kernel`: runtime VM sources.
- `src/lib/scripts/cmlib` and `src/lib/selftest/cmlib_selftest.galaxy`: generic library and established runtime self-test.
- Supplied map-debug/battle map: read-only UI reference only. Its `WarClassicSystem.SC2Mod` dependency is unavailable locally.

## Write Scope

- `src/config/workspace.json`
- `src/projects/generic-runtime-lab/**`
- `artifacts/projects/generic-runtime-lab/**`

## Tasks

1. Build the map from the minimal map skeleton and current VM/CMLib sources.
2. Add a map-owned `function.invoke` adapter that exercises CMLib integer clamping.
3. Add a delayed Marine-versus-Zergling arena and write readiness into the VM Bank.
4. Pack the map with the existing StormLib packer.
5. Run static source tests, the VM probe, and the isolated CMLib control-map runtime self-test.

## Outputs

- `artifacts/projects/generic-runtime-lab/stage01-foundation/maps/RuntimeLab.SC2Map`
- `artifacts/projects/generic-runtime-lab/stage01-foundation/maps/build-report.json`
- Stage evidence quartet.

## Validation

```text
python -m pytest -q src/projects/generic-runtime-lab/tests
python src/projects/generic-runtime-lab/scripts/build_runtime_lab.py
node tools/analysis/galaxy-lint.mjs artifacts/projects/generic-runtime-lab/stage01-foundation/build/RuntimeLab.SC2Map/MapScript.galaxy --format text
python tools/galaxy-vibe/tier100_live_probe.py --port <exclusive-api-port> --map artifacts/projects/generic-runtime-lab/stage01-foundation/maps/RuntimeLab.SC2Map --tag runtime-lab-preseeded --out-dir artifacts/projects/generic-runtime-lab/stage01-foundation/runtime
python src/lib/cmlib_runtime_test.py artifacts/projects/generic-runtime-lab/stage01-foundation/maps/CMLibControl.SC2Map
```

The live paths require an exclusive SC2 API plus GalaxyVibe Bank lease, launcher/API
evidence, and a same-window ScriptError verdict. Before the probe, archive any existing
Bank and pre-seed a no-history `GalaxyVibe` Bank containing only `preload_marker`; do
not pass `--fresh-bank`, because it removes that required seed. A launcher start alone
is not a pass.

`RuntimeLab.SC2Map` exercises CMLib through its map-local `function.invoke` adapter.
The full CMLib self-test runs in `CMLibControl.SC2Map`: the arena reference map contains
debug-map state that makes broad unit/order checks non-deterministic and would otherwise
flood the tactical fixture with diagnostic units.
