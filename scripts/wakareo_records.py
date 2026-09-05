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
    return re.sub(r"\s+", " ", text).strip()


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

    tail = _RULE.split(record, maxsplit=1)
    body = tail[1] if len(tail) > 1 else ""
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
