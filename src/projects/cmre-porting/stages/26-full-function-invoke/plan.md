# Stage 26 Plan: Full Function Invoke Expansion

## Objective

Expand the bounded Debug VM `function.invoke` surface from the 20 hand-written
typed adapters to every function declaration in the reproducible owned-package
catalog, through compile-time generated typed adapters plus a Galaxy-side
handle registry. No runtime reflection is introduced.

## Policy decision record

- Stage 25 catalog policy `inventory_only_functions_are_not_runtime_callable`
  is overturned for the owned-package scope: inventory-only declarations become
  callable through generated typed adapters.
- `arbitrary_reflection: false` remains true. Dispatch is a statically
  generated integer dispatch table; function IDs are assigned by the generator
  and recorded in `invoke-plan.json`.
- Historical declaration parity remains an open reconciliation item: the current
  clean scan contains 35,314 declarations (22,780 owned-package declarations
  plus 12,534 CMRE-dev declarations) versus the historical 35,404 baseline.
  CMRE-dev contributes zero unique signatures beyond the owned source. Stage 26
  therefore consumes the reproducible 22,780 owned declarations and emits
  11,676 callable adapters with 155 explicit exclusions; 603 funcref candidates
  remain after excluding uncallable and MapScript-local targets.

## Scope

1. Generator `generate_invoke_adapters.py` deduplicates the catalog by
   signature, assigns integer function IDs, classifies every parameter and
   return type, and emits:
   - `artifacts/projects/cmre-porting/stage26-full-function-invoke/invoke-plan.json`
   - rewritten `tools/galaxy-vibe/kernel/function-registry.json` (hand-written
     20 entries preserved, generated entries marked `generated: true` and
     `debug_only: true`)
   - Galaxy shards under `tools/galaxy-vibe/kernel/generated/` plus
     `LibVibeInvokeDispatch.galaxy`.
2. Type marshalling classes:
   - basic `int/fixed/bool/string/text`: JSON encode/decode via existing
     kernel Args helpers.
   - handle types (`unitgroup`, `point`, `region`, `playergroup`, `trigger`,
     `bank`, `timer`, `actor`, `wave`, `wavetarget`, `waveinfo`, `aifilter`,
     `marker`, `revealer`, `soundlink`, `order`, `abilcmd`, `color`,
     `datetime`, `unitfilter`, `doodad`): `LibVibeHandles.galaxy` registry
     tables; `unit` keeps engine tags; `point` accepts `{x,y}` construction;
     `color` accepts `R,G,B`.
   - funcref parameters: per-adapter static lookup generated from the catalog;
     unknown values return `FUNCREF_UNKNOWN`.
   - structref parameters: registry entries only obtainable from other call
     returns; unknown IDs return `HANDLE_NOT_FOUND`.
3. Kernel `function.invoke` accepts integer-style generated IDs routed to the
   generated dispatch; legacy string IDs keep the 20 hand-written handlers.
4. Overlay copies the kernel file list including `LibVibeHandles.galaxy` and
   `generated/*.galaxy`, and injects their includes into the staged MapScript.
5. Host-side validation (debug_vm/vibe_host) switches to the full registry;
   every generated entry is debug-only; strategy rejection unchanged.
6. Whitelist gains `handle.drop`, `handle.clear`, `handle.query`.

## Verification commands

```text
node src/projects/cmre-porting/stages/25-ai-ally-capability-completion/discover_function_catalog.mjs --out artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/discovery/function-catalog.json --source cmre-owned-project=src/projects/cmre-porting/packages --source vibe-kernel=tools/galaxy-vibe/kernel
python -m pytest -q src/projects/cmre-porting/stages/26-full-function-invoke/test_generate_invoke_adapters.py
python -m pytest -q src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_debug_vm.py tools/galaxy-vibe/tests/test_kernel.py
powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/run-all-validation.ps1
```

Runtime verification uses the approved `tools/launchers/launch-cmre-alenger.ps1`
launcher with the staged Dead of Night map: type-family sample probes, a
bounded read-only census of the safe subset, and the same-window ScriptError
gate. Exact artifact paths are recorded in `log.md` as evidence accrues.

## Risks and mitigations

- Galaxy compile time/size at ~120k generated lines is unknown: staged rollout
  limits (100, 1000, full) with recorded compile/package evidence; increase
  shard granularity or trim by kind if limits are hit.
- Same-name cross-library collisions with identical signatures cannot be
  disambiguated at link time: mark them `AMBIGUOUS` in the plan and exclude
  with truthful accounting.
- Full census can mutate mission state: default census is the read-only safe
  subset; mutating families are sampled only.

## Write scope

See `project.json` writeScope additions for stage 26: stage directory,
`tools/galaxy-vibe/kernel/**` including `generated/`, debug-mod and Dead of
Night kernel copies, overlay library and tests, `vibe/debug_vm.py`,
`tools/galaxy-vibe/host/vibe_host.py`, and stage 26 artifacts.
