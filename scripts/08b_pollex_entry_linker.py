"""Populate pollex_entry_links — bridge POLLEX cognate sets to dictionary entries.

POLLEX records Māori reflexes (pollex_reflexes.language_slug='maori') but never
points them at the words a user actually looks up. This links each Māori reflex
to every matching `entry` row by macron-neutral headword key
(normalise_search_key), so the app can surface the whole proto-tree
(POLLEX → LPO → ACD ancestry) on a Te Aka / Williams / Papakupu / etc. entry.

Match is exact on the normalised key (ā/aa/a all fold together), confidence 1.0.
A reflex field may hold several comma/slash/semicolon-separated forms; each is
matched independently. One reflex can match several entries (homonyms, multiple
sources) — all are kept.

Usage:
  py scripts/08b_pollex_entry_linker.py              # dry run, print stats
  py scripts/08b_pollex_entry_linker.py --write      # write to DB
  py scripts/08b_pollex_entry_linker.py --write --reset  # clear first, then write
"""

import argparse, re, sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding='utf-8')
from utils import DB_PATH, normalise_search_key

# Split a reflex field into individual forms. '/' is NOT a separator: POLLEX
# uses it to mark a morpheme boundary inside one word, so 'Hoi/hoi' is hoihoi
# and 'Ahu/nga' is ahunga. Splitting on it keyed those to `hoi` and to `ahu`
# plus `nga`, moving an etymology onto words that never had it — 17 `hoi`
# entries carried PN.SOI.3 'Interjection expressing exasperation' while the 9
# `hoihoi` entries glossed 'noisy, deafening, loud' carried none (D33).
# Commas and semicolons do separate: 'Aa/ku, oo/ku' is āku and ōku.
_SPLIT_RE = re.compile(r'[,;]')
# Keep only Māori orthographic letters (incl. macron vowels); drop notes/punct.
# This also removes the '/' inside a part, joining the morphemes back up.
_CLEAN_RE = re.compile(r'[^a-zāēīōū]')


def _reflex_keys(reflex: str) -> set[str]:
    """Yield distinct macron-neutral match keys for a raw reflex field."""
    keys = set()
    for part in _SPLIT_RE.split(reflex or ''):
        part = _CLEAN_RE.sub('', part.lower().strip())
        if len(part) < 2:
            continue
        key = normalise_search_key(part)
        if key:
            keys.add(key)
    return keys


def _build_entry_index(conn: sqlite3.Connection) -> dict:
    """Return {headword_search: [entry_id, ...]} over the unified entry table."""
    idx: dict = {}
    for eid, hs in conn.execute(
        # Loanwords are excluded here for the same reason as in
        # 52_build_etymology_unified: a borrowed word cannot descend from
        # Proto-Polynesian, and the two bridges must agree or the parity
        # test between them is meaningless.
        'SELECT id, headword_search FROM entry '
        'WHERE headword_search IS NOT NULL AND loan_marker IS NULL '
        "  AND COALESCE(part_of_speech, '') NOT LIKE '%loan%' "
        "  AND COALESCE(part_of_speech_en, '') NOT LIKE '%Loan%'"
    ):
        idx.setdefault(hs, []).append(eid)
    return idx


def find_links(conn: sqlite3.Connection) -> list[dict]:
    entry_idx = _build_entry_index(conn)
    seen: set[tuple] = set()
    links: list[dict] = []
    for rid, cs_id, reflex in conn.execute(
        "SELECT id, cognateset_id, reflex FROM pollex_reflexes "
        "WHERE language_slug = 'maori'"
    ):
        for key in _reflex_keys(reflex):
            for eid in entry_idx.get(key, ()):
                dedup = (cs_id, eid)
                if dedup in seen:
                    continue
                seen.add(dedup)
                links.append({
                    'cognateset_id': cs_id,
                    'reflex_id': rid,
                    'entry_id': eid,
                    'match_key': key,
                    'match_method': 'headword_exact',
                    'match_confidence': 1.0,
                })
    return links


def run(write: bool, reset: bool) -> None:
    conn = sqlite3.connect(DB_PATH)

    n_reflex = conn.execute(
        "SELECT COUNT(*) FROM pollex_reflexes WHERE language_slug='maori'"
    ).fetchone()[0]
    print(f'Māori reflexes: {n_reflex}')
    print('Building entry index...')

    links = find_links(conn)

    linked_cs = len({l['cognateset_id'] for l in links})
    linked_entries = len({l['entry_id'] for l in links})
    total_cs = conn.execute('SELECT COUNT(*) FROM pollex_cognatesets').fetchone()[0]
    print(f'\nLinks found: {len(links)}')
    print(f'  distinct cognatesets linked: {linked_cs} / {total_cs}')
    print(f'  distinct entries linked:     {linked_entries}')

    # entries-per-source breakdown
    by_source: dict[str, int] = {}
    src = dict(conn.execute('SELECT id, source_id FROM entry'))
    for l in links:
        s = src.get(l['entry_id'], '?')
        by_source[s] = by_source.get(s, 0) + 1
    print('\nLinks by entry source:')
    for s, n in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f'  {s}: {n}')

    if not write:
        print('\n(dry run — pass --write to persist)')
        conn.close()
        return

    if reset:
        conn.execute('DELETE FROM pollex_entry_links')
        conn.commit()
        print('\nCleared pollex_entry_links.')

    conn.executemany(
        '''INSERT INTO pollex_entry_links
           (cognateset_id, reflex_id, entry_id, match_key, match_method, match_confidence)
           VALUES (:cognateset_id, :reflex_id, :entry_id, :match_key,
                   :match_method, :match_confidence)''',
        links,
    )
    conn.commit()
    final = conn.execute('SELECT COUNT(*) FROM pollex_entry_links').fetchone()[0]
    conn.close()
    print(f'\nInserted. pollex_entry_links now has {final} rows.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true', help='Write results to DB')
    parser.add_argument('--reset', action='store_true', help='Clear table before writing')
    args = parser.parse_args()
    run(args.write, args.reset)
