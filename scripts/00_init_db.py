"""Creates staging_dictionary.db with all tables, FTS virtual tables, triggers,
and seeds source_metadata. Safe to re-run (CREATE IF NOT EXISTS).
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sweep_patch import PATCH_DDL
from sweep_queue import QUEUE_DDL

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
            headword_note  TEXT,          -- bracket qualifier printed with the headword
                                          --   ('pl. wāhine', 'poetical')
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

        -- ── TaiKupu (Ngāpuhi vocab app; shown in-app under the Papakupu banner) ─
        CREATE TABLE IF NOT EXISTS taikupu_entries (
            id                  INTEGER PRIMARY KEY,
            source_entry_id     TEXT NOT NULL UNIQUE,   -- TaiKupu API id (e.g. e_1780218354352_y91cn1); stable across refreshes
            headword            TEXT NOT NULL,          -- maori
            headword_sort       TEXT NOT NULL,
            headword_search     TEXT NOT NULL,
            part_of_speech      TEXT,                   -- present in API but currently always empty
            definition          TEXT,                   -- english gloss
            usage_examples      TEXT,                   -- JSON array of {text_mi, text_en}
            level               INTEGER,                -- learning poutama position 1..100
            notes               TEXT,
            content_hash        TEXT,
            first_seen          TEXT,
            created_at          TEXT DEFAULT (datetime('now')),
            last_updated        TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_taikupu_search
            ON taikupu_entries(headword_search);
        CREATE INDEX IF NOT EXISTS idx_taikupu_sort
            ON taikupu_entries(headword_sort);

        CREATE VIRTUAL TABLE IF NOT EXISTS taikupu_fts USING fts5(
            headword, definition, usage_examples,
            content='taikupu_entries', content_rowid='id',
            tokenize='unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS taikupu_fts_ins AFTER INSERT ON taikupu_entries BEGIN
            INSERT INTO taikupu_fts(rowid, headword, definition, usage_examples)
            VALUES (new.id, new.headword, new.definition, new.usage_examples);
        END;
        CREATE TRIGGER IF NOT EXISTS taikupu_fts_upd AFTER UPDATE ON taikupu_entries BEGIN
            INSERT INTO taikupu_fts(taikupu_fts, rowid, headword, definition, usage_examples)
            VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
            INSERT INTO taikupu_fts(rowid, headword, definition, usage_examples)
            VALUES (new.id, new.headword, new.definition, new.usage_examples);
        END;
        CREATE TRIGGER IF NOT EXISTS taikupu_fts_del AFTER DELETE ON taikupu_entries BEGIN
            INSERT INTO taikupu_fts(taikupu_fts, rowid, headword, definition, usage_examples)
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

        -- ── Te Mara Reo (temarareo.org) ───────────────────────────────────────
        -- Richard Benton's Maori plant-name garden. Two page families feed two
        -- layers: TMR-*.html Maori names -> temarareo_entries (unified core, the
        -- only slice that unifies), and PPN-*.html protoforms ->
        -- temarareo_cognatesets + _reflexes + _chain (ETY_* comparative layer).
        -- CC BY-NC 3.0 NZ: redistributable with attribution, non-commercial only.
        CREATE TABLE IF NOT EXISTS temarareo_entries (
            id               INTEGER PRIMARY KEY,
            source_entry_id  TEXT NOT NULL UNIQUE,  -- page stem, or 'idx:<ppn>:<name>' for index-only names
            headword         TEXT NOT NULL,         -- Maori plant name, annotations stripped
            headword_sort    TEXT,                  -- normalise_sort_key
            headword_search  TEXT,                  -- normalise_search_key (macron/vowel-fold)
            homonym_no       INTEGER,               -- index homonym marker, e.g. 'parapara [2]'
            variant          TEXT,                  -- alternative spelling, e.g. 'ti (tii)'
            definition       TEXT,                  -- gloss from the name page, else the index note
            note             TEXT,                  -- secondary prose line from the page
            species          TEXT,                  -- JSON array of scientific binomials
            related_names    TEXT,                  -- JSON array of {names, literal_meaning, species, note}
            ppn_form         TEXT,                  -- protoform this name is listed under
            stage_no         INTEGER,               -- index stage 1..14 (etymological layer)
            stage_name       TEXT,
            page             TEXT,                  -- TMR-*.html, NULL when index-only
            url              TEXT,
            has_page         INTEGER NOT NULL DEFAULT 0  -- 1 = has its own TMR page (fuller record)
        );
        CREATE INDEX IF NOT EXISTS idx_tmr_entry_search ON temarareo_entries(headword_search);
        CREATE INDEX IF NOT EXISTS idx_tmr_entry_sort   ON temarareo_entries(headword_sort);

        CREATE TABLE IF NOT EXISTS temarareo_cognatesets (
            id            INTEGER PRIMARY KEY,
            page          TEXT NOT NULL UNIQUE,   -- PPN-*.html
            protoform     TEXT NOT NULL,          -- as printed, without the leading *
            proto_key     TEXT,                   -- normalise_proto_key, for cross-source matching
            level_code    TEXT,                   -- ETY_level.code, NULL if unmapped
            level_name    TEXT,                   -- as written, e.g. 'Proto Polynesian'
            gloss         TEXT,
            species       TEXT,                   -- JSON array
            related_words TEXT,                   -- discussion prose
            further_info  TEXT,                   -- bibliography pointer, e.g. 'lpo3 pp.98-100'
            url           TEXT,
            variant_protoforms TEXT,              -- JSON array; pages covering several related protoforms
            under_construction INTEGER NOT NULL DEFAULT 0  -- source marks the page as a stub
        );
        CREATE INDEX IF NOT EXISTS idx_tmr_cog_key ON temarareo_cognatesets(proto_key);

        CREATE TABLE IF NOT EXISTS temarareo_reflexes (
            id            INTEGER PRIMARY KEY,
            cognateset_id INTEGER NOT NULL,       -- FK temarareo_cognatesets.id
            language      TEXT NOT NULL,          -- 'Tongan', 'Wayan Fijian', ...
            qualifier     TEXT,                   -- parenthetical, e.g. 'Duke of York Islands, PNG'
            form          TEXT,                   -- lead comparative form
            gloss         TEXT,                   -- full comparative text (Tregear precedent)
            kind          TEXT,                   -- polynesian | austronesian
            seq           INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_tmr_refl_set  ON temarareo_reflexes(cognateset_id);
        CREATE INDEX IF NOT EXISTS idx_tmr_refl_lang ON temarareo_reflexes(language);

        -- One row per step of a page's reconstruction chain (PAn -> PMP -> POc -> PPn),
        -- in printed order. Drives the ETY_link ancestry edges built by script 52.
        CREATE TABLE IF NOT EXISTS temarareo_chain (
            id            INTEGER PRIMARY KEY,
            cognateset_id INTEGER,                -- FK temarareo_cognatesets.id (PPN page)
            entry_id      INTEGER,                -- FK temarareo_entries.id (TMR page); one of the two
            seq           INTEGER NOT NULL,       -- 0-based order down the chain
            level_code    TEXT,
            level_name    TEXT,
            form          TEXT NOT NULL,
            proto_key     TEXT,
            gloss         TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tmr_chain_set   ON temarareo_chain(cognateset_id);
        CREATE INDEX IF NOT EXISTS idx_tmr_chain_entry ON temarareo_chain(entry_id);
        CREATE INDEX IF NOT EXISTS idx_tmr_chain_key   ON temarareo_chain(proto_key);

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
            sense_id         INTEGER REFERENCES sense(id),  -- which sense the protoform means;
                                                            --   NULL until the sweep decides
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
            target_sense_id INTEGER REFERENCES sense(id),   -- Williams prints sense-level pointers
                                                            --   ('apa (i), 2'); NULL until resolved
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


# --- Wakareo ā-ipurangi components (session 67) ---------------------------
# Ten landing tables, one per component dictionary. Each preserves its
# source's NATIVE lookup direction; 50_build_unified.py inverts the EN->MI
# ones so entry.headword is always Māori. These are the curated landing
# zone — cleanups edit them in place, never the JSON.

_WAKAREO_COMMON = """
            id              INTEGER PRIMARY KEY,
            source_entry_id TEXT NOT NULL,          -- 'WR-HMN.297' — a PRINT reference, NOT unique:
                                                     --   several records legitimately share one
            wakareo_id      INTEGER NOT NULL UNIQUE, -- Browse.aspx?ID=n — the true record identity
            ref_no          INTEGER NOT NULL,       -- the n in WR-XX.n
            headword        TEXT NOT NULL,
            headword_sort   TEXT NOT NULL,
            headword_search TEXT NOT NULL,
            part_of_speech  TEXT,
            search_scope    TEXT,                   -- JSON array of authored variants
            body_raw        TEXT,                   -- source HTML, kept as the archive: Tregear's
                                                     --   <B> runs still delimit its sense blocks
            body_text       TEXT,                   -- body_raw with markup stripped; NULL when only
                                                     --   the lemma survives. Consumers read THIS.
            content_hash    TEXT,
            first_seen      TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            last_updated    TEXT DEFAULT (datetime('now'))
"""

WAKAREO_EN_MI_TABLES = (
    "ngata_entries", "kimikupu_hou_entries", "he_kupu_arotake_entries",
    "kupu_rorohiko_entries", "kupu_mataora_entries",
)
WAKAREO_MI_EN_TABLES = (
    "tregear_exceptions_entries", "tai_kupu_variants_entries",
    "nga_tini_a_tangaroa_entries", "maori_law_lexicon_entries",
)


def create_wakareo_tables(conn: sqlite3.Connection) -> None:
    for table in WAKAREO_EN_MI_TABLES:
        conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            {_WAKAREO_COMMON},
            equivalents     TEXT,                   -- JSON array of Māori terms
            qualifier       TEXT,                   -- prose before the bold run, narrows the English lemma
            example_en      TEXT,
            example_mi      TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_{table}_search ON {table}(headword_search);
        CREATE INDEX IF NOT EXISTS idx_{table}_sort   ON {table}(headword_sort);
        """)
    for table in WAKAREO_MI_EN_TABLES:
        conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            {_WAKAREO_COMMON},
            gloss_en        TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_{table}_search ON {table}(headword_search);
        CREATE INDEX IF NOT EXISTS idx_{table}_sort   ON {table}(headword_sort);
        """)
    # Te Matatiki additionally carries a bracketed derivation citing Williams pages.
    conn.executescript(f"""
    CREATE TABLE IF NOT EXISTS te_matatiki_entries (
        {_WAKAREO_COMMON},
        gloss_en        TEXT,
        derivation      TEXT,
        williams_refs   TEXT                        -- JSON array of Williams page ints
    );
    CREATE INDEX IF NOT EXISTS idx_te_matatiki_entries_search
        ON te_matatiki_entries(headword_search);
    CREATE INDEX IF NOT EXISTS idx_te_matatiki_entries_sort
        ON te_matatiki_entries(headword_sort);
    """)


def _add_column(conn: sqlite3.Connection, table: str, col: str, decl: str) -> None:
    """Idempotent helper: add a column only if it does not exist."""
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _has_unique_constraint(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """True if *column* is the sole member of some UNIQUE index on *table*.

    Reads live index metadata (PRAGMA index_list/index_info) rather than
    parsing the CREATE TABLE text, so it is unaffected by comment wording or
    whitespace in the DDL -- it answers the actual constraint question.
    """
    for idx in conn.execute(f"PRAGMA index_list({table})").fetchall():
        idx_name, is_unique = idx[1], idx[2]
        if not is_unique:
            continue
        cols = [r[2] for r in conn.execute(f"PRAGMA index_info({idx_name})").fetchall()]
        if cols == [column]:
            return True
    return False


def _wakareo_create_sql(table: str, shape: str) -> str:
    """CREATE TABLE text for *table* under the CURRENT (fixed) schema shape.

    Mirrors create_wakareo_tables()'s three column layouts exactly, built
    from the same _WAKAREO_COMMON block, so a rebuilt table is byte-for-byte
    equivalent to one created fresh by create_wakareo_tables().
    """
    if shape == "en_mi":
        extra = """
            equivalents     TEXT,                   -- JSON array of Māori terms
            qualifier       TEXT,                   -- prose before the bold run, narrows the English lemma
            example_en      TEXT,
            example_mi      TEXT"""
    elif shape == "te_matatiki":
        extra = """
            gloss_en        TEXT,
            derivation      TEXT,
            williams_refs   TEXT                        -- JSON array of Williams page ints"""
    else:
        extra = """
            gloss_en        TEXT"""
    return f"CREATE TABLE {table} (\n{_WAKAREO_COMMON},{extra}\n)"


# Ruling P8: source_entry_id ('WR-HMN.297') is a print-dictionary reference,
# NOT a unique record identity -- several distinct entries legitimately share
# one (e.g. three separate Ngata entries for 'Alone' all cite WR-HMN.294).
# UNIQUE belongs on wakareo_id instead. This is the exhaustive, hardcoded set
# of the ten Wakareo landing tables that constraint applies to -- nothing
# else in this shared 417MB staging database is in scope for this migration.
WAKAREO_TABLE_SHAPES = {
    **{t: "en_mi" for t in WAKAREO_EN_MI_TABLES},
    **{t: "mi_en" for t in WAKAREO_MI_EN_TABLES},
    "te_matatiki_entries": "te_matatiki",
}


def migrate_wakareo_unique_key(conn: sqlite3.Connection) -> None:
    """Idempotent repair for ruling P8: move UNIQUE off source_entry_id and
    onto wakareo_id on any of the ten Wakareo tables still built under the
    old (buggy) constraint.

    Detects the old constraint via live index metadata (_has_unique_constraint),
    not by assuming a database's age or provenance -- so this is a genuine
    no-op on any database already migrated (including one freshly created by
    create_wakareo_tables(), which always uses the current, fixed DDL).

    Rebuilds via the standard SQLite pattern (temp table, copy, drop, rename)
    so existing rows are preserved. This can only repair the CONSTRAINT going
    forward -- any rows already silently overwritten by the old
    UNIQUE(source_entry_id) + INSERT OR REPLACE bug were destroyed before
    this migration ever ran and cannot be recovered from the database; the
    row counts printed below are what survives to be preserved, not evidence
    that nothing was lost.

    Scoped to exactly the ten names in WAKAREO_TABLE_SHAPES -- structurally
    incapable of touching any other table in this database.
    """
    for table, shape in WAKAREO_TABLE_SHAPES.items():
        if not _table_exists(conn, table):
            continue  # not created yet; create_wakareo_tables() will make it fresh (fixed schema)
        if not _has_unique_constraint(conn, table, "source_entry_id"):
            continue  # already on the fixed schema -- no-op

        n_before = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        col_list = ", ".join(cols)
        tmp = f"_migrate_p8_{table}"

        conn.execute(f"DROP TABLE IF EXISTS {tmp}")
        conn.execute(_wakareo_create_sql(tmp, shape))
        conn.execute(f"INSERT INTO {tmp} ({col_list}) SELECT {col_list} FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {tmp} RENAME TO {table}")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_search ON {table}(headword_search)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_sort   ON {table}(headword_sort)")
        n_after = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  migrated (P8): {table} -- UNIQUE moved source_entry_id -> wakareo_id; "
              f"{n_before} row(s) carried over unchanged ({n_after} now present). "
              f"Any rows already overwritten by the old constraint before this "
              f"migration ran are not recoverable -- this only fixes the constraint.")


def migrate_pos_columns(conn: sqlite3.Connection) -> None:
    """Add part-of-speech columns to sense and entry tables (idempotent)."""
    _add_column(conn, "sense", "note", "TEXT")   # editorial remarks, kept out of the gloss
    _add_column(conn, "sense", "part_of_speech", "TEXT")
    _add_column(conn, "sense", "part_of_speech_en", "TEXT")
    _add_column(conn, "sense", "part_of_speech_mi", "TEXT")
    _add_column(conn, "entry", "part_of_speech_en", "TEXT")
    _add_column(conn, "entry", "part_of_speech_mi", "TEXT")


def create_sweep_patch(conn: sqlite3.Connection) -> None:
    """The audit sweep's patch layer and cluster queue.

    50_build_unified.py rebuilds a source's slice from scratch, so sweep
    corrections cannot live in the unified core. They are recorded here and
    replayed after each build.
    """
    conn.executescript(PATCH_DDL)
    conn.executescript(QUEUE_DDL)


def migrate_wakareo_body_text(conn: sqlite3.Connection) -> None:
    """Add body_text to every Wakareo landing table (idempotent)."""
    for table in WAKAREO_EN_MI_TABLES + WAKAREO_MI_EN_TABLES + ("te_matatiki_entries",):
        _add_column(conn, table, "body_text", "TEXT")


def migrate_tables(conn: sqlite3.Connection) -> None:
    """Add columns that were missing from initial schema versions."""
    _add_column(conn, "williams_entries", "headword_note", "TEXT")
    # A headword could always be addressed; a sense never could. Williams's
    # 'see apa (i), sense 2' and POLLEX's '*afo is sense 2' both needed this.
    _add_column(conn, "ETY_entry_link", "sense_id", "INTEGER REFERENCES sense(id)")
    _add_column(conn, "relation", "target_sense_id", "INTEGER REFERENCES sense(id)")
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


def seed_source_metadata(conn: sqlite3.Connection) -> None:
    sources = [
        ("williams",           "Williams Dictionary (1844/1971)",           "CC BY-SA 3.0 NZ", "https://nzetc.victoria.ac.nz/tm/scholarly/tei-WillDict.html", None, 0, "Primary open-licence source; TEI encoding"),
        ("papakupu",           "Papakupu o Tai Tokerau",                    "For Private Use Only", None,                                              None, 0, "Northland dialect; local use only; do not distribute"),
        ("taikupu",            "Papakupu o Tai Tokerau",                    "Used with permission", "https://maoriminute.com/taikupu-app",                     None, 0, "Ngapuhi vocab app (Maori Minute); used with owner permission; shown in-app under the Papakupu banner; public JSON API /api/dictionary"),
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
        ("temarareo",          "Te Mara Reo (The Language Garden)",         "CC BY-NC 3.0 NZ", "https://www.temarareo.org/TMR-Ingoa.html",                None, 0, "Richard Benton's Maori plant-name etymologies; scraped from temarareo.org. Maori plant names unify into the core; Proto-Polynesian protoform pages feed the ETY_* layer. Open licence — attribution required, non-commercial use only"),

        # ── Wakareo ā-ipurangi components (session 67; permitted-use revision
        #    2026-09-06 — see docs/superpowers/specs/2026-09-05-wakareo-
        #    extraction-design.md, "Permitted use") ───────────────────────────
        ("tregear_exceptions",  "Wordstream Tregear Exceptions",   "Wordstream Corporation (c) 2002",        "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; used with permission for a private, non-commercial app; not for public distribution"),
        ("ngata",               "H.M. Ngata English-Maori Dictionary", "Whai Ngata; Learning Media 1993",    "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; English headword, inverted at unify; used with permission for a private, non-commercial app; not for public distribution"),
        ("te_matatiki",         "Te Matatiki Contemporary Maori Words", "Te Taura Whiri (c) 1996; OUP written-permission clause", "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; used with permission for a private, non-commercial app; not for public distribution"),
        ("kimikupu_hou",        "Kimikupu Hou modern words",       "NZCER; kaitiaki Te Taura Whiri",         "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; English headword, inverted at unify; used with permission for a private, non-commercial app; not for public distribution"),
        ("he_kupu_arotake",     "He Kupu Arotake",                 "Crown copyright (c) 1995; Education Review Office", "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; English headword, inverted at unify; used with permission for a private, non-commercial app; not for public distribution"),
        ("kupu_rorohiko",       "Kupu Rorohiko",                   "Te Taka Keegan; University of Waikato",  "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; Maori IT terms; English headword, inverted at unify; used with permission for a private, non-commercial app; not for public distribution"),
        ("tai_kupu_variants",   "Tai Kupu (Maori word variances)", "Wordstream Corporation (c) 2003",        "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; NOT the Maori Minute `taikupu` source; used with permission for a private, non-commercial app; not for public distribution"),
        ("nga_tini_a_tangaroa", "Nga tini a Tangaroa (fish names)","Ministry of Fisheries; Strickland",       "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; used with permission for a private, non-commercial app; not for public distribution"),
        ("kupu_mataora",        "Kupu Mataora",                    "Not asserted in Wakareo Legal.aspx",     "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; English headword, inverted at unify; used with permission for a private, non-commercial app; not for public distribution"),
        ("maori_law_lexicon",   "Custom Maori Law Lexicon",        "Not asserted in Wakareo Legal.aspx",     "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; used with permission for a private, non-commercial app; not for public distribution"),
    ]
    conn.executemany(
        """INSERT OR IGNORE INTO source_metadata
               (source_id, display_name, licence, url, last_updated, entry_count, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        sources,
    )
    # Seed the known dialect defaults (idempotent; only fills NULLs). Runs after the
    # INSERT so brand-new Tai Tokerau sources are tagged on their first init too.
    conn.execute(
        "UPDATE source_metadata SET default_dialect = 'Tai Tokerau' "
        "WHERE source_id IN ('papakupu', 'taikupu') AND default_dialect IS NULL"
    )
    # INSERT OR IGNORE above will not touch the ten Wakareo rows already seeded
    # (session 67) with the old "staging only — not exported" wording, now
    # false under the 2026-09-06 permitted-use revision. Update them explicitly;
    # idempotent, and scoped to exactly these ten source_ids.
    conn.executemany(
        "UPDATE source_metadata SET notes = ? WHERE source_id = ?",
        [(notes, source_id) for source_id, _, _, _, _, _, notes in sources
         if source_id in (
             "tregear_exceptions", "ngata", "te_matatiki", "kimikupu_hou",
             "he_kupu_arotake", "kupu_rorohiko", "tai_kupu_variants",
             "nga_tini_a_tangaroa", "kupu_mataora", "maori_law_lexicon",
         )],
    )


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        create_tables(conn)
        create_wakareo_tables(conn)
        create_sweep_patch(conn)
        migrate_wakareo_unique_key(conn)
        migrate_wakareo_body_text(conn)
        migrate_pos_columns(conn)
        migrate_tables(conn)
        seed_source_metadata(conn)
        conn.commit()
    print(f"Database initialised: {DB_PATH}")


if __name__ == "__main__":
    main()
