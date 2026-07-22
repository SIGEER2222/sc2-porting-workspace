# Reborn Composition Fix Plan

## Objective

Execute the focused project retry plan until the generated Raynor composition passes its persistent
static gates and becomes eligible for runtime testing.

## Inputs

- `stages/02-pilot-onboarding/result.json`
- `src/projects/reborn-zexpedition03-raynor-mvp/stages/03-composition-fix/plan.md`

## Write scope

- The exact paths declared by the project stage 03 plan.
- `stages/03-composition-fix/`

## Validation

- Focused launcher and composer tests.
- Launcher plan schema validation.
- Composer dependency closure and document roundtrip.
- Non-empty runtime acceptance assertions.

## Stop conditions

- Preserve concurrent legacy-project changes.
- Do not launch SC2 until static eligibility is true.
