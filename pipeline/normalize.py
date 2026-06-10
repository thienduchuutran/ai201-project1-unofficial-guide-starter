"""Milestone 3, step 1: normalize raw scraped JSON before chunking.

Reads:  scrapers/data/raw/catalog/program_*.json, course_*.json
        scrapers/data/raw/seats/*.json
Writes: pipeline/data/processed/normalized/program_*.json, course_*.json
        pipeline/data/processed/normalized/seats/*.json

Run as: python normalize.py
"""

import glob
import html
import json
import os
import re

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_CATALOG = os.path.join(PIPELINE_DIR, "..", "scrapers", "data", "raw", "catalog")
RAW_SEATS = os.path.join(PIPELINE_DIR, "..", "scrapers", "data", "raw", "seats")
OUT_DIR = os.path.join(PIPELINE_DIR, "data", "processed", "normalized")

# Fields whose value IS a course code (normalized with the strict rule).
CODE_KEYS = {"course_code", "Course Number"}
# Fields that must never be rewritten by the embedded-code pass.
SKIP_EMBED_KEYS = {"source_url", "scraped_at", "coid", "CRN"}

# Course-code tokens embedded in prose, e.g. "ENGL3500", "CSC-3700", "CSC  3700".
EMBEDDED_CODE_RE = re.compile(r"\b([A-Z]{2,5})[\s\-]*(\d{4})([A-Z]?)\b")

# Counters mutated while walking documents.
stats = {"codes_changed": 0, "seat_fields_nulled": 0}


def clean_string(s):
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_code(code):
    return re.sub(r"[\s\-]+", " ", code).strip().upper()


def normalize_embedded_codes(text):
    def repl(m):
        fixed = "%s %s%s" % (m.group(1), m.group(2), m.group(3))
        if fixed != m.group(0):
            stats["codes_changed"] += 1
        return fixed

    return EMBEDDED_CODE_RE.sub(repl, text)


def transform(obj, key=None):
    """Recursively clean every string; apply code normalization by field kind."""
    if isinstance(obj, str):
        s = clean_string(obj)
        if key in CODE_KEYS:
            fixed = normalize_code(s)
            if fixed != obj:
                stats["codes_changed"] += 1
            return fixed
        if key not in SKIP_EMBED_KEYS:
            s = normalize_embedded_codes(s)
        return s
    if isinstance(obj, list):
        return [transform(v, key) for v in obj]
    if isinstance(obj, dict):
        return {k: transform(v, k) for k, v in obj.items()}
    return obj


def coerce_seat_nulls(row):
    """Empty / TBA / N/A values in a seats row become None (JSON null)."""
    out = {}
    for k, v in row.items():
        if v is None or (isinstance(v, str) and v.strip().upper() in ("", "TBA", "N/A")):
            if v is not None:
                stats["seat_fields_nulled"] += 1
            out[k] = None
        else:
            out[k] = v
    return out


def write_json(path, doc):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(os.path.join(OUT_DIR, "seats"), exist_ok=True)

    files_normalized = 0
    skipped = []

    catalog_files = sorted(glob.glob(os.path.join(RAW_CATALOG, "*.json")))
    print("Normalizing %d catalog files..." % len(catalog_files))
    for i, path in enumerate(catalog_files, 1):
        name = os.path.basename(path)
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
            write_json(os.path.join(OUT_DIR, name), transform(doc))
            files_normalized += 1
        except (json.JSONDecodeError, OSError, KeyError, TypeError) as e:
            print("  SKIP %s: %s" % (name, e))
            skipped.append(name)
        if i % 200 == 0 or i == len(catalog_files):
            print("  %d/%d catalog files done" % (i, len(catalog_files)))

    seat_files = sorted(glob.glob(os.path.join(RAW_SEATS, "*.json")))
    print("Normalizing %d seats files..." % len(seat_files))
    for path in seat_files:
        name = os.path.basename(path)
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
            doc = transform(doc)
            doc["rows"] = [coerce_seat_nulls(r) for r in doc.get("rows", [])]
            write_json(os.path.join(OUT_DIR, "seats", name), doc)
            files_normalized += 1
            print("  %s: %d rows" % (name, len(doc["rows"])))
        except (json.JSONDecodeError, OSError, KeyError, TypeError) as e:
            print("  SKIP %s: %s" % (name, e))
            skipped.append(name)

    print()
    print("=== normalize.py summary ===")
    print("Files normalized:        %d" % files_normalized)
    print("Files skipped (bad):     %d %s" % (len(skipped), skipped if skipped else ""))
    print("Course codes changed:    %d" % stats["codes_changed"])
    print("Seat fields -> null:     %d" % stats["seat_fields_nulled"])
    print("Output: %s" % os.path.abspath(OUT_DIR))


if __name__ == "__main__":
    main()
