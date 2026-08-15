# Stage 27 Plan: 斗蛐蛐 Behavior Plugin

## Objective

Add an opt-in, map-scoped runtime development plugin. The live Galaxy VM/RPC
module is the primary implementation and the Python VM is its deterministic
contract surface. A later static Galaxy/Catalog overlay may固化 the behavior,
but it is not required for the runtime development milestone.

## Behavior contract

- Reaver attack: configurable chance to spawn one Zealot.
- Vulture: base three mines plus two storage; refill charges for 50 minerals; death leaves three SpiderMines.
- Infested Banshee: every ten game seconds, spend 20 energy to spawn one Marine.
- Brood Lord attack: configurable chance to spawn one Baneling.
- Hydralisk kill: heal the killer by 25, capped at max life.
- Kerrigan kill: spawn two KerriganInfestBroodling units.

Defaults are deliberately configuration-backed so the runtime VM and live Galaxy
module can be tuned without changing the event API. CMRE catalog IDs are used explicitly:
`K5Kerrigan` is the Kerrigan hero and `InfestedBanshee` is the infected Banshee.
The runtime feature is disabled unless the launcher receives
`-EnableDouQuquRuntime`. `-EnableDouQuquBehavior` remains the separate opt-in
for the later static event/Catalog patch.

## Runtime-first contract

- `LibDouQuquRuntime.galaxy` registers only explicit `function.invoke douququ.*`
  calls; it does not register map event hooks and does not modify Catalog data.
- The WebUI/demo can invoke, observe, and repeat the rules in the current game
  without rebuilding the source map. The staged map is an isolated runtime copy.
- Death mines use the real `SpiderMineBurrowed` catalog state. The RPC returns
  three unit tags and `douququ.snapshot` counts both mine catalog states.
- The static behavior/Catalog overlay is deferred until the runtime contract is
  intentionally固化 in a later stage.

## Verification

```text
python -m pytest -q src/projects/cmre-porting/stages/27-dou-ququ-behavior-plugin/test_dou_ququ_behavior.py
python -m py_compile src/projects/cmre-porting/vibe/dou_ququ_behavior.py
python -m pytest -q tools/launchers/tests/test_launch_cmre_alenger_static.py
```

Live verification uses the approved CMRE launcher on the user-provided 斗蛐蛐 map,
with the feature switch enabled, and requires API readiness, runtime heartbeat,
eight event assertions, and a same-window ScriptError gate. That map is a standalone
Galaxy-only test map without a `Triggers` file, so its Stage 27 contract explicitly
allows that missing optional source and does not require the CMRE `Starting Game Q`
trigger; the launcher default remains strict for Stage 26 CMRE contracts.

## Write scope

Stage 27 directory, `tools/cmre-webui/**`,
`src/projects/cmre-porting/vibe/dou_ququ_behavior.py`,
`src/projects/cmre-porting/vibe/dou_ququ_behavior.json`, the CMRE launcher and
on-demand overlay, the two Galaxy overlay files, and stage artifacts.
