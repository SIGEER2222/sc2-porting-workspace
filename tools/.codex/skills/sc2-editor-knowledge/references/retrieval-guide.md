# Retrieval Guide

How to query the SC2 editor knowledge base and interpret results.

## Quick start

```powershell
# Optional: use a locally cached model instead of downloading from HuggingFace.
# Skip this line to let sentence-transformers download BAAI/bge-small-zh-v1.5
# on first run.
$env:KB_EMBEDDING_MODEL = "C:\path\to\bge-small-zh-v1.5"

# Build (or rebuild) the vector index from docs/kb-sources/
python tools/kb/kb-build.py

# Query the index
python tools/kb/kb-query.py "how to check if a unit is alive in galaxy"

# Limit results
python tools/kb/kb-query.py --top-k 5 "bank save format"
```

## Chunk format

Each chunk stored in the index has:

- `text`: the chunk content (a heading plus the body until the next same-or-higher-level heading).
- `source`: relative path inside `docs/kb-sources/` (e.g. `galaxy/syntax.md`).
- `heading`: the heading line (e.g. `## Statements and blocks`).
- `chunk_index`: 0-based integer within the source file.
- `topic`: top-level directory name (e.g. `galaxy`, `catalog`, `bank`).

For files without Markdown headings (`.galaxy`, `.txt` samples), the chunker
falls back to fixed-size windows of `chunk_size` characters with `chunk_overlap`
overlap. Their `heading` is the file's first non-empty line.

## Query tips

- Phrase the query as a natural-language question. bge-small-zh-v1.5 is
  optimized for Chinese and English retrieval; mixed queries are fine.
- For identifier lookup (e.g. "UnitIsAlive"), prefer direct
  `Read` on `galaxy/natives-reference.md` over the vector index. Identifiers
  may be split across chunks and exact-match retrieval beats semantic search.
- For conceptual questions (e.g. "what is the difference between
  DocumentHeader and DocumentInfo"), use the vector index.
- For structural questions (e.g. "what files are in a SC2Mod"), consult
  `references/topic-index.md` and read the file directly.

## Interpreting scores

`kb-query.py` prints each result's score in `[0, 1]`. bge-small-zh-v1.5 with
cosine similarity typically yields:

- `>= 0.7`: strong match; trust the result.
- `0.5 - 0.7`: relevant context; read the full chunk before citing.
- `< 0.5`: weak match; consider rephrasing the query or consulting the topic
  index directly.

A score of `0.0` for every result indicates the index is empty or built from a
different model version. Run `kb-build.py --force` to rebuild.

## Manifest and freshness

`artifacts/kb-index/manifest.json` records:

- `source_hash`: SHA-256 of the sorted file list and content hashes inside `docs/kb-sources/`.
- `model_name`: embedding model identifier.
- `model_dim`: embedding dimension (must match the running model).
- `chunk_count`: total chunks indexed.
- `built_at`: ISO timestamp.

`kb-query.py` checks the manifest on startup. If `source_hash` does not match
the current `docs/kb-sources/` tree, it prints a rebuild hint and exits with code 2.
Pass `--allow-stale` to query anyway.

## Rebuild triggers

Run `kb-build.py` when:

- A file under `docs/kb-sources/` is added, edited, or removed.
- `requirements.txt` is upgraded and the model version changes.
- The manifest hash mismatch warning appears during a query.
- After a fresh clone on a new machine (the index is Git-ignored).

## Cross-machine portability

The index lives under `artifacts/kb-index/` and is Git-ignored. The committed
`manifest.json` lets contributors detect drift. The embedding model is
downloaded by `sentence-transformers` on first run and cached in the user's
default HuggingFace cache (`~/.cache/huggingface/hub/`).

To share the model offline across machines, copy the cached model directory
into the new machine's HF cache before running `kb-build.py`.
