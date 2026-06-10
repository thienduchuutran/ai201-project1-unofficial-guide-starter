"""Milestone 3, step 2: chunk normalized JSON into chunks.jsonl.

Reads:  pipeline/data/processed/normalized/  (output of normalize.py)
Writes: pipeline/data/processed/chunks.jsonl (one JSON object per line)

Chunking strategy (see planning.md):
  - one chunk per course JSON
  - one chunk per requirement section of a program JSON; footnote ("Note:")
    definitions are appended to every section chunk in their scope that
    contains a footnote marker (*, **, ***, ****)
  - one chunk per seats row, prefixed with the semester slug

Run as: python chunk.py
"""

import glob
import json
import os
import re

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
NORM_DIR = os.path.join(PIPELINE_DIR, "data", "processed", "normalized")
OUT_PATH = os.path.join(PIPELINE_DIR, "data", "processed", "chunks.jsonl")

TOKEN_LIMIT = 512


def estimate_tokens(text):
    return int(len(text.split()) * 1.3)


def make_chunk(chunk_id, text, doc_type, source_url, scraped_at,
               course_code=None, semester=None, modality=None,
               program_name=None, section_heading=None):
    return {
        "chunk_id": chunk_id,
        "text": text,
        "doc_type": doc_type,
        "source_url": source_url,
        "scraped_at": scraped_at,
        "metadata": {
            "course_code": course_code,
            "semester": semester,
            "modality": modality,
            "program_name": program_name,
            "section_heading": section_heading,
        },
    }


def id_from_url(url, param):
    m = re.search(r"%s=(\d+)" % param, url or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------- courses

def chunk_course(course_json):
    code = course_json.get("course_code") or "Unknown"
    title = course_json.get("course_title") or "Untitled"
    credits = (course_json.get("credits") or "").replace("cr.", "").strip() or "N/A"
    coid = id_from_url(course_json.get("source_url"), "coid") or code.replace(" ", "")

    lines = ["Course: %s — %s (%s credits)" % (code, title, credits)]
    if course_json.get("description"):
        lines.append(course_json["description"])
    lines.append("Prerequisites: %s" % (course_json.get("prerequisites") or "None listed"))
    text = "\n".join(lines)

    est = estimate_tokens(text)
    if est > TOKEN_LIMIT:
        print("  WARNING: course coid=%s (%s) is %d est. tokens (> %d) — kept whole"
              % (coid, code, est, TOKEN_LIMIT))

    return [make_chunk("course_%s_0" % coid, text, "course",
                       course_json.get("source_url"), course_json.get("scraped_at"),
                       course_code=code)]


# ---------------------------------------------------------------- programs

def is_note_section(section):
    return section.get("heading", "").strip().rstrip(":").lower() in ("note", "notes")


def section_lines(section):
    """All body lines of a section: prose content, items, then course lines."""
    lines = list(section.get("content") or [])
    for item in section.get("items") or []:
        if item not in lines:
            lines.append(item)
    for c in section.get("courses") or []:
        line = "%s — %s — %s credits" % (
            c.get("course_code") or "?",
            c.get("course_title") or "?",
            c.get("credits") or "?",
        )
        if c.get("footnote"):
            line += " %s" % c["footnote"]
        lines.append(line)
    return [ln for ln in lines if ln and ln.strip()]


def has_footnote_marker(section):
    """True if any course footnote, content line, or item contains *."""
    for c in section.get("courses") or []:
        if "*" in (c.get("footnote") or ""):
            return True
    for ln in (section.get("content") or []) + (section.get("items") or []):
        if "*" in ln:
            return True
    return False


def build_section_chunks(program_json, section, note_text, header, idx_start,
                         source_url, scraped_at):
    """Assemble one section into 1..N chunks, splitting at line boundaries."""
    heading = section.get("heading", "").strip()
    body = section_lines(section)
    notes_line = "Notes: %s" % (note_text if note_text else "None")
    head_lines = header + ["Section: %s" % heading]

    full_text = "\n".join(head_lines + body + [notes_line])
    if estimate_tokens(full_text) <= TOKEN_LIMIT:
        parts = [body]
    else:
        # Split at course-list / line boundaries, 0 overlap; header and notes
        # are repeated on every part so markers never lose their definitions.
        fixed_cost = estimate_tokens("\n".join(head_lines + [notes_line]))
        parts, current, cost = [], [], fixed_cost
        for ln in body:
            ln_cost = estimate_tokens(ln)
            if current and cost + ln_cost > TOKEN_LIMIT:
                parts.append(current)
                current, cost = [], fixed_cost
            current.append(ln)
            cost += ln_cost
        if current:
            parts.append(current)
        print("  WARNING: section '%s' of '%s' is %d est. tokens (> %d) — split "
              "into %d chunks at line boundaries"
              % (heading, program_json.get("program_name"),
                 estimate_tokens(full_text), TOKEN_LIMIT, len(parts)))

    chunks = []
    poid = id_from_url(source_url, "poid") or "unknown"
    for i, part in enumerate(parts):
        text = "\n".join(head_lines + part + [notes_line])
        chunks.append(make_chunk(
            "program_section_%s_%d" % (poid, idx_start + i), text,
            "program_section", source_url, scraped_at,
            program_name=program_json.get("program_name"),
            section_heading=heading or None))
    return chunks


def chunk_program_section(program_json):
    """One chunk per requirement section; Note definitions are appended to
    every section chunk in their scope that contains a footnote marker.

    A "Note:" section applies to the run of sections that precedes it (that is
    how the catalog pages read). Within that run the note text is appended to
    every section containing a marker; if no section in the run has a marker
    we are unsure, so the notes are appended to every section in the run
    rather than dropped. A marker section whose run has no note block gets
    all note text found anywhere in the program as a fallback.
    """
    sections = program_json.get("requirement_sections") or []
    source_url = program_json.get("source_url")
    scraped_at = program_json.get("scraped_at")
    header = ["Program: %s (%s)" % (program_json.get("program_name") or "Unknown",
                                    program_json.get("degree_type") or "?")]

    # Group sections into runs, each terminated by one or more Note sections.
    runs, current, pending_note = [], [], []
    for s in sections:
        if is_note_section(s):
            pending_note.extend(section_lines(s))
        else:
            if pending_note:
                runs.append((current, "\n".join(pending_note)))
                current, pending_note = [], []
            current.append(s)
    runs.append((current, "\n".join(pending_note) if pending_note else None))

    all_notes = "\n".join(t for _, t in runs if t)

    chunks = []
    idx = 0
    for run_sections, note_text in runs:
        content_sections = [s for s in run_sections
                            if section_lines(s) or s.get("heading", "").strip()]
        if note_text and not content_sections:
            # Orphan note block (nothing precedes it): emit it standalone.
            text = "\n".join(header + ["Section: Note", "Notes: %s" % note_text])
            chunks.append(make_chunk(
                "program_section_%s_%d" % (id_from_url(source_url, "poid") or "unknown", idx),
                text, "program_section", source_url, scraped_at,
                program_name=program_json.get("program_name"),
                section_heading="Note"))
            idx += 1
            continue

        any_marker = any(has_footnote_marker(s) for s in content_sections)
        for s in content_sections:
            if not section_lines(s):
                continue  # heading-only section, nothing to embed
            if note_text:
                applies = note_text if (has_footnote_marker(s) or not any_marker) else None
            else:
                applies = all_notes if (has_footnote_marker(s) and all_notes) else None
            new = build_section_chunks(program_json, s, applies, header, idx,
                                       source_url, scraped_at)
            chunks.extend(new)
            idx += len(new)
    return chunks


# ---------------------------------------------------------------- seats

def chunk_seat_row(row, semester_slug, row_index=0, source_url=None, scraped_at=None):
    code = row.get("Course Number") or "Unknown"
    title = row.get("Course Title") or "Untitled"

    when = " ".join(p for p in (row.get("Days"), row.get("Time")) if p)
    lines = [
        "Semester: %s" % semester_slug,
        "%s — %s | Section %s" % (code, title, row.get("CRN") or "TBA"),
        "Faculty: %s | %s" % (row.get("Faculty") or "TBA", when or "TBA"),
        "Modality: %s | Seats: %s/%s available: %s" % (
            row.get("Modality") or "TBA",
            row.get("Actual") if row.get("Actual") is not None else "TBA",
            row.get("Max") if row.get("Max") is not None else "TBA",
            row.get("Avail") if row.get("Avail") is not None else "TBA"),
    ]
    if row.get("Comments"):
        lines.append(row["Comments"])

    return make_chunk(
        "seat_%s_%d" % (semester_slug, row_index), "\n".join(lines), "seat",
        source_url, scraped_at,
        course_code=row.get("Course Number"),
        semester=semester_slug,
        modality=row.get("Modality"))


def chunk_seats_file(doc, semester_slug):
    """One chunk per row. Continuation rows (extra sections of the same
    course) have a null Course Number — forward-fill from the previous row so
    every chunk carries a filterable course_code."""
    chunks = []
    last_code = None
    for i, row in enumerate(doc.get("rows") or []):
        if row.get("Course Number"):
            last_code = row["Course Number"]
        elif last_code:
            row = dict(row, **{"Course Number": last_code})
        chunks.append(chunk_seat_row(row, semester_slug, row_index=i,
                                     source_url=doc.get("source_url"),
                                     scraped_at=doc.get("scraped_at")))
    return chunks


# ---------------------------------------------------------------- main

def main():
    if not os.path.isdir(NORM_DIR):
        print("ERROR: %s not found — run normalize.py first." % NORM_DIR)
        return

    counts = {"course": 0, "program_section": 0, "seat": 0}
    skipped = []

    with open(OUT_PATH, "w", encoding="utf-8") as out:
        def emit(chunks):
            for c in chunks:
                out.write(json.dumps(c, ensure_ascii=False) + "\n")
                counts[c["doc_type"]] += 1

        course_files = sorted(glob.glob(os.path.join(NORM_DIR, "course_*.json")))
        print("Chunking %d course files..." % len(course_files))
        for i, path in enumerate(course_files, 1):
            try:
                with open(path, encoding="utf-8") as f:
                    emit(chunk_course(json.load(f)))
            except (json.JSONDecodeError, OSError, KeyError, TypeError) as e:
                print("  SKIP %s: %s" % (os.path.basename(path), e))
                skipped.append(os.path.basename(path))
            if i % 200 == 0 or i == len(course_files):
                print("  %d/%d course files done" % (i, len(course_files)))

        program_files = sorted(glob.glob(os.path.join(NORM_DIR, "program_*.json")))
        print("Chunking %d program files..." % len(program_files))
        for i, path in enumerate(program_files, 1):
            try:
                with open(path, encoding="utf-8") as f:
                    emit(chunk_program_section(json.load(f)))
            except (json.JSONDecodeError, OSError, KeyError, TypeError) as e:
                print("  SKIP %s: %s" % (os.path.basename(path), e))
                skipped.append(os.path.basename(path))
            if i % 50 == 0 or i == len(program_files):
                print("  %d/%d program files done" % (i, len(program_files)))

        seat_files = sorted(glob.glob(os.path.join(NORM_DIR, "seats", "*.json")))
        print("Chunking %d seats files..." % len(seat_files))
        for path in seat_files:
            slug = os.path.splitext(os.path.basename(path))[0]
            try:
                with open(path, encoding="utf-8") as f:
                    emit(chunk_seats_file(json.load(f), slug))
                print("  %s done" % os.path.basename(path))
            except (json.JSONDecodeError, OSError, KeyError, TypeError) as e:
                print("  SKIP %s: %s" % (os.path.basename(path), e))
                skipped.append(os.path.basename(path))

    total = sum(counts.values())
    print()
    print("=== chunk.py summary ===")
    for k, v in counts.items():
        print("  %-16s %d" % (k, v))
    print("  total            %d" % total)
    if skipped:
        print("  skipped files:   %s" % skipped)
    print("Output: %s" % os.path.abspath(OUT_PATH))


if __name__ == "__main__":
    main()
