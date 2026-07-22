# SC2 Porting Workspace

Engineering workspace for porting, decomposing, adapting, and validating StarCraft II maps and mods.

This repository does not own the existing maps, mods, or external tools yet. It provides the
contracts used to discover original dependencies, identify initializers and triggers, design narrow
adapters, run static and dynamic analysis, and execute repeatable AI-assisted porting loops.

Start with:

```powershell
node tools/workspace.mjs validate
node tools/workspace.mjs status
```

Project-local skills live under `tools/.codex/skills`. New development projects will be created under
`src/projects/<project-id>` only after their source assets and scope are registered.
