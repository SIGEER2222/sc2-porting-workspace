---
name: sc2-editor-knowledge
description: Retrieve SC2 editor, Galaxy script, Catalog, document structure, triggers, data spaces, Bank, MPQ, and runtime contract knowledge from the kb-sources subrepository. Use before writing or adapting Galaxy code, before editing Catalog data, before touching SC2Map/SC2Mod document files, when investigating a ScriptError, when designing an adapter, or when runtime behavior needs an editor-side explanation.
---

# SC2 Editor Knowledge

Retrieve canonical editor knowledge before proposing changes to SC2 assets.

## When to use

Invoke this skill whenever an active task touches one of:

- Galaxy script (`.galaxy`, `_h.galaxy`, `MapScript.galaxy`, `TriggerLibs/`).
- Catalog data (`Base.SC2Data/GameData.xml`, `GameData/*.xml`).
- Document files (`DocumentHeader`, `DocumentInfo`, `MapInfo`, `Objects`, `Triggers`, `Attributes`).
- Trigger GUI behavior, libraries, init order, or registration.
- Data space mode and modular catalog layout.
- Bank persistence (read/write, signature, encryption).
- MPQ container format (`.SC2Map`, `.SC2Mod`) and repacking.
- Runtime observer evidence and ScriptError interpretation.

## Source of truth

Knowledge lives in the `docs/kb-sources/` subrepository as plain Markdown and text. See
`docs/kb-sources/README.md` for the directory layout and per-directory `SOURCES.md` for
attribution. The sources are versioned and editable through normal Git workflows.

## Retrieval workflow

1. Read `references/topic-index.md` for a flat topic overview.
2. For each relevant topic, attempt one of:
   - **Semantic retrieval** via `tools/kb/kb-query.py "<question>"`. This hits
     the local Qdrant embedded index built by `tools/kb/kb-build.py`. If the
     index is missing or out of date, the script prints a rebuild hint.
   - **Direct read** via `Read` on a specific file listed in `topic-index.md`
     when the query is structural (e.g. "what files are inside a SC2Map").
3. For Galaxy native function lookup, also consult `galaxy/natives-reference.md`
   and `galaxy/natives-missing.galaxy` directly; the index may not capture every
   native identifier.
4. For canonical Blizzard docs, follow external links in
   `docs/kb-sources/editor/SOURCES.md` (https://mapster.talv.space,
   https://s2editor-guides.readthedocs.io).

## Chunking and freshness

- `kb-build.py` chunks each Markdown by H2/H3 headings. Each chunk carries the
  source path, heading, and chunk index as payload metadata.
- The index is rebuilt whenever `docs/kb-sources/` content changes. The build script
  writes `artifacts/kb-index/manifest.json` recording the source tree hash and
  model version. Compare this hash before trusting a stale index.
- The index data is Git-ignored (machine-specific); only `manifest.json` is
  committed. A mismatched hash on a fresh clone prompts a single rebuild.

## Backend neutrality

The skill does not depend on the global `knowledge-base` skill or any external
Qdrant service. It uses `qdrant-client`'s embedded mode (local file storage under
`artifacts/kb-index/qdrant/`) and the local `bge-small-zh-v1.5` model cached by
`sentence-transformers`. Cross-machine portability requires only Python 3.10+ and
a one-time model download on first run.

## Output discipline

- Cite the source path and heading for every retrieved fact.
- Label retrieved claims as `static` (from documents) or `inference` (your
  synthesis) following the workspace AGENTS.md evidence rules.
- Do not replace runtime evidence with knowledge-base claims. When runtime
  evidence contradicts the docs, runtime wins and the docs need an update.

## See also

- `references/retrieval-guide.md` — chunk format, query syntax, examples.
- `references/topic-index.md` — flat topic-to-file map for direct reads.
- `docs/kb-sources/README.md` — source layout and contribution guide.
