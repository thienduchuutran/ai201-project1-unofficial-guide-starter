"""Milestone 6, step 1: run the 5 planning.md questions end-to-end.

For each question this records the top-5 retrieval hits (doc_type, distance,
chunk_id) and the full generated answer with sources, then writes everything
to data/eval_results.json so the README evaluation report can quote it.

Run as: python run_eval.py
"""

import json
import os
import sys

from query import ask
from retrieve import retrieve

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(PIPELINE_DIR, "data", "eval_results.json")

# The 5 questions and expected answers from planning.md, verbatim.
QUESTIONS = [
    ("What GPA and exams do I need before I can take HIST 3900 "
     "(Methods in Teaching History)?",
     "Overall GPA 2.75, 3.0 in major courses, passing MTEL Communication "
     "and Literacy and Subject Area Exam (**** footnote)."),
    ("What are the prerequisites for MATH 1700 Applied Statistics?",
     "Adjusted HS GPA 2.7+ (within two years), OR Accuplacer placement, "
     "OR MATH 0300/0500, OR a credit-bearing math course."),
    ("Is ARAB 2030 offered online in Fall 2026, and how many seats are open?",
     "Yes, online; 13 of 20 available (7 enrolled) as of scrape date; "
     "cross-listed with Day CRN 16472 and SGOCE sections."),
    ("Can I get credit for both MATH 1700 and MATH 1800?",
     "No — cross-listed, credit for only one."),
    ("What must Biology Initial Licensure students pass before taking "
     "their footnoted licensure courses?",
     "A Stage I review; ENGL 4700 also requires GPA 2.5 and Stage I Review."),
]


def main():
    results = []
    for n, (question, expected) in enumerate(QUESTIONS, 1):
        print("=" * 70)
        print("Q%d: %s" % (n, question))
        print("=" * 70)

        hits = retrieve(question, k=5)
        print("--- top-5 retrieval ---")
        for i, h in enumerate(hits, 1):
            meta = h["metadata"]
            label = meta.get("course_code") or meta.get("program_name") or ""
            print("[%d] dist=%.3f | %s | %s | %s"
                  % (i, h["distance"], h["doc_type"], h["chunk_id"], label))

        result = ask(question)
        print("--- answer ---")
        print(result["answer"])
        print("--- sources ---")
        for i, s in enumerate(result["sources"], 1):
            print("[%d] %s | %s | as of %s"
                  % (i, s["doc_type"], s["source_url"] or "no url",
                     s["scraped_at"] or "unknown"))
        print()

        results.append({
            "n": n,
            "question": question,
            "expected": expected,
            "retrieval": [
                {"chunk_id": h["chunk_id"], "doc_type": h["doc_type"],
                 "distance": round(h["distance"], 4),
                 "course_code": h["metadata"].get("course_code"),
                 "program_name": h["metadata"].get("program_name")}
                for h in hits
            ],
            "answer": result["answer"],
            "has_sufficient_context": result["has_sufficient_context"],
            "sources": result["sources"],
        })

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("Wrote %s" % OUT_PATH)


if __name__ == "__main__":
    main()
