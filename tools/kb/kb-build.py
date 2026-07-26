#!/usr/bin/env python3
"""Build the SC2 editor knowledge vector index from docs/kb-sources/.

Uses sentence-transformers (bge-small-zh-v1.5) for embeddings and qdrant-client
in embedded mode for local storage. The index lives under artifacts/kb-index/
and is not tracked by Git; only manifest.json is committed for drift detection.

Usage:
    python tools/kb/kb-build.py             # build if hash changed
    python tools/kb/kb-build.py --force    # rebuild unconditionally
    python tools/kb/kb-build.py --status   # print current manifest and exit
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from kb_common import (
    REPO_ROOT,
    compute_source_hash_from_index,
    iter_all_source_files,
    load_config,
    retrieval_text,
    source_origin,
)


def chunk_markdown(text: str, source: str, chunk_size: int, chunk_overlap: int) -> list[dict]:
    """Chunk a Markdown file by H2/H3 headings. Falls back to fixed-size windows."""
    lines = text.splitlines()
    chunks: list[dict] = []
    current_heading: str | None = None
    current_body: list[str] = []
    chunk_index = 0

    def flush():
        nonlocal chunk_index, current_heading, current_body
        body = "\n".join(current_body).strip()
        if body:
            chunks.append({
                "text": body,
                "source": source,
                "heading": current_heading or "(no heading)",
                "chunk_index": chunk_index,
            })
            chunk_index += 1
        current_body = []

    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("## ") or stripped.startswith("# "):
            flush()
            current_heading = stripped
        current_body.append(line)
    flush()

    if not chunks:
        # Fixed-size fallback for files without headings (.galaxy, .xml, .txt).
        text_len = len(text)
        start = 0
        idx = 0
        while start < text_len:
            end = min(start + chunk_size, text_len)
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append({
                    "text": chunk_text,
                    "source": source,
                    "heading": text.splitlines()[0] if text else "(empty)",
                    "chunk_index": idx,
                })
                idx += 1
            start = end - chunk_overlap if end < text_len else end
            if start <= 0 or start >= text_len:
                break

    return chunks


def resolve_model_name(config: dict) -> str:
    """Resolve embedding model identifier or local path.

    Priority:
      1. KB_EMBEDDING_MODEL environment variable.
      2. config['embeddingModel'].
    If the resolved value is an existing path on disk, sentence-transformers will
    load from that path; otherwise it is treated as a HuggingFace model ID and
    downloaded on first run.
    """
    import os
    model_name = os.environ.get("KB_EMBEDDING_MODEL") or config["embeddingModel"]
    return model_name


def load_embeddings_model(model_name: str, device: str):
    """Lazy import so --status works without the dependency installed."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        sys.stderr.write(
            "ERROR: sentence-transformers is not installed.\n"
            "Install dependencies first:\n"
            "    pip install -r tools/kb/requirements.txt\n"
        )
        raise SystemExit(2) from exc
    print(f"Loading embedding model on device: {device}")
    # If the model name resolves to an existing path, load from there directly.
    # This avoids requiring network access when a local copy is available.
    if Path(model_name).exists():
        print(f"Loading embedding model from local path: {model_name}")
        return SentenceTransformer(model_name, device=device)
    return SentenceTransformer(model_name, device=device)


def build_index(config: dict, force: bool) -> int:
    index_root = REPO_ROOT / config["indexRoot"]
    qdrant_path = REPO_ROOT / config["qdrantPath"]
    manifest_path = REPO_ROOT / config["manifestPath"]
    collection = config["collectionName"]
    expected_dim = config["embeddingDim"]
    chunk_size = config.get("chunkSize", 1200)
    chunk_overlap = config.get("chunkOverlap", 200)
    embedding_device = config.get("embeddingDevice", "cpu")

    sources_root = REPO_ROOT / config["sourcesRoot"]
    if not sources_root.is_dir():
        sys.stderr.write(f"ERROR: sources root not found: {sources_root}\n")
        return 1

    index = iter_all_source_files(config)
    if not index:
        sys.stderr.write(f"ERROR: no source files found under {sources_root}\n")
        return 1

    source_hash = compute_source_hash_from_index(index)
    model_name = resolve_model_name(config)

    if not force and manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8") as f:
            existing = json.load(f)
        if existing.get("source_hash") == source_hash and existing.get("model_name") == config["embeddingModel"]:
            print(f"Index is up to date (hash={source_hash[:12]}, chunks={existing.get('chunk_count')}, files={existing.get('files_indexed')}).")
            print("Use --force to rebuild unconditionally.")
            return 0

    print(f"Building index from {len(index)} files...")
    print(f"Source hash: {source_hash}")

    # Chunk all files. Track per-topic chunk counts for visibility.
    all_chunks: list[dict] = []
    per_topic_counts: dict[str, int] = {}
    per_alias_counts: dict[str, int] = {}
    for path, source_alias, topic in index:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="replace")
        chunks = chunk_markdown(text, source_alias, chunk_size, chunk_overlap)
        for c in chunks:
            c["topic"] = topic
        all_chunks.extend(chunks)
        per_topic_counts[topic] = per_topic_counts.get(topic, 0) + len(chunks)
        # alias is the first segment of source_alias before '/'.
        alias_key = source_alias.split("/", 1)[0] if "/" in source_alias else "(kb-sources)"
        per_alias_counts[alias_key] = per_alias_counts.get(alias_key, 0) + len(chunks)

    print(f"Total chunks: {len(all_chunks)}")
    print("Per-alias chunk counts:")
    for alias, count in sorted(per_alias_counts.items()):
        print(f"  {alias}: {count}")
    print("Top 10 topics by chunk count:")
    for topic, count in sorted(per_topic_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"  {topic}: {count}")

    print(f"Loading embedding model: {model_name}")
    model = load_embeddings_model(model_name, embedding_device)
    actual_dim = model.get_sentence_embedding_dimension()
    if actual_dim != expected_dim:
        print(f"WARNING: model dimension {actual_dim} != configured {expected_dim}; using actual.")
        expected_dim = actual_dim

    print(f"Embedding {len(all_chunks)} chunks...")
    import torch
    if torch.cuda.is_available():
        print(f"Using GPU: {torch.cuda.get_device_name(0)}")
        batch_size = 32
    else:
        print("Using CPU")
        batch_size = 64
    texts = [retrieval_text(c["text"], "passage") for c in all_chunks]
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True,
        batch_size=batch_size,
    )

    # Open Qdrant embedded collection.
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.http import models as qmodels
    except ImportError as exc:
        sys.stderr.write(
            "ERROR: qdrant-client is not installed.\n"
            "Install dependencies first:\n"
            "    pip install -r tools/kb/requirements.txt\n"
        )
        raise SystemExit(2) from exc

    index_root.mkdir(parents=True, exist_ok=True)
    if qdrant_path.exists():
        # Wipe previous collection by removing the directory.
        import shutil
        shutil.rmtree(qdrant_path, ignore_errors=True)

    client = QdrantClient(path=str(qdrant_path))
    client.recreate_collection(
        collection_name=collection,
        vectors_config=qmodels.VectorParams(
            size=expected_dim,
            distance=qmodels.Distance.COSINE,
        ),
    )

    print(f"Uploading to Qdrant collection '{collection}'...")
    # Batch upload to avoid OOM on large indices.
    batch_size = 500
    for start in range(0, len(all_chunks), batch_size):
        end = min(start + batch_size, len(all_chunks))
        client.upsert(
            collection_name=collection,
            points=[
                qmodels.PointStruct(
                    id=start + i,
                    vector=embeddings[start + i].tolist(),
                    payload={
                        "text": all_chunks[start + i]["text"],
                        "source": all_chunks[start + i]["source"],
                        "heading": all_chunks[start + i]["heading"],
                        "chunk_index": all_chunks[start + i]["chunk_index"],
                        "topic": all_chunks[start + i]["topic"],
                        "origin": source_origin(all_chunks[start + i]["topic"]),
                    },
                )
                for i in range(end - start)
            ],
        )

    # Flush Qdrant local SQLite store to disk before exiting.
    client.close()

    manifest = {
        "schemaVersion": 1,
        "source_hash": source_hash,
        "model_name": config["embeddingModel"],
        "model_source": "local-path" if Path(model_name).exists() else "huggingface-hub",
        "model_dim": expected_dim,
        "chunk_count": len(all_chunks),
        "built_at": datetime.now(timezone.utc).isoformat(),
        "collection_name": collection,
        "files_indexed": len(index),
        "scan_roots": [config["sourcesRoot"]] + [r["path"] for r in config.get("extraScanRoots", [])],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"Manifest written: {manifest_path}")
    print("Build complete.")
    return 0


def print_status(config: dict) -> int:
    manifest_path = REPO_ROOT / config["manifestPath"]
    if not manifest_path.exists():
        print("No manifest found. Index has not been built yet.")
        return 1
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))

    index = iter_all_source_files(config)
    current_hash = compute_source_hash_from_index(index)
    if current_hash == manifest.get("source_hash"):
        print(f"\nStatus: UP TO DATE (hash={current_hash[:12]})")
        return 0
    print(f"\nStatus: STALE")
    print(f"  manifest hash: {manifest.get('source_hash', '')[:12]}")
    print(f"  current hash: {current_hash[:12]}")
    print(f"  run `python tools/kb/kb-build.py` to rebuild.")
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Rebuild even if hash matches.")
    parser.add_argument("--status", action="store_true", help="Print current manifest and exit.")
    args = parser.parse_args()

    config = load_config()
    if args.status:
        return print_status(config)
    return build_index(config, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
