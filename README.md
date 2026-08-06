# SC2 Porting Workspace

Engineering workspace for porting, decomposing, adapting, and validating StarCraft II maps and mods.

This repository does not own the existing maps, mods, or external tools yet. It provides the
contracts used to discover original dependencies, identify initializers and triggers, design narrow
adapters, run static and dynamic analysis, and execute repeatable AI-assisted porting loops.

Start with:

```powershell
node tools/utils/workspace.mjs validate
node tools/utils/workspace.mjs status
```

## Validation environment

Stage validation commands require **Python 3.13** via `py -3.13`; the default `python` on this
machine is older and does not carry stage dependencies. Do not mix interpreters inside one
stage's validation commands.

```powershell
py -3.13 -m pip install pytest        # one-time bootstrap
py -3.13 -m pytest -q <test-file>     # canonical stage test invocation
```

Stage `result.json` files must match `docs/schemas/stage-result.schema.json`; the active
project is resolved from `activeProject` in `src/config/workspace.json`.

Project-local skills live under `tools/.codex/skills`. New development projects will be created under
`src/projects/<project-id>` only after their source assets and scope are registered.
