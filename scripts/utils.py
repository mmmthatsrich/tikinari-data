import unicodedata, re, sqlite3, hashlib, json
from pathlib import Path

TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
DB_PATH = Path(__file__).parent.parent / "data" / "staging_dictionary.db"

# Regex matches citation patterns at end of usage examples:
#   (TTR 1996:46)  (TWMNT 5/6/1877)  (JPS)  (J. vii. 132)
_CITATION_RE = re.compile(r'\(([A-Z][A-Za-z.]+(?:\s[^)]+)?)\)')


def normalise_sort_key(text: str) -> str:
    """Strips macrons only — used for ORDER BY alphabetic sort."""
    text = unicodedata.normalize('NFD', text.lower().strip())
    return ''.join(c for c in text if unicodedata.category(c) != 'Mn')


def normalise_search_key(text: str) -> str:
    """Strips macrons AND collapses double vowels — used for search matching.

    ā/aa/a → a; whānau/whaanau/whanau → whanau; kaokao unchanged (ao ≠ oo).
    """
    text = normalise_sort_key(text)
    return re.sub(r'([aeiou])\1+', r'\1', text)


def compute_content_hash(fields: dict) -> str:
    """SHA-256 of the canonical JSON serialisation of *fields*.

    Lists are sorted before serialisation so that reordered-but-identical
    arrays hash identically.  Pass only the fields that constitute 'material'
    content — omit internal IDs, sort keys, timestamps, and the hash itself.
    """
    def _sort(v):
        if isinstance(v, list):
            items = [_sort(i) for i in v]
            try:
                return sorted(items)
            except TypeError:
                # List of dicts: sort by their JSON representation
                return sorted(items, key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))
        if isinstance(v, dict):
            return {k: _sort(val) for k, val in v.items()}
        return v

    canonical = {k: _sort(v) for k, v in fields.items()}
    blob = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_source_abbrevs(source_dict: str, db_path: Path = DB_PATH) -> dict[str, dict]:
    """Return {abbrev: {full_name, pub_type, year_range, notes}} for a given source_dict.

    source_dict is 'te_aka', 'williams', etc.  Cache results in a module-level
    dict so callers can call this repeatedly without reopening the DB each time.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT abbrev, full_name, pub_type, year_range, notes "
            "FROM source_abbreviations WHERE source_dict = ?",
            (source_dict,),
        ).fetchall()
    return {r["abbrev"]: dict(r) for r in rows}


def _has_table(con, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def resolve_within_source_relations(con) -> int:
    """Point a relation at its target where the source names it unambiguously.

    14,853 relations name a headword that exists in their own source and were
    never resolved — hepatakakupu's synonyms had no resolution pass at all,
    though Te Aka's synonyms and Williams's see_also each have one.

    Only the unambiguous ones are resolved: 5,197 where exactly one entry in
    that source carries the headword. The other 9,656 name a headword held by
    two or more entries — hepatakakupu splits senses across entries, so 'ahu' is
    several rows — and choosing one would be a guess dressed as a fact. Those
    stay NULL and are the sweep's to judge.

    Matching is case-insensitive: Williams capitalises its main headwords but
    writes cross-reference targets in lower case, so an exact match never fired
    for 230 of its own relations and 1,056 of Te Matatiki's.

    Never crosses a source boundary, never overwrites a target already set, and
    never points an entry at itself.
    """
    if not _has_table(con, "relation"):
        return 0
    n = con.execute("""
        UPDATE relation SET target_entry_id = (
            SELECT t.id FROM entry t
             WHERE t.source_id = (SELECT e.source_id FROM entry e
                                   WHERE e.id = relation.entry_id)
               AND LOWER(t.headword) = LOWER(relation.target_headword)
               AND t.id <> relation.entry_id)
        WHERE target_entry_id IS NULL
          AND target_headword IS NOT NULL
          AND (SELECT COUNT(*) FROM entry t
                WHERE t.source_id = (SELECT e.source_id FROM entry e
                                      WHERE e.id = relation.entry_id)
                  AND LOWER(t.headword) = LOWER(relation.target_headword)
                  AND t.id <> relation.entry_id) = 1
    """).rowcount
    con.commit()
    return n


def resolve_unambiguous_senses(con) -> dict:
    """Point entry-level references at a sense, where the sense is determined.

    ETY_entry_link and relation can name an entry but not a sense, so Williams's
    'see apa (i), sense 2' and POLLEX's '*afo is sense 2' were both inexpressible.

    Where the target entry has exactly ONE sense there is nothing to judge — the
    sense follows from the entry. That covers 89% of etymology links and 58% of
    resolved relations. Everything else is left NULL for the audit sweep, and a
    sense already chosen is never overwritten, so a sweep judgement survives the
    next rebuild.

    Resolving a pointer makes it PRECISE, not CORRECT: every etymology link is
    still match_method='headword_exact', matched on spelling with no semantic
    check. A spurious link stays spurious, now about a specific sense.

    Both tables are repopulated by their build scripts (50 rebuilds a source's
    relations, 52 deletes and reinserts every link), so this runs at the end of
    each of those, not once.
    """
    counts = {}
    single = ("(SELECT entry_id FROM sense GROUP BY entry_id HAVING COUNT(*) = 1)")
    if _has_table(con, "ETY_entry_link"):
        counts["ETY_entry_link"] = con.execute(
            "UPDATE ETY_entry_link SET sense_id = "
            "  (SELECT s.id FROM sense s WHERE s.entry_id = ETY_entry_link.entry_id) "
            f"WHERE sense_id IS NULL AND entry_id IN {single}").rowcount
    if _has_table(con, "relation"):
        counts["relation"] = con.execute(
            "UPDATE relation SET target_sense_id = "
            "  (SELECT s.id FROM sense s WHERE s.entry_id = relation.target_entry_id) "
            "WHERE target_sense_id IS NULL AND target_entry_id IS NOT NULL "
            f"  AND target_entry_id IN {single}").rowcount
    con.commit()
    return counts


_POS_QUALIFIER = re.compile(r"\s*\(([^)]*)\)\s*$")


def pos_atoms(raw: str | None) -> list[str]:
    """Split a raw part-of-speech string into atomic codes.

    Te Matatiki and Kimikupu Hou bracket the whole value — '[noun, transitive
    verb]' — so a plain comma split severed the brackets and produced '[noun'
    and 'transitive verb]'. Neither is a part of speech, neither is in std_pos,
    and between them they accounted for most of the unmapped atoms; the stripped
    forms were in std_pos all along.

    A trailing parenthetical is a subject note, not part of the code:
    'noun (volleyball)' is a noun. A value that is ONLY parenthesised, '(prefix)',
    keeps its word.
    """
    if not raw:
        return []
    text = raw.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    out = []
    for tok in (t.strip() for t in text.split(",")):
        tok = tok.strip("[]").strip()
        if not tok:
            continue
        stripped = _POS_QUALIFIER.sub("", tok).strip("[]").strip()
        out.append(stripped or tok.strip("()").strip())
    return [t for t in out if t]


def expand_citations(text: str, abbrevs: dict[str, dict]) -> str:
    """Replace inline citation abbreviations in *text* with expanded forms.

    abbrevs is the dict returned by load_source_abbrevs().

    Example:
        expand_citations(
            'Ko te aho he mea nui (TTR 1996:46).',
            load_source_abbrevs('te_aka')
        )
        → 'Ko te aho he mea nui (Ngā Tāngata Taumata Rau 1996:46).'
    """
    def _replace(m: re.Match) -> str:
        inner = m.group(1)
        # Abbreviation is everything up to the first space or end
        parts = inner.split(None, 1)
        abbrev = parts[0]
        rest = (" " + parts[1]) if len(parts) > 1 else ""
        info = abbrevs.get(abbrev)
        if info:
            return f"({info['full_name']}{rest})"
        return m.group(0)

    return _CITATION_RE.sub(_replace, text)


# One reconstruction node, spelled differently across sources: ACD's CLDF writes
# all-caps PAN/POC, LPO tags a couple of sets PSS. Collapse each onto the mixed-
# case scholarly standard (also the parent_code spelling used in the depth ladder)
# so ETY_cognateset.level and ETY_level carry exactly one code per node.
LEVEL_VARIANT_CANON = {"PAN": "PAn", "POC": "POc", "PSS": "PSES"}


def canonical_level(code: str | None) -> str | None:
    """Return the canonical spelling of a reconstruction-level code.

    Maps duplicate source spellings (PAN->PAn, POC->POc, PSS->PSES) onto one code;
    any other code, and None/empty, passes through unchanged. Apply at every source
    ingest so no variant reaches the unified ETY_* layer.
    """
    if not code:
        return code
    return LEVEL_VARIANT_CANON.get(code, code)


def normalise_proto_key(form: str) -> str:
    """Strip proto-form notation for fuzzy comparison matching.

    *afo(afo) -> afo;  AHO -> aho;  qafa-qi -> qafaqi;  *t<um>agis -> tagis
    Used to normalise POLLEX, LPO, and ACD reconstructed forms before matching.
    """
    form = form.lower().strip().lstrip('*')
    # Normalise Unicode mathematical angle brackets ⟨⟩ (used in LPO) to ASCII
    form = form.replace('⟨', '<').replace('⟩', '>')
    form = re.sub(r'\(.*?\)', '', form)   # strip (variant) alternates
    form = re.sub(r'\{.*?\}', '', form)   # strip {class markers}
    form = re.sub(r'<.*?>', '', form)     # strip <infix> notation
    form = re.sub(r'[-\s]+', '', form)    # collapse hyphens and spaces
    return form.strip()


ENV_PATH = Path(__file__).parent.parent / ".env"


def load_env(*keys: str) -> dict:
    """Read KEY=VALUE pairs from the gitignored repo-root .env file.

    Process environment wins, so a value exported in the shell overrides .env.
    Raises RuntimeError naming any requested key that resolves empty, so a
    scraper fails at startup rather than mid-crawl with a bad session.
    """
    import os

    values = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            values[k.strip()] = v.strip().strip('"').strip("'")

    resolved = {k: os.environ.get(k) or values.get(k, "") for k in keys}
    missing = [k for k, v in resolved.items() if not v]
    if missing:
        raise RuntimeError(
            f"Missing credential(s) {', '.join(missing)} — set them in {ENV_PATH}"
        )
    return resolved
