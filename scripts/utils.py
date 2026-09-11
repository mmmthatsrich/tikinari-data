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
