# The Unofficial Guide — Project 1

A retrieval-augmented advising assistant for Fitchburg State University. Ask it "What do I need before I can take HIST 3900?" or "Is ARAB 2030 open in Fall 2026?" and it answers from the scraped course catalog, program requirement pages, and live seat-availability data — with a source URL and scrape date for every claim.

**Run it:** `python app.py` → http://localhost:7860 (Gradio UI), or `python pipeline/query.py "your question"` (CLI). Requires a `GROQ_API_KEY` in `.env`.

---

## Domain

Academic advising knowledge for Fitchburg State University: degree program requirements, course descriptions with prerequisites, and seat availability for upcoming semesters. This knowledge is valuable but hard to use through official channels because it is split across two disconnected systems: the Acalog catalog, where critical advising rules hide in footnotes ("Must have passed a Stage I review", "overall GPA of 2.75 … and passing score on the MTEL"), and an Oracle APEX schedule app, where seat counts and cross-listing caveats sit in per-row comments across four separate semester tabs. Answering a real question like "can I take this course next semester?" requires manually cross-referencing all of them; this system does that in one query.

---

## Document Sources

| # | Source | Type | URL or file path |
|---|--------|------|-----------------|
| 1 | Undergraduate Day Programs index (all 170 programs) | Acalog catalog page | https://catalog.fitchburgstate.edu/content.php?catoid=53&navoid=3675 |
| 2 | Program pages: 170 scraped (requirements, footnotes) | Acalog catalog pages | `preview_program.php?catoid=53&poid={poid}` → `scrapers/data/raw/catalog/program_*.json` |
| 3 | Program: Computer Science, B.S. | Acalog catalog page | https://catalog.fitchburgstate.edu/preview_program.php?catoid=53&poid=12796 |
| 4 | Program: History, Secondary Ed with Initial Teacher Licensure, B.A. (GPA/MTEL footnotes) | Acalog catalog page | https://catalog.fitchburgstate.edu/preview_program.php?catoid=53&poid=12772 |
| 5 | Program: Biology, Initial Licensure, B.A. ("Stage I review" footnotes) | Acalog catalog page | https://catalog.fitchburgstate.edu/preview_program.php?catoid=53&poid=12848 |
| 6 | Course pages — 989 scraped (descriptions, credits, raw prerequisites) | Acalog catalog pages | `preview_course_nopop.php?catoid=53&coid={coid}` → `scrapers/data/raw/catalog/course_*.json` |
| 7 | Course: MATH 1700 Applied Statistics (placement prereqs, cross-listing) | Acalog catalog page | https://catalog.fitchburgstate.edu/preview_course_nopop.php?catoid=53&coid=102364 |
| 8 | Day Fall 2026 schedule: 901 sections (seats, faculty, times, comments) | Oracle APEX report | https://web4.fitchburgstate.edu/apex/f?p=127:2:::NO::: → `scrapers/data/raw/seats/day_fall_2026.json` |
| 9 | Day Spring 2027 schedule: 841 sections | Oracle APEX report | https://web4.fitchburgstate.edu/apex/f?p=127:14:::NO::: → `scrapers/data/raw/seats/day_spring_2027.json` |
| 10 | SGOCE Fall 2026 schedule — 378 sections | Oracle APEX report | https://web4.fitchburgstate.edu/apex/f?p=127:4:::NO::: → `scrapers/data/raw/seats/sgoce_fall_2026.json` |
| 11 | SGOCE Spring 2027 schedule: 314 sections | Oracle APEX report | https://web4.fitchburgstate.edu/apex/f?p=127:15:::NO::: → `scrapers/data/raw/seats/sgoce_spring_2027.json` |

---

## Chunking Strategy

**Chunk size:** Structure-aware, not fixed-size. One chunk per course JSON (descriptions run ~80–250 estimated tokens, so they fit whole). One chunk per requirement *section* of a program page (heading + course list + that section's footnote definitions), split at ~200 estimated tokens (word count × 1.3) at course-line boundaries — never mid-prose — with the program name, section heading, and Note definitions repeated on every part. One chunk per schedule row (course section + its comments), prefixed with the semester name. After the Milestone 4 retrieval eval, each course line carrying a `*`-marker footnote additionally emits a small dedicated chunk pairing that course with its specific Note definition (e.g. "Note for HIST 3900 … (footnote ****): … GPA of 2.75 … MTEL …") — inside a 6-course section chunk that rule ranked ~35th for "HIST 3900 GPA requirement"; as a dedicated chunk it ranks 1st.

**Overlap:** 0 tokens. Oversized program sections split only at course-list line boundaries with headers and Note definitions repeated on every part, so the mid-prose case overlap is meant to protect never arises.

**Why these choices fit your documents:** The corpus is structured records, not flowing prose. The key facts — a prerequisite, a footnote, a seat count — live in one self-contained record, so fixed-size splitting with overlap would only sever footnote markers (`****`) from the "Note:" definitions that explain them, which is exactly the failure mode that matters most in this domain. The boundaries that matter are semantic: a requirement section must keep its footnote definitions, and a schedule row must keep its comments (cross-listing and seat caveats). Prepending program/semester names compensates for context lost by chunking — a section titled "Core Required Courses" is meaningless without knowing which major it belongs to.

**Preprocessing (before chunking, in `pipeline/normalize.py`):** course codes standardized via whitespace collapse + uppercase so "CSC 3700", "CSC3700", and "CSC-3700" all become "CSC 3700"; residual HTML entities from BeautifulSoup stripped; missing/empty seat values coerced to null. Seat chunks also store `course_code`, `semester`, and `modality` as explicit ChromaDB metadata fields, enabling metadata-filtered retrieval (e.g. `where={"semester": "day_fall_2026"}`).

**Final chunk count:** **4,576** chunks in `pipeline/data/processed/chunks.jsonl` — 989 course chunks (one per course), 1,153 program_section chunks (from 170 programs), and 2,434 seat chunks (one per schedule row across 4 semesters).

---

## Embedding Model

**Model used:** `BAAI/bge-small-en-v1.5` via sentence-transformers, cosine space, with the bge "Represent this sentence for searching relevant passages: " prefix on queries (not on passages). This was an evaluation-driven change: the plan started with `all-MiniLM-L6-v2`, which failed the code-heavy evaluation questions — flat ~0.44 distances with no discrimination between relevant and irrelevant chunks, and its 256-token window truncates long program sections before their Note definitions. The planned fallback `multi-qa-MiniLM-L6-cos-v1` fixed two questions but lost the "prereqs for CSC 3700" and "HIST 3900 GPA" spot-checks entirely. `bge-small-en-v1.5` (same size tier, 512-token window) gave the best discrimination — relevant hits land at 0.14–0.26.

**Production tradeoff reflection:** With no cost constraint I would weigh: (1) *domain accuracy on terse, code-heavy text* — course codes like "HIST 3900" and abbreviations like "MTEL" are out-of-vocabulary-ish for general models, so a larger model (text-embedding-3-large, voyage-3) with better subword handling should retrieve more reliably on code-based queries; (2) *context length* — a longer window would let me embed whole programs instead of sections and drop the program-name-prefix workaround (which, as the failure case below shows, has a real cost); (3) *latency and privacy* — an API-hosted model adds a network round-trip per query and sends student queries to a third party, while the local model is instant and private; (4) *multilingual support* matters little since the catalog is English-only. I would not pick on benchmark scores alone — I'd re-run my 5 evaluation questions against each candidate, because retrieval of footnote/prerequisite chunks is the bottleneck in this domain, and that is exactly how the bge switch was made.

---

## Grounded Generation

Generation uses Groq (`llama-3.3-70b-versatile`, temperature 0) in `pipeline/generate.py`.

**System prompt grounding instruction** (the actual rules, abridged from `generate.py`):

> You answer questions ONLY using the provided document excerpts. …
> 3. If the documents do not contain enough information to answer, respond with exactly: "I don't have enough information in my sources to answer that question."
> 4. Never use your training knowledge to fill gaps. If a requirement is not in the provided excerpts, it does not exist for the purposes of your answer.
> 5. For any answer that includes seat counts or availability, you must state the scraped_at date of that data. Seat data goes stale within hours — never present it as current fact.

**Structural mechanisms beyond the prompt:**

- Retrieved chunks are formatted as numbered blocks — `[Source N: doc_type | source_url | As of: scraped_at]` followed by the chunk text — so the model always sees attribution alongside content.
- Insufficient context is detected by **exact string match** on the mandated refusal phrase (rule 3), never by asking the LLM to self-report; the UI prepends a visible "⚠️ INSUFFICIENT CONTEXT" warning when it matches.
- Seat questions trigger a second, metadata-filtered retrieval (`where={"semester": …}`, with the semester slug read from the best-ranked seat hit) merged into the context, so same-semester rows aren't crowded out by other semesters.

**How source attribution is surfaced in the response:** sources are built **programmatically** from the retrieved chunks' metadata — the LLM never produces a URL, so it cannot hallucinate one. The CLI prints a numbered source list (doc_type, URL, scraped_at) under every answer; the Gradio UI renders the same as a sources table and shows a banner with the most recent scrape date of the whole collection.

---

## Evaluation Report

Full transcripts (retrieval rankings, complete answers, sources) are in `pipeline/data/eval_results.json`, produced by `python pipeline/run_eval.py` on 2026-06-11.

| # | Question | Expected answer | System response (summarized) | Retrieval quality | Response accuracy |
|---|----------|-----------------|------------------------------|-------------------|-------------------|
| 1 | What GPA and exams do I need before I can take HIST 3900 (Methods in Teaching History)? | Overall GPA 2.75, 3.0 in major courses, passing MTEL Communication & Literacy and Subject Area Exam (the `****` footnote) | Listed exactly those three requirements; cited both History Secondary Ed licensure program pages (poids 12772, 12770). The dedicated footnote chunks ranked 1–2 (dist 0.17). | Relevant | **Accurate** |
| 2 | What are the prerequisites for MATH 1700 Applied Statistics? | Adjusted HS GPA 2.7+ (within two years) OR Accuplacer placement OR MATH 0300/0500 OR a credit-bearing math course | Quoted the full prerequisite text verbatim, all four OR branches included; cited the MATH 1700 catalog page (top hit, dist 0.14). | Relevant | **Accurate** |
| 3 | Is ARAB 2030 offered online in Fall 2026, and how many seats are open? | Yes — online, 13/20 seats available (7 enrolled), cross-listed with Day CRN 16472 + SGOCE sections, seats may not reflect true availability | "Yes, online" — Day section 16465: 13/20 available; SGOCE 16672: 5/5 available; stated the scraped_at date for each count and quoted the "may not be a true reflection" caveat. All 4 cross-listed seat rows retrieved. | Relevant | **Accurate** |
| 4 | Can I get credit for both MATH 1700 and MATH 1800? | No — cross-listed, credit awarded for only one | "No," quoting three independent cross-listing notes from seat-row comments and the MATH 1700 course description. | Relevant | **Accurate** |
| 5 | What must Biology Initial Licensure students pass before taking their footnoted licensure courses? | A Stage I review — those courses carry "(Must have passed a Stage I review)"; ENGL 4700 also requires GPA 2.5 + Stage I Review | Listed the pre-licensure course sequence, said students "must go through two review processes (Stage I and Stage II)" generically, and added an unrelated 2.0-grade rule. Never stated the footnote rule itself or tied Stage I to the footnoted courses. | Partially relevant | **Partially accurate** |

**Retrieval quality:** Relevant / Partially relevant / Off-target
**Response accuracy:** Accurate / Partially accurate / Inaccurate

---

## Failure Case Analysis

**Question that failed:** Q5 — "What must Biology Initial Licensure students pass before taking their footnoted licensure courses?"

**What the system returned:** All five retrieved chunks were program_section chunks from the right two programs (Biology Initial Licensure B.A. poid 12848 and B.S. poid 12700) — but the wrong *sections* of them: an intro prose section about laboratory skills, the 2.0-minimum-grade rule, and B.S. course lists. The two chunks that actually contain "(Must have passed a Stage I review)" ranked **8th and 11th** (`program_section_12848_9` at 0.2215 and `program_section_12848_8` at 0.2262), outside the top-5 cutoff. The generator then did the best it could with partial context: a generic mention of "two review processes (Stage I and Stage II)" lifted from a B.S. overview section, padded with requirements nobody asked about.

**Root cause (tied to a specific pipeline stage):** This is a chunking–embedding interaction, and specifically the back side of a deliberate design choice. Every program_section chunk gets the program name prepended so that course-code queries (like Q1) can find sections without surrounding context — that fix is why Q1 passes. But Q5 names the *program*, not a course: "Biology Initial Licensure students…" matches the shared prefix that all ~24 section chunks of these two programs carry. The query's strongest term is the one thing every candidate has in common, so distances collapse into a near-tie — the top 5 span 0.2003–0.2104, with the answer chunk at 0.2262, a gap of just 0.026 — and ranking within the program is decided by incidental wording rather than by the Stage I content. A second contributing factor: "Must have passed a Stage I review" is an *inline parenthetical* on a course line, unlike the `*`-marker footnotes which got dedicated course+rule chunks in the Milestone 4 refinement. The Stage I rule's signal stays diluted inside a course-list chunk; the MTEL rule's signal got its own chunk, which is exactly why Q1 succeeds where Q5 fails.

**What you would change to fix it:** Extend the dedicated-footnote-chunk refinement to inline parenthetical notes, so every course line with "(Must have passed a Stage I/II review)" also emits a tiny chunk pairing the course with that rule — the identical fix already moved the HIST 3900 MTEL rule from rank ~35 to rank 1. Secondarily, for queries whose top hits are many near-tied sections of one program, retrieve with a larger k and diversify (maximal marginal relevance), since the near-tie itself is detectable from the distance distribution.

---

## Spec Reflection

**One way the spec helped you during implementation:** Writing the 5 evaluation questions with expected answers *before* any pipeline code turned them into an executable spec, and they directly caught a bad component choice: the planned `all-MiniLM-L6-v2` embedding model looked fine on paper but produced flat ~0.44 distances on the code-heavy questions when the eval was run at Milestone 4 — before generation was even wired up. The planning.md Retrieval Approach section had pre-committed to exactly this procedure ("re-run my 5 evaluation questions against each candidate"), so the model swap to bge-small-en-v1.5 was a planned decision path, not a panic. The same eval drove the chunking refinements (200-token section splits, dedicated footnote chunks).

**One way your implementation diverged from the spec, and why:** The architecture diagram specified the **Claude API** for the generation stage; the implementation uses **Groq with llama-3.3-70b-versatile**. The reason was practical: Groq's free tier covers the whole project's query volume at zero cost, and at temperature 0 with a strict grounding prompt, generation quality is not the bottleneck in this system — retrieval is (as the failure case shows: the only eval miss was a retrieval miss, not a generation miss). The grounding *requirements* from the spec (cite source_url + scraped_at, refuse beyond retrieved context, surface seat caveats) transferred to the Groq implementation unchanged. The chunking spec also drifted in a documented way: the planned 512-token cap and 50-token overlap became 200-token section splits with 0 overlap once the retrieval eval showed multi-course sections embedding too diffusely to rank.

---

## AI Usage

**Instance 1 — chunking pipeline (Milestone 3)**

- *What I gave the AI:* The Chunking Strategy section of planning.md plus two sample scraped files (`program_12772.json`, `course_102364.json`), asking Claude Code to implement `normalize.py` and a `chunk_documents()` producing `{text, source_url, scraped_at, doc_type}` records — one chunk per course, one per program requirement section, one per seat row.
- *What it produced:* A working chunker that kept each requirement section whole up to the spec's 512-token cap, with program names prepended and Note definitions appended to sections containing footnote markers.
- *What I changed or overrode:* After the Milestone 4 retrieval eval, I overrode the 512-token section cap down to ~200 tokens (multi-course sections embedded too diffusely to ever rank in top-5) and directed adding a new chunk type the AI hadn't proposed: dedicated course+footnote chunks pairing each `*`-marked course with its specific Note text. Verified by spot-check: the HIST 3900 chunk had to contain both the `****` marker and the MTEL note text, which is what made eval Q1 pass.

**Instance 2 — embedding and retrieval (Milestone 4)**

- *What I gave the AI:* The Retrieval Approach section of planning.md, asking for `embed.py` (sentence-transformers → ChromaDB) and `retrieve(query, k=5, filters)` with metadata filtering.
- *What it produced:* Working embed/retrieve code using the model the spec named at the time, `all-MiniLM-L6-v2`.
- *What I changed or overrode:* I rejected the model after running the 5 eval questions: MiniLM gave flat ~0.44 distances on code-heavy queries. I tested the spec's planned fallback (`multi-qa-MiniLM-L6-cos-v1` — better on two questions, lost two spot-checks) and then directed the switch to `BAAI/bge-small-en-v1.5`, including a detail the original code lacked: bge requires the "Represent this sentence for searching relevant passages: " prefix on queries but not passages.

**Instance 3 — grounded generation (Milestone 5)**

- *What I gave the AI:* The Grounded Generation requirements (cite source_url + scraped_at, refuse beyond retrieved context, surface seat-count staleness), asking for the system prompt and the generation wrapper.
- *What it produced:* A grounding system prompt and a `generate()` that initially left sufficiency detection and attribution up to the LLM's own output.
- *What I changed or overrode:* I directed two structural changes so grounding doesn't depend on the LLM's honesty: (1) the refusal must be an exact mandated phrase detected by string match — never by asking the model whether it had enough context; (2) sources are built programmatically from chunk metadata, so URLs in the output can never be hallucinated. I also added the seat-question augmentation in `query.py` (second retrieval filtered to the top seat hit's semester) when eval Q3 showed cross-semester rows competing for top-k slots.

---

## Demo Video

See `DEMO_SCRIPT.md` for the shot list. The video shows: three queries with visible source citations (HIST 3900, ARAB 2030 seats, MATH 1700/1800 credit), one query that works end-to-end well (Q1), the failure query (Q5) with narration of the root cause above, and a walkthrough of this evaluation report.
