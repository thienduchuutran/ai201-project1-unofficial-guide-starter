# Project 1 Planning: The Unofficial Guide

> Write this document before you write any pipeline code.
> Your spec and architecture diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Update the Retrieval Approach and Chunking Strategy sections if you change your approach during implementation.
> Update this file before starting any stretch features.

---

## Domain

<!-- What domain did you choose? Why is this knowledge valuable and hard to find through official channels? -->

Academic advising knowledge for Fitchburg State University: degree program requirements, course descriptions with prerequisites, and live seat availability for upcoming semesters. This knowledge is hard to use through official channels because it is split across two disconnected systems: the Acalog catalog (requirements and prerequisites, with critical advising rules buried in footnotes like "Must have passed a Stage I review" or "overall GPA of 2.75 and passing MTEL scores") and an Oracle APEX schedule app (seat counts and cross-listing caveats hidden in per-row comments). A student planning their semester today has to manually cross-reference catalog footnotes, prerequisite text inside course descriptions, and four separate schedule tabs; this system answers those questions in one place.

---

## Documents

<!-- List your specific sources: URLs, subreddit names, forum threads, or file descriptions.
     Aim for at least 10 sources that together cover different subtopics or perspectives within your domain. -->

| # | Source | Description | URL or location |
|---|--------|-------------|-----------------|
| 1 | Undergraduate Day Programs index (Acalog) | Master list of all 170 undergraduate programs | https://catalog.fitchburgstate.edu/content.php?catoid=53&navoid=3675 |
| 2 | Program pages — 170 scraped | Degree type, department, requirement sections, course lists, footnotes | `https://catalog.fitchburgstate.edu/preview_program.php?catoid=53&poid={poid}` → `scrapers/data/raw/catalog/program_*.json` |
| 3 | Program: Computer Science, B.S. | Core major requirements incl. footnoted capstone (CSC 4100 *) | https://catalog.fitchburgstate.edu/preview_program.php?catoid=53&poid=12796 |
| 4 | Program: History, Secondary Education with Initial Teacher Licensure, B.A. | Licensure course sequence with GPA/MTEL footnotes (`***`, `****`) | https://catalog.fitchburgstate.edu/preview_program.php?catoid=53&poid=12772 |
| 5 | Program: Biology, Initial Licensure: UG Biology concentration, B.A. | Courses footnoted "(Must have passed a Stage I review)" | https://catalog.fitchburgstate.edu/preview_program.php?catoid=53&poid=12848 |
| 6 | Course pages: 989 scraped | Title, credits, full description, raw prerequisite text, cross-listings | `https://catalog.fitchburgstate.edu/preview_course_nopop.php?catoid=53&coid={coid}` → `scrapers/data/raw/catalog/course_*.json` |
| 7 | Course: MATH 1700 Applied Statistics | Placement-based prerequisites; cross-listed with MATH 1800 (credit for only one) | https://catalog.fitchburgstate.edu/preview_course_nopop.php?catoid=53&coid=102364 |
| 8 | Course: ENGL 4700 Teaching Reading and Writing Across the Content Area | Prerequisite: "GPA of 2.5 and Stage I Review." | https://catalog.fitchburgstate.edu/preview_course_nopop.php?catoid=53&coid=102046 |
| 9 | Day Fall 2026 course schedule (Oracle APEX) | 901 sections: seats (actual/max/avail), faculty, times, modality, comments | https://web4.fitchburgstate.edu/apex/f?p=127:2:::NO::: → `scrapers/data/raw/seats/day_fall_2026.json` |
| 10 | Day Spring 2027 course schedule (Oracle APEX) | 841 sections, same schema | https://web4.fitchburgstate.edu/apex/f?p=127:14:::NO::: → `scrapers/data/raw/seats/day_spring_2027.json` |
| 11 | SGOCE Fall 2026 course schedule (Oracle APEX) | 378 evening/online (Grad & Continuing Ed) sections | https://web4.fitchburgstate.edu/apex/f?p=127:4:::NO::: → `scrapers/data/raw/seats/sgoce_fall_2026.json` |
| 12 | SGOCE Spring 2027 course schedule (Oracle APEX) | 314 sections, same schema | https://web4.fitchburgstate.edu/apex/f?p=127:15:::NO::: → `scrapers/data/raw/seats/sgoce_spring_2027.json` |

---

## Chunking Strategy

<!-- How will you split documents into chunks?
     State your chunk size (in tokens or characters), overlap size, and explain why those
     numbers fit the structure of your documents.
     A review-heavy corpus warrants different chunking than a long FAQ. -->

**Chunk size:** Structure-aware, capped at ~400 tokens. One chunk per course JSON (description blocks run ~80–250 tokens — they fit whole). One chunk per requirement *section* of a program JSON (heading + course list + that section's footnotes), with the program name prepended to every chunk. One chunk per schedule row (course section + its comments), prefixed with the semester name.

**Overlap:** 0 tokens between structured chunks. Overlap only applies if a long program description block must be split mid-prose, in which case 50 tokens.

**Reasoning:** The corpus is structured records, not flowing prose — the key facts (a prerequisite, a footnote, a seat count) live in one self-contained record, so fixed-size splitting with overlap would only sever footnote markers (`***`) from the "Note:" definitions that explain them. The chunk boundaries that matter are semantic: a requirement section and its footnote definitions must stay in the same chunk, and a schedule row must keep its comments (cross-listing/seat caveats). Prepending program/semester names compensates for context lost by chunking (a section titled "Core Required Courses" is meaningless without knowing which major it belongs to).

**Seat chunk metadata:** Each seat row chunk must also store `course_code`, `semester`, and `modality` as explicit ChromaDB metadata fields (not just embedded in the text string), enabling metadata-filtered queries like `where={"semester": "day_fall_2026"}` before the vector search. This prevents cross-semester seat rows for the same course from crowding out the target semester in top-k results.

---

## Retrieval Approach

<!-- Which embedding model are you using (e.g., all-MiniLM-L6-v2 via sentence-transformers)?
     How many chunks will you retrieve per query (top-k)?
     If you were deploying this for real users and cost wasn't a constraint, what tradeoffs
     would you weigh in choosing a different embedding model — context length, multilingual
     support, accuracy on domain-specific text, latency? -->

**Embedding model:** `all-MiniLM-L6-v2` via sentence-transformers — free, local, fast, and its 256-token effective window fits my chunk sizes.

**Top-k:** 5 — enough to combine a program section with the relevant course descriptions and a seats row for cross-system questions, without flooding the context with near-duplicate sections from sibling programs.

**Production tradeoff reflection:** With no cost constraint I would weigh: (1) *domain accuracy on terse, code-heavy text* — course codes like "HIST 3900" and abbreviations like "MTEL" are out-of-vocabulary-ish for general models, so a larger model (e.g. text-embedding-3-large or voyage-3) with better subword handling should retrieve more reliably on code-based queries; (2) *context length* — a longer window would let me embed whole programs instead of sections and avoid the program-name-prefix workaround; (3) *latency and hosting* — an API-hosted model adds a network round-trip per query and sends student queries to a third party, while local MiniLM is instant and private; (4) *multilingual support matters little here* since the catalog is English-only. I would not pick a model for benchmark scores alone — I'd re-run my 5 evaluation questions against each candidate, since retrieval of footnote/prerequisite chunks is the bottleneck in this domain. One concrete alternative at the same size/speed tier is `multi-qa-MiniLM-L6-cos-v1`, which was trained on QA pairs rather than sentence similarity; if evaluation shows code-based queries ("prereqs for CSC 3700") retrieving worse than name-based queries ("prereqs for Algorithms and Data Structures"), switching to this model is the first thing to try.

---

## Evaluation Plan

<!-- List your 5 test questions with their expected correct answers.
     Questions should be specific enough that you can judge whether the system's response
     is right or wrong. "What are good dining halls?" is too vague.
     "What do students say about wait times at [dining hall name] during lunch?" is testable. -->

| # | Question | Expected answer |
|---|----------|-----------------|
| 1 | What GPA and exams do I need before I can take HIST 3900 (Methods in Teaching History)? | An overall GPA of 2.75, a 3.0 in the major courses, and a passing score on the MTEL Communication and Literacy and Subject Area Exam (the `****` footnote on HIST 3900 in the History Secondary Ed licensure program). |
| 2 | What are the prerequisites for MATH 1700 Applied Statistics? | Adjusted high school GPA of 2.7+ (within two years of graduation), OR a passing Accuplacer placement score, OR completion of MATH 0300/MATH 0500, OR a credit-bearing math course. |
| 3 | Is ARAB 2030 offered online in Fall 2026, and how many seats are open? | Yes — online modality, 13 of 20 seats available (7 enrolled) as of the scrape date, with the caveat that it is cross-listed with Day CRN 16472 and SGOCE sections, so listed seats may not reflect true availability. |
| 4 | Can I get credit for both MATH 1700 and MATH 1800? | No — they are cross-listed and credit is not awarded for both. |
| 5 | What must Biology Initial Licensure students pass before taking their footnoted licensure courses? | A Stage I review — those courses carry the footnote "(Must have passed a Stage I review)"; the related course ENGL 4700 also requires a GPA of 2.5 and Stage I Review. |

---

## Anticipated Challenges

<!-- What could go wrong? Name at least two specific risks with reasoning.
     Consider: noisy or inconsistent documents, missing source attribution, off-topic
     retrieval, chunks that split key information across boundaries. -->

1. **Footnote markers getting separated from their definitions.** In the catalog, a course line says only `HIST 3900 ****` — the rule it points to ("GPA of 2.75, 3.0 in major, passing MTEL") lives in a separate "Note:" section further down the page. If chunking splits a requirement section from its Note block, retrieval will return the marker without the meaning, and the model will either hallucinate the rule or answer "no information." Mitigation: my chunker keeps each requirement section together and appends the program's Note definitions to every section chunk that contains a footnote marker.

2. **Seat data is a snapshot that decays immediately.** Seat counts (`Actual/Max/Avail`) were true at `scraped_at` and wrong an hour later; worse, the site's own comments warn that cross-listed sections' "seats available may not be a true reflection of the number of open seats." If generation states counts as current facts, answers will be confidently wrong. Mitigation: every seats chunk carries its `scraped_at` timestamp and any cross-listing comment, and the system prompt requires answers about availability to state the as-of date and caveats.

---

## Architecture

<!-- Draw a diagram of your pipeline showing the five stages:
     Document Ingestion → Chunking → Embedding + Vector Store → Retrieval → Generation
     Label each stage with the tool or library you're using.
     You can use ASCII art, a Mermaid diagram, or embed a sketch as an image.
     You'll use this diagram as context when prompting AI tools to implement each stage. -->

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1. DOCUMENT INGESTION                                               │
│    scrapers/scrape_catalog.py  (requests + beautifulsoup4)          │
│    scrapers/scrape_seats.py    (playwright, chromium headless)      │
│    → scrapers/data/raw/catalog/*.json  (170 programs, 989 courses)  │
│    → scrapers/data/raw/seats/*.json    (4 semesters, 2,434 rows)    │
└────────────────────────────┬────────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 2. NORMALIZATION  (plain Python — normalize.py)                     │
│    Standardize course codes: re.sub(r'\s+', ' ', code).upper()      │
│    Strip residual HTML entities from BeautifulSoup output           │
│    Coerce missing/empty seat values to null                         │
│    → consistent input for chunker; prevents same course appearing   │
│      under two string variants in the vector store                  │
└────────────────────────────┬────────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 3. CHUNKING  (plain Python)                                         │
│    course JSON → 1 chunk | program JSON → 1 chunk per requirement   │
│    section (+ Note defs) | seats row → 1 chunk (+ comments)         │
│    every chunk: prefixed context + source_url + scraped_at metadata │
└────────────────────────────┬────────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 4. EMBEDDING + VECTOR STORE                                         │
│    sentence-transformers all-MiniLM-L6-v2 → ChromaDB (local)        │
└────────────────────────────┬────────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 5. RETRIEVAL  (ChromaDB)                                            │
│    embed query → top-k=5 nearest chunks (with source metadata)      │
│    optional metadata pre-filter, e.g. where={"semester": …}         │
└────────────────────────────┬────────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 6. GENERATION                                                       │
│    Claude API; grounded system prompt; cites source_url +           │
│    scraped_at for every claim; refuses beyond retrieved context     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## AI Tool Plan

<!-- For each part of the pipeline below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, which requirements)
     - What you expect it to produce
     - How you'll verify the output matches your spec

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Chunking Strategy section and ask it to implement chunk_text()
     with my specified chunk size and overlap" is a plan. -->

**Milestone 3 — Ingestion and chunking:** Give Claude Code the Chunking Strategy section above plus two sample files (`program_12772.json`, `course_102364.json`) and ask it to implement `normalize.py` alongside `chunk_documents()` producing `{text, source_url, scraped_at, doc_type}` dicts. Verify by spot-checking that the HIST 3900 chunk contains both the `****` marker and the MTEL note text, that no chunk exceeds ~400 tokens, and that "CSC 3700", "CSC3700", and "CSC-3700" all normalize to "CSC 3700". (The scrapers themselves were already built with Claude Code against the Scraper 1/2 spec; I verified their output against live pages — see README AI Usage.)

**Milestone 4 — Embedding and retrieval:** Give Claude Code the Retrieval Approach section and ask for an `embed_and_store.py` (sentence-transformers → ChromaDB) and a `retrieve(query, k=5)` function. Verify by running the 5 evaluation questions and checking the retrieved chunks contain the expected source documents before any generation is wired up — retrieval quality is testable without an LLM.

**Milestone 5 — Generation and interface:** Give Claude the Grounded Generation requirements (cite `source_url` + `scraped_at`, refuse beyond retrieved context, surface seat-count caveats) and ask for the system prompt plus a plain CLI loop. Verify with the evaluation table: each answer must cite a real scraped URL, and question 3's answer must include the as-of date — if it states seat counts as current facts, the grounding instruction failed and gets tightened.
