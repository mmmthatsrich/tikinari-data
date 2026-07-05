"""Derive a clean English gloss from a raw Papakupu definition.

A Papakupu ``definition`` is the whole entry body: the English gloss prose is
followed, with no separating punctuation, by bilingual usage examples
(``<Māori sentence>. <English translation>. [SRC]``) and sometimes a trailing
``#[Note from Te Mātāpunenga ©] ...`` editorial block. Storing that whole blob
as ``sense.gloss_en`` pollutes the gloss with paragraphs of example text.

``clean_gloss`` keeps only the leading definition, cutting at the earliest of:
  * the first ``[Note ...]`` editorial block,
  * the start of the first usage example (its Māori sentence),
  * any stored ``example.text_mi`` string (a backstop that guarantees no
    example Māori text survives in the gloss, even when the boundary heuristic
    under-cuts).
Trailing source/citation markers ([SRC], ****, dangling separators) are tidied.

Finding the gloss->example boundary is the hard part: the first example's Māori
sentence is glued onto the gloss (``... sympathy He mate ano ...``). The Māori
half cannot be split off by punctuation, and short glosses whose letters happen
to all be valid Māori letters (``to mouth``, ``open``, ``narrow``) defeat a
naïve letter test. We instead scan for the first *capitalised* word that begins
a run of >=3 alphabetic Māori tokens ending in a sentence terminator, and only
treat it as an example boundary when the removed tail actually carries an
English translation or a [SRC] code -- a real example always does, whereas a
trailing all-Māori phrase in an English note (a hapū census list such as
``Ngapuhi at Kokohuia in 1918.``) does not, and is kept.
"""
import re

# Māori orthography: a Māori word uses only these letters (vowels incl. macrons +
# consonants h k m n p r t w; g only in the digraph 'ng'). Any other letter marks
# a token as English. Mirrors 02_papakupu_extract._MAORI_CHARS / _ENGLISH_ONLY.
_MAORI_CHARS = set("aāeēiīoōuūhkmnprtwg")
_ENGLISH_ONLY = set("bcdfjlqsvxyz")

_WORD = re.compile(r"\S+")
_END = re.compile(r"[.!?]$")
_SRC_ANY = re.compile(r"\[[A-Z0-9][A-Z0-9/:.\-]*\]")          # [TTU] [NGH3] [041126]
_NOTE = re.compile(r"#?\[Note\b")                             # #[Note from Te Mātāpunenga ©]
# trailing junk to peel off the end of a gloss: [SRC] codes, redaction '****',
# leftover [Note ...], and dangling separators / whitespace.
_TRAIL = re.compile(r"\s*(\[[A-Z0-9][A-Z0-9/:.\-]*\]|\*{2,}|#?\[Note[^\]]*\])\s*$")
_TRAIL_SEP = re.compile(r"[\s:;,.\-]+$")


def _ws(s: str) -> str:
    """Collapse all whitespace (incl. newlines) to single spaces."""
    return re.sub(r"\s+", " ", s).strip() if s else ""


def _is_maori(tok: str):
    """True if token is Māori, False if it carries an English-only letter, None if
    it has no letters (pure digits / punctuation)."""
    letters = [c for c in tok.lower() if c.isalpha()]
    if not letters:
        return None
    if any(c in _ENGLISH_ONLY for c in letters):
        return False
    return all(c in _MAORI_CHARS for c in letters)


def _example_start(flat: str) -> int:
    """Char offset in ``flat`` where the first usage example begins, or -1.

    The example's Māori sentence starts at a capitalised word beginning a run of
    >=3 alphabetic Māori tokens that ends in a sentence terminator. It only counts
    as an example (rather than a trailing Māori name-list inside an English note)
    when the text from that point on carries an English-only letter or a [SRC] code.
    """
    toks = [(m.group(0), m.start()) for m in _WORD.finditer(flat)]
    n = len(toks)
    for i, (w, pos) in enumerate(toks):
        first_alpha = next((c for c in w if c.isalpha()), "")
        if not first_alpha or first_alpha != first_alpha.upper():
            continue                                   # must start with a capital
        if _is_maori(w) is False:
            continue
        alpha = 0
        ended = False
        for j in range(i, n):
            wj = toks[j][0]
            if _is_maori(wj) is False:
                break
            if any(c.isalpha() for c in wj):
                alpha += 1
            if _END.search(wj.strip("\"')”’")):
                ended = True
                break
        if ended and alpha >= 3:
            tail = flat[pos:]
            if any(c in _ENGLISH_ONLY for c in tail.lower()) or _SRC_ANY.search(tail):
                return pos
    return -1


def _tidy(g: str) -> str:
    """Strip trailing source/citation markers, redactions and dangling separators."""
    prev = None
    while g != prev:
        prev = g
        g = _TRAIL.sub("", g)
        g = _TRAIL_SEP.sub("", g)
    return g.strip()


def clean_gloss(definition, example_texts=()):
    """Return the definition-only gloss, or None if nothing remains.

    ``example_texts`` are the entry's stored ``example.text_mi`` values; each is
    used as a backstop cut so no example Māori text can survive in the gloss.
    """
    flat = _ws(definition)
    if not flat:
        return None

    cuts = []
    nm = _NOTE.search(flat)
    if nm:
        cuts.append(nm.start())
    es = _example_start(flat)
    if es >= 0:
        cuts.append(es)
    gloss = flat[:min(cuts)] if cuts else flat

    for t in example_texts:
        t = _ws(t)
        if t and t in gloss:
            gloss = gloss[:gloss.find(t)]

    gloss = _tidy(gloss)
    return gloss or None
