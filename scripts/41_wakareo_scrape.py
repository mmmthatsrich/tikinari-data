"""Download Wakareo ā-ipurangi records by numeric ID.

Wakareo (reotupu.co.nz) is a subscription compilation of 11 dictionaries.
`Browse.aspx?ID={n}` returns ONE record as a plain authenticated GET — no
__VIEWSTATE postback needed for navigation. Every record carries a
`[Reference: WR-XX.n]` tag naming its component, so the sweep routes records
by what they say they are rather than by an assumed ID range.

IDs 1..25578 are the Wordstream Williams Corpus, a duplicate of the existing
NZETC-derived `williams` source. The sweep starts after them, and any record
that still reports WR-WWC is discarded rather than saved.

Credentials come from the gitignored .env via utils.load_env. Access is by
paid subscription plus written permission from Wordstream.

Usage:
  py scripts/41_wakareo_scrape.py                    # full run (~55k requests, ~23h)
  py scripts/41_wakareo_scrape.py --limit 200        # bounded smoke run
  py scripts/41_wakareo_scrape.py --from 47746 --to 47800   # targeted refetch
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# MUST precede `import requests`: Norton Antivirus intercepts TLS on this
# machine, so certifi cannot validate the chain but the Windows store can.
import truststore
truststore.inject_into_ssl()
import requests

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_env
from wakareo_records import split_template

BASE = "https://reotupu.co.nz/WSLiveWakareo/"
LOGIN_URL = BASE + "login.aspx?ReturnUrl=%2fWSLiveWakareo%2f"
RAW_DIR = Path(__file__).parent.parent / "sources" / "wakareo" / "raw"
MANIFEST = RAW_DIR / "manifest.json"

HEADERS = {"User-Agent": "MaoriDictResearch/1.0 (rich@kaio.co.nz)"}
DELAY_SECONDS = 1.5
FIRST_NON_WILLIAMS_ID = 25_579
STOP_AFTER_EMPTY = 50          # consecutive empties => end of the ID space
SAVE_INTERVAL = 50
MAX_RETRIES = 3
RETRY_DELAY = 15

_HIDDEN = re.compile(r'(?is)<input[^>]*type="hidden"[^>]*>')


def _hidden_fields(html: str) -> dict:
    out = {}
    for tag in _HIDDEN.findall(html):
        name = re.search(r'name="([^"]+)"', tag)
        value = re.search(r'value="([^"]*)"', tag)
        if name:
            out[name.group(1)] = value.group(1) if value else ""
    return out


def login() -> requests.Session:
    creds = load_env("WAKAREO_USER", "WAKAREO_PASS")
    session = requests.Session()
    session.headers.update(HEADERS)
    page = session.get(LOGIN_URL, timeout=45)
    page.raise_for_status()
    form = _hidden_fields(page.text)
    form["Login1$UserName"] = creds["WAKAREO_USER"]
    form["Login1$Password"] = creds["WAKAREO_PASS"]
    form["Login1$LoginButton"] = "Log In"
    time.sleep(1)
    landing = session.post(page.url, data=form, timeout=45)
    if "login.aspx" in landing.url.lower():
        raise SystemExit(
            "ERROR: Wakareo login failed. Check WAKAREO_USER / WAKAREO_PASS in .env."
        )
    return session


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {
        "fetched": [], "empty": [], "errors": {},
        "last_id": FIRST_NON_WILLIAMS_ID - 1,
        "tag_counts": {},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


def save_manifest(m: dict, fetched: set, empty: set, errors: dict) -> None:
    m["fetched"] = sorted(fetched)
    m["empty"] = sorted(empty)
    m["errors"] = errors
    m["last_saved"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(m, indent=2), encoding="utf-8")


def fetch(session: requests.Session, entry_id: int):
    """Return (html, session). Re-authenticates once on session expiry."""
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(BASE + f"Browse.aspx?ID={entry_id}", timeout=45)
            if "login.aspx" in r.url.lower():
                print("  session expired — re-authenticating")
                session = login()
                r = session.get(BASE + f"Browse.aspx?ID={entry_id}", timeout=45)
                if "login.aspx" in r.url.lower():
                    raise SystemExit("ERROR: re-login failed; aborting run.")
            r.raise_for_status()
            return r.text, session
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES - 1:
                return None, session
            print(f"  retry {attempt + 1}/{MAX_RETRIES} on ID {entry_id}: {exc}")
            time.sleep(RETRY_DELAY)
    return None, session


def main():
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    ap = argparse.ArgumentParser(description="Scrape Wakareo records by ID.")
    ap.add_argument("--limit", type=int, help="stop after N requests (smoke run)")
    ap.add_argument("--from", dest="start", type=int, help="first ID (default: resume)")
    ap.add_argument("--to", dest="end", type=int, help="last ID (inclusive)")
    args = ap.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    fetched = set(manifest["fetched"])
    empty = set(manifest["empty"])
    errors = dict(manifest["errors"])
    tag_counts = dict(manifest["tag_counts"])

    entry_id = args.start if args.start else manifest["last_id"] + 1
    if entry_id < FIRST_NON_WILLIAMS_ID and not args.start:
        entry_id = FIRST_NON_WILLIAMS_ID

    session = login()
    print(f"Logged in. Sweeping from ID {entry_id}"
          + (f" to {args.end}" if args.end else "")
          + (f" (limit {args.limit})" if args.limit else ""))

    requests_made = 0
    consecutive_empty = 0
    try:
        while True:
            if args.end and entry_id > args.end:
                break
            if args.limit and requests_made >= args.limit:
                break
            if consecutive_empty >= STOP_AFTER_EMPTY:
                print(f"Stopping: {STOP_AFTER_EMPTY} consecutive empty IDs.")
                break

            path = RAW_DIR / f"{entry_id}.html"
            if entry_id in fetched or entry_id in empty:
                entry_id += 1
                continue

            html, session = fetch(session, entry_id)
            requests_made += 1
            time.sleep(DELAY_SECONDS)

            if html is None:
                errors[str(entry_id)] = "request failed"
                entry_id += 1
                continue

            # Route on the record's own WR- tag, via the SAME parser the pipeline
            # uses downstream. Sharing split_template (rather than re-deriving the
            # regex here) is what keeps the Williams discard below exactly aligned
            # with what the parser will later recognise.
            slots = split_template(html)
            if slots is None:
                empty.add(entry_id)
                consecutive_empty += 1
            else:
                tag = slots["ref_tag"]
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
                consecutive_empty = 0
                if tag == "WWC":
                    empty.add(entry_id)        # duplicate source — do not save
                else:
                    path.write_text(html, encoding="utf-8")
                    fetched.add(entry_id)

            manifest["last_id"] = entry_id
            manifest["tag_counts"] = tag_counts
            if requests_made % SAVE_INTERVAL == 0:
                save_manifest(manifest, fetched, empty, errors)
                print(f"  ID {entry_id}: {len(fetched):,} saved, "
                      f"{len(empty):,} skipped, {len(errors)} errors")
            entry_id += 1
    finally:
        save_manifest(manifest, fetched, empty, errors)
        print(f"\nSaved {len(fetched):,} records; skipped {len(empty):,}; "
              f"{len(errors)} errors.")
        print("Tag counts:", json.dumps(tag_counts, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
