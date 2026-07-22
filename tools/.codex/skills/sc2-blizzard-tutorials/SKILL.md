---
name: sc2-blizzard-tutorials
description: Retrieve Blizzard official SC2 Editor tutorials (maintained by SC2Mapster community) when the task needs how-to guidance for editor operations — terrain editing, trigger GUI, data editor catalogs, actors, cutscenes, Banks, GalaxyScript integration, dialog UI, or specific lessons like creating an aura ability. Use when the user asks "how do I do X in the editor" or when implementing a feature that maps to a documented editor workflow.
---

# SC2 Blizzard Tutorials

Retrieve official Blizzard tutorial guidance before implementing editor workflows.

## When to use

Invoke this skill when an active task needs **how-to guidance for StarCraft II Editor operations**, including:

- Terrain editing (cliffs, textures, water, foliage, doodads, cameras, lighting, pathing).
- Trigger Editor GUI usage (actions, conditions, events, variables, records, control statements, dialogs, dialog panels, text tags, camera actions, math functions, UI events, unit selection events, custom values, trigger organization, loggers, debug cheats, code optimization).
- GalaxyScript integration (when to use raw script vs GUI, include mechanism, custom script objects).
- Multithreading via Action Definitions (asynchronous trigger design).
- Banks (save/load, sections, keys, signature, encryption, local storage location).
- Data Editor operations (87 catalogs overview, units, actors, actor messages, range actors, sound actors, doodad actors, event macros, site operations, model data viewer, click response behaviors, validators, footprints, buttons, sounds).
- Cutscene Editor usage.
- Text Editor and font styles.
- Specific lessons: aura abilities, WASD keyboard controls, first-person camera, spellswap system, displaying variables on screen, resource placement for competitive play, testing mods offline, finding testers, marketing, exporting game assets.
- Publishing maps/mods to Battle.net.
- Mapmaking best practices and mastering mapmaking concepts.

**Do NOT use this skill for:**

- Raw Galaxy native function lookup → use `sc2-editor-knowledge` skill instead.
- Catalog XML structure or GameData file format → use `sc2-editor-knowledge`.
- Document file internals (DocumentHeader, DocumentInfo, MapInfo) → use `sc2-editor-knowledge`.
- MPQ container format or repacking → use `sc2-editor-knowledge`.

## Source of truth

The tutorials live in the `reference/sc2mapster/blizzard-tutorials/` git submodule
(cloned from https://github.com/SC2Mapster/blizzard-tutorials). The Markdown
sources are under `reference/sc2mapster/blizzard-tutorials/docs/`. Online
deployment: https://s2editor-guides.readthedocs.io

## Retrieval workflow

1. **Read `references/tutorial-index.md`** for a flat, organized overview of all
   94 tutorials grouped by module. Use this to locate the right tutorial file
   path before reading or querying.
2. For each relevant tutorial, attempt one of:
   - **Semantic retrieval** via `python tools/kb/kb-query.py "<question>"`. The
     `blizzard-tutorials` alias is indexed as an `extraScanRoot` in
     `tools/kb/kb-config.json`. Query results will include the source path
     prefixed with `blizzard-tutorials/`.
   - **Direct read** via `Read` on the specific `.md` file listed in
     `tutorial-index.md` when the query is structural (e.g. "what fields does
     an Actor have" → read `New_Tutorials/04_Data_Editor/060_Actors.md`).
3. Tutorial files contain image references like `./resources/XXX.png` — these
   are not retrievable via text index. When an image is essential, open the
   online deployment at the corresponding URL.

## Tutorial structure (4 sections, 94 tutorials)

| Section | Path | Count | Coverage |
|---------|------|-------|----------|
| Classic Tutorials | `docs/Classic_Tutorials/` | 18 | Original Blizzard tutorials: Terrain (5), Trigger (4), Data (4), Misc (5) |
| New Tutorials | `docs/New_Tutorials/` | 75 | Full editor guide: Introduction (17), Terrain (12), Trigger (26), Data (19), Text (2), Cutscene (1), Lessons (9) — note: Trigger has 26 files numbered 032–058, Data has 19 files numbered 058–076 (058 is shared between sections) |
| Data Primer | `docs/Data_Primer/` | 1 | Simple Firebolt ability walkthrough with sample .SC2Map |
| Index | `docs/index.md` | 1 | Site landing page |

See `references/tutorial-index.md` for the complete file-by-file listing with
direct path references.

## Relationship to other skills

- **`sc2-editor-knowledge`** — complementary. Use that skill for API reference,
  Catalog structure, document format, MPQ internals. Use this skill for
  *operational* guidance on how to use the editor to achieve a goal.
- **`sc2-static-analysis`**, **`sc2-runtime-analysis`**, **`sc2-adapter-design`**,
  **`sc2-ai-development-loop`** — unrelated to tutorial retrieval.

## Output discipline

- Cite the tutorial file path (e.g. `blizzard-tutorials/New_Tutorials/04_Data_Editor/060_Actors.md`)
  and the section heading for every retrieved fact.
- Label retrieved claims as `static` (from tutorials) or `inference` (your
  synthesis) following the workspace AGENTS.md evidence rules.
- Tutorial content describes the **editor GUI workflow**. When mapping it to
  programmatic data manipulation (XML editing, Galaxy script), make the
  translation explicit in your response.

## Rebuild triggers

The blizzard-tutorials alias is part of the kb index. Run
`python tools/kb/kb-build.py` to rebuild when:

- The `reference/sc2mapster/blizzard-tutorials` submodule is updated to a new
  commit.
- `kb-config.json` is edited (the alias or file extensions change).
- A fresh clone (the index is Git-ignored).

## See also

- `references/tutorial-index.md` — flat tutorial-to-file map for direct reads.
- `tools/kb/README.md` — kb index build and query instructions.
- `https://s2editor-guides.readthedocs.io` — online deployment with images.
