"""
Scrape the Tregear Maori-Polynesian Comparative Dictionary (1891) from NZETC.

Source: Edward Tregear, "The Maori-Polynesian Comparative Dictionary", Lyon and
Blair, Wellington, 1891. NZETC TEI encoding, CC BY-SA 3.0 NZ.

URL note (verified live 2026-07-01): nzetc.victoria.ac.nz now 302-redirects to the
National Library web-archive (ndhadeliver.natlib.govt.nz). The archived viewer is a
WABAC service-worker frameset (empty body). Raw archived HTML is retrieved by
inserting the pywb `id_` "identity" modifier after the timestamp, e.g.

  https://ndhadeliver.natlib.govt.nz/webarchive/20210104000423id_/http://nzetc.victoria.ac.nz/tm/scholarly/tei-TreMaor-c1-1.html

The dictionary body is 15 letter sections tei-TreMaor-c1-1 .. c1-15
(A E H I K M N NG O P R T U W WH). This scraper reads the table of contents
(tei-TreMaor.html), harvests the c1-* letter links dynamically, and also grabs the
ABBREVIATIONS (f8) and GEOGRAPHICAL/DIALECTICAL REFERENCES (f7-14) reference pages
for the S53 language-name normalisation map. (The b3-* pages are the English->Maori
index, NOT the dictionary — deliberately skipped.)

Only ~17 pages, so this is a short scrape. Fully resumable: already-downloaded pages
are skipped; a manifest records what was fetched.

Usage:
  py 17_tregear_scrape.py            # full run
  py 17_tregear_scrape.py --limit 2  # stop after 2 *requests* (test mode)
  py 17_tregear_scrape.py --force    # re-download even if present
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")

WB_HOST = "https://ndhadeliver.natlib.govt.nz/webarchive"
TIMESTAMP = "20210104000423"
NZETC_BASE = "http://nzetc.victoria.ac.nz/tm/scholarly"
TOC_PAGE = "tei-TreMaor.html"
# Reference pages fetched alongside the dictionary body (used in S53 parse).
REFERENCE_PAGES = ["tei-TreMaor-f8.html", "tei-TreMaor-f7-14.html"]

RAW_DIR = Path(__file__).parent.parent / "sources" / "tregear" / "raw"
MANIFEST_PATH = RAW_DIR / "manifest.json"

HEADERS = {"User-Agent": "MaoriDictResearch/1.0 (rich@kaio.co.nz)"}
DELAY_SECONDS = 3
MAX_RETRIES = 3
RETRY_DELAY = 15


def archived_url(page: str) -> str:
    """Raw (identity) archived URL for a scholarly page via the pywb id_ modifier."""
    return f"{WB_HOST}/{TIMESTAMP}id_/{NZETC_BASE}/{page}"


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        "pages": [],
        "errors": {},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


def save_manifest(manifest: dict) -> None:
    manifest["last_saved"] = datetime.now(timezone.utc).isoformat()
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def fetch(session: requests.Session, page: str) -> str | None:
    url = archived_url(page)
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, headers=HEADERS, timeout=45, allow_redirects=True)
            if resp.status_code == 200:
                resp.encoding = "utf-8"
                return resp.text
            print(f"  [http {resp.status_code}] {page}")
            return None
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                print(f"    [retry {attempt + 1}/{MAX_RETRIES - 1}] {exc}")
                time.sleep(RETRY_DELAY)
            else:
                print(f"    [error] {page}: {exc}")
                return None
    return None


def discover_letter_pages(toc_html: str) -> list[str]:
    """Return the ordered c1-N dictionary letter pages from the table of contents."""
    hrefs = re.findall(r'href="(tei-TreMaor-c1-\d+\.html)"', toc_html)
    seen, ordered = set(), []
    for h in hrefs:
        if h not in seen:
            seen.add(h)
            ordered.append(h)
    ordered.sort(key=lambda p: int(re.search(r"c1-(\d+)", p).group(1)))
    return ordered


def main() -> None:
    parser = argparse.ArgumentParser(description="Tregear (NZETC TEI) scraper")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Stop after N HTTP requests (skips don't count).")
    parser.add_argument("--force", action="store_true",
                        help="Re-download pages even if already saved.")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    fetched = set(manifest["pages"])
    requests_made = 0

    with requests.Session() as session:
        # 1. Table of contents (always refetched — small, drives discovery).
        print("Fetching table of contents...")
        toc_html = fetch(session, TOC_PAGE)
        requests_made += 1
        if not toc_html:
            print("FATAL: could not fetch table of contents; aborting.")
            sys.exit(1)
        (RAW_DIR / TOC_PAGE).write_text(toc_html, encoding="utf-8")
        if TOC_PAGE not in fetched:
            manifest["pages"].append(TOC_PAGE)
            fetched.add(TOC_PAGE)

        letter_pages = discover_letter_pages(toc_html)
        print(f"Discovered {len(letter_pages)} dictionary letter pages: "
              f"{', '.join(letter_pages)}")
        targets = letter_pages + REFERENCE_PAGES

        time.sleep(DELAY_SECONDS)

        for page in targets:
            filepath = RAW_DIR / page
            if filepath.exists() and not args.force:
                if page not in fetched:
                    manifest["pages"].append(page)
                    fetched.add(page)
                print(f"  [skip] {page} (already downloaded)")
                continue

            if args.limit and requests_made >= args.limit:
                print(f"  [limit] reached {args.limit} requests -- stopping.")
                break

            html = fetch(session, page)
            requests_made += 1
            if html is None:
                manifest["errors"][page] = "fetch_failed"
            else:
                filepath.write_bytes(html.encode("utf-8"))
                if page not in fetched:
                    manifest["pages"].append(page)
                    fetched.add(page)
                manifest["errors"].pop(page, None)
                print(f"  [ok]   {page} ({len(html):,} chars)")

            save_manifest(manifest)
            time.sleep(DELAY_SECONDS)

    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    save_manifest(manifest)
    print(f"\nDone. {len(manifest['pages'])} pages on disk, "
          f"{len(manifest['errors'])} errors, {requests_made} requests this run.")


if __name__ == "__main__":
    main()
