"""Clean papakupu_entries.definition: remove the source code {..} and part-of-speech
[..] tokens that have already been extracted into the source_code / part_of_speech
columns.

Rules (per user decision):
  - Only remove source codes wrapped in {..} and POS-style brackets [Capital+lowercase ..].
    Uppercase example-attribution codes ([TTU], [NGH3]), date codes ([041126]) and
    sense refs ([1]) are KEPT.
  - Only remove the single occurrence whose inner text == the value already stored in the
    column (the first/extracted one). Per-sense markers that were never captured are kept.
  - Leftover separators/whitespace produced by the removal are tidied.

Dry-run by default; pass --apply to write. A timestamped DB backup is made before writing.
FTS stays in sync automatically via the papakupu_fts_upd trigger.

Usage:
    py scripts/09_papakupu_clean_definitions.py            # dry-run, prints stats
    py scripts/09_papakupu_clean_definitions.py --apply    # write changes
"""
import argparse, re, shutil, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH

POS_RE = re.compile(r"\[[A-Z][a-z][^\]]*\]")   # POS-style bracket, e.g. [Noun], [Stative]
BRACE_RE = re.compile(r"\{[^}]*\}")            # source code, e.g. {RK2}, {NKM}


def remove_first_matching(text: str, regex: re.Pattern, value: str) -> tuple[str, bool]:
    """Remove the first regex match whose inner text == value. Returns (text, removed)."""
    for m in regex.finditer(text):
        if m.group(0)[1:-1].strip() == value:
            return text[:m.start()] + text[m.end():], True
    return text, False


def tidy(t: str) -> str:
    t = re.sub(r"[ \t]{2,}", " ", t)     # collapse runs of spaces/tabs (keep newlines)
    t = re.sub(r"^[\s:;,]+", "", t)      # strip leading whitespace / dangling separators
    t = re.sub(r"[ \t]+\n", "\n", t)     # trailing spaces before a newline
    return t.strip()


def clean(definition: str, source_code: str | None, part_of_speech: str | None) -> str:
    new = definition
    if source_code:
        new, _ = remove_first_matching(new, BRACE_RE, source_code)
    if part_of_speech:
        new, _ = remove_first_matching(new, POS_RE, part_of_speech)
    return tidy(new)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT id, definition, source_code, part_of_speech FROM papakupu_entries"
    ).fetchall()

    updates = []      # (new_def, id)
    emptied = []
    for id_, d, sc, pos in rows:
        if d is None:
            continue
        new = clean(d, sc, pos)
        if new != d:
            updates.append((new, id_))
            if not new.strip():
                emptied.append(id_)

    print(f"rows scanned: {len(rows)}")
    print(f"definitions changed: {len(updates)}")
    print(f"definitions emptied (def was only the code): {len(emptied)} -> ids {emptied}")

    if not args.apply:
        print("\nDRY-RUN. Re-run with --apply to write.")
        con.close()
        return

    backup = Path(str(DB_PATH) + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(DB_PATH, backup)
    print(f"\nbackup written: {backup}")

    now = datetime.now(timezone.utc).isoformat()
    con.executemany(
        "UPDATE papakupu_entries SET definition=?, last_updated=? WHERE id=?",
        [(nd, now, i) for nd, i in updates],
    )
    con.commit()

    # verify: no removable token of a kind we deleted should remain as the *extracted* one
    remaining_brace = remaining_pos = 0
    for id_, d, sc, pos in con.execute(
        "SELECT id, definition, source_code, part_of_speech FROM papakupu_entries"
    ).fetchall():
        d = d or ""
        if sc and any(m.group(0)[1:-1].strip() == sc for m in BRACE_RE.finditer(d)):
            remaining_brace += 1
        if pos and any(m.group(0)[1:-1].strip() == pos for m in POS_RE.finditer(d)):
            remaining_pos += 1
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"applied. remaining extracted source tokens: {remaining_brace}, "
          f"remaining extracted POS tokens: {remaining_pos}")
    print(f"integrity_check: {integrity}")
    con.close()


if __name__ == "__main__":
    main()
