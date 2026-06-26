"""
Scrape Paekupu word pages by subject area and save raw HTML.

Phase 1 (always runs first, ~18 requests):
  Fetches wordlist pages for 9 subject areas x 2 directions.
  URL: https://paekupu.co.nz/words/wordlist/{area-slug}/{direction}
  Parses all <a href="/word/{slug}"> links per page.
  Saves: sources/paekupu/parsed/paekupu_slugs.json
    Format: {"slug": ["area-slug1", "area-slug2", ...], ...}

Phase 2:
  For each unique slug, downloads the word page.
  URL: https://paekupu.co.nz/word/{slug}
  Saves: sources/paekupu/raw/{slug}.html
  Delay: 2 seconds between requests. Fully resumable.

Usage:
  py 04_paekupu_scrape.py            # full run
  py 04_paekupu_scrape.py --limit 5  # Phase 2: stop after 5 requests

robots.txt: paekupu.co.nz returns 404 (no restrictions).
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests
from lxml import html

BASE_URL = "https://paekupu.co.nz"
WORDLIST_URL = BASE_URL + "/words/wordlist/{area_slug}/{direction}"
WORD_URL = BASE_URL + "/word/{slug}"

DIRECTIONS = ["maori-to-english", "english-to-maori"]

# (display_name, primary_slug, fallback_slugs)
# Slugs use macrons exactly as they appear in the site navigation hrefs.
WORDLIST_AREAS = [
    ("Te Reo Matatini",   "te-reo-matatini",     []),
    ("Hauora",            "hauora",               []),
    ("Pangarau",          "pāngarau",             []),
    ("Putaiao",           "pūtaiao",              []),
    ("Hangarau",          "hangarau",             []),
    ("Tikanga a-Iwi",     "tikanga-ā-iwi",        []),
    ("Nga Toi",           "ngā-toi",              []),
    ("Para Kore",         "para-kore",            []),
    ("Matauranga Whanui", "mātauranga-whānui",    []),
]

RAW_DIR = Path(__file__).parent.parent / "sources" / "paekupu" / "raw"
PARSED_DIR = Path(__file__).parent.parent / "sources" / "paekupu" / "parsed"
SLUGS_JSON = PARSED_DIR / "paekupu_slugs.json"

HEADERS = {"User-Agent": "MaoriDictResearch/1.0 (rich@kaio.co.nz)"}
PHASE1_DELAY = 1   # seconds between Phase 1 wordlist requests
PHASE2_DELAY = 2   # seconds between Phase 2 word-page requests
MAX_RETRIES = 3
RETRY_DELAY = 15


def fetch_with_retry(session: requests.Session, url: str) -> "requests.Response | None":
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            return resp
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                print(f"    [retry {attempt + 1}/{MAX_RETRIES - 1}] {exc}")
                time.sleep(RETRY_DELAY)
            else:
                print(f"    [error] {exc}")
                return None
    return None


# ---------------------------------------------------------------------------
# Phase 1: collect word slugs from wordlist pages
# ---------------------------------------------------------------------------

def parse_wordlist_page(raw_html: bytes) -> list:
    """Extract all unique /word/{slug} href values from a wordlist page."""
    doc = html.fromstring(raw_html)
    slugs = []
    for a in doc.xpath("//a[@href]"):
        href = a.get("href", "")
        if href.startswith("/word/"):
            slug = href[len("/word/"):]
            if slug:
                slugs.append(slug)
    return slugs


def run_phase1(session: requests.Session) -> dict:
    """Fetch all wordlist pages; return {word_slug: [area_slugs]} mapping."""
    print("=== Phase 1: wordlist pages ===")
    slug_to_areas: dict = {}

    for display_name, primary_slug, fallbacks in WORDLIST_AREAS:
        area_slugs_to_try = [primary_slug] + fallbacks
        resolved = False

        for area_slug in area_slugs_to_try:
            got_any = False
            for direction in DIRECTIONS:
                url = WORDLIST_URL.format(area_slug=area_slug, direction=direction)
                resp = fetch_with_retry(session, url)
                time.sleep(PHASE1_DELAY)

                if resp is None or resp.status_code != 200:
                    code = resp.status_code if resp is not None else "err"
                    print(f"  [{code}]  {area_slug}/{direction}")
                    continue

                word_slugs = parse_wordlist_page(resp.content)
                for ws in word_slugs:
                    if ws not in slug_to_areas:
                        slug_to_areas[ws] = []
                    if area_slug not in slug_to_areas[ws]:
                        slug_to_areas[ws].append(area_slug)

                print(f"  [ok]    {area_slug}/{direction}: {len(word_slugs)} word links")
                got_any = True

            if got_any:
                resolved = True
                break  # primary slug worked; skip fallbacks

        if not resolved:
            tried = ", ".join(area_slugs_to_try)
            print(f"  [warn]  {display_name}: no wordlist pages found (tried: {tried})")

    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    SLUGS_JSON.write_text(
        json.dumps(slug_to_areas, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(f"\n{len(slug_to_areas):,} unique word slugs -> {SLUGS_JSON}")
    return slug_to_areas


# ---------------------------------------------------------------------------
# Phase 2: download word pages
# ---------------------------------------------------------------------------

def run_phase2(session: requests.Session, slug_to_areas: dict, limit: "int | None") -> None:
    """Download word pages for all slugs; skip already-saved files."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    total = len(slug_to_areas)
    requests_made = 0

    for i, slug in enumerate(sorted(slug_to_areas), 1):
        filepath = RAW_DIR / f"{slug}.html"

        if filepath.exists():
            print(f"  [skip]  {i}/{total}  {slug}")
            continue

        if limit and requests_made >= limit:
            print(f"  [limit] reached {limit} requests -- stopping.")
            break

        url = WORD_URL.format(slug=slug)
        resp = fetch_with_retry(session, url)
        requests_made += 1

        if resp is None:
            print(f"  [error] {slug}: connection failed")
        elif resp.status_code == 404:
            print(f"  [404]   {slug}")
        elif resp.status_code == 200:
            filepath.write_bytes(resp.content)
            print(f"  [ok]    {i}/{total}  {slug} ({len(resp.content):,} bytes)")
        else:
            print(f"  [error] {slug}: HTTP {resp.status_code}")

        time.sleep(PHASE2_DELAY)

    print(f"\nPhase 2: {requests_made} requests made.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Paekupu scraper")
    parser.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Stop Phase 2 after N HTTP requests. Skips of already-downloaded "
             "files do not count. Useful for test runs.",
    )
    args = parser.parse_args()

    limit_note = f" (limit={args.limit})" if args.limit else ""
    print(f"Paekupu scraper starting{limit_note}")

    with requests.Session() as session:
        slug_to_areas = run_phase1(session)
        print(f"\n=== Phase 2: word pages ({len(slug_to_areas):,} unique slugs) ===")
        run_phase2(session, slug_to_areas, args.limit)

    print("\nAll done.")


if __name__ == "__main__":
    main()
