"""Split a He Pātaka Kupu <strong> into its suffixes and its domain.

Pure strings; no DB, no lxml.

The element holds a word's derived-form suffixes and then its semantic
domain in brackets:

    -tia -hia -ngia -tanga -nga
    [Tūmatauenga]

05_hepataka_parse.py has always regexed the bracket out and discarded
everything in front of it, losing every suffix hepatakakupu records — 22,911
tokens across 14,996 pages.

Tokens come back UNFILTERED and in source order. Parse records what the
source wrote; the vocabulary filter lives at unify, where the refusal report
can count what it rejects. Filtering here would hide the 8 malformed tokens
hepatakakupu's own text contains.
"""
import re

# The bracket opens the domain; everything before it is the suffix field.
_DOMAIN = re.compile(r"\[([^\]]*)\]")
_TOKEN = re.compile(r"-[a-zāēīōū]+", re.I)


def split_strong(text):
    """(suffix_tokens, semantic_domain) for a <strong>'s text.

    Pass `strong.text`, NOT `"".join(strong.itertext())`: the element has a
    child <span> carrying the part of speech, and .text stops before it.
    """
    text = text or ""
    match = _DOMAIN.search(text)
    head = text[:match.start()] if match else text
    domain = match.group(1).strip() if match else None
    return (_TOKEN.findall(head), domain or None)
