"""Milestone 4, step 1: embed chunks.jsonl into a persistent ChromaDB collection.

Run as: python embed.py
"""

import json
import os
import sys
from collections import defaultdict

import chromadb
from sentence_transformers import SentenceTransformer

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
CHUNKS_PATH = os.path.join(PIPELINE_DIR, "data", "processed", "chunks.jsonl")
CHROMA_DIR = os.path.join(PIPELINE_DIR, "data", "chroma")
COLLECTION_NAME = "fsu_advising"
BATCH_SIZE = 64
# planning.md Retrieval Approach: candidate models are judged on the 5 eval
# questions. all-MiniLM-L6-v2 (256-token window truncates program-section
# Notes) and multi-qa-MiniLM-L6-cos-v1 both failed code-heavy queries;
# bge-small-en-v1.5 (512-token window) is the current pick.
MODEL_NAME = "BAAI/bge-small-en-v1.5"


def load_chunks():
    chunks = []
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks


def sanitize_metadata(chunk):
    """Flatten chunk metadata for ChromaDB (str/int/float/bool only).

    Returns (clean_dict, None) or (None, offending_field) if a value can't
    be converted (e.g. a nested dict).
    """
    meta = dict(chunk.get("metadata") or {})
    meta["doc_type"] = chunk.get("doc_type")
    meta["source_url"] = chunk.get("source_url")
    meta["scraped_at"] = chunk.get("scraped_at")

    clean = {}
    for field, value in meta.items():
        if value is None:
            clean[field] = ""
        elif isinstance(value, list):
            clean[field] = ", ".join(str(v) for v in value)
        elif isinstance(value, (str, int, float, bool)):
            clean[field] = value
        else:
            return None, field
    return clean, None


def main():
    chunks = load_chunks()

    print("=== chunk counts by doc_type ===")
    by_type = defaultdict(int)
    for c in chunks:
        by_type[c.get("doc_type")] += 1
    for doc_type in sorted(by_type):
        print("  %-16s %d" % (doc_type, by_type[doc_type]))
    print("  total            %d" % len(chunks))
    print()

    client = chromadb.PersistentClient(path=CHROMA_DIR)

    existing = None
    try:
        existing = client.get_collection(COLLECTION_NAME)
    except Exception:
        pass

    if existing is not None:
        if existing.count() == len(chunks):
            print("Collection up to date, skipping embed")
            return
        print("Collection has %d documents but chunks.jsonl has %d — rebuilding."
              % (existing.count(), len(chunks)))
        client.delete_collection(COLLECTION_NAME)

    collection = client.create_collection(
        COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )

    print("Loading SentenceTransformer %s ..." % MODEL_NAME)
    model = SentenceTransformer(MODEL_NAME)

    # Drop chunks whose metadata can't be made ChromaDB-safe, never crash.
    usable = []
    for c in chunks:
        clean, bad_field = sanitize_metadata(c)
        if bad_field is not None:
            print("SKIP %s: metadata field '%s' has unsupported type"
                  % (c.get("chunk_id"), bad_field))
            continue
        usable.append((c, clean))

    total = len(usable)
    n_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    embedded = 0

    for i in range(n_batches):
        batch = usable[i * BATCH_SIZE:(i + 1) * BATCH_SIZE]
        texts = [c["text"] for c, _ in batch]
        embeddings = model.encode(texts, normalize_embeddings=True).tolist()
        ids = [c["chunk_id"] for c, _ in batch]
        metadatas = [m for _, m in batch]
        try:
            collection.add(ids=ids, embeddings=embeddings,
                           documents=texts, metadatas=metadatas)
            embedded += len(batch)
        except Exception:
            # One bad record in the batch — add one at a time to isolate it.
            for (c, m), emb, text in zip(batch, embeddings, texts):
                try:
                    collection.add(ids=[c["chunk_id"]], embeddings=[emb],
                                   documents=[text], metadatas=[m])
                    embedded += 1
                except Exception as e:
                    print("SKIP %s: ChromaDB rejected metadata (%s)"
                          % (c["chunk_id"], e))
        print("[batch %d/%d] Embedded %d/%d chunks"
              % (i + 1, n_batches, embedded, total))

    print()
    print("Embedded %d chunks into collection '%s'. Done."
          % (collection.count(), COLLECTION_NAME))


if __name__ == "__main__":
    main()
