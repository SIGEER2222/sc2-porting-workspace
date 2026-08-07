# Stage 06 Plan: Map Closure Repair

## Objective

Restore the owned Revolution Overdrive map closure from the registered read-only source, make the approved launcher use a valid packed map for direct/WebUI launches, and rerun the native runtime MVP.

## Write scope

- `src/projects/revolution-overdrive-porting/project.json`
- `src/projects/revolution-overdrive-porting/stages/06-map-closure/**`
- `artifacts/projects/revolution-overdrive-porting/stage06-map-closure/**`
- `src/projects/revolution-overdrive-porting/packages/Maps/**`
- `tools/launchers/launch-revolution-overdrive.ps1`

## Steps

1. Compare all 31 read-only source map directories with the owned map package and record missing, changed, and extra files.
2. Copy only missing source files into the owned package; fail without copying if any common file hash differs.
3. Re-run the all-map closure audit and verify the representative `traynor01` MPQ with the existing pack/verify tools.
4. Update the approved launcher to pack the staged map through `tools/mpq/scripts/pack_mpq.py` before `-run`; record the packed artifact for API probes.
5. Run the launcher `-NoLaunch` staging path and the WebUI route regression.
6. Run one real SC2 API session with the packed `traynor01` map: CreateGame, JoinGame, RequestStep, Observation, raw P1 ownership, and `ActionChat("Iron")`.
7. Scan the same launch window for ScriptError files and compare runtime owners/alliances with the Stage 04 AI contract.

## Stop conditions

- Never modify `C:\Users\22448\Downloads\RevolutionOverdrive缝合版\RevolutionOverdrive缝合版`.
- Do not claim runtime success from MPQ readability, launcher readiness, or WebUI staging alone.
- If the complete owned map still cannot be opened, record the exact SC2 response and leave the stage blocked.

## Validation

- Full source/owned closure manifest for all 31 maps.
- `python tools/mpq/scripts/pack_mpq.py` and `verify_mpq.py` for `traynor01`.
- Approved launcher staging and packed direct-run path.
- `python -m unittest src/projects/revolution-overdrive-porting/stages/04-ai-ally/test_ai_ally_adapter.py -v`.
- `python -m unittest tools/cmre-webui/test_revolution_overdrive.py -v`.
- Native API runtime evidence plus same-window ScriptError verdict.
