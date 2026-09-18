"""
Parse saved He Pataka Kupu HTML files into JSON.

Reads sources/hepataka/raw/{ID}.html for each valid ID in manifest.json.
Writes sources/hepataka/parsed/hepataka_entries.json.

One JSON record per sense div.  A single word page can have multiple senses
(each with its own numeric div id).  Two page layouts exist:

  Pattern A: every sense div has its own <h2 class="title">.
  Pattern B: only the first sense has <h2>; later senses inherit the headword
             and get a <strong class="def num">N.</strong> for sense number.

Usage:
  py 05_hepataka_parse.py
"""

import json
import re
import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))
from hepataka_suffixes import split_strong

sys.stdout.reconfigure(encoding="utf-8")

RAW_DIR    = Path(__file__).parent.parent / "sources" / "hepataka" / "raw"
PARSED_DIR = Path(__file__).parent.parent / "sources" / "hepataka" / "parsed"
OUTPUT_PATH   = PARSED_DIR / "hepataka_entries.json"
MANIFEST_PATH = RAW_DIR / "manifest.json"

_PARSER = etree.HTMLParser()


def _ws(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _text_no_sup(elem) -> str:
    """Collect text content while skipping <sup> inner text (sense-ref numbers)."""
    parts = [elem.text or ""]
    for child in elem:
        if child.tag != "sup":
            parts.append(_text_no_sup(child))
        parts.append(child.tail or "")
    return "".join(parts)


def parse_page(html_bytes: bytes, word_id: int) -> list[dict]:
    tree = etree.fromstring(html_bytes, _PARSER)

    centre_divs = tree.xpath(
        '//div[contains(@class,"center") and contains(@class,"clearfix") and @id]'
    )
    sense_divs = [d for d in centre_divs if d.get("id", "").isdigit()]
    if not sense_divs:
        return []

    records: list[dict] = []
    last_headword: str | None = None

    for div in sense_divs:
        sense_id = int(div.get("id"))

        # ── headword ──────────────────────────────────────────────────────────
        h2 = div.find('.//h2[@class="title"]')
        if h2 is not None:
            hw = _ws(h2.text)
            if hw:
                last_headword = hw
        headword = last_headword or ""
        if not headword:
            continue

        # ── sense number ──────────────────────────────────────────────────────
        # Check <strong class="def num"> first (Pattern B and B-first);
        # fall back to <sup> inside h2 (Pattern A).
        sense_num: int | None = None
        num_strong = div.find('.//strong[@class="def num"]')
        if num_strong is not None:
            t = _ws(num_strong.text or "").rstrip(".")
            sense_num = int(t) if t.isdigit() else None
        if sense_num is None and h2 is not None:
            sup = h2.find("sup")
            if sup is not None:
                t = _ws(sup.text or "")
                sense_num = int(t) if t.isdigit() else None

        # ── POS + semantic domain ─────────────────────────────────────────────
        pos: str | None = None
        semantic_domain: str | None = None
        suffixes: list[str] = []
        def_span = div.find('.//span[@class="def"]')
        if def_span is not None:
            cls_span = def_span.find('.//span[@class="class"]')
            if cls_span is not None:
                pos = _ws(cls_span.text or "").rstrip(".").strip() or None
            strong = def_span.find("strong")
            if strong is not None:
                # .text, not itertext(): <strong> has a child <span> holding
                # the part of speech, and .text stops before it. The suffixes
                # sit in front of the bracketed domain and were discarded
                # here until now — 22,911 tokens across 14,996 pages.
                suffixes, semantic_domain = split_strong(strong.text)

        # ── definition (Maori description) ────────────────────────────────────
        desc_span = div.find('.//span[@class="description"]')
        definition = _ws(desc_span.text or "") or None if desc_span is not None else None

        # ── usage examples ────────────────────────────────────────────────────
        examples_span = div.find('.//span[@class="examples"]')
        usage_examples: list[str] = []
        if examples_span is not None:
            for em in examples_span.findall(".//em"):
                t = _ws("".join(em.itertext()))
                if t:
                    usage_examples.append(t)

        # ── synonyms ──────────────────────────────────────────────────────────
        # A synonym may name a SENSE of its target: 'hikoki (2)'. The number was
        # being stripped, so a pointer at one sense of a multi-sense word arrived
        # pointing at none (D35). The <sup> that _text_no_sup drops is the
        # target's homograph index, which is a different thing and stays dropped.
        synonyms_span = div.find('.//span[@class="synonyms"]')
        synonyms: list[str] = []
        synonym_senses: list[int | None] = []
        if synonyms_span is not None:
            raw = _ws(_text_no_sup(synonyms_span)).strip("{}").strip()
            for part in raw.split(","):
                part = _ws(part)
                m_sense = re.search(r"\(\s*(\d+)\s*\)", part)
                name = _ws(re.sub(r"\s*\(\s*\d+\s*\)\s*", " ", part))
                if name:
                    synonyms.append(name)
                    synonym_senses.append(int(m_sense.group(1)) if m_sense else None)

        # ── master definition ─────────────────────────────────────────────────
        # He Pataka Kupu names the entry holding this sense's authoritative
        # definition: <a class="master_definition" href="/word/1226">hurori (1)</a>
        # says turori sense 1 is defined at word 1226, sense 1 — and the two
        # definition texts are identical because it is the same definition.
        # 14,379 of these exist and none was being read.
        master_word_id: int | None = None
        master_sense: int | None = None
        for a in div.iter("a"):
            if "master_definition" not in (a.get("class") or ""):
                continue
            m_word = re.search(r"/word/(\d+)", a.get("href") or "")
            if not m_word:
                continue
            master_word_id = int(m_word.group(1))
            # '<headword> <sup>homograph</sup> (sense)' — the word id already
            # settles the homograph, so only the trailing parenthesis is new.
            m_sense = re.search(r"\((\d+)\)\s*$", _ws("".join(a.itertext())))
            master_sense = int(m_sense.group(1)) if m_sense else None
            break

        records.append({
            "id":              sense_id,
            "word_id":         word_id,
            "headword":        headword,
            "sense_number":    sense_num,
            "semantic_domain": semantic_domain,
            "suffixes":        suffixes,
            "part_of_speech":  pos,
            "definition":      definition,
            "usage_examples":  usage_examples,
            "synonyms":        synonyms,
            "synonym_senses":  synonym_senses,
            "master_word_id":  master_word_id,
            "master_sense":    master_sense,
        })

    return records


def main() -> None:
    PARSED_DIR.mkdir(parents=True, exist_ok=True)

    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        valid_ids: list[int] = manifest["valid_ids"]
        print(f"Using manifest: {len(valid_ids):,} valid IDs")
    else:
        valid_ids = sorted(int(p.stem) for p in RAW_DIR.glob("*.html") if p.stem.isdigit())
        print(f"No manifest -- processing {len(valid_ids):,} HTML files")

    all_records: list[dict] = []
    skipped = 0

    for i, word_id in enumerate(valid_ids, 1):
        html_path = RAW_DIR / f"{word_id}.html"
        if not html_path.exists():
            skipped += 1
            continue
        try:
            records = parse_page(html_path.read_bytes(), word_id)
            all_records.extend(records)
            if not records:
                print(f"  [skip] {word_id}: no sense divs found")
                skipped += 1
        except Exception as exc:
            print(f"  [error] {word_id}: {exc}")
            skipped += 1

        if i % 1000 == 0:
            print(f"  ...{i:,}/{len(valid_ids):,} ({len(all_records):,} records so far)")

    OUTPUT_PATH.write_text(
        json.dumps(all_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nWrote {len(all_records):,} records -> {OUTPUT_PATH}")
    if skipped:
        print(f"Skipped/errors: {skipped}")


if __name__ == "__main__":
    main()
