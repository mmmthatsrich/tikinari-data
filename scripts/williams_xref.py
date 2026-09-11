"""Extract Williams '‖' cross-references out of a definition string.

Williams uses the double-bar glyph '‖' as a "compare" marker. What follows is
either a headword reference (a lowercase Māori root word, sometimes with a
sense pointer, e.g. "apa (i), 2") or a literature citation (e.g. "J. vii, 128",
"Wai 23"). Both currently leak into the packed definition -> gloss_en. This
module strips each ‖-span out and returns it as a typed reference so the
unified builder can store it as a relation.

Pure string -> (clean_definition, list[dict]); no DB. Each ref dict is
{"type": "see_also"|"citation", "target": str}.

Key cases handled (see the design discussion / williams_senses.py):
  * mid-entry ‖ followed by a later numbered sense  (Hapū: "‖ pu. 4. Species…")
  * ref-internal sense pointer                      (apū:  "‖ apa (i), 2.")
  * citation target with internal periods           (Aituā:"‖ J. vii, 120.")
  * multiple ‖ in one entry                          (Pūhore:"‖ J… ‖ muhore.")
  * ‖ inside parentheses -> left in place, not stripped (Manawa)
"""
import re

from utils import normalise_search_key

BAR = "‖"

# Relative / editorial pointers that are NOT a headword to link to.
_NOT_HEADWORD = {"etc", "below", "above", "ibid", "ff", "sq", "do", "id", "cf", "and"}
# A target segment carrying a sense pointer: "ahu (ii)" -> ("ahu", "ii").
_SENSE_PAREN = re.compile(r"^(.*?)\s*\(([ivxlcdm]+)\)\.?$", re.I)
_ROMAN_ONLY = re.compile(r"^[ivxlcdm]+$", re.I)
_NON_WORD = re.compile(r"^[\d\W]+$")

# A literature citation run: optional uppercase source abbrev, optional roman
# volume(s), at least one page number, then any number of further
# page / volume / source segments joined by , ; or dashes.
_SRC = r"[A-Z][A-Za-z]{0,4}"
_ROMAN = r"[ivxlcdm]+"
_PAGE = r"\d+[a-z]?"
_CITATION = re.compile(
    r"(?:" + _SRC + r"\.?[,\s]\s*)?"
    r"(?:" + _ROMAN + r"\s*,?\s*)*"
    + _PAGE
    + r"(?:\s*[,;–—-]\s*(?:" + _SRC + r"\.?[,\s]\s*)?"
      r"(?:" + _ROMAN + r"\s*,?\s*)*" + _PAGE + r")*"
)

# A see_also clause that trips either of these is editorial prose / a swallowed
# example sentence, not a terse cross-ref. Leave such ‖ in place rather than emit
# a junk target (real refs have balanced parens and no English note words).
_NOTE = re.compile(r"\b(which|takes|seems|appears|said|quoted|paragraph)\b", re.I)

_WS = re.compile(r"\s+")


def _norm(text):
    return _WS.sub(" ", text).strip()


def _looks_like_prose(target):
    return target.count("(") != target.count(")") or bool(_NOTE.search(target))


def _inside_parens(text, idx):
    """True if position idx sits inside an unclosed '(' run."""
    head = text[:idx]
    return head.count("(") > head.count(")")


def extract_xrefs(definition):
    """Return (clean_definition, [{"type", "target"}, ...]).

    clean_definition has every ‖-span removed (except those inside parens).
    """
    if not definition or BAR not in definition:
        return (definition or ""), []

    out, refs, pos = [], [], 0
    while True:
        b = definition.find(BAR, pos)
        if b == -1:
            out.append(definition[pos:])
            break

        if _inside_parens(definition, b):
            # Leave the ‖ in place; stripping would corrupt the sentence.
            out.append(definition[pos:b + 1])
            pos = b + 1
            continue

        out.append(definition[pos:b])  # text before ‖ (drop the ‖ itself)

        i = b + 1
        while i < len(definition) and definition[i].isspace():
            i += 1

        ref_type, target, end = _read_ref(definition, i)
        if ref_type == "skip":
            # Prose / example sentence after ‖ — keep it (and the ‖) inline.
            out.append(definition[pos:b + 1])
            pos = b + 1
            continue
        if target:
            refs.append({"type": ref_type, "target": target})
        pos = end

    return _norm("".join(out)), refs


def _read_ref(text, i):
    """Read one reference starting at text[i]. Return (type, target, end)."""
    if i < len(text) and text[i].isupper():
        cm = _CITATION.match(text, i)
        if cm and any(c.isdigit() for c in cm.group()):
            end = cm.end()
            if end < len(text) and text[end] == ".":
                end += 1
            return "citation", cm.group().strip(), end

    # Headword reference: a short clause ending at the first period.
    dot = text.find(".", i)
    if dot == -1:
        dot = len(text)
    target = text[i:dot].strip().strip(",").strip()
    if _looks_like_prose(target):
        return "skip", None, dot + 1
    return "see_also", target, dot + 1


def parse_see_also_targets(raw):
    """Parse a raw see_also target string into [(search_key, roman_sense), ...].

    The raw text is the decorated cross-ref Williams prints after '‖' (e.g.
    "apa (i), 2", "mataaho, tiaho", "Tah, ao"). Returns one tuple per linkable
    Māori headword, with decoration stripped:

      "pakuhā"          -> [("pakuha", None)]
      "hea (i)"         -> [("hea", "i")]
      "apa (i), 2"      -> [("apa", "i")]          # ", 2" = sense-of-apa pointer
      "mataaho, tiaho"  -> [("mataho", None), ("tiaho", None)]   # multi-target split
      "6, below"        -> []                       # relative pointer, no headword
      "Tah, ao"         -> []                        # uppercase abbrev lead = cognate

    search_key is normalise_search_key()'d so it matches williams_entries.headword_search
    directly. roman_sense is the lowercase roman pointer or None.
    """
    if not raw:
        return []
    segs = [s.strip() for s in raw.split(",")]
    if not segs:
        return []
    # A leading uppercase abbreviation (Tah, Haw, J, F …) marks the whole clause as
    # a Polynesian cognate or literature pointer, not an internal headword link.
    lead = segs[0].lstrip("([")
    if lead and lead[0].isupper():
        return []

    out = []
    for seg in segs:
        m = _SENSE_PAREN.match(seg)
        if m:
            word, sense = m.group(1).strip(), m.group(2).lower()
        else:
            word, sense = seg, None
        word = word.strip().strip(".").strip()
        if not word or word[0].isupper():
            continue
        if word.lower() in _NOT_HEADWORD:
            continue
        if _NON_WORD.match(word) or _ROMAN_ONLY.match(word):
            continue
        out.append((normalise_search_key(word), sense))
    return out

# Williams marks a variant with '=' at the head of an entry — 'Ahine. = wahine.'
# — as distinct from the '‖' compare marker handled above. 680 senses open with
# one and 611 of those entries had no relation at all, so the link was invisible
# and the POS and gloss behind it stayed stranded in the definition.
#
# The shape is '= target[, target...][, POS.] rest'. Targets are comma-separated
# and the list ends at the first part-of-speech abbreviation, which is what
# separates 'au, awau, awahau' (three variants) from 'kahore, ad.' (one variant
# then a POS).
_EQ_POS = (r"v\.t\.i|v\.t|v\.i|v|n|a|ad|adv|pt|pl|pos|int|num|pron|def|indef"
           r"|prefix|conj|prep|interj|l\.n|loc|part|art|suf|pref")
_EQ_HEAD = re.compile(r"^\s*=\s*(.+)$", re.S)
_EQ_POS_RE = re.compile(rf"^({_EQ_POS})\.", re.I)
_EQ_STOP_RE = re.compile(r"\.(?=\s+[A-Z0-9Ā-ſ]|\s*$)")


def parse_equals_variants(definition):
    """('targets', remaining definition) for a leading '= ...' variant marker.

    The list terminates at the FIRST full stop, not at a comma: 'Hakirara' reads
    '= hakurara. 1. a. Idling...' and everything after that stop is the entry's
    own numbered senses. Within the head, targets are comma-separated, and a
    trailing part-of-speech abbreviation belongs to the definition rather than
    the list — 'kahore, ad.' is one variant and a POS, while 'au, awau, awahau'
    is three variants.

    Only a marker at the very START counts. A '=' later in the text is a gloss
    equivalence ('Tahu. = tuahine.') and belongs to the prose.
    """
    if not definition:
        return [], ""
    m = _EQ_HEAD.match(definition)
    if not m:
        return [], definition
    rest = m.group(1).strip()
    if not rest:
        return [], definition

    # The terminator is a SENTENCE stop — one followed by the end of the text or
    # by a capital or a digit. A stop inside an abbreviation ('v.t.', 'l.n.') is
    # not one, and splitting there turned 'v.t.' into 'v. t.'.
    stop = _EQ_STOP_RE.search(rest)
    head, tail = ((rest, "") if not stop
                  else (rest[:stop.start()], rest[stop.end():].strip()))

    tokens = [t.strip() for t in head.split(",") if t.strip()]
    if not tokens:
        return [], definition
    if len(tokens) > 1 and _EQ_POS_RE.match(tokens[-1] + "."):
        # The stop we split on was the POS abbreviation's own.
        tail = (tokens[-1] + ". " + tail).strip()
        tokens = tokens[:-1]
    return tokens, tail
