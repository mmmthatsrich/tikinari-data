"""
Parse saved Te Aka Māori Dictionary HTML files into JSON.

Reads sources/te_aka/raw/{ID}.html for each valid ID listed in manifest.json
(or all .html files if manifest is absent — useful for partial runs).
Writes sources/te_aka/parsed/te_aka_entries.json.

One JSON object per word_id.  All senses are bundled into a single
definition string ("1. ... | 2. ... | 3. ...").
"""

import json
import re
import sys
from pathlib import Path

from lxml import html as lhtml

RAW_DIR    = Path(__file__).parent.parent / "sources" / "te_aka" / "raw"
PARSED_DIR = Path(__file__).parent.parent / "sources" / "te_aka" / "parsed"
OUTPUT_PATH   = PARSED_DIR / "te_aka_entries.json"
MANIFEST_PATH = RAW_DIR / "manifest.json"

AUDIO_BASE = "https://storage.googleapis.com/maori-dictionary-prod2-web-assets/public/{id}.mp3"


# ── HTML parsing ──────────────────────────────────────────────────────────────

def _ws(text: str) -> str:
    """Collapse runs of whitespace (including newlines) to a single space."""
    return re.sub(r"\s+", " ", text).strip()


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

    for div in def_divs:
        # Main definition paragraph
        detail = div.xpath('./div[contains(@class,"flex-1")]')
        if not detail:
            continue
        p_list = detail[0].xpath('./p[@class="mb-0"]')
        if not p_list:
            continue
        def_p = p_list[0]

        # Sense number and POS from <strong> children
        strongs = def_p.xpath('./strong')
        sense_num = None
        pos_parts: list[str] = []
        for s in strongs:
            t = (s.text or "").strip()
            if re.match(r"^\d+\.$", t):
                sense_num = int(t[:-1])
            elif re.match(r"^\([^)]+\)$", t):
                pos_parts.append(t[1:-1])  # strip parens

        def_str = _def_text(def_p)
        senses.append({
            "sense_num": sense_num,
            "pos":       ", ".join(pos_parts) if pos_parts else None,
            "definition": def_str,
        })

        # Source citations: p.text-slate.mb-0 without x-show (not example paras)
        cit_paras = detail[0].xpath(
            './/p[contains(@class,"text-slate") and contains(@class,"mb-0") and not(@x-show)]'
        )
        for cp in cit_paras:
            ct = _ws(cp.text_content())
            if ct:
                all_citations.append(ct)

        # Usage examples (in DOM regardless of show/hide state)
        ex_paras = div.xpath('.//p[@x-show="showExample"]')
        for ep in ex_paras:
            em_tags = ep.xpath('.//em')
            if em_tags:
                ex_text = _ws(em_tags[0].text_content())
                if ex_text:
                    all_examples.append(ex_text)

        # Synonyms (dictionary-link anchors)
        for link in div.xpath('.//a[contains(@class,"dictionary-link")]'):
            href = link.get("href", "")
            m = re.search(r"/word/(\d+)", href)
            syn_id = int(m.group(1)) if m else None
            syn_text = link.text_content().strip()
            entry = {"text": syn_text, "word_id": syn_id}
            if syn_text and entry not in all_synonyms:
                all_synonyms.append(entry)

    if not senses:
        return None

    # ── combine multi-sense entries ───────────────────────────────────────────
    def_parts = []
    for s in senses:
        prefix = f"{s['sense_num']}. " if s["sense_num"] else ""
        def_parts.append(prefix + s["definition"])
    combined_def = " | ".join(def_parts)

    # POS from first sense that has one
    combined_pos = next((s["pos"] for s in senses if s["pos"]), None)

    return {
        "word_id":         word_id,
        "headword":        headword,
        "part_of_speech":  combined_pos,
        "definition":      combined_def,
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
