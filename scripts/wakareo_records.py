"""Parse Wakareo ā-ipurangi record HTML into plain dicts.

Pure: no DB, no network, no filesystem. Every function takes and returns
plain Python values so the whole module is unit-testable against fixtures.

Each record uses one template, emitted BEFORE the page's <!DOCTYPE>:

    <TD><TD><FONT SIZE='+2'>{headword}</FONT></TD>
    <TD>{pos}</TD>
    <TD ALIGN='Right'>{search_scope}</TD>
    <BR><HR SIZE='2' WIDTH='100%'><BR>
    {body}
    <BR><BR>[Reference: WR-{TAG}.{n}]

The page <title> reads "Custom Māori Law Lexicon" on EVERY record — an
upstream template bug. Only the WR- tag identifies the component.
"""
import re

_HEADWORD = re.compile(r"(?is)<FONT\s+SIZE='\+2'>(.*?)</FONT>")
_POS = re.compile(r"(?is)</FONT>\s*</TD>\s*<TD>(.*?)</TD>")
_SCOPE = re.compile(r"(?is)<TD\s+ALIGN='Right'>(.*?)</TD>")
_RULE = re.compile(r"(?is)<HR[^>]*>\s*(?:<BR>)?")
_REF = re.compile(r"(?is)\[Reference:\s*WR-([A-Z]+)\.(\d+)\]")
_SCOPE_INNER = re.compile(r"(?is)[\(\[]\s*Search Scope:\s*(.*?)\s*[\)\]]")
_TAG = re.compile(r"(?is)<[^>]+>")


def strip_tags(html: str) -> str:
    """Drop tags, decode the only entity Wakareo emits, collapse whitespace."""
    if not html:
        return ""
    text = _TAG.sub(" ", html).replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text).strip()
    # A tag immediately before punctuation (e.g. "<B>alarm</B>.") becomes a
    # space once the tag is blanked out ("alarm ."); close that back up.
    return re.sub(r"\s+([.,;:!?])", r"\1", text)


def split_template(html: str) -> dict | None:
    """Split one record page into its four slots plus the provenance tag.

    Returns None when the page carries no record (empty ID, or a login
    redirect body).
    """
    if not html:
        return None
    record = html.split("<!DOCTYPE")[0]
    ref = _REF.search(record)
    hw = _HEADWORD.search(record)
    if not (ref and hw):
        return None

    pos = _POS.search(record)
    scope = _SCOPE.search(record)

    # `entry_DICT*` full-page captures carry a nav-breadcrumb <HR> BEFORE
    # the record <TABLE>, in addition to the real separator <HR> after it
    # (`shape_*` fixtures only ever have the one, real, separator). Both
    # formats agree that the body follows the LAST <HR> before the
    # doctype cut, so split on every rule and take the final part rather
    # than splitting once and taking the first tail.
    parts = _RULE.split(record)
    body = parts[-1] if len(parts) > 1 else ""
    body = _REF.sub("", body)

    return {
        "headword": strip_tags(hw.group(1)),
        "pos": strip_tags(pos.group(1)) if pos else "",
        "search_scope": strip_tags(scope.group(1)) if scope else "",
        "body": body.strip(),
        "ref_tag": ref.group(1),
        "ref_no": int(ref.group(2)),
    }


def parse_search_scope(text: str) -> list[str]:
    """['ahua', 'ahūa', 'āhua'] from either bracket style, [] when absent."""
    if not text:
        return []
    m = _SCOPE_INNER.search(text)
    if not m:
        return []
    return [p.strip() for p in m.group(1).split(",") if p.strip()]


TAG_TO_SOURCE = {
    "TE":  "tregear_exceptions",
    "HMN": "ngata",
    "TM":  "te_matatiki",
    "KKH": "kimikupu_hou",
    "HKA": "he_kupu_arotake",
    "HKR": "kupu_rorohiko",
    "TK":  "tai_kupu_variants",
    "NT":  "nga_tini_a_tangaroa",
    "KM":  "kupu_mataora",
    "CL":  "maori_law_lexicon",
    # "WWC" (Wordstream Williams Corpus) is deliberately absent — duplicate of
    # the NZETC-derived `williams` source, discarded at parse time.
}

EN_MI_SOURCE_IDS = frozenset(
    {"ngata", "kimikupu_hou", "he_kupu_arotake", "kupu_rorohiko", "kupu_mataora"}
)

_BR = re.compile(r"(?i)<BR\s*/?>")
_W_REF = re.compile(r"(?i)\bW\.(\d+)")


def _segments(body: str) -> list[str]:
    """Body split on <BR>, tags stripped, empties dropped."""
    return [s for s in (strip_tags(p) for p in _BR.split(body)) if s]


_BOLD = re.compile(r"(?is)<B>(.*?)</B>")


def _parse_en_mi(rec: dict, body: str) -> dict:
    """English headword -> Māori equivalents, optional qualifier and EN/MI pair.

    The Māori equivalents are the FIRST <B>...</B> run — never simply the first
    <BR> segment. Kimikupu Hou 52724 is the proof: its body is
    `View, argument<BR><B>haurite</B>`, where "View, argument" qualifies the
    English lemma and `haurite` is the actual equivalent. Taking segment 0 there
    yields ['View', 'argument'] — silently wrong across ~22,500 entries.

    Ngata bodies carry later <B> runs as emphasis inside the example sentences,
    so "first bold run" is correct there too.
    """
    bold = _BOLD.search(body)
    if not bold:
        rec["equivalents"], rec["qualifier"] = [], None
        rec["example_en"] = rec["example_mi"] = None
        return rec

    rec["equivalents"] = [
        e.strip() for e in strip_tags(bold.group(1)).split(",") if e.strip()
    ]
    before = strip_tags(body[:bold.start()])
    rec["qualifier"] = before or None
    after = _segments(body[bold.end():])
    rec["example_en"] = after[0] if len(after) > 0 else None
    rec["example_mi"] = after[1] if len(after) > 1 else None
    return rec


def _parse_mi_en(rec: dict, segs: list[str]) -> dict:
    """Māori headword -> English gloss (all remaining prose)."""
    rec["gloss_en"] = " ".join(segs) if segs else ""
    return rec


def _parse_te_matatiki(rec: dict, segs: list[str]) -> dict:
    """Like MI->EN, but a trailing [...] block is a derivation citing Williams pages."""
    derivation = None
    prose = list(segs)
    if prose and prose[-1].startswith("["):
        derivation = prose.pop()
    rec["gloss_en"] = " ".join(prose) if prose else ""
    rec["derivation"] = derivation
    rec["williams_refs"] = (
        [int(n) for n in _W_REF.findall(derivation)] if derivation else []
    )
    return rec


def _body_text(rec: dict, body: str) -> str | None:
    """Markup-free body for consumers, or None when only the lemma survives.

    `body_raw` is kept alongside as the archive: Tregear's <B> runs delimit the
    definition block from its `Maori Example:` / `Compare With:` sections, so the
    markup is still needed to split those senses later.

    Kimikupu Hou bodies are often `<BR><B>{equivalent}</B><BR><BR>` — stripping
    leaves the equivalent itself, which is not a definition and must not read as
    one.
    """
    text = strip_tags(body)
    if not text:
        return None
    lemmas = {rec["headword"].casefold()}
    lemmas.update(e.casefold() for e in rec.get("equivalents") or [])
    return None if text.casefold() in lemmas else text


def parse_record(html: str) -> dict | None:
    """Full parse of one record page. None for Williams Corpus or a non-record."""
    slots = split_template(html)
    if slots is None:
        return None
    source_id = TAG_TO_SOURCE.get(slots["ref_tag"])
    if source_id is None:
        return None                      # WR-WWC and any future unknown tag

    rec = {
        "source_id": source_id,
        "ref_no": slots["ref_no"],
        "source_entry_id": f"WR-{slots['ref_tag']}.{slots['ref_no']}",
        "headword": slots["headword"],
        "pos": slots["pos"],
        "search_scope": parse_search_scope(slots["search_scope"]),
        "body_raw": slots["body"],
    }
    if source_id in EN_MI_SOURCE_IDS:
        rec = _parse_en_mi(rec, slots["body"])     # needs raw body for the bold run
    else:
        segs = _segments(slots["body"])
        rec = (_parse_te_matatiki(rec, segs) if source_id == "te_matatiki"
               else _parse_mi_en(rec, segs))
    rec["body_text"] = _body_text(rec, slots["body"])
    return rec
