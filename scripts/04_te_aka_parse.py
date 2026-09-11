"""
Parse saved Te Aka Māori Dictionary HTML files into JSON.

Reads sources/te_aka/raw/{ID}.html for each valid ID listed in manifest.json
(or all .html files if manifest is absent — useful for partial runs).
Writes sources/te_aka/parsed/te_aka_entries.json.

One JSON object per word_id.  Each entry carries a structured ``senses`` list
(one dict per sense, with its own POS, gloss, and examples) so the unify step
can explode it into per-sense rows.  A legacy ``definition`` string
("1. ... | 2. ... | 3. ...") and flat ``usage_examples`` are kept alongside for
FTS and content-hash continuity.
"""

import json
import re
import sys
from pathlib import Path

from lxml import html as lhtml

sys.path.insert(0, str(Path(__file__).parent))
from te_aka_examples import split_example

RAW_DIR    = Path(__file__).parent.parent / "sources" / "te_aka" / "raw"
PARSED_DIR = Path(__file__).parent.parent / "sources" / "te_aka" / "parsed"
OUTPUT_PATH   = PARSED_DIR / "te_aka_entries.json"
MANIFEST_PATH = RAW_DIR / "manifest.json"

AUDIO_BASE = "https://storage.googleapis.com/maori-dictionary-prod2-web-assets/public/{id}.mp3"


# ── HTML parsing ──────────────────────────────────────────────────────────────

def _ws(text: str) -> str:
    """Collapse runs of whitespace (including newlines) to a single space."""
    return re.sub(r"\s+", " ", text).strip()


_PASSIVE_RE = re.compile(r"^\(-[^)]*\)\s*")


def _strip_passive(gloss: str) -> str:
    """Strip a leading passive/transitive marker, e.g. '(-ia,-ngia) to drive' ->
    'to drive'. Mirrors the Williams convention: the marker stays in
    definition_raw, gloss_en holds the bare gloss."""
    return _PASSIVE_RE.sub("", gloss).strip()


def _def_text(p_elem) -> str:
    """Extract definition text from a <p class='mb-0'> paragraph.

    Collects the tail text of every <strong> child (the text *after* the
    bold tag) plus the full text content of any non-<strong> children.
    Strongs themselves hold the sense number and POS markers, which we skip.
    """
    parts = []
    if p_elem.text and p_elem.text.strip():
        parts.append(p_elem.text.strip())
    for child in p_elem:
        if child.tag == "strong":
            if child.tail and child.tail.strip():
                parts.append(child.tail.strip())
        else:
            ct = child.text_content().strip()
            if ct:
                parts.append(ct)
            if child.tail and child.tail.strip():
                parts.append(child.tail.strip())
    return _ws(" ".join(p for p in parts if p))


def parse_page(html_bytes: bytes, word_id: int) -> dict | None:
    tree = lhtml.fromstring(html_bytes)

    # ── word-def section ─────────────────────────────────────────────────────
    wd_list = tree.xpath('//*[contains(@class,"word-def")]')
    if not wd_list:
        return None
    wd = wd_list[0]

    # ── headword (h2.title) ──────────────────────────────────────────────────
    h2_list = wd.xpath('.//h2[contains(@class,"title")]')
    if not h2_list:
        return None
    h2 = h2_list[0]
    headword = (h2.text or "").strip()
    if not headword:
        return None

    # ── audio URL ────────────────────────────────────────────────────────────
    has_audio = "no-audio" not in (h2.get("class") or "")
    audio_url = AUDIO_BASE.format(id=word_id) if has_audio else None

    # ── word-level filter tags (e.g. "Historical Loan Word") ─────────────────
    filter_spans = h2.xpath(
        './/span[contains(@class,"text-darkgray") and contains(@class,"font-bold") and contains(@class,"text-xs")]'
    )
    filters = [s.text_content().strip() for s in filter_spans if s.text_content().strip()]

    # ── definition containers (div#d{N}.flex) ────────────────────────────────
    def_divs = wd.xpath('.//div[starts-with(@id,"d") and contains(@class,"flex")]')

    senses: list[dict] = []
    all_examples: list[str] = []
    all_synonyms: list[dict] = []
    all_citations: list[str] = []

    for ordinal, div in enumerate(def_divs, 1):
        # Main definition paragraph
        detail = div.xpath('./div[contains(@class,"flex-1")]')
        if not detail:
            continue
        p_list = detail[0].xpath('./p[@class="mb-0"]')
        if not p_list:
            continue
        def_p = p_list[0]

        # Sense number and POS from <strong> children. Parenthesised strongs hold
        # the POS (e.g. "(verb)"); passive/transitive markers like "(-ia,-ngia)"
        # live in the body text, never in a strong, but guard against them anyway.
        strongs = def_p.xpath('./strong')
        sense_num = None
        pos_parts: list[str] = []
        for s in strongs:
            t = (s.text or "").strip()
            if re.match(r"^\d+\.$", t):
                sense_num = int(t[:-1])
            elif re.match(r"^\([^)]+\)$", t):
                inner = t[1:-1]
                if not inner.startswith("-"):
                    pos_parts.append(inner)  # POS, not a passive marker

        def_str = _def_text(def_p)
        pos = ", ".join(pos_parts) if pos_parts else None

        # Per-sense source citations: p.text-slate.mb-0 without x-show
        sense_citations: list[str] = []
        cit_paras = detail[0].xpath(
            './/p[contains(@class,"text-slate") and contains(@class,"mb-0") and not(@x-show)]'
        )
        for cp in cit_paras:
            ct = _ws(cp.text_content())
            if ct:
                sense_citations.append(ct)

        # Per-sense usage examples (in DOM regardless of show/hide state)
        # Te Aka gives both halves: <em>Māori (citation)</em> / English. Only the
        # <em> was read, so all 45,939 example rows had no translation while the
        # English sat in the same paragraph. Emitted as {mi, en} dicts; the
        # unify step still accepts bare strings from data parsed before this.
        sense_examples: list[dict] = []
        for ep in div.xpath('.//p[@x-show="showExample"]'):
            em_tags = ep.xpath('.//em')
            if em_tags:
                pair = split_example(ep.text_content(), em_tags[0].text_content())
                if pair:
                    sense_examples.append(pair)

        # Per-sense synonyms (dictionary-link anchors)
        sense_synonyms: list[dict] = []
        for link in div.xpath('.//a[contains(@class,"dictionary-link")]'):
            href = link.get("href", "")
            m = re.search(r"/word/(\d+)", href)
            syn_id = int(m.group(1)) if m else None
            syn_text = link.text_content().strip()
            syn = {"text": syn_text, "word_id": syn_id}
            if syn_text and syn not in sense_synonyms:
                sense_synonyms.append(syn)

        senses.append({
            "sense_number":   sense_num or ordinal,
            "part_of_speech": pos,
            "gloss_en":       _strip_passive(def_str),
            "definition_raw": def_str,
            "examples":       sense_examples,
            "citations":      sense_citations,
            "synonyms":       sense_synonyms,
        })

        # Entry-level aggregates (legacy / FTS / synonym resolution)
        all_examples.extend(sense_examples)
        all_citations.extend(sense_citations)
        for syn in sense_synonyms:
            if syn not in all_synonyms:
                all_synonyms.append(syn)

    if not senses:
        return None

    # ── legacy combined definition string (kept for FTS + content-hash) ────────
    def_parts = []
    for s in senses:
        prefix = f"{s['sense_number']}. " if s["sense_number"] else ""
        def_parts.append(prefix + s["definition_raw"])
    combined_def = " | ".join(def_parts)

    # Entry-level POS: first sense that has one (per-sense POS lives in senses[])
    combined_pos = next((s["part_of_speech"] for s in senses if s["part_of_speech"]), None)

    return {
        "word_id":         word_id,
        "headword":        headword,
        "part_of_speech":  combined_pos,
        "definition":      combined_def,
        "senses":          senses,
        "usage_examples":  all_examples,
        "audio_url":       audio_url,
        "synonyms":        all_synonyms,
        "source_citations": all_citations,
        "filters":         filters,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    PARSED_DIR.mkdir(parents=True, exist_ok=True)

    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        valid_ids: list[int] = manifest["valid_ids"]
        print(f"Using manifest: {len(valid_ids):,} valid IDs")
    else:
        valid_ids = sorted(int(p.stem) for p in RAW_DIR.glob("*.html") if p.stem.isdigit())
        print(f"No manifest — processing {len(valid_ids):,} HTML files in {RAW_DIR}")

    entries: list[dict] = []
    skipped = 0

    for i, word_id in enumerate(valid_ids, 1):
        html_path = RAW_DIR / f"{word_id}.html"
        if not html_path.exists():
            skipped += 1
            continue
        try:
            entry = parse_page(html_path.read_bytes(), word_id)
            if entry:
                entries.append(entry)
            else:
                print(f"  [skip] {word_id}: no parseable word-def")
                skipped += 1
        except Exception as exc:
            print(f"  [error] {word_id}: {exc}")
            skipped += 1

        if i % 1000 == 0:
            print(f"  ...{i:,}/{len(valid_ids):,} processed ({len(entries):,} entries)")

    OUTPUT_PATH.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nWrote {len(entries):,} entries -> {OUTPUT_PATH}")
    if skipped:
        print(f"Skipped / errors: {skipped}")


if __name__ == "__main__":
    main()
