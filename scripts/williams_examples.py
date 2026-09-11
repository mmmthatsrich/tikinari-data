"""Separate a Williams gloss from its usage examples and citations.

Pure string -> (gloss, [{text, citation}]); no DB, no HTML.

Williams prints an entry's examples inline, in Māori, straight after the English
gloss and usually followed by a parenthesised citation:

    Throw, cast. Me titere mai kia kai atu au ko te waha (Ngā Mōteatea 19)

Nothing ever separated them, so `example` held 61 rows across 14,942 entries
while the sentences sat in `definition_raw`.

**Why orthography rather than the source's own markup.** The section HTML
italicises many glosses, which looks like a clean delimiter until you read
enough entries: `Kaihua (i)` has no <i> at all, and `Kiwi` uses <i> for Latin
binomials *inside* its example run. Italics mark emphasis generally, not glosses
specifically, so they cannot carry the split.

Orthography can. Māori uses a 15-phoneme alphabet — the five vowels (with or
without macrons) plus h k m n p r t w and g only in the digraph 'ng'. Any of
b c d f j l q s v x y z marks a token as English, which is also what keeps Latin
binomials (`Myrsine australis`, `Apteryx`) out of the example runs. This mirrors
02_papakupu_extract._MAORI_CHARS, proven over 10,071 papakupu examples; the
papakupu variant is not reused directly because it requires an English letter or
a [SRC] code in the trailing text, which a Williams citation such as
`(Ngā Mōteatea 124)` does not have.

A splitter that worked on sentence punctuation instead would fail on `Tinei`
("...extinguish.Ka po, ka tikina..." — no space after the period) while
over-splitting its neighbours. Orthography is indifferent to the spacing.
"""
import re

# Mirrors 02_papakupu_extract / papakupu_gloss.
_MAORI_CHARS = set("aāeēiīoōuūhkmnprtwg")
_ENGLISH_ONLY = set("bcdfjlqsvxyz")

_WORD = re.compile(r"\S+")
_END = re.compile(r"[.!?]$")
# A trailing citation: '(Ngā Mōteatea 124)', '(Tregear 57)', '(M. lxxxiii)'.
# A sentence period may follow the closing paren, and often does.
_CITATION = re.compile(r"\(([^()]{2,60})\)[.\s]*$")
# 'extinguish.Ka po' — the source omits the space after a gloss's period often
# enough that the two words arrive as one token. Restore the break before
# tokenising; without it the glued token reads as English and the example that
# follows is never seen.
_GLUED = re.compile(r"(?<=[.!?])(?=[A-ZĀĒĪŌŪ])")
_MIN_EXAMPLE_TOKENS = 3


def _is_maori(tok: str):
    """True if Māori, False if it carries an English-only letter, None if no letters."""
    letters = [c for c in tok.lower() if c.isalpha()]
    if not letters:
        return None
    if any(c in _ENGLISH_ONLY for c in letters):
        return False
    return all(c in _MAORI_CHARS for c in letters)


def _runs(text: str) -> list[tuple[int, int]]:
    """(start, end) char spans of the Māori example runs in `text`.

    A run starts at a capitalised Māori token and continues while tokens stay
    Māori, ending at the first sentence terminator. It only counts as an example
    when it holds at least _MIN_EXAMPLE_TOKENS alphabetic Māori tokens, which is
    what stops a stray Māori word or two inside an English gloss from being
    lifted out ('A variety of kumara ahuahu.').
    """
    toks = [(m.group(0), m.start(), m.end()) for m in _WORD.finditer(text)]
    spans, i, n = [], 0, len(toks)
    while i < n:
        word, start, _ = toks[i]
        first_alpha = next((c for c in word if c.isalpha()), "")
        if not first_alpha or first_alpha != first_alpha.upper() or _is_maori(word) is False:
            i += 1
            continue
        alpha, end, j, ended = 0, None, i, False
        while j < n:
            wj, wstart, wend = toks[j]
            # An opening bracket starts a parenthetical — a citation, almost
            # always — and is never part of the example sentence. It has to end
            # the run even when the word inside scans as Māori: '(Korero',
            # '(Ngā', '(Māori' all do, and swallowing the bracket left the
            # citation check with nothing to find on 1,050 senses.
            if wj.startswith("(") and j > i:
                break
            if _is_maori(wj) is False:
                break
            if any(c.isalpha() for c in wj):
                alpha += 1
            end = wend
            if _END.search(wj.strip("\"')”’")):
                ended = True
                j += 1
                break
            j += 1
        # A citation closes an example as surely as a full stop does: once
        # abbreviations are expanded it carries English letters, so the Māori
        # run breaks on it before ever reaching a terminator.
        cite = re.match(r"\s*\([^()]{2,60}\)", text[end:]) if end else None
        # A run that reaches the end of the text needs no terminator either.
        if alpha >= _MIN_EXAMPLE_TOKENS and (ended or cite or j >= n):
            if cite:
                end += cite.end()
                while j < n and toks[j][2] <= end:
                    j += 1
            spans.append((start, end))
            i = j
        else:
            i += 1
    return spans


def split_gloss_examples(definition: str | None) -> tuple[str, list[dict]]:
    """Return (gloss, examples) for one Williams sense.

    Everything that is not an example run stays in the gloss — including English
    text that follows one, which in Williams is a sub-entry note rather than
    part of the example (`Kaihua (i)`: 'Tao kaihua, a long spear, ...').
    """
    if not definition:
        return "", []
    text = _GLUED.sub(" ", re.sub(r"\s+", " ", definition).strip())
    spans = _runs(text)
    if not spans:
        return text, []

    examples, kept, cursor = [], [], 0
    for start, end in spans:
        kept.append(text[cursor:start])
        chunk = text[start:end].strip()
        citation = None
        if (m := _CITATION.search(chunk)):
            citation = m.group(1).strip()
            chunk = chunk[:m.start()].strip()
        chunk = chunk.rstrip(" ,;")
        if chunk:
            examples.append({"text": chunk, "citation": citation})
        cursor = end
    kept.append(text[cursor:])

    gloss = re.sub(r"\s+", " ", " ".join(kept)).strip()
    gloss = re.sub(r"\s+([.,;:])", r"\1", gloss)
    # Excising an example can leave the gloss's own stop next to the sentence
    # stop that followed the citation.
    gloss = re.sub(r"\.{2,}", ".", gloss)
    # 'Stone, rock,' + the excised example's own stop -> 'Stone, rock,.'
    gloss = re.sub(r"[,;:]+(\s*[.!?])", r"\1", gloss).strip(" ,;")
    # A sense that is nothing but an example would be left with no gloss at all,
    # which is worse than leaving the text in place for the sweep to judge.
    if not gloss:
        return text, []
    return gloss, examples
