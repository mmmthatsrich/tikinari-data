"""Translate untranslated POLLEX reflex glosses (Spanish + French) into English.

Some POLLEX source dictionaries gloss their reflexes in the source author's own
language rather than English:
  - Spanish  (Easter Island / Rapanui sources: Englert, Fuentes, Barthel ...)
  - French   (Tahitian, Marquesan, Mangarevan, Wallisian/Futunan sources:
              Lemaitre, Rensch, Bataillon, Rougier ...)

This script replaces each such gloss with a curated English translation (per the
user decision: replace with English only; original kept in git history + the
.bak backup, and always re-derivable from a POLLEX re-import).

Matching is by the EXACT original gloss string (the JSON key), not by row id:
  - idempotent  : once translated, the foreign string is gone, so re-runs no-op
  - re-import-safe: after a POLLEX re-import restores foreign glosses, re-running
                    re-applies the same fix; wire this in after the POLLEX import
                    and before scripts/60_export_app_db.py
  - duplicate-safe: identical (reflex, gloss) rows get the same translation

`pollex_reflexes` has no FTS table / triggers, so a plain UPDATE is sufficient.

Dry-run by default; pass --apply to write. A timestamped DB backup is made first.

Usage:
    py scripts/15_pollex_translate_glosses.py            # dry-run, prints stats
    py scripts/15_pollex_translate_glosses.py --apply    # write changes
"""
import argparse, json, shutil, sqlite3, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH

MAP_PATH = Path(__file__).parent / "pollex_gloss_en.json"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()

    translations: dict[str, str] = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    print(f"curated translations loaded: {len(translations)}")

    con = sqlite3.connect(DB_PATH)

    matched = 0          # rows that will change
    unmatched_keys = []  # curated origs not present in the DB (transcription drift)
    for orig, en in translations.items():
        n = con.execute(
            "SELECT COUNT(*) FROM pollex_reflexes WHERE gloss = ?", (orig,)
        ).fetchone()[0]
        if n == 0:
            unmatched_keys.append(orig)
        else:
            matched += n

    print(f"reflex rows that will be updated: {matched}")
    if unmatched_keys:
        print(f"\nWARNING: {len(unmatched_keys)} curated key(s) matched no row "
              f"(transcription drift — fix the JSON):")
        for k in unmatched_keys:
            print(f"  - {k!r}")

    if not args.apply:
        print("\nDRY-RUN. Re-run with --apply to write.")
        con.close()
        return

    backup = Path(str(DB_PATH) + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(DB_PATH, backup)
    print(f"\nbackup written: {backup}")

    con.executemany(
        "UPDATE pollex_reflexes SET gloss = ? WHERE gloss = ?",
        [(en, orig) for orig, en in translations.items()],
    )
    con.commit()

    # verify: none of the curated originals remain
    remaining = sum(
        con.execute("SELECT COUNT(*) FROM pollex_reflexes WHERE gloss = ?", (orig,)).fetchone()[0]
        for orig in translations
    )
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"applied. remaining untranslated (curated origins still present): {remaining}")
    print(f"integrity_check: {integrity}")
    con.close()


if __name__ == "__main__":
    main()
