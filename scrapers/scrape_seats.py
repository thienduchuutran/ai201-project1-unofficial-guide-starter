"""Scrape Fitchburg State's Oracle APEX course schedule (seat availability).

For each semester tab, sets the 'Display' rows-per-page select to its largest
value (5000), clicks Go, and parses the classic report table generically using
the header row as the schema. Falls back to 'Next' pagination if needed.

Outputs data/raw/seats/{semester_slug}.json. Run as: python scrape_seats.py
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

TABS = [
    ("day_fall_2026", "Day Fall 2026", "https://web4.fitchburgstate.edu/apex/f?p=127:2:::NO:::"),
    ("day_spring_2027", "Day Spring 2027", "https://web4.fitchburgstate.edu/apex/f?p=127:14:::NO:::"),
    ("sgoce_fall_2026", "SGOCE Fall 2026", "https://web4.fitchburgstate.edu/apex/f?p=127:4:::NO:::"),
    ("sgoce_spring_2027", "SGOCE Spring 2027", "https://web4.fitchburgstate.edu/apex/f?p=127:15:::NO:::"),
]

OUT_DIR = Path(__file__).parent / "data" / "raw" / "seats"

# Reads the classic report table: header row drives the schema. Rows with a
# single cell (e.g. 'Comments: ...') are merged into the previous row.
PARSE_TABLE_JS = """() => {
    const table = document.querySelector('table.report-standard');
    if (!table) return {headers: [], rows: []};
    const trs = [...table.querySelectorAll('tr')];
    let headers = [];
    const rows = [];
    for (const tr of trs) {
        const ths = [...tr.querySelectorAll('th')];
        if (ths.length > 1) {
            headers = ths.map(th => th.innerText.trim());
            continue;
        }
        const tds = [...tr.querySelectorAll('td')];
        if (tds.length === headers.length && headers.length > 0) {
            const row = {};
            headers.forEach((h, i) => { row[h] = tds[i].innerText.trim(); });
            rows.push(row);
        } else if (tds.length === 1 && rows.length > 0) {
            const text = tds[0].innerText.trim();
            if (text) {
                const sep = text.indexOf(':');
                const key = sep > 0 ? text.slice(0, sep).trim() : 'Extra';
                const val = sep > 0 ? text.slice(sep + 1).trim() : text;
                if (val) rows[rows.length - 1][key] = val;
            }
        }
    }
    return {headers, rows};
}"""


def report_row_count(page):
    return page.locator("table.report-standard tr").count()


def scrape_tab(page, slug, semester, url):
    print(f"  Loading {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)

    rows = []
    used_fallback = False
    try:
        rows_select = page.locator('select[id$="_ROWS"]').first
        options = rows_select.locator("option").all_text_contents()
        largest = max(options, key=lambda o: int(o.strip()))
        print(f"  Setting Display to {largest} and clicking Go")
        rows_select.select_option(largest.strip())
        page.locator('button[id$="_GO"]').first.click()
        page.wait_for_load_state("domcontentloaded", timeout=120000)
        try:
            page.wait_for_load_state("networkidle", timeout=60000)
        except Exception:
            pass
        try:
            # full report should exceed 100 rows; short timeout since small
            # tabs may legitimately have fewer
            page.wait_for_function(
                "document.querySelectorAll('table.report-standard tr').length > 100",
                timeout=15000,
            )
        except Exception:
            pass
        result = page.evaluate(PARSE_TABLE_JS)
        rows = result["rows"]
        print(f"  Parsed {len(rows)} rows (headers: {result['headers']})")
    except Exception as exc:
        print(f"  ! Display/Go path failed ({exc}); falling back to Next pagination")
        used_fallback = True

    if used_fallback or not rows:
        # paginate with the 'Next' link, accumulating rows
        used_fallback = True
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        rows = []
        page_num = 1
        while True:
            result = page.evaluate(PARSE_TABLE_JS)
            rows.extend(result["rows"])
            print(f"  Page {page_num}: accumulated {len(rows)} rows")
            next_link = page.locator('a.t-Button:has-text("Next")').first
            if next_link.count() == 0 or not next_link.is_visible():
                break
            next_link.click()
            page.wait_for_load_state("domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)
            page_num += 1
            if page_num > 200:  # safety stop
                break

    data = {
        "semester": semester,
        "source_url": url,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(rows),
        "rows": rows,
    }
    out_path = OUT_DIR / f"{slug}.json"
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Wrote {out_path} ({len(rows)} rows{', via pagination fallback' if used_fallback else ''})")
    return len(rows)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    counts = {}
    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for idx, (slug, semester, url) in enumerate(TABS, 1):
            print(f"[{idx}/{len(TABS)}] Scraping semester: {semester}")
            try:
                counts[semester] = scrape_tab(page, slug, semester, url)
            except Exception as exc:
                print(f"  ! FAILED {semester}: {exc}")
                failures.append(semester)
        browser.close()

    print("\n===== SUMMARY =====")
    for semester, count in counts.items():
        print(f"{semester}: {count} rows")
    if failures:
        print(f"Failed tabs: {', '.join(failures)}")
    else:
        print("All tabs scraped successfully.")


if __name__ == "__main__":
    main()
