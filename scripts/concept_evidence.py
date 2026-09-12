"""Evidence rules for concept membership. Pure strings and dicts; no DB.

See docs/superpowers/specs/2026-09-12-concept-layer-design.md.

Within a source, identity is STATED — each source groups its own senses into
words. Across sources it must be inferred from circumstantial evidence and
judged. These functions keep those two things apart.
"""
import re

# Grouping by headword inside a source is right for Ngata's 14 'hoatu' rows,
# but it would merge two genuine Ngata homographs and nothing in the source's
# structure would say otherwise. Everything else is 'certain'.
SEED_CONFIDENCE = {"ngata": "probable", "papakupu": "probable"}

_WORD_ID = re.compile(r"word_id=(\d+)")

# Sources whose senses are split across rows sharing one headword.
_GROUP_BY_HEADWORD = {"ngata", "papakupu"}


def lexeme_key(source_id, source_entry_id, headword_search, locator):
    """Which lexeme a sense belongs to WITHIN its own source.

    He Pātaka Kupu scatters one lemma over several rows and names the grouping
    in entry.locator ('word_id=930'). Ngata and Papakupu split by headword.
    Williams and Te Aka give one entry per word.
    """
    if source_id == "hepatakakupu":
        m = _WORD_ID.search(locator or "")
        if m:
            return (source_id, "word", m.group(1))
    if source_id in _GROUP_BY_HEADWORD:
        return (source_id, "hw", (headword_search or "").strip().lower())
    return (source_id, "entry", str(source_entry_id))


# Ordered strongest first. The confidence a membership earns is the strongest
# kind present, so these are tiers rather than a sum.
EVIDENCE_WEIGHT = {
    "cites_source":       1.0,   # Te Matatiki citing 'himoemoe W.50'
    "shared_example":     0.9,   # two sources printing the same sentence
    "attributed_quote":   0.7,   # Te Aka citing 'W 1971:54'
    "shared_cognate_set": 0.6,
    "gloss_overlap":      0.5,
}

EVIDENCE_CONFIDENCE = {
    "cites_source":       "certain",
    "shared_example":     "certain",
    "attributed_quote":   "probable",
    "shared_cognate_set": "probable",
    "gloss_overlap":      "probable",
}

_STOPWORDS = frozenset({
    "a", "an", "the", "of", "to", "in", "is", "be", "or", "and", "for", "with",
    "as", "by", "at", "from", "on", "into", "it", "that", "this", "any", "some",
    "one", "used", "esp", "etc", "see", "also", "n", "v", "adj", "vt", "vi",
})

# The one tuning parameter in the design. Set by measuring against the judged
# calibration clusters (Task 14); two shared content words is the floor that
# keeps 'ridge of a hill' while rejecting 'of a the'.
GLOSS_OVERLAP_MIN = 2


def _content_words(text):
    return frozenset(w for w in re.findall(r"[a-z]+", (text or "").lower())
                     if w not in _STOPWORDS and len(w) > 2)


def positive_evidence(a, b):
    """[{kind, detail, weight}] linking two senses, strongest first.

    Cross-source only. Within-source grouping is the seeding step's job, and
    counting it here would let one source's internal repetition masquerade as
    corroboration from another.

    Same headword_search is deliberately absent: it generates candidates, and
    is never itself evidence.
    """
    if a["source_id"] == b["source_id"]:
        return []

    found = []

    if b["entry_id"] in a["cites"] or a["entry_id"] in b["cites"]:
        found.append(("cites_source",
                      f"{a['source_id']} cites the {b['source_id']} entry"))

    shared_ex = a["examples"] & b["examples"]
    if shared_ex:
        found.append(("shared_example",
                      f"both print {sorted(shared_ex)[0][:60]!r}"))

    shared_cit = a["citations"] & b["citations"]
    if shared_cit:
        found.append(("attributed_quote",
                      f"both cite {sorted(shared_cit)[0][:40]!r}"))

    shared_sets = a["cognate_sets"] & b["cognate_sets"]
    if shared_sets:
        found.append(("shared_cognate_set",
                      f"{len(shared_sets)} shared cognate set(s)"))

    overlap = _content_words(a["gloss_en"]) & _content_words(b["gloss_en"])
    if len(overlap) >= GLOSS_OVERLAP_MIN:
        found.append(("gloss_overlap",
                      "glosses share " + ", ".join(sorted(overlap)[:4])))

    return [{"kind": k, "detail": d, "weight": EVIDENCE_WEIGHT[k]}
            for k, d in found]
