"""Milestone 4, step 2: retrieve(query, k, filters) against the fsu_advising collection.

Run as: python retrieve.py "what are the prereqs for HIST 3900" 5
"""

import os
import sys

import chromadb
from sentence_transformers import SentenceTransformer

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMA_DIR = os.path.join(PIPELINE_DIR, "data", "chroma")
COLLECTION_NAME = "fsu_advising"
# Must match the model used in embed.py.
MODEL_NAME = "BAAI/bge-small-en-v1.5"
# bge models expect this prefix on queries (not on passages).
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# Loaded once per script run, on first retrieve() call.
_MODEL = None
_COLLECTION = None


def _get_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = SentenceTransformer(MODEL_NAME)
    return _MODEL


def _get_collection():
    global _COLLECTION
    if _COLLECTION is None:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        _COLLECTION = client.get_collection(COLLECTION_NAME)
    return _COLLECTION


def retrieve(query: str, k: int = 5, filters: dict = None) -> list:
    """Return the k nearest chunks to query, optionally metadata-filtered.

    Valid filter keys: doc_type, course_code, semester, modality, program_name.
    Example: filters={"semester": "day_fall_2026"}
    """
    model = _get_model()
    collection = _get_collection()

    embedding = model.encode([QUERY_PREFIX + query],
                             normalize_embeddings=True).tolist()
    result = collection.query(
        query_embeddings=embedding,
        n_results=k,
        where=filters,
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    for chunk_id, text, meta, dist in zip(
        result["ids"][0], result["documents"][0],
        result["metadatas"][0], result["distances"][0],
    ):
        hits.append({
            "chunk_id": chunk_id,
            "text": text,
            "doc_type": meta.get("doc_type", ""),
            "source_url": meta.get("source_url", ""),
            "scraped_at": meta.get("scraped_at", ""),
            "metadata": meta,
            "distance": float(dist),
        })
    hits.sort(key=lambda h: h["distance"])
    return hits


def main():
    if len(sys.argv) < 2:
        print('Usage: python retrieve.py "query string" [k]')
        return
    query = sys.argv[1]
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    for i, hit in enumerate(retrieve(query, k=k), 1):
        extra = ""
        if hit["metadata"].get("course_code"):
            extra = " | course_code=%s" % hit["metadata"]["course_code"]
        print("[%d] distance=%.2f | doc_type=%s%s"
              % (i, hit["distance"], hit["doc_type"], extra))
        print("    source: %s" % hit["source_url"])
        print("    ---")
        print("    %s" % hit["text"][:300].replace("\n", "\n    "))
        print()


if __name__ == "__main__":
    main()
