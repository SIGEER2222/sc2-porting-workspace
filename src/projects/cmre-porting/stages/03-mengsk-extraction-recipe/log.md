# Stage Log: Mengsk Extraction Recipe

## Progress

- Generated the Mengsk extraction working tree under `artifacts/projects/cmre-porting/mengsk-extraction`.
- Ran the catalog extraction recipe successfully: 240 whole entries moved, 15 Catalog files modified,
  source files unchanged.
- Compared source and generated Base-to-Mengsk chains: no unexpected differences, seven planned
  Catalog entry differences only.

## Evidence

- `comparison-report.json` shows the only changed entries are the seven planned field-move targets.
- `extract-catalog-boundary.mjs` and `compare-catalog-chains.mjs` are reusable for later commander
  extractions.

## Changes

- The generated working Mengsk package still needs a real SC2 runtime baseline before acceptance.

## Problems

- Runtime launch/observer validation remains outstanding.

## Handoff

- Next stage should run the actual `cmre.dead-of-night.mengsk-source` runtime scenario, then compare
  the generated composition on a real observer instead of only structural Catalog equality.
