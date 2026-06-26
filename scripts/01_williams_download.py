"""
Download 14 alphabetic section HTML pages from the Wayback Machine
(2019-01-27 capture of NZETC Williams Dictionary).
Saves to sources/williams/raw/ with a manifest.json.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = (
    "https://web.archive.org/web/20190127031703/"
    "http://nzetc.victoria.ac.nz/tm/scholarly/"
    "tei-WillDict-t1-body-d1-d{n}.html"
)

SECTIONS = [
    (1, "A"), (2, "E"), (3, "H"), (4, "I"), (5, "K"),
    (6, "M"), (7, "N"), (8, "Ng"), (9, "O"), (10, "P"),
    (11, "R"), (12, "T"), (13, "U"), (14, "W"),
]

RAW_DIR = Path(__file__).parent.parent / "sources" / "williams" / "raw"
MANIFEST_PATH = RAW_DIR / "manifest.json"

HEADERS = {"User-Agent": "MaoriDictResearch/1.0 (rich@kaio.co.nz)"}
DELAY_SECONDS = 2


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def download_section(session: requests.Session, n: int, letter: str, manifest: dict) -> dict:
    filename = f"section_{letter}.html"
    filepath = RAW_DIR / filename
    url = BASE_URL.format(n=n)

    if filepath.exists():
        size = filepath.stat().st_size
        print(f"  [skip] {filename} already exists ({size:,} bytes)")
        entry = manifest.get(filename, {})
        entry.setdefault("url", url)
        entry.setdefault("letter", letter)
        entry["file_size"] = size
        return entry

    print(f"  [get]  {url}")
    resp = session.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    filepath.write_bytes(resp.content)
    size = filepath.stat().st_size
    print(f"         saved {filename} ({size:,} bytes)")

    return {
        "url": url,
        "letter": letter,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "file_size": size,
        "http_status": resp.status_code,
    }


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()

    with requests.Session() as session:
        for i, (n, letter) in enumerate(SECTIONS):
            filename = f"section_{letter}.html"
            entry = download_section(session, n, letter, manifest)
            manifest[filename] = entry

            if i < len(SECTIONS) - 1 and not (RAW_DIR / filename).exists():
                time.sleep(DELAY_SECONDS)

    save_manifest(manifest)
    print(f"\nDone. {len(manifest)} entries in manifest.")

    # Verify
    missing = [f"section_{l}.html" for _, l in SECTIONS if not (RAW_DIR / f"section_{l}.html").exists()]
    if missing:
        print(f"WARNING: missing files: {missing}")
    else:
        print("All 14 section files present.")


if __name__ == "__main__":
    main()
