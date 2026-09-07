"""
Scrape Te Māra Reo — the Index of Names and every protoform / Māori-name page.

Source: Richard Benton, "Te Māra Reo: The Language Garden", temarareo.org.
Licence: Creative Commons Attribution-Noncommercial 3.0 New Zealand
         (http://creativecommons.org/licenses/by-nc/3.0/nz/) — redistributable
         with attribution for non-commercial use, unlike the Wakareo components.

The index (TMR-Ingoa.html) is a 3-column table — Proto-Polynesian name / Māori
name(s) / species bearing that name — grouped into 14 etymological stages from
Proto-Austronesian through to terms acquired from English. The substance lives in
the pages it links: PPN-*.html (protoform, gloss, etymology chain, reflexes across
Polynesian and wider Austronesian languages) and TMR-*.html (Māori plant name,
definition, etymology, cognates, related names).

Page discovery is driven off the index, so a page added upstream is picked up
without editing this file. The site's own chrome links 19 boilerplate pages from
every page (HOME / ORIGINS / THANKS / …); those are subtracted, except the three
that are also real content pages (TMR-Aka, TMR-Aruhe, TMR-Raupo are linked from
the sidebar as featured names).

No robots.txt is served (404), so nothing is disallowed; the delay below is
politeness, not compliance. ~192 requests at 2s ≈ 7 minutes.

Fully resumable: pages already on disk are skipped; a manifest records what was
fetched and what failed.

Usage:
  py 42_temarareo_scrape.py             # full run
  py 42_temarareo_scrape.py --limit 3   # stop after 3 *requests* (test mode)
  py 42_temarareo_scrape.py --force     # re-download even if present
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import truststore

truststore.inject_into_ssl()

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://www.temarareo.org"
INDEX_PAGE = "TMR-Ingoa.html"

RAW_DIR = Path(__file__).parent.parent / "sources" / "temarareo" / "raw"
MANIFEST_PATH = RAW_DIR / "manifest.json"

HEADERS = {"User-Agent": "MaoriDictResearch/1.0 (rich@kaio.co.nz)"}
DELAY_SECONDS = 2
MAX_RETRIES = 3
RETRY_DELAY = 15

# Site chrome, linked from every page. Subtracted from the discovered link set so
# the crawl stays inside the name pages.
NAV_PAGES = {
    "TMR-Arohaina.html", "TMR-General_Intro.html", "TMR-Hoparatanga.html",
    "TMR-Ingoa.html", "TMR-Kaiwhakahaere.html", "TMR-Koru.html",
    "TMR-Language_Intro.html", "TMR-Locations.html", "TMR-Nga_Mihi.html",
    "TMR-Nga_Puna.html", "TMR-Nga_Rongo.html", "TMR-Tardis.html",
    "TMR-Te_Maara.html", "TMR-Urunga.html", "TMR-Whakapa.html",
    "TMR-Whakapapa.html",
}

HREF_RE = re.compile(r'href="([^"]+)"', re.I)


def discover_pages(index_html: str) -> list[str]:
    """Return the ordered PPN-*/TMR-* content pages linked from the index.

    Anchors (#KKaha) and query strings are stripped, absolute URLs and the site
    chrome dropped, so each page is fetched exactly once.
    """
    found, ordered = set(), []
    for href in HREF_RE.findall(index_html):
        page = href.split("#", 1)[0].split("?", 1)[0].strip()
        if not page or page.startswith(("http://", "https://", "mailto:", "javascript:")):
            continue
        if not re.fullmatch(r"(?:PPN|TMR)-[^/]+\.html", page, re.I):
            continue
        if page in NAV_PAGES or page in found:
            continue
        found.add(page)
        ordered.append(page)
    ordered.sort()
    return ordered


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
    url = f"{BASE}/{page}"
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, headers=HEADERS, timeout=45, allow_redirects=True)
            if resp.status_code == 200:
                # Pages declare utf-8 in a meta tag but the server sends no charset,
                # so requests would otherwise fall back to latin-1 and mangle macrons.
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Te Māra Reo scraper")
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
        # 1. Index — always refetched; it drives discovery and is itself parsed.
        print("Fetching index of names...")
        index_html = fetch(session, INDEX_PAGE)
        requests_made += 1
        if not index_html:
            print("FATAL: could not fetch the index; aborting.")
            sys.exit(1)
        (RAW_DIR / INDEX_PAGE).write_text(index_html, encoding="utf-8")
        if INDEX_PAGE not in fetched:
            manifest["pages"].append(INDEX_PAGE)
            fetched.add(INDEX_PAGE)

        targets = discover_pages(index_html)
        n_ppn = sum(1 for p in targets if p.upper().startswith("PPN"))
        print(f"Discovered {len(targets)} content pages "
              f"({n_ppn} PPN protoform, {len(targets) - n_ppn} TMR name).")

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
