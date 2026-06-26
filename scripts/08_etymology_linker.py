"""Session 21 — Populate etymology_links table.

Links POLLEX cognatesets to LPO (Proto-Oceanic) and ACD (PAN/PMP) cognatesets
using three tiers:
  Tier 1: same-level form-key exact match, validated by gloss-word overlap
  Tier 2a: ACD form explicitly cited in POLLEX notes
  Tier 2b: LPO POc form explicitly cited in POLLEX notes

Usage:
  py scripts/08_etymology_linker.py              # dry run, print stats
  py scripts/08_etymology_linker.py --write      # write to DB
  py scripts/08_etymology_linker.py --write --reset  # clear first, then write
"""

import argparse, re, sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding='utf-8')
from utils import DB_PATH, normalise_proto_key

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# POLLEX level -> list of (db_name, target_level_key) to try
LEVEL_MAP = {
    'OC': [('lpo', 'POc'), ('acd', 'POC')],
    'AN': [('lpo', 'PAn'), ('acd', 'PAN')],
    'MP': [('lpo', 'PMP'), ('acd', 'PMP')],
    'EO': [('lpo', 'PEOc')],
    'FJ': [('lpo', 'PCP')],
    'CP': [('lpo', 'PCP')],
}

TIER1_GLOSS_THRESHOLD = 0.20  # Jaccard similarity floor for Tier 1 acceptance
TIER2_GLOSS_THRESHOLD = 0.10  # Floor for Tier 2 — lighter but catches clear mismatches
STOPWORDS = frozenset({'a', 'an', 'the', 'of', 'to', 'in', 'is', 'be', 'or',
                       'and', 'for', 'with', 'as', 'by', 'at', 'from', 'on',
                       'into', 'v', 'n', 'adj', 'sp', 'vs'})

# Regex patterns for POLLEX notes citations
# Captures: level-prefix, form, gloss, optional LPO citation tag
_ACD_RE = re.compile(
    r'\b(P[A-Z]+)\s+'        # proto-language label e.g. PAN, PMP, POC
    r'\*?(\S+)\s+'            # reconstructed form (may be asterisk-prefixed)
    r'"([^"]+)"\s*'           # gloss in double quotes
    r'\(ACD\)'                # explicit ACD attribution
)
_LPO_RE = re.compile(
    r'POC?\s+'                # POC or POc label
    r'\*?(\S+)\s+'            # reconstructed form
    r'"([^"]+)"\s*'           # gloss in double quotes
    r'\(LPO\s*([^)]+)\)'      # LPO citation with volume:page
)
# Trailing disambiguation suffix on POLLEX forms: .1  .2  .1A  .A
_DISAMBIG_RE = re.compile(r'\.[0-9]+[A-Za-z]?$')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gloss_words(text: str) -> frozenset:
    return frozenset(re.findall(r'[a-z]+', text.lower())) - STOPWORDS


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _pollex_form_key(protoform_name: str) -> str:
    """POLLEX protoform_name is 'LEVEL.FORM[.N]'. Extract and normalise FORM."""
    form = protoform_name.split('.', 1)[1] if '.' in protoform_name else protoform_name
    form = _DISAMBIG_RE.sub('', form)
    return normalise_proto_key(form)


# ---------------------------------------------------------------------------
# In-memory index builders
# ---------------------------------------------------------------------------

def _build_lpo_index(conn: sqlite3.Connection) -> dict:
    """Return {level: {name_key: [(id, description)]}}."""
    idx: dict = {}
    for row in conn.execute('SELECT id, name_key, level, description FROM lpo_cognatesets'):
        lid, key, level, desc = row
        idx.setdefault(level, {}).setdefault(key, []).append((lid, desc or ''))
    return idx


def _build_acd_index(conn: sqlite3.Connection) -> dict:
    """Return {level: {name_key: [(id, description)]}}."""
    idx: dict = {}
    for row in conn.execute('SELECT id, name_key, level, description FROM acd_cognatesets'):
        aid, key, level, desc = row
        idx.setdefault(level, {}).setdefault(key, []).append((aid, desc or ''))
    return idx


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------

def _best_match(candidates: list[tuple], gloss: str,
                tier: str, confidence: float) -> tuple | None:
    """Pick the highest-gloss-overlap candidate from a list of (id, desc) tuples.

    Returns (id, actual_confidence, tier) or None if no candidate passes threshold.
    Applies a looser threshold for Tier 2 than Tier 1.
    """
    threshold = TIER1_GLOSS_THRESHOLD if tier == 'tier1_formkey' else TIER2_GLOSS_THRESHOLD
    g_words = _gloss_words(gloss)
    best_score = -1.0
    best_id = None
    for cid, cdesc in candidates:
        score = _jaccard(g_words, _gloss_words(cdesc))
        if score > best_score:
            best_score = score
            best_id = cid
    if best_id is None or best_score < threshold:
        return None
    eff_confidence = max(confidence, best_score) if tier == 'tier1_formkey' else confidence
    return (best_id, eff_confidence, tier)


def find_links(pollex_id: str, protoform_name: str, level: str,
               description: str, notes: str,
               lpo_idx: dict, acd_idx: dict) -> list[dict]:
    """Return a list of link dicts for this POLLEX cognateset."""
    desc = description or ''
    notes = notes or ''

    best_lpo: tuple | None = None  # (lpo_id, confidence, method, lpo_citation)
    best_acd: tuple | None = None  # (acd_id, confidence, method)

    # -----------------------------------------------------------------------
    # Tier 1: form-key at mapped level
    # -----------------------------------------------------------------------
    if level in LEVEL_MAP:
        key = _pollex_form_key(protoform_name)
        for db_name, target_level in LEVEL_MAP[level]:
            if db_name == 'lpo':
                candidates = lpo_idx.get(target_level, {}).get(key, [])
                if candidates:
                    result = _best_match(candidates, desc, 'tier1_formkey', 0.85)
                    if result and (best_lpo is None or result[1] > best_lpo[1]):
                        best_lpo = (result[0], result[1], result[2], '')
            elif db_name == 'acd':
                candidates = acd_idx.get(target_level, {}).get(key, [])
                if candidates:
                    result = _best_match(candidates, desc, 'tier1_formkey', 0.85)
                    if result and (best_acd is None or result[1] > best_acd[1]):
                        best_acd = (result[0], result[1], result[2])

    # -----------------------------------------------------------------------
    # Tier 2a: ACD form explicitly cited in notes
    # -----------------------------------------------------------------------
    for m in _ACD_RE.finditer(notes):
        cited_level, cited_form, cited_gloss = m.group(1), m.group(2), m.group(3)
        key = normalise_proto_key(cited_form)
        candidates = acd_idx.get(cited_level, {}).get(key, [])
        if not candidates:
            continue
        result = _best_match(candidates, cited_gloss, 'tier2_acd_citation', 0.9)
        if result and (best_acd is None or result[1] > best_acd[1]):
            best_acd = (result[0], result[1], result[2])

    # -----------------------------------------------------------------------
    # Tier 2b: LPO POc form cited in notes
    # -----------------------------------------------------------------------
    for m in _LPO_RE.finditer(notes):
        cited_form, cited_gloss, lpo_ref = m.group(1), m.group(2), m.group(3).strip()
        key = normalise_proto_key(cited_form)
        candidates = lpo_idx.get('POc', {}).get(key, [])
        if not candidates:
            continue
        result = _best_match(candidates, cited_gloss, 'tier2_lpo_citation', 0.9)
        if result and (best_lpo is None or result[1] > best_lpo[1]):
            best_lpo = (result[0], result[1], result[2], lpo_ref)

    if best_lpo is None and best_acd is None:
        return []

    lpo_id = best_lpo[0] if best_lpo else None
    acd_id = best_acd[0] if best_acd else None

    # Determine method and confidence for the combined row
    methods = []
    if best_lpo:
        methods.append(best_lpo[2])
    if best_acd:
        methods.append(best_acd[2])
    method = '+'.join(sorted(set(methods)))
    confidence = max(
        (best_lpo[1] if best_lpo else 0.0),
        (best_acd[1] if best_acd else 0.0),
    )
    lpo_citation = best_lpo[3] if best_lpo else ''

    return [{
        'pollex_cognateset_id': pollex_id,
        'lpo_cognateset_id': lpo_id,
        'acd_cognateset_id': acd_id,
        'match_confidence': round(confidence, 3),
        'match_method': method,
        'lpo_citation': lpo_citation,
        'notes': None,
    }]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(write: bool, reset: bool) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print('Building LPO index...')
    lpo_idx = _build_lpo_index(conn)
    print('Building ACD index...')
    acd_idx = _build_acd_index(conn)

    pollex_rows = conn.execute(
        'SELECT id, protoform_name, level, description, notes FROM pollex_cognatesets'
    ).fetchall()
    print(f'Processing {len(pollex_rows)} POLLEX cognatesets...')

    all_links: list[dict] = []
    for row in pollex_rows:
        links = find_links(
            row['id'], row['protoform_name'], row['level'],
            row['description'], row['notes'],
            lpo_idx, acd_idx,
        )
        all_links.extend(links)

    # Stats
    lpo_only = sum(1 for l in all_links if l['lpo_cognateset_id'] and not l['acd_cognateset_id'])
    acd_only = sum(1 for l in all_links if l['acd_cognateset_id'] and not l['lpo_cognateset_id'])
    both     = sum(1 for l in all_links if l['lpo_cognateset_id'] and l['acd_cognateset_id'])
    pollex_linked = len({l['pollex_cognateset_id'] for l in all_links})

    print(f'\nLinks found: {len(all_links)} total')
    print(f'  LPO only:  {lpo_only}')
    print(f'  ACD only:  {acd_only}')
    print(f'  Both:      {both}')
    print(f'  POLLEX cognatesets with at least one link: {pollex_linked} / {len(pollex_rows)}')

    by_method: dict[str, int] = {}
    for l in all_links:
        by_method[l['match_method']] = by_method.get(l['match_method'], 0) + 1
    print('\nBy method:')
    for m, n in sorted(by_method.items(), key=lambda x: -x[1]):
        print(f'  {m}: {n}')

    if not write:
        print('\n(dry run — pass --write to persist)')
        conn.close()
        return

    if reset:
        conn.execute('DELETE FROM etymology_links')
        conn.commit()
        print('\nCleared etymology_links.')

    conn.executemany(
        '''INSERT INTO etymology_links
           (pollex_cognateset_id, lpo_cognateset_id, acd_cognateset_id,
            match_confidence, match_method, lpo_citation, notes)
           VALUES (:pollex_cognateset_id, :lpo_cognateset_id, :acd_cognateset_id,
                   :match_confidence, :match_method, :lpo_citation, :notes)''',
        all_links,
    )
    conn.commit()
    final_count = conn.execute('SELECT COUNT(*) FROM etymology_links').fetchone()[0]
    conn.close()
    print(f'\nInserted. etymology_links now has {final_count} rows.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--write',  action='store_true', help='Write results to DB')
    parser.add_argument('--reset',  action='store_true', help='Clear table before writing')
    args = parser.parse_args()
    run(args.write, args.reset)
