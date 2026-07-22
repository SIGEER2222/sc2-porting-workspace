# Stage Log: CMRE Static Boundaries

## Progress

- Resolved the declared Void campaign against `official-data/campaigns/void.sc2campaign`.
- Parsed all 47 trigger Galaxy files with the registered AST parser: 0 parse errors, 8204 functions,
  61006 calls, 112 internal include edges, and 97 cross-file call edges.
- Parsed the Dead of Night map script: 0 parse errors, 340 functions, 265 trigger API calls, 31
  objective calls, no direct Bank call, and six external runtime includes.
- Parsed 38,531 Base Catalog entries and generated an exact 242-entry Mengsk selector plus reverse
  references.
- Reduced the extraction to 240 whole entries, four shared exceptions, and seven field-level moves.

## Evidence

- `static`: `evidence/static/trigger-galaxy-graph.json` and
  `evidence/static/dead-of-night-galaxy-graph.json` are AST-derived and contain no parser errors.
- `static`: `evidence/static/mengsk-residual-selector.json` contains all 242 `id`/`parent` matches
  and 14 non-selected reverse-reference owners.
- `static`: `boundary-decision.json` classifies every reverse reference as shared exception,
  field-level move, whole-entry expansion, or asset-path false positive.

## Changes

- Added reusable AST Galaxy and structured Catalog analyzer wrappers.
- Added normalized Stage 02 evidence and the first approved extraction decision.
- No CMRE source or generated SC2 package content changed.

## Problems

- Twenty-five trigger includes resolve from official/native dependencies rather than the trigger Mod
  itself; composition validation must include those dependencies.
- The source runtime baseline remains pending and is required before generated content is accepted.

## Handoff

The next stage may generate an extraction recipe for `cmre.extract-base-mengsk-residual`. It must
preserve the four shared Actor exceptions and implement the seven field-level moves exactly.
