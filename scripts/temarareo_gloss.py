"""Assemble Te Māra Reo's gloss and definition_raw. Pure string -> string.

Te Māra Reo records a plant name's prose definition, an optional note, and a
structured species list. The unified builder appended the species list to the
definition unconditionally, which duplicated it: `aruhe`'s definition already
reads 'Pteridium esculentum (Dennstaedtiaceae)', so the appended
'[Pteridium esculentum]' said nothing new. 29 entries duplicated every species
they list, and 86 more have no definition at all — for those the species list IS
the content the source gives, and wrapping it in brackets made a bare list look
like an afterthought to a definition that was never there.

Two entries (`kauere`, `Pūriri`) carry '*Kauere' as their whole definition: the
scraper picked up the protoform heading rather than a gloss. A lone protoform is
not a definition, so it is treated as absent and the species list supplies the
gloss through the builder's existing fallback.
"""
import re

# A definition that is nothing but a reconstructed form: '*Kauere', '*kau-ere'.
_PROTOFORM_ONLY = re.compile(r"^\*[\wĀ-ſ-]+$")
# A trailing alias, written either way by the source:
#   'Elaeocarpus dentatus [a.k.a. hīnau]' / 'Vitex lucens (a.k.a. pūriri)'
# Stripped only to test whether the definition already names the species.
_ALIAS = re.compile(r"\s*[\[(][^\])]*[\])]\s*$")


def clean_definition(definition: str | None) -> str | None:
    """The definition, or None when it is absent or merely a protoform."""
    if not definition or not definition.strip():
        return None
    text = definition.strip()
    return None if _PROTOFORM_ONLY.match(text) else text


def dedupe_species(species) -> list[str]:
    """One entry per species, in order of first appearance.

    `harakeke` lists Astelia banksii three times and Phormium tenax twice;
    `kauere` lists 'Vitex lucens (a.k.a. pūriri)' and 'Vitex lucens'. Where the
    same species appears more than once the fullest form wins, since the alias
    is the part that carries information.
    """
    best: dict[str, str] = {}
    for s in species or []:
        base = _ALIAS.sub("", s).strip()
        if base not in best or len(s) > len(best[base]):
            best[base] = s
    return list(best.values())


def residual_species(definition: str | None, species) -> list[str]:
    """The species the definition does not already name."""
    if not species:
        return []
    if not definition:
        return list(species)
    return [s for s in species if _ALIAS.sub("", s).strip() not in definition]


def build_raw(definition: str | None, note: str | None, species) -> str | None:
    """definition + note + only those species the definition omits.

    With no definition the species list stands on its own, unbracketed — it is
    the record's content, not a parenthetical to it.
    """
    definition = clean_definition(definition)
    note = (note or "").strip() or None
    # Match species against the note as well: where the definition is only a
    # protoform the content sits in the note, and `kauere`'s note already names
    # Vitex lucens.
    extra = residual_species(" ".join(filter(None, [definition, note])) or None,
                             list(species or []))
    parts = [definition, note]
    if extra:
        joined = "; ".join(extra)
        parts.append(f"[{joined}]" if definition or note else joined)
    text = " ".join(p for p in parts if p)
    # The source writes 'Vitex lucens , "Pūriri"'.
    text = re.sub(r"\s+([,;])", r"\1", text).strip()
    return text or None
