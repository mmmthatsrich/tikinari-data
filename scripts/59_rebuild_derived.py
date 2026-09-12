"""Rebuild everything derived from the unified core, in dependency order.

50_build_unified rewrites a source's slice and clears the entry-link tables.
Five things must then run, in this order, and skipping one leaves the app DB
quietly disagreeing with staging:

    52_build_etymology_unified --reset   ETY_* from the raw etymology sources
    08b_pollex_entry_linker --write --reset   POLLEX -> entry bridge
    53_build_word_origin --write         derivation + loan_origin
    54_build_concepts --write            concepts
    60_export_app_db                     the app projection

    py scripts/59_rebuild_derived.py
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
SCRIPTS = Path(__file__).parent

STEPS = [
    ("52_build_etymology_unified.py", ["--reset"]),
    ("08b_pollex_entry_linker.py", ["--write", "--reset"]),
    ("53_build_word_origin.py", ["--write"]),
    ("54_build_concepts.py", ["--write"]),
    ("60_export_app_db.py", []),
]


def main() -> int:
    for name, args in STEPS:
        print(f"\n=== {name} {' '.join(args)} ".ljust(70, "="))
        result = subprocess.run([sys.executable, str(SCRIPTS / name), *args])
        if result.returncode != 0:
            print(f"\nFAILED at {name} — later steps not run.", file=sys.stderr)
            return result.returncode
    print("\nAll derived tables rebuilt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
