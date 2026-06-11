# Demo Video Script (target 3–5 minutes)

Before recording: `python app.py`, open http://localhost:7860, have README.md open in a second window scrolled to the Evaluation Report.

## 0:00 — Intro (~20s)

- "This is the Unofficial Advising Guide for Fitchburg State — a RAG system over 4,576 chunks from the course catalog, 170 program pages, and four semesters of seat data."
- Point at the yellow banner: the UI states up front when seat data was last scraped.

## 0:20 — Query 1, works well end-to-end (~60s)

Ask: **"What GPA and exams do I need before I can take HIST 3900?"**

- Read the answer: overall GPA 2.75, 3.0 in major, passing MTEL.
- Scroll to the sources table — point at the two catalog program URLs and scrape dates. "Every claim is cited; the URLs are attached programmatically from chunk metadata, the LLM never writes them."
- Mention: this rule lives in a `****` footnote far from the course line on the real catalog page — the chunker emits a dedicated course+footnote chunk, which is why it's the top retrieval hit.

## 1:20 — Query 2, seat data + staleness (~50s)

Ask: **"Is ARAB 2030 offered online in Fall 2026, and how many seats are open?"**

- Point at: seat counts come **with the scraped_at date** ("as of 2026-06-10") — the system prompt forbids presenting seat data as current fact.
- Point at the quoted cross-listing caveat ("seats available may not be a true reflection…") — that caveat lives in a per-row comment on the schedule site and the chunker keeps it attached to the row.

## 2:10 — Query 3, cross-system reasoning (~30s)

Ask: **"Can I get credit for both MATH 1700 and MATH 1800?"**

- "No" — quoting cross-listing notes from both the catalog course description and schedule row comments; citations visible in the sources table.

## 2:40 — Failure query, narrated (~60s)

Ask: **"What must Biology Initial Licensure students pass before taking their footnoted licensure courses?"**

Narrate while the answer is on screen:

- "The right answer is 'a Stage I review' — that exact footnote is in the corpus. The system instead gives a generic answer about 'two review processes' and pads with an unrelated grade rule."
- "Why: every program chunk is prefixed with its program name so course-code queries work. But this query names the *program*, so all ~24 sections of the two Biology Licensure programs become near-ties — top-5 distances span 0.200–0.210 and the chunk with the actual footnote ranks 11th at 0.226. The prefix that fixes question 1 breaks question 5."
- "The fix is the same one that already worked for HIST 3900: emit a dedicated chunk pairing each footnoted course with its rule."

## 3:40 — Evaluation report walkthrough (~40s)

Switch to README.md:

- Show the 5-question table: 4 accurate, 1 partially accurate, every row judged against an expected answer written in planning.md before any code existed.
- Show the Failure Case Analysis section: root cause tied to the chunking–embedding interaction, with the rank-11 evidence from `pipeline/data/eval_results.json`.
- Optional close: ask "What's the best pizza place near campus?" to show the exact refusal phrase + insufficient-context warning.

## Checklist (all required moments)

- [ ] ≥3 different queries with source citations visible (Queries 1, 2, 3)
- [ ] One query where retrieval + generation both work well (Query 1)
- [ ] One failing query with narration of what went wrong (Query 4)
- [ ] Brief walkthrough of the evaluation report (README)
- [ ] 3–5 minutes total
