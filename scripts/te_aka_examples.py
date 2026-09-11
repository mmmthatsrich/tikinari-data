"""Split a Te Aka usage example into its Māori and English halves.

Pure strings -> dict; no DOM, no DB.

Te Aka renders both halves in one paragraph, the Māori in <em> and the English
after a slash:

    <em>Ka piki haere ... ki te ahuone (Te Ara 2015).</em> / Māori knowledge of
    horticulture developed.

The parser read only the <em>, so every one of the 45,939 example rows carried
text_mi and nothing else — while the translations sat in the cached pages all
along. 99% of example paragraphs have one.

The split is anchored to the END of the <em> text rather than to the first
slash in the paragraph, because Te Aka citations carry dates:
'(Te Wananga 16/11/1878:576)' has three slashes of its own before the real
separator.
"""
import re


def _ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip() if text else ""


def split_example(para_text: str | None, em_text: str | None) -> dict | None:
    """{'mi': ..., 'en': ...} for one example paragraph, or None if empty.

    `en` is None when the source gives no translation — an empty string would
    read as present-but-blank to everything downstream.
    """
    mi = _ws(em_text)
    if not mi:
        return None
    para = _ws(para_text)
    tail = ""
    # Anchor past the Māori half, then take what follows the separator.
    if para.startswith(mi):
        tail = para[len(mi):].lstrip()
    elif (idx := para.find(mi)) != -1:
        tail = para[idx + len(mi):].lstrip()
    en = _ws(tail[1:]) if tail.startswith("/") else ""
    return {"mi": mi, "en": en or None}
