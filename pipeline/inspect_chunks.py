"""Milestone 3, step 3: verify chunks.jsonl before embedding (Milestone 4).

Run as: python inspect_chunks.py
"""

import json
import os
import random
import re
from collections import defaultdict

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
CHUNKS_PATH = os.path.join(PIPELINE_DIR, "data", "processed", "chunks.jsonl")

TAG_RE = re.compile(r"<[^>]+>")
ENTITY_RE = re.compile(r"&amp;|&nbsp;|&#")


def estimate_tokens(text):
    return int(len(text.split()) * 1.3)


def load_chunks():
    chunks = []
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                chunks.append(json.loads(line))
            except json.JSONDecodeError as e:
                print("  WARNING: line %d is not valid JSON: %s" % (line_no, e))
    return chunks


def show_samples(chunks):
    by_type = defaultdict(list)
    for c in chunks:
        by_type[c.get("doc_type")].append(c)
    for doc_type in sorted(by_type):
        sample = random.sample(by_type[doc_type], min(2, len(by_type[doc_type])))
        for c in sample:
            print("-" * 70)
            print("chunk_id: %s   (doc_type: %s)" % (c["chunk_id"], doc_type))
            print(c["text"])
            print("metadata: %s" % json.dumps(c["metadata"], ensure_ascii=False))
    print("-" * 70)


def run_checks(chunks):
    failures = defaultdict(list)

    for c in chunks:
        text = c.get("text") or ""
        meta = c.get("metadata") or {}

        if not text.strip():
            failures["a"].append(c["chunk_id"])
        if TAG_RE.search(text):
            failures["b"].append(c["chunk_id"])
        if ENTITY_RE.search(text):
            failures["c"].append(c["chunk_id"])
        if c.get("doc_type") == "seat":
            if not (meta.get("course_code") and meta.get("semester") and meta.get("modality")):
                failures["d"].append(c["chunk_id"])
        if c.get("doc_type") == "program_section":
            if "*" in text and "note" not in text.lower():
                failures["e"].append(c["chunk_id"])
        if estimate_tokens(text) > 600:
            failures["f"].append(c["chunk_id"])

    if not 1000 <= len(chunks) <= 15000:
        failures["g"].append("total=%d" % len(chunks))

    descriptions = {
        "a": "no chunk has empty text",
        "b": "no chunk text contains a raw HTML tag",
        "c": "no chunk text contains an HTML entity (&amp;, &nbsp;, &#)",
        "d": "every seat chunk has non-null course_code, semester, modality",
        "e": "every program_section chunk with a footnote marker also says Note",
        "f": "no chunk exceeds 600 tokens (words * 1.3)",
        "g": "total chunk count is between 1,000 and 15,000",
    }
    passed = 0
    for key in "abcdefg":
        bad = failures[key]
        status = "FAIL" if bad else "PASS"
        passed += 0 if bad else 1
        print("%s  check %s: %s" % (status, key, descriptions[key]))
        if bad:
            print("      %d offender(s), first 5: %s" % (len(bad), bad[:5]))
    return passed, 7 - passed


def main():
    if not os.path.isfile(CHUNKS_PATH):
        print("ERROR: %s not found — run chunk.py first." % CHUNKS_PATH)
        return
    chunks = load_chunks()

    print("=== chunk counts by doc_type ===")
    by_type = defaultdict(int)
    for c in chunks:
        by_type[c.get("doc_type")] += 1
    for doc_type in sorted(by_type):
        print("  %-16s %d" % (doc_type, by_type[doc_type]))
    print("  total            %d" % len(chunks))

    print()
    print("=== 2 random chunks per doc_type ===")
    show_samples(chunks)

    print()
    print("=== checks ===")
    passed, failed = run_checks(chunks)

    print()
    ready = "YES" if failed == 0 else "NO"
    print("%d chunks total. %d checks passed, %d failed. Ready to embed: %s"
          % (len(chunks), passed, failed, ready))


if __name__ == "__main__":
    main()
