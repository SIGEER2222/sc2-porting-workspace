# Stage 12 Handoff

Stage 12 is complete and should be treated as the Vibe workflow contract milestone.

## What exists now

- src/projects/cmre-porting/vibe/task_manifest.py
  - direct CLI
  - vibe.ps1 manifest integration
  - compact simulator smoke
- Stage 12 artifacts:
  - manifest.json
  - scenario.json
  - regions.json
  - task.simulator.json
  - task.sc2-stub.json
  - task.live.json
  - runtime-recipe.json
  - scenario.vtest
  - simulator-smoke-result.json
- run-all-validation.ps1 covers the new manifest generator.
- workflow_status.py includes vibe.task_manifest.

## Key evidence

- vibe.ps1 manifest -RunId stage12-manifest: PASS
- vibe.ps1 validate -RunId stage12-validate: PASS, 52/52
- simulator smoke: PASS, 1339 initial entities, 2/2 assertions
- workflow status: command PASS, overall remains warn due legacy parser path only

## Do not misclassify

- task.live.json, runtime-recipe.json, and scenario.vtest are runtime-pending.
- They are executable live contracts, not runtime evidence.
- Runtime evidence requires approved launcher execution plus new ScriptError log check.

## Recommended next stage

Stage 13 should consume scenario.vtest through tools/galaxy-vibe/launch-galaxy-vibe.ps1, capture launcher output, run ScriptError validation, and bundle runtime evidence.
