"""
Spot-check a random sample of not_found_ids from the Te Aka manifest.
Reports whether each is a true 404, a 200-with-no-def (correct skip),
or a 200-with-word-def (false negative — scraper missed a real entry).

Usage:
  py 04b_te_aka_verify_notfound.py              # sample 20 IDs
  py 04b_te_aka_verify_notfound.py --count 50   # sample 50 IDs
"""

import argparse
import json
import random
import time
from pathlib import Path

import requests

MANIFEST_PATH = Path(__file__).parent.parent / "sources" / "te_aka" / "raw" / "manifest.json"
BASE_URL = "https://maoridictionary.co.nz/word/{id}"
HEADERS = {"User-Agent": "MaoriDictResearch/1.0 (rich@kaio.co.nz)"}
DELAY_SECONDS = 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Te Aka not-found IDs")
    parser.add_argument("--count", type=int, default=20, metavar="N",
                        help="Number of IDs to sample (default: 20)")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    not_found = manifest["not_found_ids"]
    count = min(args.count, len(not_found))
    sample = sorted(random.sample(not_found, count))

    print(f"Sampling {count} of {len(not_found):,} not-found IDs ...\n")

    false_negatives = []

    with requests.Session() as session:
        for word_id in sample:
            url = BASE_URL.format(id=word_id)
            try:
                resp = session.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
            except requests.RequestException as exc:
                print(f"  {word_id:6d}  ERROR  {exc}")
                continue

            has_def = b"word-def" in resp.content

            if resp.status_code == 404:
                kind = "TRUE 404        "
            elif has_def:
                kind = "FALSE NEGATIVE !"
                false_negatives.append(word_id)
            else:
                kind = "200 no-def (ok) "

            print(f"  {word_id:6d}  HTTP {resp.status_code}  {kind}  {url}")
            time.sleep(DELAY_SECONDS)

    print(f"\nDone. {len(false_negatives)} false negatives in this sample.", flush=True)
    if false_negatives:
        print(f"  IDs to re-check: {false_negatives}")


if __name__ == "__main__":
    main()
