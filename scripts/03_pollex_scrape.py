"""
Scrape Māori reflexes from POLLEX-Online and save raw HTML + parsed JSON.

Phase 1 — Māori listing pages (always runs):
  URL: https://pollex.eva.mpg.de/language/maori/?page={N}  N=1..69
  Saves: sources/pollex/raw/page_{N:03d}.html
  Parses: sources/pollex/parsed/pollex_maori.json
    Fields: protoform, protoform_desc, maori_reflex, maori_gloss,
            source_citation, source_author, pollex_url

Phase 2 — protoform entry pages (only with --entries flag):
  URL: https://pollex.eva.mpg.de/entry/{slug}/  (~2,931 unique pages)
  Saves: sources/pollex/raw/entries/{slug}.html
  Parses: sources/pollex/parsed/pollex_all_reflexes.json
    One record per protoform; each has a 'reflexes' list covering all
    Polynesian languages (Hawaiian, Tongan, Samoan, etc.)
  Runtime: ~147 minutes at 3s/req; fully resumable.

Usage:
  python 03_pollex_scrape.py                      # listing pages only
  python 03_pollex_scrape.py --limit 5            # listing: stop after 5 requests
  python 03_pollex_scrape.py --entries            # listing + all entry pages
  python 03_pollex_scrape.py --entries --limit 5  # entry pages: stop after 5 requests
"""

import argparse
import copy
import json
import re
import time
from pathlib import Path

import requests
from lxml import html

POLLEX_BASE = "https://pollex.eva.mpg.de"
LIST_URL = POLLEX_BASE + "/language/maori/?page={n}"
ENTRY_URL = POLLEX_BASE + "/entry/{slug}/"
TOTAL_PAGES = 69

RAW_DIR = Path(__file__).parent.parent / "sources" / "pollex" / "raw"
ENTRIES_DIR = RAW_DIR / "entries"
PARSED_DIR = Path(__file__).parent.parent / "sources" / "pollex" / "parsed"
MAORI_JSON = PARSED_DIR / "pollex_maori.json"
ALL_REFLEXES_JSON = PARSED_DIR / "pollex_all_reflexes.json"

HEADERS = {"User-Agent": "MaoriDictResearch/1.0 (rich@kaio.co.nz)"}
DELAY_SECONDS = 3
MAX_RETRIES = 3
RETRY_DELAY = 15

# Matches: "Entries for AHO [CE] Breath" -> group 1="Breath"
_PROTO_TITLE_RE = re.compile(r"Entries for \S+ \[\w+\] (.+)")


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
# Phase 1: listing pages
# ---------------------------------------------------------------------------

def _extract_protoform_desc(title: str) -> str:
    """Pull description out of link title attr: 'Entries for AHO [CE] Breath' -> 'Breath'."""
    m = _PROTO_TITLE_RE.match(title)
    return m.group(1).strip() if m else ""


def parse_listing_page(raw_html: bytes, page_num: int) -> list:
    """Parse one Māori listing page; return list of entry dicts."""
    doc = html.fromstring(raw_html)
    # No <tbody> in POLLEX HTML — rows sit directly in <table>; skip header row.
    rows = doc.xpath("//table//tr")[1:]
    entries = []
    for row in rows:
        cells = row.xpath("td")
        if len(cells) < 4:
            continue

        # Column 1: Protoform (link with description in title attr)
        proto_a = cells[0].xpath("a")
        if proto_a:
            protoform = proto_a[0].text_content().strip()
            href = proto_a[0].get("href", "")
            pollex_url = (POLLEX_BASE + href) if href.startswith("/") else href
            protoform_desc = _extract_protoform_desc(proto_a[0].get("title", ""))
        else:
            protoform = cells[0].text_content().strip()
            pollex_url = ""
            protoform_desc = ""

        # Column 2: Māori reflex
        maori_reflex = cells[1].text_content().strip()
        if not maori_reflex:
            continue

        # Column 3: Māori-specific gloss
        maori_gloss = cells[2].text_content().strip()

        # Column 4: Source (short code + author in title attr)
        src_a = cells[3].xpath("a")
        if src_a:
            source_citation = src_a[0].text_content().strip()
            source_author = src_a[0].get("title", "")
        else:
            source_citation = cells[3].text_content().strip().strip("()")
            source_author = ""

        entries.append({
            "protoform": protoform,
            "protoform_desc": protoform_desc,
            "maori_reflex": maori_reflex,
            "maori_gloss": maori_gloss,
            "source_citation": source_citation,
            "source_author": source_author,
            "pollex_url": pollex_url,
            "page": page_num,
        })
    return entries


def download_listing_pages(session: requests.Session, limit: "int | None") -> int:
    """Download all 69 listing pages; return number of requests made."""
    requests_made = 0
    for n in range(1, TOTAL_PAGES + 1):
        filepath = RAW_DIR / f"page_{n:03d}.html"
        if filepath.exists():
            print(f"  [skip]  listing page {n:02d}/{TOTAL_PAGES}")
            continue
        if limit and requests_made >= limit:
            print(f"  [limit] reached {limit} requests -- stopping.")
            break
        url = LIST_URL.format(n=n)
        print(f"  [fetch] listing page {n:02d}/{TOTAL_PAGES}  {url}")
        resp = fetch_with_retry(session, url)
        requests_made += 1
        if resp is None:
            print(f"  [error] page {n}: connection failed")
            continue
        if resp.status_code != 200:
            print(f"  [error] page {n}: HTTP {resp.status_code}")
            continue
        filepath.write_bytes(resp.content)
        print(f"  [ok]    page {n:02d} ({len(resp.content):,} bytes)")
        time.sleep(DELAY_SECONDS)
    return requests_made


def parse_and_save_listings() -> list:
    """Parse all downloaded listing pages; write pollex_maori.json; return entries."""
    print("\nParsing listing pages...")
    all_entries: list = []
    for n in range(1, TOTAL_PAGES + 1):
        filepath = RAW_DIR / f"page_{n:03d}.html"
        if not filepath.exists():
            continue
        entries = parse_listing_page(filepath.read_bytes(), n)
        all_entries.extend(entries)
        print(f"  page {n:3d}: {len(entries):4d} entries")
        if not entries:
            print("           WARNING: no rows found -- check table structure")
    MAORI_JSON.write_text(
        json.dumps(all_entries, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n{len(all_entries):,} Maori entries -> {MAORI_JSON}")
    return all_entries


# ---------------------------------------------------------------------------
# Phase 2: protoform entry pages (cross-language reflexes)
# ---------------------------------------------------------------------------

def _cell_text_no_spans(cell) -> str:
    """Return text content of a cell with <span> children removed (for clean gloss)."""
    cell_copy = copy.deepcopy(cell)
    for span in cell_copy.xpath(".//span"):
        parent = span.getparent()
        if parent is not None:
            parent.remove(span)
    return " ".join(cell_copy.text_content().split())


def parse_entry_page(raw_html: bytes, slug: str) -> dict:
    """Parse one protoform entry page; return dict with metadata and all-language reflexes."""
    doc = html.fromstring(raw_html)

    # Protoform metadata table (first <table> on the page)
    description = ""
    reconstruction = ""
    notes = ""
    meta_rows = doc.xpath("//table[1]/tr")
    for row in meta_rows:
        ths = row.xpath("th/text()")
        tds = row.xpath("td")
        if not ths or not tds:
            continue
        label = ths[0].strip().rstrip(":")
        value = " ".join(tds[0].text_content().split())  # collapse whitespace
        if label == "Description":
            description = value
        elif label == "Reconstruction":
            reconstruction = value
        elif label == "Notes":
            notes = value

    # Language reflexes table (after the "Pollex entries:" heading)
    reflexes = []
    reflex_rows = doc.xpath(
        "//h2[contains(text(), 'Pollex entries')]/following-sibling::table[1]//tr"
    )[1:]  # skip header

    for row in reflex_rows:
        cells = row.xpath("td")
        if len(cells) < 4:
            continue

        # Language name + slug
        lang_a = cells[0].xpath("a")
        if lang_a:
            language = lang_a[0].text_content().strip()
            lang_href = lang_a[0].get("href", "")
            language_slug = lang_href.strip("/").split("/")[-1]
        else:
            language = cells[0].text_content().strip()
            language_slug = ""

        reflex = cells[1].text_content().strip()

        # Gloss: clean text without flag spans; flags captured separately
        gloss = _cell_text_no_spans(cells[2])
        flags = [s.text_content().strip() for s in cells[2].xpath(".//span")]

        # Source code + author
        src_a = cells[3].xpath("a")
        if src_a:
            source_code = src_a[0].text_content().strip()
            source_author = src_a[0].get("title", "")
        else:
            source_code = cells[3].text_content().strip().strip("()")
            source_author = ""

        if not reflex:
            continue

        reflexes.append({
            "language": language,
            "language_slug": language_slug,
            "reflex": reflex,
            "gloss": gloss,
            "source_code": source_code,
            "source_author": source_author,
            "flags": flags,
        })

    return {
        "slug": slug,
        "description": description,
        "reconstruction": reconstruction,
        "notes": notes,
        "reflexes": reflexes,
    }


def collect_entry_slugs(maori_entries: list) -> dict:
    """Return {slug: full_url} for every unique protoform in the Māori listing."""
    slugs: dict = {}
    for entry in maori_entries:
        url = entry.get("pollex_url", "")
        if url:
            slug = url.rstrip("/").split("/")[-1]
            slugs[slug] = url
    return slugs


def download_entry_pages(
    session: requests.Session, slugs: dict, limit: "int | None"
) -> int:
    """Download protoform entry pages; return number of requests made."""
    ENTRIES_DIR.mkdir(parents=True, exist_ok=True)
    total = len(slugs)
    requests_made = 0
    for i, (slug, url) in enumerate(sorted(slugs.items()), 1):
        filepath = ENTRIES_DIR / f"{slug}.html"
        if filepath.exists():
            print(f"  [skip]  entry {i}/{total}  {slug}")
            continue
        if limit and requests_made >= limit:
            print(f"  [limit] reached {limit} requests -- stopping.")
            break
        print(f"  [fetch] entry {i}/{total}  {url}")
        resp = fetch_with_retry(session, url)
        requests_made += 1
        if resp is None:
            print(f"  [error] {slug}: connection failed")
            continue
        if resp.status_code != 200:
            print(f"  [error] {slug}: HTTP {resp.status_code}")
            continue
        filepath.write_bytes(resp.content)
        print(f"  [ok]    {slug} ({len(resp.content):,} bytes)")
        time.sleep(DELAY_SECONDS)
    return requests_made


def parse_and_save_entries(slugs: dict) -> None:
    """Parse all downloaded entry pages; write pollex_all_reflexes.json."""
    print("\nParsing entry pages...")
    all_protoforms: list = []
    parsed = 0
    skipped = 0
    for slug in sorted(slugs):
        filepath = ENTRIES_DIR / f"{slug}.html"
        if not filepath.exists():
            skipped += 1
            continue
        entry = parse_entry_page(filepath.read_bytes(), slug)
        all_protoforms.append(entry)
        parsed += 1
        n_reflexes = len(entry["reflexes"])
        print(f"  {slug:30s}  {n_reflexes:3d} language reflexes", flush=True)

    ALL_REFLEXES_JSON.write_text(
        json.dumps(all_protoforms, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n{parsed:,} protoforms parsed ({skipped} entry pages not yet downloaded)")
    print(f"Saved -> {ALL_REFLEXES_JSON}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="POLLEX Maori reflex scraper")
    parser.add_argument(
        "--entries", action="store_true",
        help="Also download and parse protoform entry pages (cross-language reflexes). "
             "~2,931 pages, ~147 min at 3s/req. Fully resumable.",
    )
    parser.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Stop after N HTTP requests within the active download phase. "
             "Already-downloaded files don't count.",
    )
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PARSED_DIR.mkdir(parents=True, exist_ok=True)

    with requests.Session() as session:
        # Phase 1: listing pages
        print(f"=== Phase 1: Maori listing pages (69 total) ===")
        if not args.entries:
            download_listing_pages(session, args.limit)
        else:
            download_listing_pages(session, None)  # always complete before entries

        maori_entries = parse_and_save_listings()

        # Phase 2: entry pages (opt-in)
        if args.entries:
            slugs = collect_entry_slugs(maori_entries)
            print(f"\n=== Phase 2: protoform entry pages ({len(slugs):,} unique) ===")
            download_entry_pages(session, slugs, args.limit)
            parse_and_save_entries(slugs)


if __name__ == "__main__":
    main()
