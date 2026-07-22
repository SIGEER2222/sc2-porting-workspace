# Composition Fix Plan

## Objective

Make the Reborn Raynor generated plan schema-valid and align direct document dependencies with the
canonical composition without modifying the downloaded Reborn source or canonical Raynor behavior.

## Inputs

- Passed discovery and composition-remediation results.
- Launcher plan schema failure and composer verification report.
- Existing dirty legacy-project changes must be preserved and reviewed before edits.

## Write scope

- `src/projects/reborn-zexpedition03-raynor-mvp/stages/03-composition-fix/`
- `src/projects/reborn-zexpedition03-raynor-mvp/project.json`
- `legacy-project:scripts/sc2-launcher/launcher-plan.ps1`
- `legacy-project:scripts/sc2-launcher/schema/launcher-plan.schema.json`
- `legacy-project:scripts/sc2-launcher/validate-config.mjs`
- `legacy-project:scripts/sc2-launcher/tests/`
- `legacy-project:scripts/sc2-composer/cli.mjs`
- `legacy-project:scripts/sc2-composer/src/`
- `legacy-project:scripts/sc2-composer/tests/`
- `legacy-project:Shared/Launcher/reborn-dependencies.json`
- `legacy-project:Mods/Reborn/MapProfiles/zexpedition03.json`
- `legacy-project:Mods/7vs1/CoreRuntime.SC2Mod/DataCenter.json`

## Tasks

1. Review existing concurrent changes in every approved legacy-project file before editing.
2. Add regression coverage for transitive packages without engine paths.
3. Generate only selected-commander dependencies and actual launcher Galaxy injections.
4. Separate direct document dependencies from transitive sync-only packages in comparison logic.
5. Normalize scoped Reborn adapter engine paths and the zexpedition03 campaign parent.
6. Lint only the effective composition closure and repair any in-scope DataCenter typo.
7. Regenerate and validate the Raynor plan and composer report.
8. Add concrete runtime assertions before authorizing a launch.

## Validation

- Focused launcher and composer tests pass.
- Generated launcher plan passes its schema.
- Dependency closure and document roundtrip pass or contain only explicitly accepted differences.
- Runtime scenario has non-empty commander, loaded-mod, and production assertions.

## Stop conditions

- Do not edit files containing unexplained concurrent changes until their intent is understood.
- Do not change downloaded Reborn content, canonical Raynor GameData, or map mission logic.
- Do not launch SC2 until the static eligibility verdict becomes true.
