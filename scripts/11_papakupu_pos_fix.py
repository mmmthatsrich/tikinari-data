"""Extract inline part-of-speech markers from papakupu_entries.definition into the
part_of_speech column (reconstruction of the session-38 fixes, re-runnable after a
papakupu re-import).

Only rows with part_of_speech IS NULL are touched. Two marker styles:

  1. Bracketed lowercase POS tokens anywhere in the definition, e.g.
     ``score [n.]`` -> def ``score``, pos ``Noun``;
     ``copy [v.t.] [document etc]`` -> def ``copy [document etc]``, pos ``Verb (transitive)``.
     The one-off malformed ``{Noun phrase]`` token is handled too.
     Domain tags like ``[medicine]`` / ``[tennis]`` are KEPT.

  2. Bare leading abbreviations (Tai Tokerau wordlist style) at the very start, e.g.
     ``u. count ...`` -> def ``count ...``, pos ``Universal``;
     ``v.t. to slice ...`` -> pos ``Verb (transitive)``.
     A lead of two or more abbreviations (``adj., v.i.`` etc.) maps to ``Universal``.

Capitalised inline sense labels ([Noun]/[Verb]/[Adverb]) inside multi-sense
narrative definitions are deliberately NOT touched — they mark per-sense POS.

Dry-run by default; pass --apply to write. A timestamped DB backup is made before
writing. FTS stays in sync via the papakupu_fts_upd trigger.

Usage:
    py scripts/11_papakupu_pos_fix.py            # dry-run
    py scripts/11_papakupu_pos_fix.py --apply    # write changes
"""
import argparse, re, shutil, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH

# --- bracketed POS tokens (case-insensitive) -> canonical POS -------------------
# (pron is intentionally excluded — session 38 left pronoun entries untouched.)
BRACKET_POS = {
    "n.": "Noun", "noun": "Noun",
    "verb": "Verb", "v.": "Verb",
    "v.t.": "Verb (transitive)", "v.i.": "Verb (intransitive)",
    "adj.": "Stative", "adv.": "Universal",
}
BRACKET_RE = re.compile(
    r"\s*\[(" + "|".join(re.escape(k) for k in sorted(BRACKET_POS, key=len, reverse=True)) + r")\]",
    re.IGNORECASE,
)
NOUN_PHRASE_RE = re.compile(r"\{Noun phrase\]\s*")

# --- bare leading abbreviations -------------------------------------------------
# one abbreviation token; the lead is one-or-more of these, comma/space separated.
_TOK = r"(?:v\.t\.|v\.i\.|adj\.?|adv\.|inter\.|[nvu]\.?)"
LEAD_RE = re.compile(r"^(" + _TOK + r"(?:[,\s]+" + _TOK + r")*)\s+(?=\S)")
SINGLE_MAP = {
    "n": "Noun", "v": "Verb", "u": "Universal",
    "adj": "Stative", "adv": "Universal",
    "vt": "Verb (transitive)", "vi": "Verb (intransitive)",
}

# Rows where session 38 deliberately did NOT strip an inline POS marker because it
# sits inside narrative text (matched here by a distinctive definition prefix so the
# guard survives re-import id churn).
SKIP_PREFIXES = (
    "{NGH3] pumice stone",
    "{KOM] Eng. Thursday",
    "< take, takee > [verb] to take leave",
)


def _norm_tok(tok: str) -> str:
    return tok.replace(".", "").strip().lower()


def fix_pos(definition: str):
    """Return (new_def, pos) or (definition, None) if no inline POS marker found."""
    if definition.startswith(SKIP_PREFIXES):
        return definition, None

    # 1. one-off malformed noun-phrase brace
    if NOUN_PHRASE_RE.search(definition):
        return NOUN_PHRASE_RE.sub("", definition, count=1).strip(), "Noun phrase"

    # 2. bare leading abbreviation run (takes precedence over a deep bracket token)
    m = LEAD_RE.match(definition)
    if m:
        toks = [_norm_tok(t) for t in re.split(r"[,\s]+", m.group(1)) if t.strip()]
        pos = SINGLE_MAP[toks[0]] if len(toks) == 1 else "Universal"
        return definition[m.end():].strip(), pos

    # 3. bracketed POS token
    m = BRACKET_RE.search(definition)
    if m:
        pos = BRACKET_POS[m.group(1).lower()]
        return (definition[:m.start()] + definition[m.end():]).strip(), pos

    return definition, None


def run(con):
    rows = con.execute(
        "SELECT id, definition FROM papakupu_entries WHERE part_of_speech IS NULL"
    ).fetchall()
    updates = []
    for id_, d in rows:
        if not d:
            continue
        nd, pos = fix_pos(d)
        if pos is not None:
            updates.append((id_, nd, pos))
    return len(rows), updates


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH)
    scanned, updates = run(con)

    import collections
    dist = collections.Counter(pos for _, _, pos in updates)
    print(f"NULL-pos rows scanned: {scanned}")
    print(f"rows to set POS: {len(updates)}")
    print(f"POS distribution: {dict(dist)}")

    if not args.apply:
        print("\nsample (first 10):")
        for id_, nd, pos in updates[:10]:
            print(f"  id {id_}: [{pos}] {nd[:60]!r}")
        print("\nDRY-RUN. Re-run with --apply to write.")
        con.close()
        return

    backup = Path(str(DB_PATH) + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-posfix")
    shutil.copy2(DB_PATH, backup)
    print(f"\nbackup written: {backup}")

    now = datetime.now(timezone.utc).isoformat()
    con.executemany(
        "UPDATE papakupu_entries SET definition=?, part_of_speech=?, last_updated=? WHERE id=?",
        [(nd, pos, now, id_) for id_, nd, pos in updates],
    )
    con.commit()
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"applied {len(updates)} updates. integrity_check: {integrity}")
    con.close()


if __name__ == "__main__":
    main()
