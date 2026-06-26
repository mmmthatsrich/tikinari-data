"""
Download all He Pātaka Kupu word pages by numeric ID.
Saves raw HTML to sources/hepataka/raw/{ID}.html.
Tracks valid/not-found IDs in manifest.json.

URL: https://www.hepatakakupu.co.nz/word/{ID}  (IDs 1..15000)
robots.txt: User-agent: * / Disallow: (empty — no restrictions)

Expected: ~5,000–10,000 valid entries from ~15,000 IDs.
Runtime at 3s/req: ~12.5 hours total. Script is fully resumable — stop
and restart at any time; already-saved files and known 404s are skipped.

Usage:
  py 04_hepataka_scrape.py            # full run
  py 04_hepataka_scrape.py --limit 3  # stop after 3 *requests* (test mode)
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "https://www.hepatakakupu.co.nz/word/{id}"
RAW_DIR = Path(__file__).parent.parent / "sources" / "hepataka" / "raw"
MANIFEST_PATH = RAW_DIR / "manifest.json"

HEADERS = {"User-Agent": "MaoriDictResearch/1.0 (rich@kaio.co.nz)"}
DELAY_SECONDS = 3
MAX_ID = 15_000
SAVE_INTERVAL = 50    # persist manifest every N IDs checked
MAX_RETRIES = 3
RETRY_DELAY = 15      # seconds to wait before retrying a failed request


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        "valid_ids": [],
        "not_found_ids": [],
        "errors": {},
        "last_checked_id": 0,
        "stats": {"valid": 0, "not_found": 0, "errors": 0},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


def save_manifest(manifest: dict, valid: set, not_found: set, errors: dict) -> None:
    manifest["valid_ids"] = sorted(valid)
    manifest["not_found_ids"] = sorted(not_found)
    manifest["errors"] = errors
    manifest["stats"] = {
        "valid": len(valid),
        "not_found": len(not_found),
        "errors": len(errors),
    }
    manifest["last_saved"] = datetime.now(timezone.utc).isoformat()
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def fetch_with_retry(session: requests.Session, url: str) -> requests.Response | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
            return resp
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                print(f"    [retry {attempt + 1}/{MAX_RETRIES - 1}] {exc}")
                time.sleep(RETRY_DELAY)
            else:
                print(f"    [error] {exc}")
                return None
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="He Pataka Kupu scraper")
    parser.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Stop after N HTTP requests (skips of already-downloaded files don't count). "
             "Useful for test runs.",
    )
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()

    valid_set = set(manifest["valid_ids"])
    not_found_set = set(manifest["not_found_ids"])
    error_dict = dict(manifest.get("errors", {}))
    last_checked = manifest.get("last_checked_id", 0)

    start_id = last_checked + 1
    limit_note = f" (limit={args.limit})" if args.limit else ""
    print(f"He Pataka Kupu scraper starting at ID {start_id} / {MAX_ID}{limit_note}")
    print(f"Progress so far: {len(valid_set)} valid, {len(not_found_set)} not-found, {len(error_dict)} errors")

    since_save = 0
    requests_made = 0

    with requests.Session() as session:
        for word_id in range(start_id, MAX_ID + 1):
            filepath = RAW_DIR / f"{word_id}.html"

            # Already downloaded — add to valid_set if missing and continue.
            if filepath.exists():
                if word_id not in valid_set:
                    valid_set.add(word_id)
                manifest["last_checked_id"] = word_id
                since_save += 1
                if since_save >= SAVE_INTERVAL:
                    save_manifest(manifest, valid_set, not_found_set, error_dict)
                    since_save = 0
                continue

            # Already known 404 — skip without a request.
            if word_id in not_found_set:
                manifest["last_checked_id"] = word_id
                continue

            url = BASE_URL.format(id=word_id)
            resp = fetch_with_retry(session, url)
            requests_made += 1

            if resp is None:
                error_dict[str(word_id)] = "connection_error"
                print(f"  [error] {word_id}: connection failed after {MAX_RETRIES} retries")

            elif resp.status_code == 404:
                not_found_set.add(word_id)

            elif resp.status_code == 200:
                filepath.write_bytes(resp.content)
                valid_set.add(word_id)
                print(f"  [ok]    {word_id} ({len(resp.content):,} bytes)")

            else:
                error_dict[str(word_id)] = f"http_{resp.status_code}"
                print(f"  [error] {word_id}: HTTP {resp.status_code}")

            manifest["last_checked_id"] = word_id
            since_save += 1

            if word_id % 500 == 0:
                print(f"  ...progress: ID {word_id} | valid={len(valid_set):,} not-found={len(not_found_set):,} errors={len(error_dict)}")

            if since_save >= SAVE_INTERVAL:
                save_manifest(manifest, valid_set, not_found_set, error_dict)
                since_save = 0

            if args.limit and requests_made >= args.limit:
                print(f"  [limit] reached {args.limit} requests -- stopping.")
                break

            time.sleep(DELAY_SECONDS)

    # Final save
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    save_manifest(manifest, valid_set, not_found_set, error_dict)

    print(f"\nDone.")
    print(f"  Valid entries : {len(valid_set):,}")
    print(f"  Not found     : {len(not_found_set):,}")
    print(f"  Errors        : {len(error_dict):,}")


if __name__ == "__main__":
    main()
