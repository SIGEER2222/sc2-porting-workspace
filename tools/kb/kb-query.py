#!/usr/bin/env python3
"""Query the SC2 editor knowledge vector index.

Usage:
    python tools/kb/kb-query.py "<question>"
    python tools/kb/kb-query.py --top-k 5 "<question>"
    python tools/kb/kb-query.py --include-reference "<question>"
    python tools/kb/kb-query.py --allow-stale "<question>"
    python tools/kb/kb-query.py --filter-topic galaxy "<question>"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kb_common import (
    REPO_ROOT,
    compute_source_hash_from_index,
    iter_all_source_files,
    load_config,
    retrieval_text,
)


def query(
    config: dict,
    question: str,
    top_k: int,
    allow_stale: bool,
    filter_topic: str | None,
    include_reference: bool,
) -> int:
    from sentence_transformers import SentenceTransformer
    from qdrant_client import QdrantClient

    manifest_path = REPO_ROOT / config["manifestPath"]
    qdrant_path = REPO_ROOT / config["qdrantPath"]
    collection = config["collectionName"]

    # Resolve model identifier or local path (env var overrides config).
    import os
    model_name = os.environ.get("KB_EMBEDDING_MODEL") or config["embeddingModel"]

    if not manifest_path.exists() or not qdrant_path.exists():
        sys.stderr.write(
            "ERROR: index has not been built yet.\n"
            "Run: python tools/kb/kb-build.py\n"
        )
        return 2

    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Freshness check: must include all scan roots (primary + extraScanRoots)
    # to match the hash recorded by kb-build.py.
    index = iter_all_source_files(config)
    current_hash = compute_source_hash_from_index(index)
    if current_hash != manifest.get("source_hash") and not allow_stale:
        sys.stderr.write(
            "WARNING: index is stale (source files changed since last build).\n"
            f"  manifest hash: {manifest.get('source_hash', '')[:12]}\n"
            f"  current hash:  {current_hash[:12]}\n"
            "Run `python tools/kb/kb-build.py` to rebuild, or pass --allow-stale.\n"
        )
        return 2

    # Freshness check compares the logical model ID (from config), not the
    # runtime-resolved path. This way manifest stays portable across machines
    # that may load the same model from different local cache paths.
    if manifest.get("model_name") != config["embeddingModel"]:
        sys.stderr.write(
            f"WARNING: model version mismatch (manifest={manifest.get('model_name')}, "
            f"config={config['embeddingModel']}).\n"
            "Rebuild with `python tools/kb/kb-build.py --force` if the model differs.\n"
        )

    print(f"Loading model: {model_name}")
    if Path(model_name).exists():
        print(f"Loading from local path: {model_name}")
        model = SentenceTransformer(model_name, device=config.get("embeddingDevice", "cpu"))
    else:
        model = SentenceTransformer(model_name, device=config.get("embeddingDevice", "cpu"))
    print(f"Embedding query: {question}")
    query_vec = model.encode(
        [retrieval_text(question, "query")], normalize_embeddings=True
    )[0].tolist()

    client = QdrantClient(path=str(qdrant_path))
    try:
        from qdrant_client.http import models as qmodels
    except ImportError:
        qmodels = None

    query_filter = None
    if qmodels:
        must = []
        if not include_reference:
            must.append(
                qmodels.FieldCondition(
                    key="origin", match=qmodels.MatchValue(value="curated")
                )
            )
        if filter_topic:
            must.append(
                qmodels.FieldCondition(
                    key="topic", match=qmodels.MatchValue(value=filter_topic)
                )
            )
        if must:
            query_filter = qmodels.Filter(must=must)

    # qdrant-client 1.10+ deprecates `search` in favor of `query_points`.
    # Use `query_points` when available; fall back to `search` for older versions.
    try:
        if hasattr(client, "query_points"):
            query_result = client.query_points(
                collection_name=collection,
                query=query_vec,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
            results = query_result.points
        else:
            results = client.search(
                collection_name=collection,
                query_vector=query_vec,
                limit=top_k,
                query_filter=query_filter,
                with_payload=True,
            )
    finally:
        # Ensure the Qdrant local file lock is released for parallel queries.
        try:
            client.close()
        except Exception:
            pass

    if not results:
        print("No results.")
        return 0

    print(f"\nTop {len(results)} results:")
    print("=" * 80)
    for i, r in enumerate(results, 1):
        payload = r.payload or {}
        score = r.score
        print(f"\n[{i}] score={score:.4f}")
        print(f"    source: {payload.get('source')}")
        print(f"    heading: {payload.get('heading')}")
        print(f"    topic: {payload.get('topic')}  origin: {payload.get('origin')}  chunk_index: {payload.get('chunk_index')}")
        text = payload.get("text", "")
        # Truncate very long chunks for terminal display.
        if len(text) > 800:
            text = text[:800] + "\n    ... [truncated]"
        print("    ---")
        for line in text.splitlines():
            print(f"    {line}")
    print("\n" + "=" * 80)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="Natural-language question to look up.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results to return (default: 5).")
    parser.add_argument("--allow-stale", action="store_true", help="Query even if the index hash differs from sources.")
    parser.add_argument("--filter-topic", help="Restrict results to a topic (e.g. galaxy, catalog, bank).")
    parser.add_argument("--include-reference", action="store_true", help="Include raw official XML and tutorial sources in addition to curated knowledge.")
    args = parser.parse_args()

    config = load_config()
    return query(
        config,
        args.question,
        args.top_k,
        args.allow_stale,
        args.filter_topic,
        args.include_reference,
    )


if __name__ == "__main__":
    raise SystemExit(main())
