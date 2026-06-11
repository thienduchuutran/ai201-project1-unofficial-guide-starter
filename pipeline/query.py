"""Milestone 5, step 2: ask() — the single end-to-end entry point.

Run as: python query.py "Is ARAB 2030 open in Fall 2026?" [k]
"""

import sys

from generate import generate
from retrieve import retrieve

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _merge_chunks(primary: list, extra: list, k: int) -> list:
    """Dedupe by chunk_id keeping the lower distance, re-sort, take top k."""
    by_id = {}
    for chunk in primary + extra:
        kept = by_id.get(chunk["chunk_id"])
        if kept is None or chunk["distance"] < kept["distance"]:
            by_id[chunk["chunk_id"]] = chunk
    return sorted(by_id.values(), key=lambda c: c["distance"])[:k]


def ask(question: str, k: int = 5) -> dict:
    """Retrieve, augment seat questions with same-semester rows, generate."""
    chunks = retrieve(question, k=k)

    seat_chunks = [c for c in chunks if c["doc_type"] == "seat"]
    if seat_chunks:
        # Semester slug is read from the best-ranked seat hit, not hardcoded:
        # seat chunk text is prefixed with the semester name, so the top seat
        # hit tracks whichever semester the question is actually about.
        best_seat = min(seat_chunks, key=lambda c: c["distance"])
        semester = (best_seat.get("metadata") or {}).get("semester")
        if semester:
            extra = retrieve(question, k=3, filters={"semester": semester})
            chunks = _merge_chunks(chunks, extra, k)

    return generate(question, chunks)


def main():
    if len(sys.argv) < 2:
        print('Usage: python query.py "question" [k]')
        return
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    result = ask(sys.argv[1], k=k)

    print(result["answer"])
    print()
    for i, source in enumerate(result["sources"], 1):
        print("[%d] %s | %s | as of %s"
              % (i, source["doc_type"], source["source_url"] or "no url",
                 source["scraped_at"] or "unknown"))


if __name__ == "__main__":
    main()
