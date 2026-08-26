# Stage 50 Log: Ares-Inspired Tactical Validation Layer

## 2026-08-18 implementation pass

- `static`: Reviewed `C:/Users/Sigeer/Downloads/sc2-simulator-implementation-plan-20260818.md` against the existing Stage50 roadmap and live `vibe` code. The plan's multi-seed, deterministic runner, A/B comparison, and Observation/Action separation requirements match the Stage50 direction.
- `static`: Confirmed write scope includes `src/projects/cmre-porting/vibe/**`, `src/projects/cmre-porting/stages/50-vm-debugger-expansion/**`, and Stage50 artifacts.
- `static`: Extended `src/projects/cmre-porting/vibe/consumers/tactical.py` instead of creating a parallel runner. Added `tactical_report.v1` fields, scenario identity hashing, seed-batch summaries, A/B compare rule, capability coverage, reliability flags, determinism health check, and Stage50 runner surfaces.
- `static`: Added `SimulatorSession.query_observation()` so strategy input crosses a session facade rather than constructing `Observation` directly at the policy boundary.
- `simulator`: Added `src/projects/cmre-porting/stages/50-vm-debugger-expansion/test_tactical_validation_layer.py`, covering `tactical_report.v1`, multi-seed batch identity, deterministic same-seed checks, and seed-batch sweep behavior.
- `simulator`: Generated Stage50 sample report artifacts:
  - `artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/stage50-tactical-report-v1.json`
  - `artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/stage50-tactical-report-v1.md`

## Verification

- `simulator`: `PYTHONPATH=src/projects/cmre-porting py -3.13 -m vibe.consumers.tactical` -> PASS; existing tactical selftest passed 16/16 checks.
- `simulator`: `py -3.13 -m unittest discover -s src/projects/cmre-porting/stages/50-vm-debugger-expansion -p test_tactical_validation_layer.py -v` -> PASS; 3 tests passed.
- `static`: `py -3.13 -m json.tool src/projects/cmre-porting/stages/50-vm-debugger-expansion/result.json` -> PASS.

## Remaining issue

- `static`: `STAGE50-STAT-SURFACE-001` remains open. Strategy input is now facade-bound, but per-run aggregate metrics still use the existing tactical consumer's direct simulator-state reads. This is acceptable for the Stage50 report-contract MVP, but should be moved behind session query helpers if Stage50 continues deeper into architecture enforcement.

- `static`: `py -3.13 -m json.tool artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/stage50-tactical-report-v1.json` -> PASS.

## WebUI Revolution Commander Route Fix - 2026-08-18

- `static`: `tools/cmre-webui/server.py` rejects `RevolutionOverdrive*` commander ids and `commanderPackage=revolution-overdrive` on non-Revolution maps before launcher spawn; `tools/cmre-webui/webui/app.js` mirrors the guard.
- `runtime`: Temporary WebUI smoke POST for `虚空降临.SC2Map` / `RevolutionOverdriveCoverts` returned HTTP 400, with `/api/status` reporting `launcherRunning=false`, `pid=null`; valid Revolution Overdrive dry-run remained routable.
- `static`: `CMRE_WEBUI_DRY_RUN=1 python -m pytest -q tools/cmre-webui/test_launch_async_contract.py tools/cmre-webui/test_revolution_overdrive.py` -> PASS, `43 passed`.

## Runtime VM Spot-Check - 2026-08-18

- `runtime`: User-requested current VM progress check captured in `artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/runtime-vm-current-check-20260818.json`.
- `runtime`: WebUI `127.0.0.1:8777` is alive, but `/api/status` reports `launcherRunning=false` and `pid=null`; TCP probes show `5896=false` and `5897=false`.
- `runtime`: `/api/vibe/status` reports `status=error` with no active current Vibe session; last candidate `repl_c9dc144c3fa8` ended as `INTERNAL_ERROR timeout` for request `33e8a4809297`.
- `runtime`: Bank signals show prior runtime init/bridge readiness (`runtime_listener_ready=1`, `bridge_heartbeat=12`) and a stale pending request, but `/api/vibe/event-log` count is `0` and `/api/vibe/rules` count is `0`.
- `static`: This spot-check does not change the Stage50 tactical simulator PASS or native/runtime claim boundary; it records that fresh VM RPC/gameplay-event claims are currently blocked by inactive session binding.

## dq-webui Recovery - 2026-08-19

- `runtime`: `dq-webui` supervisor reported exit code `1073807364`; pre-restart TCP probe showed `127.0.0.1:8777` closed while the separate `8767` WebUI process remained open.
- `runtime`: Restarted `dq-webui` through the supervisor with `py -3.13 tools/cmre-webui/server.py --host 127.0.0.1 --port 8777 --dou-ququ-map src/projects/test-arena/packages/Maps/地图调试和斗蛐蛐工具（完整功能版).SC2Map`; supervisor reported port `8777` ready.
- `runtime`: Smoke endpoints passed: `/api/status`, `/api/vibe/status`, `/api/maps`, `/api/factors`, and `/api/vibe/call-log?limit=5` all returned HTTP 200.
- `runtime`: Recovery artifact `artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/dq-webui-recovery-20260819.json` records WebUI recovered, `launcherRunning=false`, `vibe_status=disconnected`, and VM ports `5896/5897` still closed.
- `static`: This recovery only restores the WebUI control plane; it does not claim SC2 launcher readiness, VM RPC availability, or automatic gameplay event evidence.

## Offline SC2 Asset Reference Check - 2026-08-25

- `static`: Converted the read-only `reference/SC2plusSCBW/SC Evo Complete/SCEvo_Assets.SC2Mod/Base.SC2Assets/Assets/Units/Zerg/ZerglingSCBW/ZerglingSCBW.m3` with `node convert-m3.js <input.m3> <output.glb>` into `artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/sc2-model-reference/zergling-scbw-reference.glb`; conversion reported 16 animation clips.
- `static`: Blender 4.5.5 GLB import produced an Armature and actions including Stand, Walk, Attack, Burrow, and Unburrow. The clean working preview `zergling-scbw-reference-clean.blend` removes converter helper meshes and assigns Walk.
- `static`: A Blender frame-sampling check of Walk at frames 0, 24, and 48 found 111 F-Curves and maximum mesh-vertex deltas of `0.0520525` for both intervals. The visible clean action frame is `artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/sc2-model-reference/zergling-scbw-walk-frame-clean.png`.
- `static`: This is offline converter/Blender evidence only; it does not claim SC2 engine, Previewer, Data Editor, or in-game compatibility. The input is the locally available SCBW Zergling variant, not an asserted standard modern SC2 Zergling asset.

## Offline SC2 AI Asset Workflow Documentation - 2026-08-25

- `static`: Added `src/projects/cmre-porting/stages/50-vm-debugger-expansion/offline-sc2-ai-asset-authoring-workflow.md`, which records the workflow purpose, M3/M3A/DDS source-of-truth rule, distinct authoring and preview branches, AI mesh/texture contract, quality gates, current gaps, and the Zergling Round-Trip PoC acceptance criteria.
- `static`: Verified the document is nonempty, has no Git patch whitespace errors, and references existing local Zergling M3 and DDS source assets.
- `static`: The document explicitly keeps Blender/GLB/M3Studio outcomes separate from future SC2 Previewer, Actor, and in-game runtime evidence.

## Executable Offline SC2 Asset Workflow - 2026-08-25

- `static`: Reframed `offline-sc2-ai-asset-authoring-workflow.md` as the authoritative execution workflow: W0 template registration, W1 static baseline, W2 M3Studio authoring baseline, W3 texture preview, W4 AI mesh integration, W5 export/re-import, and W6 future SC2 runtime validation. A PASS only releases the current gate.
- `static`: Added the machine-readable template `asset-workflow/templates/zergling-scbw.template.json` and reusable `asset-workflow/run_static_template_baseline.py` runner. The runner records source/DDS SHA-256 values, runs M3-to-GLB conversion, and probes Stand/Walk/Attack in Blender.
- `static`: Executed W0/W1 for `zergling-scbw`; `artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/sc2-model-reference/workflow-runs/zergling-scbw-static-baseline.json` reports `status=PASS`, 44 bones, and mesh deformation across three samples for Stand, Walk, and Attack.
- `static`: W2 M3Studio authoring, W3 DDS preview mapping, and W5 M3 export/re-import remain `PENDING`; W6 remains `BLOCKED_NO_SC2`. These gates must not be inferred from the W0/W1 result.

- `static`: Repeated the W0/W1 runner. Source hashes and Stand/Walk/Attack semantic probes matched exactly; the binary GLB SHA-256 changed between runs, so the workflow records it as per-run provenance rather than treating GLB byte identity as determinism evidence.
- `static`: The runner scope and document W1 gate now use semantic action-probe repeatability as the deterministic contract.

## Offline Blender GUI Authoring and Preview - 2026-08-26

- `static`: Added `asset-workflow/run_gui_authoring.py` and the manifest `gui` output contract. The runner requires a non-background Blender process, registers M3Studio, imports the source M3, saves an untouched authoring Blend, maps declared DDS files to a separate preview material, renders action frames, and leaves an `Asset Workflow` sidebar for manual review.
- `static`: Started Blender 4.5.5 in graphical mode with the approved local M3Studio addon. The process emitted `GUI_ASSET_WORKFLOW_READY`; the report records `blenderBackground=false`, `windowCount=1`, and `sc2Integration=false`.
- `static`: `gui-authoring-report.json` reports `status=PASS`, Armature `boneCount=44`, `meshCount=6`, three required actions, three loaded DDS roles (Diffuse/Normal/Emissive), and nine rendered PNG frames for Stand/Walk/Attack.
- `static`: Manually reviewed Stand, Walk, and Attack midpoint renders. The model is visible, DDS coloration is present, and poses differ. This is offline Blender/M3Studio evidence only; no SC2, map, Mod, Previewer, Actor, or in-game process was launched.

## Offline M3 Material-Fidelity Correction - 2026-08-26

- `static`: Reproduced the visual mismatch: the prior GUI preview cleared every mesh material slot and assigned one fallback diffuse to all six meshes, while the imported M3 contains four material references. `batch-material-map.json` records the actual assignments: `Standard_8` for `Mesh`, `01 - Default` for `Mesh.001`, `HydraRemaster` for `Mesh.002`-`Mesh.004`, and `Standard_4` for `Mesh.005`.
- `static`: Updated `run_gui_authoring.py` to audit M3 material-layer declarations, preserve the untouched authoring Blend, resolve exact local layer filenames, build separate preview materials per M3 material reference, and assign them by each mesh's M3 batch pointer. The template now also registers the two locally available exact layer assets (`zergling_remastered_emissive.dds` and `Zergling_SCR_DS_Arms_diffuse.dds`).
- `static`: The corrected GUI run emitted `GUI_ASSET_WORKFLOW_READY`; `gui-authoring-report.json` records `blenderBackground=false`, four M3 layers, six mesh-batch assignments, direct-import geometry (44 bones, six meshes), nine Stand/Walk/Attack frames, and `sc2Integration=false`. Three declared channels resolve exactly locally; eleven declared body/remaster channels remain unavailable.
- `static`: Visual review of the corrected Stand, Walk, and Attack midpoint renders confirms the arms region now uses its own material instead of the body fallback, with balanced neutral lighting and readable normal detail. Remaining torso patchwork is attributed to unavailable `Zergling_SCR_DS_Diffuse.dds`, `Zergling_Remastered_Diff.dds`, `Zergling_Normal.dds`, and related M3 declarations; it is not evidence of rig or geometry loss.
- `static`: Focused verification passed: `python -m py_compile src/projects/cmre-porting/stages/50-vm-debugger-expansion/asset-workflow/run_gui_authoring.py`, `python -m json.tool src/projects/cmre-porting/stages/50-vm-debugger-expansion/asset-workflow/templates/zergling-scbw.template.json`, and `git diff --check` for the changed workflow files. No SC2 launcher was used; W6 remains blocked by the missing local SC2 installation.
- `static`: Re-ran W0/W1 after adding the two exact local M3 layer inputs; `run_static_template_baseline.py` returned `status=PASS`, preserved 44 bones and all Stand/Walk/Attack deformation probes, and recorded eight source DDS hashes plus the per-run GLB hash.
- `static`: Opened the saved `zergling-scbw-preview.blend` in Blender background mode and verified `preview-blend-verify.json`: six mesh objects retain the six expected per-M3 preview material names, `m3MaterialLayerCount=4`, and `preserved=true`.

## AI Mesh Input Preparation and Compression - 2026-08-26

- `static`: Audited the first AI-generated static GLB: it contains 594,109 vertices, 1,000,022 triangles, three 4096x4096 embedded PNG PBR channels, no skin, and no animation. A non-destructive W4-only preparation candidate reduced that mesh to 11,999 triangles and all texture channels to 2048x2048; Blender re-import preserved one mesh, one UV set, and Base Color/Metallic Roughness/Normal channel bindings. Evidence: `artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/ai-mesh-input/7445a6f209213b48bbcab9bf22c8c094/w4-candidate/`.
- `static`: Audited the user's lower-polygon replacement GLB: it already contains 50,000 triangles and 36,569 source vertices, but its three embedded 4096x4096 PNG PBR channels make the file 51,488,372 bytes. It remains an unrigged, unanimated static source.
- `static`: Created a texture-only, non-destructive lower-polygon candidate at `artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/ai-mesh-input/852191c4dad0ecc0b984c28fb848e7fa/compression-2k/zergling-ai-lowpoly-50k-2k.glb`. It retains the source mesh and UV topology, reduces all three PBR maps to 2048x2048, and reduces the GLB to 16,801,848 bytes (67.4% smaller). `compression-report.json` records the source/candidate size and retained 50,000-triangle topology.
- `static`: Fresh Blender re-import and render verification report `status=PASS`: one mesh, one UV layer, 50,000 triangles, and correctly typed 2048x2048 Base Color (sRGB), Metallic Roughness (Non-Color), and Normal Map (Non-Color) textures. Evidence: `reimport-validation.json` and `textured-preview.png` in the same candidate directory.
- `static`: These GLB preparation outcomes were the inputs to the later W4/W5 pass. The selected lower-poly candidate was subsequently bound and exported offline, while W4 visual fit remains review-required and W6 SC2 runtime validation remains blocked.

## Offline AI Mesh W4/W5 Round-Trip - 2026-08-26

- `static`: Selected the texture-only compressed 50,000-triangle AI GLB at `artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/ai-mesh-input/852191c4dad0ecc0b984c28fb848e7fa/compression-2k/zergling-ai-lowpoly-50k-2k.glb` for W4. The Blender/M3Studio runner produced `zergling-ai-w4-rigged.blend` from an untouched source authoring copy, aligned the mesh to `Ref_Origin`, transferred weights by `template-nearest-vertex-transfer`, and retained 44 template bones, 28 skin vertex groups, one UV layer, and Stand/Walk/Attack actions.
- `static`: W4 structural binding/export evidence is recorded in `ai-mesh-output/zergling-ai-50k-v5/w4-w5-export-report.json`. The report records `candidateVertices=36578`, `candidateTriangles=50000`, the 90-degree axis correction, and three rendered action midpoint previews. W4 is not promoted to PASS: `deform-bones-overlay.png` shows body/tail alignment gaps that require retargeting, proportion, or weight refinement.
- `static`: Exported `zergling-ai-sc2-candidate.m3` (2,019,426 bytes; SHA-256 `088b118cd6ad1b88a8fc9f28576d2ecdddc92a81a23394938601a7f6f30220e3`) and opened it in a fresh M3Studio/Blender scene. `w5-reimport-report.json` is `status=PASS` with 44 bones, one mesh, 50,000 triangles, one UV layer, and Stand/Walk/Attack actions; fresh re-import is structural evidence only and does not override the W4 visual gate.
- `static`: W5 re-import midpoint previews are present under `ai-mesh-output/zergling-ai-50k-v5/w5-reimport-previews/` for Stand, Walk, and Attack. These images demonstrate offline materialized geometry and pose output, not SC2 engine acceptance.
- `static`: Focused checks passed after the runner repair: `py -3.13 -m py_compile src/projects/cmre-porting/stages/50-vm-debugger-expansion/asset-workflow/run_ai_mesh_m3_roundtrip.py`, `py -3.13 -m json.tool src/projects/cmre-porting/stages/50-vm-debugger-expansion/result.json`, `py -3.13 -m json.tool src/projects/cmre-porting/stages/50-vm-debugger-expansion/issues.json`, and `git diff --check` for the workflow/stage files. No SC2 launcher was used; W6 remains `BLOCKED_NO_SC2`.

## W4 Visual-Fit Correction Probes - 2026-08-26

- `static`: Re-ran the W4 deformation audit on the selected v5 candidate. With the existing template-nearest-vertex transfer, Stand/Walk/Attack still produced non-zero mesh motion (`maxVertexDelta=0.3166/0.6987/0.5424`), so the armature actions are driving the mesh; the remaining issue is rest-pose body/tail alignment rather than an absent action binding.
- `static`: Tested bounded rest-bone retargeting and rendered `rest-retargeted-bones-overlay.png`. The altered bones detached from the candidate's intended anatomy and were not promoted.
- `static`: Tested skin-group affine fitting with `test-w4-group-fit-v21`. The resulting Stand/Walk/Attack previews (`stand-groupfit-test.png`, `walk-groupfit-test.png`, and `attack-groupfit-test.png`) introduced visibly unacceptable long-bar stretching and local deformation; the approach was rejected.
- `static`: Tested a conservative BVH/landmark surface-fit variant in a separate v6 output. Its report and textured Stand/Walk/Attack previews are retained as rejected experiment evidence; the fit caused local geometry collapse rather than a reliable mesh-to-template correction.
- `static`: Removed the rejected surface-fit option from `asset-workflow/run_ai_mesh_m3_roundtrip.py`; the runner is back to the conservative v5 alignment and weight-transfer path. `py -3.13 -m py_compile` and `git diff --check` passed after the revert, and `result.json`/`issues.json` parse successfully.
- `static`: W4 remains `REVIEW_REQUIRED`. The next valid operation is manual retopology/Weight Paint against the template or regeneration of an AI mesh constrained to the template proportions and limb/tail landmarks. No SC2 runtime, Previewer, Actor, or in-game evidence was created; W6 remains `BLOCKED_NO_SC2`.
- `static`: Ran an isolated nearest-deform-bone-segment softmax weighting probe (`sigma=0.055`, four nearest segments, 44 deform groups) against the same aligned 50,000-triangle mesh. The report is `artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/ai-mesh-output/zergling-ai-50k-v7/segment-weight-report.json` and all three action renders completed.
- `static`: Manual review of the v7 Stand/Walk/Attack renders shows worse rigid-looking bars and stretched limb/tail sections than the selected v5 transfer. The segment method is rejected and was not applied to the production runner or candidate M3.

## AI Binding Reference Package and Multi-Mode Audit - 2026-08-26

- `static`: Added `asset-workflow/references/zergling-scbw-ai-reference.json` as the machine-readable learning contract. It defines the source M3/Blend/GLB inputs, 44-bone hierarchy evidence, 28 canonical deform groups, 15 non-skin groups, attachment/hit-test preservation, the template-nearest-vertex transfer policy, required Stand/Walk/Attack actions, PBR output expectations, negative binding examples, and the offline-only evidence boundary.
- `static`: Added `asset-workflow/run_binding_reference_audit.py`. It opens a saved authoring Blend, imports one static AI GLB, builds isolated chest-rigid, pelvis-rigid, automatic, envelope, and template-nearest-vertex-transfer candidates, samples action start/middle/end frames, and writes `ai-mesh-output/zergling-ai-50k-v5/binding-reference-audit.json`. It never edits the source M3/Blend, exports M3, launches SC2, or edits a map/mod.
- `static`: Ran Blender 4.5.5 with the selected 50,000-triangle GLB. The command completed with `BINDING_REFERENCE_AUDIT_READY`; the report contains 44 template bones with names, parent links, and local coordinates, resolves `Armature_Stand 01_full`, `Armature_Walk_full`, and `Armature_Attack 01_full`, and samples frames Stand 0/50/100, Walk 0/30/60, and Attack 0/8/16.
- `static`: Final candidate census is chest-rigid 36,578 assigned/0 unassigned, pelvis-rigid 36,578/0, automatic 0/36,578, envelope 33,191/3,387, and template-nearest-vertex-transfer 36,578/0. The selected template-transfer candidate has 28 deform groups and is retained for manual visual review; rigid, automatic, and envelope modes are not production bindings.
- `static`: The Blender run emitted the expected heat-weight warning while evaluating the Envelope candidate. This warning is retained as a known negative-case diagnostic; it did not prevent report generation. Python syntax, JSON parsing, manifest/report group equality, nine reference PNG paths, and scoped `git diff --check` were verified after the run.
- `static`: Stage50 remains incomplete for W4 visual fit and W6 runtime. The deform-bone overlay still shows body/tail alignment gaps, and no local SC2 installation exists; therefore no SC2 Previewer, Actor, map, mod, or in-game claim is made.
