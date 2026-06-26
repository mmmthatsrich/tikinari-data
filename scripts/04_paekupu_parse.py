"""
Parse saved Paekupu word HTML files into JSON.

Reads sources/paekupu/raw/{slug}.html for each slug in paekupu_slugs.json.
Writes sources/paekupu/parsed/paekupu_entries.json.

One JSON record per word page.  Fields extracted:
  slug, headword (Maori), headword_en (English), part_of_speech (English),
  pos_mi (Maori POS label), subject_area (Maori area name),
  subject_area_en (English area name), subject_areas (all area slugs),
  audio_url, definition_mi (Maori short description),
  definition (English short description), alternative_words (JSON array),
  usage_examples (JSON array)

Usage:
  py 04_paekupu_parse.py
"""

import json
import re
import sys
from pathlib import Path

from lxml import etree

sys.stdout.reconfigure(encoding="utf-8")

RAW_DIR    = Path(__file__).parent.parent / "sources" / "paekupu" / "raw"
PARSED_DIR = Path(__file__).parent.parent / "sources" / "paekupu" / "parsed"
SLUGS_JSON = PARSED_DIR / "paekupu_slugs.json"
OUTPUT_PATH = PARSED_DIR / "paekupu_entries.json"

_PARSER = etree.HTMLParser()


def _ws(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).replace(" ", " ")).strip()


def _elem_text(elem) -> str:
    return _ws("".join(elem.itertext()))


def _korero_text(span_elem) -> str | None:
    """Extract plain text from a korero span containing embedded HTML.

    The span wraps an entire embedded HTML doc: <!DOCTYPE...><html>...<body><p>text</p>...
    lxml parses the <p> elements as children of the span, so we find them with .//p.
    """
    paras = span_elem.xpath(".//p")
    if paras:
        return _ws(" ".join("".join(p.itertext()) for p in paras)) or None
    # Fallback: all itertext (ignores head/meta noise since they have no text)
    return _ws("".join(span_elem.itertext())) or None


def parse_page(html_bytes: bytes, slug: str, slug_areas: list) -> dict | None:
    tree = etree.fromstring(html_bytes, _PARSER)

    # ── headword (Maori) ───────────────────────────────────────────────────────
    h1_els = tree.xpath('//div[@id="word_header"]//h1')
    if not h1_els:
        return None
    headword = _elem_text(h1_els[0])
    if not headword:
        return None

    # ── headword (English) ────────────────────────────────────────────────────
    h2_els = tree.xpath('//div[@id="word_header"]//h2[contains(@class,"english_word")]')
    headword_en = _elem_text(h2_els[0]) if h2_els else None

    # ── part of speech ────────────────────────────────────────────────────────
    cls_spans = tree.xpath('//div[@id="classification"]/span')
    part_of_speech = cls_spans[0].get("title", "").strip() or None if cls_spans else None
    pos_mi = _ws(cls_spans[0].text) or None if cls_spans else None

    # ── subject area ──────────────────────────────────────────────────────────
    ri_spans = tree.xpath('//div[@id="resource_indicator"]/span')
    subject_area = _elem_text(ri_spans[0]) or None if ri_spans else None
    subject_area_en = ri_spans[0].get("title", "").strip() or None if ri_spans else None

    # ── audio URL ─────────────────────────────────────────────────────────────
    audio_els = tree.xpath('//div[@id="main_audio_object"]/@data-url')
    audio_url = audio_els[0] if audio_els else None

    # ── Maori short description ───────────────────────────────────────────────
    mi_els = tree.xpath('//div[@id="short_description"]//div[@class="maori"]/p')
    definition_mi = _elem_text(mi_els[0]) or None if mi_els else None

    # ── English short description ─────────────────────────────────────────────
    en_els = tree.xpath('//div[@id="short_description"]//div[@class="english"]/p')
    definition = _elem_text(en_els[0]) or None if en_els else None

    # ── alternative words (KUPU KE ATU dropdown) ──────────────────────────────
    # <option disabled><p>word</p></option> — lxml may re-parse the <p> as sibling
    dropdown_areas = tree.xpath('//div[@id="short_description_dropdowns"]')
    alternative_words: list[str] = []
    if dropdown_areas:
        dd = dropdown_areas[0]
        # Collect from <option disabled> itertext (handles <p> as child or sibling)
        disabled_opts = dd.xpath('.//option[@disabled]')
        for opt in disabled_opts:
            text = _elem_text(opt)
            if text:
                alternative_words.append(text)
        # Also collect from any bare <p> elements (if <p> was split from option)
        if not alternative_words:
            paras = dd.xpath('.//p')
            for p in paras:
                text = _elem_text(p)
                if text and text not in alternative_words:
                    alternative_words.append(text)

    # ── usage examples (desktop pronounciations section only) ─────────────────
    korero_divs = tree.xpath(
        '//div[@id="pronounciations"]//div[@class="korero"]'
    )
    usage_examples: list[str] = []
    for kd in korero_divs:
        span = kd.find(".//span")
        if span is not None:
            text = _korero_text(span)
            if text:
                usage_examples.append(text)

    return {
        "slug":             slug,
        "headword":         headword,
        "headword_en":      headword_en or None,
        "part_of_speech":   part_of_speech,
        "pos_mi":           pos_mi,
        "subject_area":     subject_area,
        "subject_area_en":  subject_area_en,
        "subject_areas":    slug_areas,
        "audio_url":        audio_url,
        "definition_mi":    definition_mi,
        "definition":       definition,
        "alternative_words": alternative_words,
        "usage_examples":   usage_examples,
    }


def main() -> None:
    PARSED_DIR.mkdir(parents=True, exist_ok=True)

    if not SLUGS_JSON.exists():
        print(f"Error: {SLUGS_JSON} not found. Run 04_paekupu_scrape.py first.")
        sys.exit(1)

    slug_to_areas: dict = json.loads(SLUGS_JSON.read_text(encoding="utf-8"))
    print(f"Loaded {len(slug_to_areas):,} slugs from {SLUGS_JSON.name}")

    all_records: list[dict] = []
    skipped = 0
    missing = 0

    for i, slug in enumerate(sorted(slug_to_areas), 1):
        html_path = RAW_DIR / f"{slug}.html"
        if not html_path.exists():
            missing += 1
            continue

        try:
            record = parse_page(html_path.read_bytes(), slug, slug_to_areas[slug])
            if record is None:
                print(f"  [skip] {slug}: no headword found")
                skipped += 1
            else:
                all_records.append(record)
        except Exception as exc:
            print(f"  [error] {slug}: {exc}")
            skipped += 1

        if i % 2000 == 0:
            print(f"  ...{i:,}/{len(slug_to_areas):,} ({len(all_records):,} records so far)")

    OUTPUT_PATH.write_text(
        json.dumps(all_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nWrote {len(all_records):,} records -> {OUTPUT_PATH}")
    if missing:
        print(f"Missing HTML files: {missing}")
    if skipped:
        print(f"Skipped/errors: {skipped}")


if __name__ == "__main__":
    main()
