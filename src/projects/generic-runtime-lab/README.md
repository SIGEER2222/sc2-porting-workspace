# Generic Runtime Lab

`RuntimeLab.SC2Map` is an isolated SC2 verification map for reusable runtime
components. It is intentionally not a mission, commander, or map adapter.

The build combines four current inputs without forking them:

- `src/projects/test-arena/.../地图调试和斗蛐蛐工具（完整功能版).SC2Map`: the
  read-only arena/debug-map skeleton used as the runtime-compatible base.
- `tools/galaxy-vibe/kernel`: runtime VM and Bank RPC transport.
- `src/lib/scripts/cmlib`: reusable Galaxy helper library and self-test.
- `runtime/galaxy`: map-owned dispatch and tactical-arena fixture.

Build the packed map with:

```text
python src/projects/generic-runtime-lab/scripts/build_runtime_lab.py
```

The output is written under
`artifacts/projects/generic-runtime-lab/stage01-foundation/maps/RuntimeLab.SC2Map`.

The builder also supports isolated controls for diagnosis:

```text
python src/projects/generic-runtime-lab/scripts/build_runtime_lab.py --cmlib-control
python src/projects/generic-runtime-lab/scripts/build_runtime_lab.py --kernel-control
python src/projects/generic-runtime-lab/scripts/build_runtime_lab.py --kernel-cmlib-control
python src/projects/generic-runtime-lab/scripts/build_runtime_lab.py --kernel-control-no-triggers
python src/projects/generic-runtime-lab/scripts/build_runtime_lab.py --arena-kernel-control
```

`CMLibControl.SC2Map` exercises only the current CMLib self-test; `KernelControl.SC2Map`
exercises only the current Runtime VM and Bank registration path, with a map-owned
delayed Ghost and `GalaxyVibe` readiness marker to distinguish map compilation from
Kernel registration; `KernelCMLibControl.SC2Map` combines those two inputs without
RuntimeLab fixtures; and `ArenaKernelControl.SC2Map` verifies the arena skeleton with
the current Kernel while removing the missing `WarClassicSystem.SC2Mod` dependency in
the generated artifact.
