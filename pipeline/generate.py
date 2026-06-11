"""Milestone 5, step 1: grounded generation over retrieved chunks via Groq.

Run as: python generate.py  (runs the three grounding verification tests)
"""

import os
import sys

from dotenv import load_dotenv
from groq import Groq

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(PIPELINE_DIR, "..", ".env"))

MODEL_NAME = "llama-3.3-70b-versatile"
# Exact refusal phrase mandated by rule 3 of the system prompt. Insufficient
# context is detected by matching this string — never by asking the LLM.
REFUSAL_PHRASE = "i don't have enough information in my sources"

SYSTEM_PROMPT = """You are an academic advising assistant for Fitchburg State University.
You answer questions ONLY using the provided document excerpts.
Rules you must follow without exception:
1. If the answer is in the documents, answer precisely and completely.
   Quote specific requirements, GPA thresholds, exam names, and credit
   counts exactly as they appear — do not paraphrase numbers or
   requirements.
2. If the documents contain partial information, answer what you can
   and explicitly state what is missing.
3. If the documents do not contain enough information to answer, respond
   with exactly: "I don't have enough information in my sources to answer
   that question."
4. Never use your training knowledge to fill gaps. If a requirement is
   not in the provided excerpts, it does not exist for the purposes of
   your answer.
5. For any answer that includes seat counts or availability, you must
   state the scraped_at date of that data. Seat data goes stale within
   hours — never present it as current fact.
6. Do not speculate about what requirements "probably" are or what
   students "generally" need to do."""

# Created once, on first generate() call.
_CLIENT = None


def _get_client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = Groq()  # reads GROQ_API_KEY from the environment
    return _CLIENT


def _build_user_message(question: str, chunks: list) -> str:
    blocks = []
    for i, chunk in enumerate(chunks):
        blocks.append(
            "[Source %d: %s | %s\nAs of: %s]\n%s\n---"
            % (
                i + 1,
                chunk["doc_type"],
                chunk["source_url"] or "no url",
                chunk["scraped_at"] or "unknown",
                chunk["text"],
            )
        )
    context_block = "\n".join(blocks)
    return (
        "Here are the relevant document excerpts:\n\n%s\n\n"
        "Answer the question based only on these excerpts.\n\n"
        "Question: %s" % (context_block, question)
    )


def _build_sources(chunks: list) -> list:
    sources = []
    for chunk in chunks:
        meta = chunk.get("metadata") or {}
        sources.append({
            "chunk_id": chunk["chunk_id"],
            "doc_type": chunk["doc_type"],
            "source_url": chunk["source_url"],
            "scraped_at": chunk["scraped_at"],
            "snippet": chunk["text"][:120],
            # Extra field for the UI sources table: course_code or
            # program_name from metadata, whichever is non-empty.
            "course_program": meta.get("course_code") or meta.get("program_name") or "",
        })
    return sources


def generate(question: str, chunks: list) -> dict:
    """Answer question grounded only in chunks (as returned by retrieve()).

    Sources are built programmatically from the chunks argument — the LLM
    never produces URLs or attribution.
    """
    response = _get_client().chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(question, chunks)},
        ],
    )
    answer = response.choices[0].message.content or ""
    # Normalize curly apostrophes so the case-insensitive phrase match holds
    # even if the model typesets "don't" as "don’t".
    normalized = answer.lower().replace("’", "'")
    return {
        "answer": answer,
        "sources": _build_sources(chunks),
        "has_sufficient_context": REFUSAL_PHRASE not in normalized,
    }


if __name__ == "__main__":
    from retrieve import retrieve

    # Test 1 — in-scope question.
    chunks = retrieve("What GPA do I need before taking HIST 3900?", k=5)
    result = generate("What GPA do I need before taking HIST 3900?", chunks)
    assert result["has_sufficient_context"] is True
    assert "2.75" in result["answer"] or "MTEL" in result["answer"], \
        "FAIL: answer did not contain expected GPA or exam requirement"
    print("Test 1 PASS:", result["answer"][:200])

    # Test 2 — out-of-scope question.
    chunks = retrieve("What is the best pizza place near campus?", k=5)
    result = generate("What is the best pizza place near campus?", chunks)
    assert result["has_sufficient_context"] is False, \
        "FAIL: system should have declined but produced an answer"
    print("Test 2 PASS: system correctly declined")

    # Test 3 — seat staleness.
    chunks = retrieve("Is ARAB 2030 open in Fall 2026?", k=5)
    result = generate("Is ARAB 2030 open in Fall 2026?", chunks)
    if result["has_sufficient_context"]:
        assert any(
            s["scraped_at"] for s in result["sources"]
            if s["doc_type"] == "seat"
        ), "FAIL: seat answer missing scraped_at in sources"
        assert "scraped" in result["answer"].lower() or \
               "as of" in result["answer"].lower(), \
            "FAIL: answer about seats did not mention data date"
    print("Test 3 PASS")

    print("\nAll grounding tests passed. Ready for Milestone 6.")
