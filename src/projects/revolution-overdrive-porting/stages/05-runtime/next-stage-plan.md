# Next Stage Plan: Map Closure Repair

## Objective

Restore the owned Revolution Overdrive map closure without changing the read-only source, then rerun the native runtime MVP.

## Required work

1. Extend the next stage write scope to the owned map package only.
2. Copy `t3TextureMasks` and `Triggers` for `traynor01.SC2Map` from the registered read-only source and verify all 49 source hashes.
3. Audit all 31 owned maps against the source before packing; fail on any missing or changed file.
4. Repack one representative map with the repository's selected MPQ tool and record its header/entry verification.
5. Run the approved launcher, then require CreateGame/JoinGame, advancing RequestStep loops, raw P1 unit ownership, `ActionChat("Iron")`, and same-window ScriptError evidence.
6. Capture runtime owners and alliances for `traynor01`, `thanson01`, and `tzeratul04`; compare them with the Stage 04 contract before widening AI ally authorization.

## Stop conditions

- Do not modify the downloaded source package.
- Do not claim native success from listener readiness, MPQ parsing, WebUI dry-run, or launcher exit code.
- If the full closure still cannot be opened, leave the runtime result blocked with the SC2 response and source/owned diff.

## Validation commands

- Source/owned closure manifest for all 31 maps.
- MPQ verify for the representative packed map.
- Approved launcher with a fresh listener port.
- Runtime API probe: CreateGame, JoinGame, RequestStep, Observation, ActionChat.
- Same-window ScriptError scan.
- Targeted RO AI ally and WebUI regressions.
