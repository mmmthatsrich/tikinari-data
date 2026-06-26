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
