"""Personal lexicon CRUD module — Session 15.

Usage:
    from scripts.personal_lexicon_crud import PersonalLexicon
    lex = PersonalLexicon()
    wid = lex.add_word("āho", definition="String, line", pos="n.", tags=["nature"])
    lex.search("aho")          # finds āho via normalised key
    lex.cross_source_lookup("aho")  # queries all dictionary tables
"""

import sys
import sqlite3
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH, normalise_sort_key, normalise_search_key

_UPDATABLE_FIELDS = frozenset({
    "headword", "part_of_speech", "definition", "usage_examples",
    "tags", "pronunciation", "source_note", "is_private",
})

_SOURCE_TABLES = [
    ("williams",     "williams_entries"),
    ("papakupu",     "papakupu_entries"),
    ("pollex",       "pollex_entries"),
    ("te_aka",       "te_aka_entries"),
    ("hepatakakupu", "hepatakakupu_entries"),
    ("paekupu",      "paekupu_entries"),
]


def _deserialise(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for field in ("usage_examples", "tags"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
        else:
            d[field] = []
    return d


class PersonalLexicon:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def add_word(
        self,
        headword: str,
        definition: str = None,
        pos: str = None,
        examples: list = None,
        tags: list = None,
        pronunciation: str = None,
        source_note: str = None,
    ) -> int:
        examples = examples or []
        tags = sorted(set(tags or []))
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO personal_lexicon
                   (headword, headword_sort, headword_search, part_of_speech,
                    definition, usage_examples, tags, pronunciation, source_note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    headword,
                    normalise_sort_key(headword),
                    normalise_search_key(headword),
                    pos,
                    definition,
                    json.dumps(examples, ensure_ascii=False),
                    json.dumps(tags, ensure_ascii=False),
                    pronunciation,
                    source_note,
                ),
            )
            return cur.lastrowid

    def update_word(self, word_id: int, **fields) -> bool:
        if not fields:
            return False
        unknown = set(fields) - _UPDATABLE_FIELDS
        if unknown:
            raise ValueError(f"Unknown fields: {unknown}")

        if "usage_examples" in fields:
            fields["usage_examples"] = json.dumps(
                fields["usage_examples"], ensure_ascii=False
            )
        if "tags" in fields:
            fields["tags"] = json.dumps(
                sorted(set(fields["tags"])), ensure_ascii=False
            )
        if "headword" in fields:
            fields["headword_sort"] = normalise_sort_key(fields["headword"])
            fields["headword_search"] = normalise_search_key(fields["headword"])

        fields["last_updated"] = datetime.now().isoformat(timespec="seconds")

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE personal_lexicon SET {set_clause} WHERE id = ?",
                [*fields.values(), word_id],
            )
            return cur.rowcount > 0

    def delete_word(self, word_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM personal_lexicon WHERE id = ?", (word_id,)
            )
            return cur.rowcount > 0

    def get_word(self, word_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM personal_lexicon WHERE id = ?", (word_id,)
            ).fetchone()
        return _deserialise(row)

    def search(self, query: str, limit: int = 20) -> list[dict]:
        key = normalise_search_key(query)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM personal_lexicon WHERE headword_search = ? LIMIT ?",
                (key, limit),
            ).fetchall()
            if not rows:
                try:
                    rows = conn.execute(
                        """SELECT * FROM personal_lexicon
                           WHERE id IN (SELECT rowid FROM personal_fts WHERE personal_fts MATCH ?)
                           LIMIT ?""",
                        (query, limit),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
        return [_deserialise(r) for r in rows]

    def list_by_tag(self, tag: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT * FROM personal_lexicon WHERE tags LIKE ? ORDER BY headword_sort',
                (f'%"{tag}"%',),
            ).fetchall()
        return [_deserialise(r) for r in rows]

    def list_all_tags(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tags FROM personal_lexicon WHERE tags IS NOT NULL AND tags != '[]'"
            ).fetchall()
        tags: set[str] = set()
        for row in rows:
            try:
                tags.update(json.loads(row[0]))
            except (json.JSONDecodeError, TypeError):
                pass
        return sorted(tags)

    def export_json(self, filepath) -> int:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM personal_lexicon ORDER BY headword_sort"
            ).fetchall()
        entries = []
        for row in rows:
            d = dict(row)
            for field in ("usage_examples", "tags"):
                if d.get(field):
                    try:
                        d[field] = json.loads(d[field])
                    except (json.JSONDecodeError, TypeError):
                        pass
                else:
                    d[field] = []
            entries.append(d)
        Path(filepath).write_text(
            json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return len(entries)

    def import_json(self, filepath) -> int:
        entries = json.loads(Path(filepath).read_text(encoding="utf-8"))
        count = 0
        for e in entries:
            self.add_word(
                headword=e["headword"],
                definition=e.get("definition"),
                pos=e.get("part_of_speech"),
                examples=e.get("usage_examples") or [],
                tags=e.get("tags") or [],
                pronunciation=e.get("pronunciation"),
                source_note=e.get("source_note"),
            )
            count += 1
        return count

    def cross_source_lookup(self, headword: str) -> dict:
        key = normalise_search_key(headword)
        result = {}
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            for source_name, table in _SOURCE_TABLES:
                try:
                    rows = conn.execute(
                        f"SELECT * FROM {table} WHERE headword_search = ?", (key,)
                    ).fetchall()
                    if rows:
                        result[source_name] = [dict(r) for r in rows]
                except sqlite3.OperationalError:
                    pass
        return result
