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

        -- ── ABVD — Austronesian Basic Vocabulary Database ─────────────────────
        -- CLDF from github.com/lexibank/abvd (CC-BY-4.0). Unlike POLLEX/LPO/ACD,
        -- ABVD has NO reconstructed protoforms — a cognateset is an attested
        -- cognacy class scoped to ONE concept (e.g. 'hand-1'); members are real
        -- forms across Austronesian languages. Filtered at import (07b) to sets
        -- with >=1 Polynesian/Oceanic member (matched against pollex_languages).
        CREATE TABLE IF NOT EXISTS abvd_parameters (
            id                TEXT PRIMARY KEY,   -- CLDF concept ID
            name              TEXT NOT NULL,      -- concept gloss
            concepticon_id    TEXT,
            concepticon_gloss TEXT
        );
        CREATE TABLE IF NOT EXISTS abvd_languages (
            id             TEXT PRIMARY KEY,   -- CLDF language ID
            name           TEXT NOT NULL,
            glottocode     TEXT,
            glottolog_name TEXT,
            iso_code       TEXT,
            macroarea      TEXT,
            family         TEXT,
            is_polynesian  INTEGER NOT NULL DEFAULT 0,  -- matched pollex_languages
            subgroup       TEXT,               -- POLLEX subgroup where matched
            url            TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_abvd_lang_iso ON abvd_languages(iso_code);
        CREATE TABLE IF NOT EXISTS abvd_cognatesets (
            cognateset_id  TEXT PRIMARY KEY,   -- e.g. 'hand-1' (per-concept class)
            parameter_id   TEXT,               -- concept (FK abvd_parameters.id)
            concept_name   TEXT,
            n_members      INTEGER NOT NULL DEFAULT 0,
            n_poly_members INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_abvd_cs_param ON abvd_cognatesets(parameter_id);
        CREATE TABLE IF NOT EXISTS abvd_forms (
            id           TEXT PRIMARY KEY,   -- CLDF form ID
            language_id  TEXT NOT NULL,      -- FK abvd_languages.id
            parameter_id TEXT,               -- concept
            value        TEXT,
            form         TEXT,
            segments     TEXT,
            loan         TEXT,
            comment      TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_abvd_form_lang ON abvd_forms(language_id);
        CREATE INDEX IF NOT EXISTS idx_abvd_form_param ON abvd_forms(parameter_id);
        CREATE TABLE IF NOT EXISTS abvd_cognates (
            id            TEXT PRIMARY KEY,   -- CLDF cognate judgment ID
            form_id       TEXT NOT NULL,      -- FK abvd_forms.id
            cognateset_id TEXT NOT NULL,      -- FK abvd_cognatesets.cognateset_id
            doubt         TEXT,
            method        TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_abvd_cog_set ON abvd_cognates(cognateset_id);
        CREATE INDEX IF NOT EXISTS idx_abvd_cog_form ON abvd_cognates(form_id);

        -- ── Walworth — Polynesian comparative wordlist ───────────────────────
        -- CLDF from github.com/lexibank/walworthpolynesian (CC-BY-4.0). A
        -- Polynesian-only LingPy cognacy dataset (Walworth 2014); cognatesets are
        -- bare integer IDs (the form's `Cognacy` value), expert-coded per concept.
        -- Imported FULL + UNFILTERED (07c) — the whole set is already Polynesian,
        -- so no Polynesian-member filter (cf. ABVD). subgroup tagged where the
        -- language matches the curated pollex_languages; gap-fill source for ETY_*.
        CREATE TABLE IF NOT EXISTS walworth_parameters (
            id                TEXT PRIMARY KEY,   -- CLDF concept ID (e.g. '210_onethousand')
            name              TEXT NOT NULL,      -- concept gloss
            concepticon_id    TEXT,
            concepticon_gloss TEXT
        );
        CREATE TABLE IF NOT EXISTS walworth_languages (
            id             TEXT PRIMARY KEY,   -- CLDF language ID
            name           TEXT NOT NULL,
            glottocode     TEXT,
            glottolog_name TEXT,
            iso_code       TEXT,
            macroarea      TEXT,
            family         TEXT,
            latitude       TEXT,
            longitude      TEXT,
            is_polynesian  INTEGER NOT NULL DEFAULT 0,  -- matched pollex_languages
            subgroup       TEXT                -- POLLEX subgroup where matched
        );
        CREATE INDEX IF NOT EXISTS idx_walworth_lang_iso ON walworth_languages(iso_code);
        CREATE TABLE IF NOT EXISTS walworth_cognatesets (
            cognateset_id TEXT PRIMARY KEY,   -- bare integer cognacy class id
            parameter_id  TEXT,              -- concept (FK walworth_parameters.id)
            concept_name  TEXT,
            n_members     INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_walworth_cs_param ON walworth_cognatesets(parameter_id);
        CREATE TABLE IF NOT EXISTS walworth_forms (
            id           TEXT PRIMARY KEY,   -- CLDF form ID
            local_id     TEXT,
            language_id  TEXT NOT NULL,      -- FK walworth_languages.id
            parameter_id TEXT,              -- concept
            value        TEXT,
            form         TEXT,
            segments     TEXT,
            cognacy      TEXT,              -- cognateset id (== Cognateset_ID)
            loan         TEXT,
            comment      TEXT,
            source       TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_walworth_form_lang ON walworth_forms(language_id);
        CREATE INDEX IF NOT EXISTS idx_walworth_form_param ON walworth_forms(parameter_id);
        CREATE TABLE IF NOT EXISTS walworth_cognates (
            id            TEXT PRIMARY KEY,   -- CLDF cognate judgment ID
            form_id       TEXT NOT NULL,      -- FK walworth_forms.id
            cognateset_id TEXT NOT NULL,      -- FK walworth_cognatesets.cognateset_id
            doubt         TEXT,
            method        TEXT,
            alignment     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_walworth_cog_set ON walworth_cognates(cognateset_id);
        CREATE INDEX IF NOT EXISTS idx_walworth_cog_form ON walworth_cognates(form_id);

        -- ── Tregear — Maori-Polynesian Comparative Dictionary (1891) ─────────
        -- Edward Tregear 1891; NZETC TEI (CC BY-SA 3.0 NZ), scraped from the
        -- natlib.govt.nz webarchive snapshot (nzetc.victoria.ac.nz now redirects
        -- there). Source pages tei-TreMaor-c1-1..c1-15 = the 15 Maori letter
        -- sections (A E H I K M N NG O P R T U W WH). Each entry is a Maori
        -- headword + English gloss + a block of comparative cognates keyed by
        -- full Polynesian/Oceanic language name (Samoan, Hawaiian, Tongan, ...).
        -- Long vowels are grave/circumflex-marked in the pronunciation, not
        -- macrons. Staging-only ETY_* comparative source (no unify until S57).
        CREATE TABLE IF NOT EXISTS tregear_entries (
            id            INTEGER PRIMARY KEY,
            headword      TEXT NOT NULL,   -- raw as printed, e.g. 'HA', 'Whaka-HAERE'
            headword_norm TEXT,            -- normalise_search_key (macron/vowel-fold) for the entry bridge
            homonym_index INTEGER NOT NULL DEFAULT 1,  -- 1..n for repeated headwords
            pronunciation TEXT,            -- from (<i>..</i>); grave/circumflex length marks
            gloss_en      TEXT,            -- definition + Cf. cross-refs, plain text
            letter        TEXT,            -- source letter section: A/E/H/.../WH
            tei_ref       TEXT,            -- e.g. 'tei-TreMaor-c1-3#n40'
            page_no       INTEGER          -- nearest preceding page-break number
        );
        CREATE INDEX IF NOT EXISTS idx_tregear_entry_norm ON tregear_entries(headword_norm);
        CREATE TABLE IF NOT EXISTS tregear_cognates (
            id               INTEGER PRIMARY KEY,
            tregear_entry_id INTEGER NOT NULL,          -- FK tregear_entries.id
            language         TEXT NOT NULL,             -- normalised full name, e.g. 'Hawaiian'
            extra_polynesian INTEGER NOT NULL DEFAULT 0,-- 1 if 'Ext. Poly.' (non-Polynesian Austronesian)
            form             TEXT,                      -- lead comparative form
            gloss            TEXT,                      -- full comparative text for this language
            seq              INTEGER                    -- order within the entry
        );
        CREATE INDEX IF NOT EXISTS idx_tregear_cog_entry ON tregear_cognates(tregear_entry_id);
        CREATE INDEX IF NOT EXISTS idx_tregear_cog_lang  ON tregear_cognates(language);

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

        -- ── POLLEX reflex → unified entry links ───────────────────────────────
        -- Bridges the comparative layer to the user-facing dictionary: a POLLEX
        -- Māori reflex matched to an `entry` row by macron-neutral headword key.
        -- Lets the app surface the whole proto-tree on the word a user looks up.
        -- (entry is defined further below; SQLite allows the forward FK ref.)
        CREATE TABLE IF NOT EXISTS pollex_entry_links (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            cognateset_id    TEXT    NOT NULL REFERENCES pollex_cognatesets(id),
            reflex_id        INTEGER REFERENCES pollex_reflexes(id),
            entry_id         INTEGER NOT NULL REFERENCES entry(id),
            match_key        TEXT,    -- normalise_search_key value that matched
            match_method     TEXT,    -- 'headword_exact'
            match_confidence REAL
        );
        CREATE INDEX IF NOT EXISTS idx_pollex_entry_links_cs
            ON pollex_entry_links(cognateset_id);
        CREATE INDEX IF NOT EXISTS idx_pollex_entry_links_entry
            ON pollex_entry_links(entry_id);

        -- ════════════════════════════════════════════════════════════════════
        --  UNIFIED ETYMOLOGY LAYER  (ETY_*)  — etymology-unification plan, S56+
        --  Mirror of the entry/sense/relation core for the comparative layer.
        --  A rebuildable projection of the raw pollex_*/lpo_*/acd_*/tregear_*/
        --  abvd_*/walworth_* tables, built by scripts/52_build_etymology_unified.py.
        --  The raw per-source etymology tables stay STAGING-ONLY; the slim app DB
        --  ships ONLY these ETY_* tables (hard cutover, no compat views — S59).
        --  Provenance on every set/reflex: source, source_ref (raw id), gap_fill.
        -- ════════════════════════════════════════════════════════════════════

        -- ── ETY_level: reconstruction levels (AN>MP>OC>…>PN>NP>CE) ────────────
        -- Reference/ordering table; mirrors reconstruction_levels. level codes on
        -- ETY_cognateset are free text (not FK-enforced) — a set may carry a code
        -- absent here (e.g. 'XO').
        CREATE TABLE IF NOT EXISTS ETY_level (
            code        TEXT PRIMARY KEY,   -- AN|MP|OC|PN|NP|CE|…
            name        TEXT,               -- full name, e.g. "Central Eastern Polynesian"
            parent_code TEXT,               -- next level up (ancestry ordering)
            depth_rank  INTEGER             -- 0 = deepest (AN); higher = shallower
        );

        -- ── ETY_depth: one clean display label per depth_rank ────────────────
        -- Many level codes share a depth_rank; this gives ONE canonical name per
        -- rung (the Māori-lineage spine ancestor) for clean sort/group output.
        -- Mirrors staging depth_labels. Join: ETY_level.depth_rank = ETY_depth.depth_rank.
        CREATE TABLE IF NOT EXISTS ETY_depth (
            depth_rank INTEGER PRIMARY KEY,  -- 0 = deepest (AN); higher = shallower
            label      TEXT,                 -- e.g. "Polynesian" (spine node for the rung)
            spine_code TEXT                  -- representative ETY_level.code (NULL for 99)
        );

        -- ── ETY_language: comparative language reference ─────────────────────
        -- Mirrors pollex_languages. S56 seeds the POLLEX 67; ABVD/Tregear language
        -- sets are folded in at S57 (distinguished by `source`).
        CREATE TABLE IF NOT EXISTS ETY_language (
            lang_key   TEXT PRIMARY KEY,    -- language slug/key (POLLEX language_slug)
            name       TEXT NOT NULL,
            iso_code   TEXT,
            subgroup   TEXT,                -- Tongic|Eastern Polynesian|Samoic-Outlier|…
            region     TEXT,
            country    TEXT,                -- country_or_island_group
            notes      TEXT,
            source     TEXT NOT NULL        -- pollex|abvd|tregear
        );
        CREATE INDEX IF NOT EXISTS idx_ety_language_subgroup ON ETY_language(subgroup);

        -- ── ETY_cognateset: one reconstructed protoform (mirrors entry) ──────
        CREATE TABLE IF NOT EXISTS ETY_cognateset (
            id          INTEGER PRIMARY KEY,  -- surrogate; VOLATILE across rebuilds
            source      TEXT NOT NULL,        -- pollex|lpo|acd|tregear|abvd|walworth
            source_ref  TEXT NOT NULL,        -- raw cognateset id (traceback)
            protoform   TEXT NOT NULL,        -- reconstructed form / set name
            proto_key   TEXT,                 -- normalise_proto_key(protoform); cross-source dedup (S57)
            level       TEXT,                 -- level code (-> ETY_level.code, not enforced)
            gloss       TEXT,                 -- description / gloss
            set_group   TEXT,                 -- ACD etymon_id / LPO chapter_id (ancestry grouping)
            notes       TEXT,
            url         TEXT,
            gap_fill    INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_ety_cognateset_source   ON ETY_cognateset(source);
        CREATE INDEX IF NOT EXISTS idx_ety_cognateset_protokey ON ETY_cognateset(proto_key);
        CREATE INDEX IF NOT EXISTS idx_ety_cognateset_srcref   ON ETY_cognateset(source, source_ref);
        CREATE INDEX IF NOT EXISTS idx_ety_cognateset_level    ON ETY_cognateset(level);

        -- ── ETY_reflex: one language reflex of a set (mirrors sense/form) ────
        CREATE TABLE IF NOT EXISTS ETY_reflex (
            id            INTEGER PRIMARY KEY,  -- surrogate; VOLATILE across rebuilds
            cognateset_id INTEGER NOT NULL REFERENCES ETY_cognateset(id),
            source        TEXT NOT NULL,        -- pollex|abvd|tregear|walworth
            source_ref    TEXT,                 -- raw reflex/form id (traceback)
            lang_key      TEXT,                 -- -> ETY_language.lang_key
            language      TEXT,                 -- display name
            form          TEXT,                 -- the reflex form
            gloss         TEXT,
            source_code   TEXT,                 -- citation code (POLLEX)
            source_author TEXT,
            flags         TEXT,                 -- JSON array
            gap_fill      INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_ety_reflex_set  ON ETY_reflex(cognateset_id);
        CREATE INDEX IF NOT EXISTS idx_ety_reflex_lang ON ETY_reflex(lang_key);
        CREATE INDEX IF NOT EXISTS idx_ety_reflex_src  ON ETY_reflex(source, source_ref);

        -- ── ETY_link: set↔set ancestry / equivalence (mirrors relation) ─────
        --  Populated at S57 from etymology_links + protoform_ancestry.
        CREATE TABLE IF NOT EXISTS ETY_link (
            id               INTEGER PRIMARY KEY,
            source_set_id    INTEGER NOT NULL REFERENCES ETY_cognateset(id),
            target_set_id    INTEGER REFERENCES ETY_cognateset(id),
            link_type        TEXT NOT NULL,     -- ancestry|equivalence|cross_ref
            relation         TEXT,              -- cf|descends_from|same_as
            match_confidence REAL,
            match_method     TEXT,
            origin           TEXT,              -- etymology_links|protoform_ancestry|notes
            notes            TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ety_link_source ON ETY_link(source_set_id);
        CREATE INDEX IF NOT EXISTS idx_ety_link_target ON ETY_link(target_set_id);

        -- ── ETY_entry_link: reflex/set → unified Māori entry bridge ─────────
        --  Populated at S57 (extends pollex_entry_links to all sources).
        CREATE TABLE IF NOT EXISTS ETY_entry_link (
            id               INTEGER PRIMARY KEY,
            cognateset_id    INTEGER NOT NULL REFERENCES ETY_cognateset(id),
            reflex_id        INTEGER REFERENCES ETY_reflex(id),
            entry_id         INTEGER NOT NULL REFERENCES entry(id),
            source           TEXT NOT NULL,     -- etymology source that produced the bridge
            match_key        TEXT,
            match_method     TEXT,
            match_confidence REAL
        );
        CREATE INDEX IF NOT EXISTS idx_ety_entry_link_set   ON ETY_entry_link(cognateset_id);
        CREATE INDEX IF NOT EXISTS idx_ety_entry_link_entry ON ETY_entry_link(entry_id);

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
            part_of_speech_en TEXT,                -- English part-of-speech (for later canonicalisation)
            part_of_speech_mi TEXT,                -- Māori part-of-speech (for later canonicalisation)
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
            register        TEXT,
            part_of_speech  TEXT,                  -- raw per-sense POS
            part_of_speech_en TEXT,                -- canonical English POS (resolved via std_pos at build)
            part_of_speech_mi TEXT                 -- canonical Māori POS (resolved via std_pos at build)
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


def _add_column(conn: sqlite3.Connection, table: str, col: str, decl: str) -> None:
    """Idempotent helper: add a column only if it does not exist."""
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def migrate_pos_columns(conn: sqlite3.Connection) -> None:
    """Add part-of-speech columns to sense and entry tables (idempotent)."""
    _add_column(conn, "sense", "part_of_speech", "TEXT")
    _add_column(conn, "sense", "part_of_speech_en", "TEXT")
    _add_column(conn, "sense", "part_of_speech_mi", "TEXT")
    _add_column(conn, "entry", "part_of_speech_en", "TEXT")
    _add_column(conn, "entry", "part_of_speech_mi", "TEXT")


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
        ("abvd",               "Austronesian Basic Vocabulary Database",     "CC-BY-4.0",       "https://abvd.eva.mpg.de/austronesian/",                   None, 0, "Attested cognate clusters across Austronesian; CLDF from github.com/lexibank/abvd; filtered to sets with a Polynesian member"),
        ("walworth",           "Walworth Polynesian comparative wordlist",   "CC-BY-4.0",       "https://github.com/lexibank/walworthpolynesian",          None, 0, "Polynesian-only LingPy cognacy dataset (Walworth 2014); CLDF from github.com/lexibank/walworthpolynesian; full + unfiltered; ETY_* gap-fill source"),
        ("tregear",            "Tregear Maori-Polynesian Comparative Dictionary (1891)", "CC BY-SA 3.0 NZ", "https://nzetc.victoria.ac.nz/tm/scholarly/tei-TreMaor.html", None, 0, "Comparative etymological (Tregear 1891); NZETC TEI scraped from natlib.govt.nz webarchive snapshot 20210104; Maori headword + English gloss + per-language Polynesian/Oceanic cognates; staging-only ETY_* source"),
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
        migrate_pos_columns(conn)
        migrate_tables(conn)
        seed_source_metadata(conn)
        conn.commit()
    print(f"Database initialised: {DB_PATH}")


if __name__ == "__main__":
    main()
