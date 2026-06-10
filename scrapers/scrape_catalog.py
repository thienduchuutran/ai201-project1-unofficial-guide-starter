"""Scrape Fitchburg State University's Acalog catalog (Undergraduate Day Programs).

Outputs one JSON per program (data/raw/catalog/program_{poid}.json) and one JSON
per course (data/raw/catalog/course_{coid}.json). Resumable: existing files are
not re-fetched. Run as: python scrape_catalog.py
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

BASE_URL = "https://catalog.fitchburgstate.edu/"
INDEX_URL = BASE_URL + "content.php?catoid=53&navoid=3675"
COURSE_URL = BASE_URL + "preview_course_nopop.php?catoid=53&coid={coid}"
PROGRAM_URL = BASE_URL + "preview_program.php?catoid=53&poid={poid}"

OUT_DIR = Path(__file__).parent / "data" / "raw" / "catalog"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

MAX_RETRIES = 2  # never retry more than twice


def norm(text):
    """Collapse whitespace and non-breaking spaces."""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def fetch(url):
    """GET a URL with rate limiting. Returns html text or None on failure."""
    for attempt in range(1 + MAX_RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            time.sleep(1)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            print(f"    ! HTTP error on {url} (attempt {attempt + 1}): {exc}")
            time.sleep(1)
    return None


def owns(core, element):
    """True if `element`'s nearest div.acalog-core ancestor is `core`.

    Acalog nests acalog-core divs; this keeps each paragraph/course in the
    innermost section only.
    """
    parent = element.parent
    while parent is not None:
        if parent is core:
            return True
        if (
            isinstance(parent, Tag)
            and parent.name == "div"
            and "acalog-core" in (parent.get("class") or [])
        ):
            return False
        parent = parent.parent
    return False


def parse_course_li(li):
    """Parse one li.acalog-course into course entry dicts (an li can hold an
    'OR' pair of courses). Footnote = li text left over after removing course
    names and credits (e.g. '***', '(Diverse Perspectives)', 'OR')."""
    entries = []
    leftover = norm(li.get_text(" ", strip=True))
    for a in li.find_all("a", onclick=True):
        m = re.search(r"showCourse\('\d+',\s*'(\d+)'", a["onclick"])
        if not m:
            continue
        coid = m.group(1)
        link_text = norm(a.get_text(" ", strip=True))
        parts = re.split(r"\s+-\s+", link_text, maxsplit=1)
        code = parts[0].strip()
        title = parts[1].strip() if len(parts) > 1 else ""
        # credits live in <strong> tags inside the same wrapping <span>
        credits = ""
        span = a.find_parent("span")
        if span is not None:
            strongs = [norm(s.get_text()) for s in span.find_all("strong")]
            nums = [s for s in strongs if re.match(r"^\d+(\.\d+)?", s)]
            if nums:
                credits = nums[0]
        entries.append({"course_code": code, "course_title": title, "credits": credits, "coid": coid})
        leftover = leftover.replace(link_text, "", 1)
    leftover = re.sub(r"\d+(\.\d+)?\s*Credit\(s\)", "", leftover)
    footnote = norm(leftover)
    for entry in entries:
        entry["footnote"] = footnote
    return entries


def parse_program(html, url):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1", id="acalog-content")
    name = norm(h1.get_text(" ", strip=True)) if h1 else ""

    if name.endswith("Minor"):
        degree_type = "Minor"
    elif "Certificate" in name:
        degree_type = "Certificate"
    elif "," in name:
        degree_type = name.rsplit(",", 1)[1].strip()
    else:
        degree_type = ""

    cores = soup.select("div.acalog-core")
    department = ""
    faculty = ""
    description = []
    sections = []

    for i, core in enumerate(cores):
        heading_tag = next(
            (h for h in core.find_all(["h2", "h3", "h4"]) if owns(core, h)), None
        )
        heading = norm(heading_tag.get_text(" ", strip=True)) if heading_tag else ""
        paragraphs = [
            norm(p.get_text(" ", strip=True))
            for p in core.find_all("p")
            if owns(core, p) and norm(p.get_text(" ", strip=True))
        ]

        if i == 0:
            # First block: department name, faculty listing, and description.
            department = heading
            table = next((t for t in core.find_all("table") if owns(core, t)), None)
            if table is not None:
                faculty = norm(table.get_text(" ", strip=True))
            description = paragraphs
            continue

        courses = []
        items = []
        for li in core.find_all("li"):
            if not owns(core, li):
                continue
            classes = li.get("class") or []
            if "acalog-course" in classes:
                courses.extend(parse_course_li(li))
            else:
                text = norm(li.get_text(" ", strip=True))
                if text:
                    items.append(text)

        if heading or paragraphs or courses or items:
            sections.append(
                {
                    "heading": heading,
                    "content": paragraphs,
                    "courses": courses,
                    "items": items,
                }
            )

    return {
        "program_name": name,
        "degree_type": degree_type,
        "department": department,
        "faculty": faculty,
        "description": description,
        "requirement_sections": sections,
        "source_url": url,
        "scraped_at": now_iso(),
    }


def parse_course(html, url):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1", id="course_preview_title")
    title_text = norm(h1.get_text(" ", strip=True)) if h1 else ""
    parts = re.split(r"\s+-\s+", title_text, maxsplit=1)
    code = parts[0].strip()
    title = parts[1].strip() if len(parts) > 1 else ""

    block = h1.parent
    credits = ""
    first_strong = block.find("strong")
    if first_strong is not None:
        text = norm(first_strong.get_text())
        if re.match(r"^\d+(\.\d+)?", text):
            credits = text

    # Description: everything after the <hr> separator, in document order.
    hr = block.find("hr")
    desc_parts = []
    started = hr is None
    for node in block.children:
        if node is hr:
            started = True
            continue
        if not started:
            continue
        if isinstance(node, NavigableString):
            desc_parts.append(str(node))
        elif isinstance(node, Tag):
            if node.name == "br":
                desc_parts.append("\n")
            else:
                desc_parts.append(node.get_text(" ", strip=True))
        desc_parts.append(" ")
    description = re.sub(r"[ \t]+", " ", "".join(desc_parts).replace("\xa0", " "))
    description = re.sub(r"\s*\n\s*", "\n", description).strip()

    # Prerequisites: raw text after the 'Prerequisite(s):' label, up to the
    # next blank line (double <br>). Stored raw, not parsed into logic.
    prerequisites = ""
    m = re.search(r"Prerequisite\(s\):\s*(.*?)(?:\n\n|\n(?=[A-Z][a-z]+.*?:)|$)", description, re.S)
    if m:
        prerequisites = norm(m.group(1).split("\n")[0]) or norm(m.group(1))

    return {
        "course_code": code,
        "course_title": title,
        "credits": credits,
        "description": description,
        "prerequisites": prerequisites,
        "source_url": url,
        "scraped_at": now_iso(),
    }


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Fetching program index: {INDEX_URL}")
    html = fetch(INDEX_URL)
    if html is None:
        print("FATAL: could not fetch program index.")
        sys.exit(1)

    soup = BeautifulSoup(html, "html.parser")
    programs = {}  # poid -> name
    for a in soup.select('a[href*="preview_program.php"]'):
        href = a.get("href", "")
        m = re.search(r"poid=(\d+)", href)
        if m and "catoid=53" in href:
            poid = m.group(1)
            programs.setdefault(poid, norm(a.get_text(" ", strip=True)))
    print(f"Found {len(programs)} unique programs.\n")

    coid_codes = {}  # coid -> course_code
    program_stats = {"scraped": 0, "skipped_existing": 0, "failed": 0}

    for idx, (poid, name) in enumerate(programs.items(), 1):
        path = OUT_DIR / f"program_{poid}.json"
        url = PROGRAM_URL.format(poid=poid)
        if path.exists():
            print(f"[{idx}/{len(programs)}] Exists, skipping program: {name}")
            program_stats["skipped_existing"] += 1
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            print(f"[{idx}/{len(programs)}] Scraping program: {name}")
            html = fetch(url)
            if html is None:
                program_stats["failed"] += 1
                continue
            data = parse_program(html, url)
            save_json(path, data)
            program_stats["scraped"] += 1
        # harvest coids (also from previously scraped files, so resume works)
        for section in data.get("requirement_sections", []):
            for course in section.get("courses", []):
                if course.get("coid"):
                    coid_codes.setdefault(course["coid"], course.get("course_code", ""))

    print(f"\nCollected {len(coid_codes)} unique courses across all programs.\n")

    course_stats = {"scraped": 0, "skipped_existing": 0, "failed": 0}
    for idx, (coid, code) in enumerate(sorted(coid_codes.items()), 1):
        path = OUT_DIR / f"course_{coid}.json"
        if path.exists():
            print(f"[{idx}/{len(coid_codes)}] Exists, skipping course: {code} (coid {coid})")
            course_stats["skipped_existing"] += 1
            continue
        print(f"[{idx}/{len(coid_codes)}] Scraping course: {code} (coid {coid})")
        url = COURSE_URL.format(coid=coid)
        html = fetch(url)
        if html is None:
            course_stats["failed"] += 1
            continue
        save_json(path, parse_course(html, url))
        course_stats["scraped"] += 1

    print("\n===== SUMMARY =====")
    print(f"Programs: {program_stats['scraped']} scraped, "
          f"{program_stats['skipped_existing']} already existed, "
          f"{program_stats['failed']} failed")
    print(f"Courses:  {course_stats['scraped']} scraped, "
          f"{course_stats['skipped_existing']} already existed, "
          f"{course_stats['failed']} failed")


if __name__ == "__main__":
    main()
