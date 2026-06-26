"""Creates staging_dictionary.db with all tables, FTS virtual tables, triggers,
and seeds source_metadata. Safe to re-run (CREATE IF NOT EXISTS).
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "staging_dictionary.db"


def create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        PRAGMA journal_mode = WAL;
        PRAGMA foreign_keys = ON;

        -- ── source registry ──────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS source_metadata (
            source_id    TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            licence      TEXT,
            url          TEXT,
            last_updated TEXT,
            entry_count  INTEGER DEFAULT 0,
            notes        TEXT,
            default_dialect TEXT          -- seeds entry.dialect for this source (e.g. Papakupu -> 'Tai Tokerau')
        );

        -- ── Williams Dictionary ──────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS williams_entries (
            id             INTEGER PRIMARY KEY,
            headword       TEXT NOT NULL,
            headword_sort  TEXT NOT NULL,
            headword_search TEXT NOT NULL,
            part_of_speech TEXT,
            definition     TEXT,
            usage_examples TEXT,          -- JSON array
            sense_number   INTEGER,
            cross_refs     TEXT,          -- JSON array
            page_number    INTEGER,
            source_section TEXT,
            created_at     TEXT DEFAULT (datetime('now')),
            last_updated   TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_williams_search
            ON williams_entries(headword_search);
        CREATE INDEX IF NOT EXISTS idx_williams_sort
            ON williams_entries(headword_sort);

        CREATE VIRTUAL TABLE IF NOT EXISTS williams_fts USING fts5(
            headword, definition, usage_examples,
            content='williams_entries', content_rowid='id',
            tokenize='unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS williams_fts_ins AFTER INSERT ON williams_entries BEGIN
            INSERT INTO williams_fts(rowid, headword, definition, usage_examples)
            VALUES (new.id, new.headword, new.definition, new.usage_examples);
        END;
        CREATE TRIGGER IF NOT EXISTS williams_fts_upd AFTER UPDATE ON williams_entries BEGIN
            INSERT INTO williams_fts(williams_fts, rowid, headword, definition, usage_examples)
            VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
            INSERT INTO williams_fts(rowid, headword, definition, usage_examples)
            VALUES (new.id, new.headword, new.definition, new.usage_examples);
        END;
        CREATE TRIGGER IF NOT EXISTS williams_fts_del AFTER DELETE ON williams_entries BEGIN
            INSERT INTO williams_fts(williams_fts, rowid, headword, definition, usage_examples)
            VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
        END;

        -- ── Papakupu o Tai Tokerau ───────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS papakupu_entries (
            id                  INTEGER PRIMARY KEY,
            headword            TEXT NOT NULL,
            headword_sort       TEXT NOT NULL,
            headword_search     TEXT NOT NULL,
            part_of_speech      TEXT,
            definition          TEXT,
            usage_examples      TEXT,          -- JSON array
            variant_forms       TEXT,          -- JSON array
            variant_search_keys TEXT,          -- JSON array of normalised keys
            source_code         TEXT,
            loan_marker         TEXT,
            see_also            TEXT,          -- JSON array
            pdf_page            INTEGER,
            created_at          TEXT DEFAULT (datetime('now')),
            last_updated        TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_papakupu_search
            ON papakupu_entries(headword_search);
        CREATE INDEX IF NOT EXISTS idx_papakupu_sort
            ON papakupu_entries(headword_sort);

        CREATE VIRTUAL TABLE IF NOT EXISTS papakupu_fts USING fts5(
            headword, definition, usage_examples,
            content='papakupu_entries', content_rowid='id',
            tokenize='unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS papakupu_fts_ins AFTER INSERT ON papakupu_entries BEGIN
            INSERT INTO papakupu_fts(rowid, headword, definition, usage_examples)
            VALUES (new.id, new.headword, new.definition, new.usage_examples);
        END;
        CREATE TRIGGER IF NOT EXISTS papakupu_fts_upd AFTER UPDATE ON papakupu_entries BEGIN
            INSERT INTO papakupu_fts(papakupu_fts, rowid, headword, definition, usage_examples)
            VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
            INSERT INTO papakupu_fts(rowid, headword, definition, usage_examples)
            VALUES (new.id, new.headword, new.definition, new.usage_examples);
        END;
        CREATE TRIGGER IF NOT EXISTS papakupu_fts_del AFTER DELETE ON papakupu_entries BEGIN
            INSERT INTO papakupu_fts(papakupu_fts, rowid, headword, definition, usage_examples)
            VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
        END;

        -- ── POLLEX ───────────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS pollex_entries (
            id             INTEGER PRIMARY KEY,
            headword       TEXT NOT NULL,
            headword_sort  TEXT NOT NULL,
            headword_search TEXT NOT NULL,
            part_of_speech TEXT,
            definition     TEXT,
            usage_examples TEXT,          -- JSON array
            protoform      TEXT,
            protoform_desc TEXT,
            maori_reflex   TEXT,
            maori_gloss    TEXT,
            source_citation TEXT,
            source_author  TEXT,
            cognateset_id  TEXT,          -- FK to pollex_cognatesets(id)
            pollex_url     TEXT,
            created_at     TEXT DEFAULT (datetime('now')),
            last_updated   TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_pollex_search
            ON pollex_entries(headword_search);

        CREATE VIRTUAL TABLE IF NOT EXISTS pollex_fts USING fts5(
            headword, definition, usage_examples,
            content='pollex_entries', content_rowid='id',
            tokenize='unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS pollex_fts_ins AFTER INSERT ON pollex_entries BEGIN
            INSERT INTO pollex_fts(rowid, headword, definition, usage_examples)
            VALUES (new.id, new.headword, new.definition, new.usage_examples);
        END;
        CREATE TRIGGER IF NOT EXISTS pollex_fts_upd AFTER UPDATE ON pollex_entries BEGIN
            INSERT INTO pollex_fts(pollex_fts, rowid, headword, definition, usage_examples)
            VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
            INSERT INTO pollex_fts(rowid, headword, definition, usage_examples)
            VALUES (new.id, new.headword, new.definition, new.usage_examples);
        END;
        CREATE TRIGGER IF NOT EXISTS pollex_fts_del AFTER DELETE ON pollex_entries BEGIN
            INSERT INTO pollex_fts(pollex_fts, rowid, headword, definition, usage_examples)
            VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
        END;

        -- ── POLLEX cognate sets (one row per protoform entry page) ──────────
        CREATE TABLE IF NOT EXISTS pollex_cognatesets (
            id             TEXT PRIMARY KEY,   -- URL slug, e.g. "aho"
            protoform_name TEXT NOT NULL,      -- bare name, e.g. "AHO"
            level          TEXT NOT NULL,      -- CE|PN|NP|OC|AN|MP|FJ|…
            description    TEXT,
            reconstruction TEXT,              -- level full name, e.g. "Central-Eastern Polynesian"
            notes          TEXT,              -- free text; may contain "LPO N:NNN" citations
            pollex_url     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_pollex_cognatesets_level
            ON pollex_cognatesets(level);

        -- ── POLLEX cross-language reflexes (all 67 languages) ────────────────
        CREATE TABLE IF NOT EXISTS pollex_reflexes (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            cognateset_id  TEXT NOT NULL REFERENCES pollex_cognatesets(id),
            language       TEXT NOT NULL,
            language_slug  TEXT,
            reflex         TEXT,
            gloss          TEXT,
            source_code    TEXT,
            source_author  TEXT,
            flags          TEXT              -- JSON array, e.g. ["Borrowed"]
        );
        CREATE INDEX IF NOT EXISTS idx_pollex_reflexes_cs
            ON pollex_reflexes(cognateset_id);
        CREATE INDEX IF NOT EXISTS idx_pollex_reflexes_lang
            ON pollex_reflexes(language_slug);

        -- ── POLLEX language reference ────────────────────────────────────────
        -- One row per language; language_slug matches pollex_reflexes.language_slug.
        CREATE TABLE IF NOT EXISTS pollex_languages (
            language_slug         TEXT PRIMARY KEY,
            language              TEXT NOT NULL,
            iso_code              TEXT,
            subgroup              TEXT NOT NULL,  -- Tongic|Eastern Polynesian|Samoic-Outlier|Polynesian Outlier|Fijian|Rotuman|Other Oceanic
            region                TEXT,
            country_or_island_group TEXT,
            notes                 TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_pollex_languages_subgroup
            ON pollex_languages(subgroup);

        -- ── LPO / tlopo — Proto-Oceanic cognate sets ─────────────────────────
        -- Level values: POc, PAn, PMP, PEOc, PNGOc, PEMP, PCP, PPT
        -- Chapter linkage via cognatesetreferences.csv (Cognateset_ID -> Chapter_ID)
        CREATE TABLE IF NOT EXISTS lpo_cognatesets (
            id            TEXT PRIMARY KEY,   -- CLDF ID
            name          TEXT NOT NULL,      -- reconstructed form, e.g. "Rumaq"
            name_key      TEXT NOT NULL,      -- normalise_proto_key(name) for matching
            description   TEXT,
            level         TEXT,              -- POc|PAn|PMP|PEOc|…
            chapter_id    TEXT,
            chapter_title TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_lpo_name_key ON lpo_cognatesets(name_key);
        CREATE INDEX IF NOT EXISTS idx_lpo_level ON lpo_cognatesets(level);

        -- ── ACD — Proto-Austronesian / Proto-Malayo-Polynesian cognate sets ──
        -- Level is embedded in Name field: "PMP *abaw 'high, lofty'"
        -- Parse: level = first token, name = *form, description = text in quotes
        -- Etymon_ID groups related reconstructions (PAN + PMP sharing same etymon)
        CREATE TABLE IF NOT EXISTS acd_cognatesets (
            id          TEXT PRIMARY KEY,   -- CLDF ID
            name        TEXT NOT NULL,      -- bare reconstructed form (asterisk stripped from Name)
            name_key    TEXT NOT NULL,      -- normalise_proto_key(name)
            description TEXT,              -- gloss parsed from Name (inside single quotes)
            level       TEXT,              -- PAN|PMP|PWMP|POC|PPH|PCEMP|… (parsed from Name)
            etymon_id   TEXT               -- groups related forms; join WHERE etymon_id=? for chain
        );
        CREATE INDEX IF NOT EXISTS idx_acd_name_key ON acd_cognatesets(name_key);
        CREATE INDEX IF NOT EXISTS idx_acd_level ON acd_cognatesets(level);
        CREATE INDEX IF NOT EXISTS idx_acd_etymon ON acd_cognatesets(etymon_id);

        -- ── Etymology linking table ───────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS etymology_links (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            pollex_cognateset_id TEXT NOT NULL REFERENCES pollex_cognatesets(id),
            lpo_cognateset_id    TEXT REFERENCES lpo_cognatesets(id),
            acd_cognateset_id    TEXT REFERENCES acd_cognatesets(id),
            match_confidence     REAL,    -- 0.0–1.0
            match_method         TEXT,    -- "level_embedded"|"notes_citation"|"form_fuzzy"|"manual"
            lpo_citation         TEXT,    -- raw "LPO N:NNN" text from notes, if found
            notes                TEXT     -- curation comments
        );
        CREATE INDEX IF NOT EXISTS idx_etymology_pollex
            ON etymology_links(pollex_cognateset_id);

        -- ── Personal Lexicon ─────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS personal_lexicon (
            id             INTEGER PRIMARY KEY,
            headword       TEXT NOT NULL,
            headword_sort  TEXT NOT NULL,
            headword_search TEXT NOT NULL,
            part_of_speech TEXT,
            definition     TEXT,
            usage_examples TEXT,          -- JSON array
            tags           TEXT,          -- JSON array
            pronunciation  TEXT,
            source_note    TEXT,
            is_private     INTEGER DEFAULT 0,
            created_at     TEXT DEFAULT (datetime('now')),
            last_updated   TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_personal_search
            ON personal_lexicon(headword_search);

        CREATE VIRTUAL TABLE IF NOT EXISTS personal_fts USING fts5(
            headword, definition, usage_examples,
            content='personal_lexicon', content_rowid='id',
            tokenize='unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS personal_fts_ins AFTER INSERT ON personal_lexicon BEGIN
            INSERT INTO personal_fts(rowid, headword, definition, usage_examples)
            VALUES (new.id, new.headword, new.definition, new.usage_examples);
        END;
        CREATE TRIGGER IF NOT EXISTS personal_fts_upd AFTER UPDATE ON personal_lexicon BEGIN
            INSERT INTO personal_fts(personal_fts, rowid, headword, definition, usage_examples)
            VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
            INSERT INTO personal_fts(rowid, headword, definition, usage_examples)
            VALUES (new.id, new.headword, new.definition, new.usage_examples);
        END;
        CREATE TRIGGER IF NOT EXISTS personal_fts_del AFTER DELETE ON personal_lexicon BEGIN
            INSERT INTO personal_fts(personal_fts, rowid, headword, definition, usage_examples)
            VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
        END;

        -- ── Te Aka ───────────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS te_aka_entries (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            word_id          INTEGER NOT NULL,
            headword         TEXT NOT NULL,
            headword_sort    TEXT NOT NULL,
            headword_search  TEXT NOT NULL,
            part_of_speech   TEXT,
            definition       TEXT,
            usage_examples   TEXT DEFAULT '[]',
            audio_url        TEXT,
            synonyms         TEXT DEFAULT '[]',
            source_citations TEXT DEFAULT '[]',
            filters          TEXT DEFAULT '[]',
            content_hash     TEXT,              -- SHA-256 of material fields; used for refresh diffing
            first_seen       TEXT,              -- datetime of first import
            created_at       TEXT DEFAULT (datetime('now')),
            last_updated     TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_te_aka_word_id
            ON te_aka_entries(word_id);
        CREATE INDEX IF NOT EXISTS idx_te_aka_search
            ON te_aka_entries(headword_search);

        CREATE VIRTUAL TABLE IF NOT EXISTS te_aka_fts USING fts5(
            headword, definition, usage_examples,
            content='te_aka_entries', content_rowid='id',
            tokenize='unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS te_aka_fts_ins AFTER INSERT ON te_aka_entries BEGIN
            INSERT INTO te_aka_fts(rowid, headword, definition, usage_examples)
            VALUES (new.id, new.headword, new.definition, new.usage_examples);
        END;
        CREATE TRIGGER IF NOT EXISTS te_aka_fts_upd AFTER UPDATE ON te_aka_entries BEGIN
            INSERT INTO te_aka_fts(te_aka_fts, rowid, headword, definition, usage_examples)
            VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
            INSERT INTO te_aka_fts(rowid, headword, definition, usage_examples)
            VALUES (new.id, new.headword, new.definition, new.usage_examples);
        END;
        CREATE TRIGGER IF NOT EXISTS te_aka_fts_del AFTER DELETE ON te_aka_entries BEGIN
            INSERT INTO te_aka_fts(te_aka_fts, rowid, headword, definition, usage_examples)
            VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
        END;

        -- ── He Pātaka Kupu (stub) ────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS hepatakakupu_entries (
            id             INTEGER PRIMARY KEY,
            headword       TEXT NOT NULL,
            headword_sort  TEXT NOT NULL,
            headword_search TEXT NOT NULL,
            part_of_speech TEXT,
            definition     TEXT,
            usage_examples TEXT,          -- JSON array
            word_id        INTEGER,
            definition_mi  TEXT,
            created_at     TEXT DEFAULT (datetime('now')),
            last_updated   TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_hepatakakupu_search
            ON hepatakakupu_entries(headword_search);

        CREATE VIRTUAL TABLE IF NOT EXISTS hepatakakupu_fts USING fts5(
            headword, definition, usage_examples,
            content='hepatakakupu_entries', content_rowid='id',
            tokenize='unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS hepatakakupu_fts_ins AFTER INSERT ON hepatakakupu_entries BEGIN
            INSERT INTO hepatakakupu_fts(rowid, headword, definition, usage_examples)
            VALUES (new.id, new.headword, new.definition, new.usage_examples);
        END;
        CREATE TRIGGER IF NOT EXISTS hepatakakupu_fts_upd AFTER UPDATE ON hepatakakupu_entries BEGIN
            INSERT INTO hepatakakupu_fts(hepatakakupu_fts, rowid, headword, definition, usage_examples)
            VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
            INSERT INTO hepatakakupu_fts(rowid, headword, definition, usage_examples)
            VALUES (new.id, new.headword, new.definition, new.usage_examples);
        END;
        CREATE TRIGGER IF NOT EXISTS hepatakakupu_fts_del AFTER DELETE ON hepatakakupu_entries BEGIN
            INSERT INTO hepatakakupu_fts(hepatakakupu_fts, rowid, headword, definition, usage_examples)
            VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
        END;

        -- ── Source Abbreviations ─────────────────────────────────────────────
        -- Lookup table for expanding inline source citations across all dictionaries.
        -- abbrev: as it appears in text, e.g. "TTR", "J."
        -- source_dict: which dictionary uses it, e.g. "te_aka", "williams", "all"
        CREATE TABLE IF NOT EXISTS source_abbreviations (
            abbrev       TEXT NOT NULL,
            source_dict  TEXT NOT NULL,
            full_name    TEXT NOT NULL,
            pub_type     TEXT,       -- 'newspaper', 'book', 'journal', 'bible', 'curriculum', 'reference', 'thesis', 'other'
            year_range   TEXT,       -- e.g. '1921-1932' or '2008'
            notes        TEXT,
            PRIMARY KEY (abbrev, source_dict)
        );
        CREATE INDEX IF NOT EXISTS idx_source_abbrevs_dict
            ON source_abbreviations(source_dict);

        -- ── Paekupu ──────────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS paekupu_entries (
            id               INTEGER PRIMARY KEY,
            headword         TEXT NOT NULL,
            headword_sort    TEXT NOT NULL,
            headword_search  TEXT NOT NULL,
            part_of_speech   TEXT,
            definition       TEXT,
            usage_examples   TEXT,             -- JSON array
            headword_en      TEXT,
            subject_area     TEXT,
            content_hash     TEXT,             -- SHA-256 of material fields; used for refresh diffing
            first_seen       TEXT,             -- datetime of first import
            created_at       TEXT DEFAULT (datetime('now')),
            last_updated     TEXT DEFAULT (datetime('now'))
        );

        -- ── Cross-source duplicate candidates ────────────────────────────────
        -- Detected algorithmically; AI-reviewed via Claude Code; human-approved.
        -- UNIQUE constraint prevents dismissed/approved pairs from being re-inserted.
        CREATE TABLE IF NOT EXISTS cross_source_candidates (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            headword_search TEXT NOT NULL,
            source_a        TEXT NOT NULL,
            entry_id_a      INTEGER NOT NULL,
            source_b        TEXT NOT NULL,
            entry_id_b      INTEGER NOT NULL,
            status          TEXT NOT NULL DEFAULT 'unreviewed',
                            -- unreviewed | pending | approved | dismissed_by_ai | dismissed
            ai_reasoning    TEXT,
            detected_at     TEXT,
            reviewed_at     TEXT,
            review_notes    TEXT,
            UNIQUE (source_a, entry_id_a, source_b, entry_id_b)
        );
        CREATE INDEX IF NOT EXISTS idx_cross_source_status
            ON cross_source_candidates(status);
        CREATE INDEX IF NOT EXISTS idx_cross_source_headword
            ON cross_source_candidates(headword_search);

        -- One row per detection run.
        CREATE TABLE IF NOT EXISTS cross_source_detection_runs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at           TEXT DEFAULT (datetime('now')),
            new_pairs        INTEGER DEFAULT 0,
            skipped_existing INTEGER DEFAULT 0,
            notes            TEXT
        );

        -- ── Data refresh tracking ─────────────────────────────────────────────
        -- One row per run of a refresh import (--refresh mode).
        CREATE TABLE IF NOT EXISTS data_refresh_runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source_dict     TEXT NOT NULL,          -- 'te_aka' or 'paekupu'
            run_at          TEXT DEFAULT (datetime('now')),
            new_count       INTEGER DEFAULT 0,
            modified_count  INTEGER DEFAULT 0,
            deleted_count   INTEGER DEFAULT 0,
            unchanged_count INTEGER DEFAULT 0,
            total_scraped   INTEGER DEFAULT 0,
            notes           TEXT
        );

        -- One row per changed entry (new / modified / deleted).
        -- For 'modified': changed_fields lists which fields differed;
        --                 old_values / new_values hold those fields' values as JSON objects.
        -- For 'deleted':  old_values holds the full material snapshot; new_values is NULL.
        -- For 'new':      old_values is NULL; new_values is NULL (entry is already in DB).
        CREATE TABLE IF NOT EXISTS data_refresh_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          INTEGER NOT NULL REFERENCES data_refresh_runs(id),
            source_dict     TEXT NOT NULL,
            entry_key       TEXT NOT NULL,   -- word_id (te_aka) or slug (paekupu)
            headword        TEXT,
            change_type     TEXT NOT NULL,   -- 'new' | 'modified' | 'deleted'
            changed_fields  TEXT,            -- JSON array of field names; NULL for new/deleted
            old_values      TEXT,            -- JSON object; NULL for new entries
            new_values      TEXT,            -- JSON object; NULL for deleted entries
            logged_at       TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_refresh_log_run
            ON data_refresh_log(run_id);
        CREATE INDEX IF NOT EXISTS idx_refresh_log_entry
            ON data_refresh_log(source_dict, entry_key);
        CREATE INDEX IF NOT EXISTS idx_paekupu_search
            ON paekupu_entries(headword_search);

        CREATE VIRTUAL TABLE IF NOT EXISTS paekupu_fts USING fts5(
            headword, definition, usage_examples,
            content='paekupu_entries', content_rowid='id',
            tokenize='unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS paekupu_fts_ins AFTER INSERT ON paekupu_entries BEGIN
            INSERT INTO paekupu_fts(rowid, headword, definition, usage_examples)
            VALUES (new.id, new.headword, new.definition, new.usage_examples);
        END;
        CREATE TRIGGER IF NOT EXISTS paekupu_fts_upd AFTER UPDATE ON paekupu_entries BEGIN
            INSERT INTO paekupu_fts(paekupu_fts, rowid, headword, definition, usage_examples)
            VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
            INSERT INTO paekupu_fts(rowid, headword, definition, usage_examples)
            VALUES (new.id, new.headword, new.definition, new.usage_examples);
        END;
        CREATE TRIGGER IF NOT EXISTS paekupu_fts_del AFTER DELETE ON paekupu_entries BEGIN
            INSERT INTO paekupu_fts(paekupu_fts, rowid, headword, definition, usage_examples)
            VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
        END;

        -- ════════════════════════════════════════════════════════════════════
        --  CANONICAL UNIFIED CORE  (SCHEMA_PROPOSAL.md §3)
        --  One row per SOURCE entry — provenance kept, shape unified. Built as a
        --  rebuildable projection of the per-source *_entries tables by
        --  scripts/50_build_unified.py. The per-source tables remain the raw,
        --  curated landing zone; this core is regenerated, never hand-edited.
        -- ════════════════════════════════════════════════════════════════════

        -- ── entry: one row per source headword-entry ─────────────────────────
        CREATE TABLE IF NOT EXISTS entry (
            id              INTEGER PRIMARY KEY,   -- INTERNAL surrogate only; NOT the device id.
                                                   --   Volatile across per-source rebuilds (see 50_build_unified.py).
            source_id       TEXT NOT NULL,         -- FK source_metadata.source_id
            source_entry_id TEXT,                  -- original id/word_id/slug; device id '{source_id}:{source_entry_id}'
                                                   --   is minted downstream by the Tikinari build, not here.
            headword        TEXT NOT NULL,
            headword_sort   TEXT NOT NULL,         -- normalise_sort_key (macron-stripped)
            headword_search TEXT NOT NULL,         -- normalise_search_key (macron + double-vowel collapsed)
            homonym_no      INTEGER,               -- distinguishes homographs
            headword_en     TEXT,                  -- Paekupu English headword
            part_of_speech  TEXT,                  -- RAW passthrough for now; joins to std_pos for later canonicalisation
            loan_marker     TEXT,                  -- Papakupu
            dialect         TEXT,                  -- e.g. 'Tai Tokerau'; source-defaulted via source_metadata.default_dialect.
                                                   --   Drives the app's dialect boost; ranking reads THIS, never source_id.
            audio_url       TEXT,                  -- Te Aka, Paekupu
            locator         TEXT,                  -- pdf_page / url / source_section, as text
            content_hash    TEXT,
            first_seen      TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            last_updated    TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_entry_source  ON entry(source_id);
        CREATE INDEX IF NOT EXISTS idx_entry_search  ON entry(headword_search);
        CREATE INDEX IF NOT EXISTS idx_entry_sort    ON entry(headword_sort);
        CREATE INDEX IF NOT EXISTS idx_entry_srcpk   ON entry(source_id, source_entry_id);

        -- ── form: variant / alternative / inflected forms ────────────────────
        CREATE TABLE IF NOT EXISTS form (
            id          INTEGER PRIMARY KEY,
            entry_id    INTEGER NOT NULL REFERENCES entry(id),
            form        TEXT NOT NULL,
            form_search TEXT NOT NULL,             -- normalise_search_key, for matching
            form_type   TEXT,                      -- variant | alt_spelling | plural | inflected
            note        TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_form_entry  ON form(entry_id);
        CREATE INDEX IF NOT EXISTS idx_form_search ON form(form_search);

        -- ── sense: normalises sense_number rows AND inline senses ────────────
        CREATE TABLE IF NOT EXISTS sense (
            id              INTEGER PRIMARY KEY,
            entry_id        INTEGER NOT NULL REFERENCES entry(id),
            sense_number    INTEGER,
            parent_sense_id INTEGER REFERENCES sense(id),   -- sub-senses
            gloss_en        TEXT,                  -- English gloss (Te Aka/Williams/Papakupu/Paekupu)
            gloss_mi        TEXT,                  -- Māori monolingual gloss (HPK, Paekupu definition_mi)
            definition_raw  TEXT,                  -- original blob, untouched, for fidelity
            register        TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_sense_entry ON sense(entry_id);
        -- index FK-referencing cols so per-source DELETE doesn't full-scan on FK checks
        CREATE INDEX IF NOT EXISTS idx_sense_parent ON sense(parent_sense_id);

        -- ── example: structured, bilingual (fixes the lost-Māori-example bug) ─
        CREATE TABLE IF NOT EXISTS example (
            id            INTEGER PRIMARY KEY,
            sense_id      INTEGER REFERENCES sense(id),
            entry_id      INTEGER NOT NULL REFERENCES entry(id),   -- denormalised for entry-level fallback
            text_mi       TEXT,                    -- Māori sentence
            text_en       TEXT,                    -- English translation
            source_abbrev TEXT,                    -- FK source_abbreviations.abbrev (e.g. TTU, NGH3)
            citation      TEXT,                    -- full free-text citation (Te Aka)
            sort_no       INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_example_sense ON example(sense_id);
        CREATE INDEX IF NOT EXISTS idx_example_entry ON example(entry_id);

        -- ── relation: synonyms, see-also, cross-refs, antonyms, variant_of ───
        CREATE TABLE IF NOT EXISTS relation (
            id              INTEGER PRIMARY KEY,
            entry_id        INTEGER NOT NULL REFERENCES entry(id),
            rel_type        TEXT NOT NULL,         -- synonym | see_also | cross_ref | antonym | variant_of
            target_headword TEXT NOT NULL,
            target_entry_id INTEGER REFERENCES entry(id),   -- resolved when possible (Te Aka word_id)
            note            TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_relation_entry ON relation(entry_id);
        CREATE INDEX IF NOT EXISTS idx_relation_target ON relation(target_entry_id);

        -- ── entry_domain: subject / semantic-domain tags ─────────────────────
        CREATE TABLE IF NOT EXISTS entry_domain (
            id          INTEGER PRIMARY KEY,
            sense_id    INTEGER REFERENCES sense(id),
            entry_id    INTEGER NOT NULL REFERENCES entry(id),
            domain      TEXT NOT NULL,             -- HPK semantic_domain, Paekupu subject_area, Te Aka filters
            domain_lang TEXT                       -- 'mi' | 'en'
        );
        CREATE INDEX IF NOT EXISTS idx_entry_domain_entry ON entry_domain(entry_id);
        CREATE INDEX IF NOT EXISTS idx_entry_domain_sense ON entry_domain(sense_id);

        -- ── FTS over the derived core (external-content + trigger-synced) ─────
        CREATE VIRTUAL TABLE IF NOT EXISTS entry_fts USING fts5(
            headword, headword_search,
            content='entry', content_rowid='id', tokenize='unicode61'
        );
        CREATE TRIGGER IF NOT EXISTS entry_fts_ins AFTER INSERT ON entry BEGIN
            INSERT INTO entry_fts(rowid, headword, headword_search)
            VALUES (new.id, new.headword, new.headword_search);
        END;
        CREATE TRIGGER IF NOT EXISTS entry_fts_upd AFTER UPDATE ON entry BEGIN
            INSERT INTO entry_fts(entry_fts, rowid, headword, headword_search)
            VALUES ('delete', old.id, old.headword, old.headword_search);
            INSERT INTO entry_fts(rowid, headword, headword_search)
            VALUES (new.id, new.headword, new.headword_search);
        END;
        CREATE TRIGGER IF NOT EXISTS entry_fts_del AFTER DELETE ON entry BEGIN
            INSERT INTO entry_fts(entry_fts, rowid, headword, headword_search)
            VALUES ('delete', old.id, old.headword, old.headword_search);
        END;

        CREATE VIRTUAL TABLE IF NOT EXISTS sense_fts USING fts5(
            gloss_en, gloss_mi, definition_raw,
            content='sense', content_rowid='id', tokenize='unicode61'
        );
        CREATE TRIGGER IF NOT EXISTS sense_fts_ins AFTER INSERT ON sense BEGIN
            INSERT INTO sense_fts(rowid, gloss_en, gloss_mi, definition_raw)
            VALUES (new.id, new.gloss_en, new.gloss_mi, new.definition_raw);
        END;
        CREATE TRIGGER IF NOT EXISTS sense_fts_upd AFTER UPDATE ON sense BEGIN
            INSERT INTO sense_fts(sense_fts, rowid, gloss_en, gloss_mi, definition_raw)
            VALUES ('delete', old.id, old.gloss_en, old.gloss_mi, old.definition_raw);
            INSERT INTO sense_fts(rowid, gloss_en, gloss_mi, definition_raw)
            VALUES (new.id, new.gloss_en, new.gloss_mi, new.definition_raw);
        END;
        CREATE TRIGGER IF NOT EXISTS sense_fts_del AFTER DELETE ON sense BEGIN
            INSERT INTO sense_fts(sense_fts, rowid, gloss_en, gloss_mi, definition_raw)
            VALUES ('delete', old.id, old.gloss_en, old.gloss_mi, old.definition_raw);
        END;

        CREATE VIRTUAL TABLE IF NOT EXISTS example_fts USING fts5(
            text_mi, text_en,
            content='example', content_rowid='id', tokenize='unicode61'
        );
        CREATE TRIGGER IF NOT EXISTS example_fts_ins AFTER INSERT ON example BEGIN
            INSERT INTO example_fts(rowid, text_mi, text_en)
            VALUES (new.id, new.text_mi, new.text_en);
        END;
        CREATE TRIGGER IF NOT EXISTS example_fts_upd AFTER UPDATE ON example BEGIN
            INSERT INTO example_fts(example_fts, rowid, text_mi, text_en)
            VALUES ('delete', old.id, old.text_mi, old.text_en);
            INSERT INTO example_fts(rowid, text_mi, text_en)
            VALUES (new.id, new.text_mi, new.text_en);
        END;
        CREATE TRIGGER IF NOT EXISTS example_fts_del AFTER DELETE ON example BEGIN
            INSERT INTO example_fts(example_fts, rowid, text_mi, text_en)
            VALUES ('delete', old.id, old.text_mi, old.text_en);
        END;
    """)


def migrate_tables(conn: sqlite3.Connection) -> None:
    """Add columns that were missing from initial schema versions."""
    pollex_cols = {row[1] for row in conn.execute("PRAGMA table_info(pollex_entries)")}
    if "source_author" not in pollex_cols:
        conn.execute("ALTER TABLE pollex_entries ADD COLUMN source_author TEXT")
        print("  migrated: pollex_entries.source_author added")
    if "cognateset_id" not in pollex_cols:
        conn.execute("ALTER TABLE pollex_entries ADD COLUMN cognateset_id TEXT")
        print("  migrated: pollex_entries.cognateset_id added")

    te_aka_cols = {row[1] for row in conn.execute("PRAGMA table_info(te_aka_entries)")}
    if "content_hash" not in te_aka_cols:
        conn.execute("ALTER TABLE te_aka_entries ADD COLUMN content_hash TEXT")
        print("  migrated: te_aka_entries.content_hash added")
    if "first_seen" not in te_aka_cols:
        conn.execute("ALTER TABLE te_aka_entries ADD COLUMN first_seen TEXT")
        print("  migrated: te_aka_entries.first_seen added")

    paekupu_cols = {row[1] for row in conn.execute("PRAGMA table_info(paekupu_entries)")}
    if "content_hash" not in paekupu_cols:
        conn.execute("ALTER TABLE paekupu_entries ADD COLUMN content_hash TEXT")
        print("  migrated: paekupu_entries.content_hash added")
    if "first_seen" not in paekupu_cols:
        conn.execute("ALTER TABLE paekupu_entries ADD COLUMN first_seen TEXT")
        print("  migrated: paekupu_entries.first_seen added")

    meta_cols = {row[1] for row in conn.execute("PRAGMA table_info(source_metadata)")}
    if "default_dialect" not in meta_cols:
        conn.execute("ALTER TABLE source_metadata ADD COLUMN default_dialect TEXT")
        print("  migrated: source_metadata.default_dialect added")
    # Seed the one known dialect default (idempotent; only fills NULLs).
    conn.execute(
        "UPDATE source_metadata SET default_dialect = 'Tai Tokerau' "
        "WHERE source_id = 'papakupu' AND default_dialect IS NULL"
    )


def seed_source_metadata(conn: sqlite3.Connection) -> None:
    sources = [
        ("williams",           "Williams Dictionary (1844/1971)",           "CC BY-SA 3.0 NZ", "https://nzetc.victoria.ac.nz/tm/scholarly/tei-WillDict.html", None, 0, "Primary open-licence source; TEI encoding"),
        ("papakupu",           "Papakupu o Tai Tokerau",                    "For Private Use Only", None,                                              None, 0, "Northland dialect; local use only; do not distribute"),
        ("pollex",             "POLLEX-Online (Maori reflexes)",            None,              "https://pollex.eva.mpg.de/language/maori/",               None, 0, "Etymological; permission contact pending"),
        ("pollex_cognatesets", "POLLEX-Online (protoform cognate sets)",    None,              "https://pollex.eva.mpg.de/entry/",                        None, 0, "Full protoform records with cross-language reflexes; scraped"),
        ("lpo",                "The Lexicon of Proto Oceanic (tlopo)",      "CC-BY-4.0",       "https://tlopo.clld.org",                                  None, 0, "Proto-Oceanic layer; CLDF from github.com/lexibank/tlopo"),
        ("acd",                "Austronesian Comparative Dictionary",        "CC-BY-4.0",       "https://acd.clld.org",                                    None, 0, "PAN/PMP layer; CLDF from github.com/lexibank/acd"),
        ("te_aka",             "Te Aka Maori Dictionary",                   "Restricted",      "https://maoridictionary.co.nz",                           None, 0, "Stub — permissions handled externally"),
        ("hepatakakupu",       "He Pataka Kupu",                            "Restricted",      "https://www.hepatakakapu.maori.nz",                       None, 0, "Monolingual Maori; stub — permissions handled externally"),
        ("paekupu",            "Paekupu (curriculum vocabulary)",           "Restricted",      "https://www.paekupu.co.nz",                               None, 0, "Curriculum subject areas; stub — permissions handled externally"),
        ("personal",           "Personal Lexicon",                          "User-owned",      None,                                                      None, 0, "User-added words and notes"),
    ]
    conn.executemany(
        """INSERT OR IGNORE INTO source_metadata
               (source_id, display_name, licence, url, last_updated, entry_count, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        sources,
    )


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        create_tables(conn)
        migrate_tables(conn)
        seed_source_metadata(conn)
        conn.commit()
    print(f"Database initialised: {DB_PATH}")


if __name__ == "__main__":
    main()
