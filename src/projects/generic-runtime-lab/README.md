# Generic Runtime Lab

`RuntimeLab.SC2Map` is an isolated SC2 verification map for reusable runtime
components. It is intentionally not a mission, commander, or map adapter.

The build combines three current inputs without forking them:

- `tools/galaxy-vibe/kernel`: runtime VM and Bank RPC transport.
- `src/lib/scripts/cmlib`: reusable Galaxy helper library and self-test.
- `runtime/galaxy`: map-owned dispatch and tactical-arena fixture.

Build the packed map with:

```text
python src/projects/generic-runtime-lab/scripts/build_runtime_lab.py
```

The output is written under
`artifacts/projects/generic-runtime-lab/stage01-foundation/maps/RuntimeLab.SC2Map`.

The supplied "地图调试和斗蛐蛐工具" map is retained as a read-only UI reference. It
depends on `WarClassicSystem.SC2Mod`, which is not installed on this machine, so it
is not the runtime baseline for this project.
