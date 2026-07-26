# SC2 Editor Knowledge Index

Python scripts that build and query a vector index over `docs/kb-sources/`.

## Layout

```
tools/kb/
  kb-config.json     # chunk size, model name, paths
  kb-build.py        # build or rebuild the index
  kb-query.py        # query the index
  kb-hash.py         # print current source hash (no deps required)
  requirements.txt   # sentence-transformers, qdrant-client
```

The vector index lives under `artifacts/kb-index/` (Qdrant embedded mode) and is
Git-ignored. Only `artifacts/kb-index/manifest.json` is committed, recording the
source tree hash and model version so contributors can detect drift.

## Quick start

```powershell
# 1. Install dependencies (one-time per machine)
pip install -r tools/kb/requirements.txt

# 2. (Optional) point to a locally cached model to skip network download.
#    If unset, sentence-transformers downloads BAAI/bge-small-zh-v1.5 from
#    HuggingFace on first run.
$env:KB_EMBEDDING_MODEL = "C:\path\to\bge-small-zh-v1.5"

# 3. The official SC2 data mirror lives under reference/sc2mapster/SC2GameData/ (git
#    submodule, ~1.1 GB). It provides the full Blizzard Galaxy natives, AI
#    framework, GameData XML and TriggerLibs catalog headers as additional
#    indexed sources (alias: `sc2-official`). Run `git submodule update --init
#    reference/sc2mapster/SC2GameData` after cloning to populate it. If absent,
#    `kb-build.py` prints a warning and continues without those chunks.
#    See docs/kb-sources/SOURCES.md for what is covered by this mirror.

# 4. Build the index (one-time after fresh clone or after editing docs/kb-sources/)
python tools/kb/kb-build.py

# 5. Query the index
python tools/kb/kb-query.py "how does DocumentHeader differ from DocumentInfo"
python tools/kb/kb-query.py --top-k 5 "bank save format"
python tools/kb/kb-query.py --filter-topic galaxy "UnitIsAlive"
python tools/kb/kb-query.py --include-reference "UnitIsAlive"

# 6. Check status without building
python tools/kb/kb-build.py --status
python tools/kb/kb-hash.py
```

## Embedding model resolution

The scripts resolve the embedding model in this order:

1. `KB_EMBEDDING_MODEL` environment variable.
2. `embeddingModel` field in `kb-config.json` (default: `intfloat/multilingual-e5-small`).

If the resolved value is an existing path on disk (e.g. a locally cached model
directory), `sentence-transformers` loads directly from that path. Otherwise the
value is treated as a HuggingFace model ID and downloaded on first run to the
user's default HF cache (`~/.cache/huggingface/hub/` on Unix;
`%USERPROFILE%\.cache\huggingface\hub` on Windows).

The `manifest.json` records the **logical** model ID from `kb-config.json` (not
the local path) so freshness checks remain portable across machines. The
`model_source` field records whether the build loaded from a local path or
HuggingFace Hub, for diagnostic purposes only.

## Configuration

`kb-config.json` controls:

- `sourcesRoot`: directory scanned for `.md` / `.txt` / `.galaxy` files.
- `indexRoot`, `qdrantPath`, `manifestPath`: where the index and manifest live.
- `embeddingModel`: HuggingFace model ID. Default: `intfloat/multilingual-e5-small`
  (downloaded on first run to the user's HF cache).
- `embeddingDevice`: device passed to sentence-transformers, such as `cuda` or
  `cpu`.
- `embeddingDim`: must match the model's output dimension.
- `chunkSize`, `chunkOverlap`: fallback chunking for files without Markdown
  headings.
- `excludePaths`: source-relative paths omitted from vector retrieval. Navigation
  pages are excluded by default because they crowd out mechanism-specific chunks.
  They remain available for manual reading.
- `extraScanRoots`: additional scan roots beyond `sourcesRoot`. Each entry has
  `path`, `alias`, `description`, `fileExtensions`, `excludeSubpaths`. The
  default adds the local Blizzard data mirror at `src/sc2-data-trigger/` under
  the `sc2-official` alias. Chunks from extra roots have their `source` field
  prefixed with `<alias>/` so the origin is traceable from query results.

Queries search authored knowledge by default. Pass `--include-reference` to add
raw official XML and tutorial sources when tracing exact catalog fields or native
declarations.

## Cross-machine portability

- The index is Git-ignored. Contributors run `kb-build.py` once on a fresh clone.
- The embedding model is downloaded by `sentence-transformers` to the user's
  default HuggingFace cache (`~/.cache/huggingface/hub/` on Unix;
  `%USERPROFILE%\.cache\huggingface\hub` on Windows). To work offline, copy this
  directory between machines.
- `manifest.json` is committed so drift is detected: if a contributor edits
  `docs/kb-sources/` without rebuilding, queries will print a stale-index warning and
  exit with code 2. Pass `--allow-stale` to query anyway.

## Integration with skills

The project-local skill `tools/.codex/skills/sc2-editor-knowledge/SKILL.md` documents
how AI agents should use this index. The skill's `references/retrieval-guide.md`
covers chunk format, scoring, and rebuild triggers in detail.
