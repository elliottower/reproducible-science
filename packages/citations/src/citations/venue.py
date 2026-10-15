"""Is the venue an entry names the venue its record was published in?

Venue identity comes from registries, not from string rules. A venue is a set of identifiers:
ISSNs, an OpenAlex source id, a Wikidata item, an NLM catalog id, a DBLP venue key. The record
carries some of them directly (Crossref's ISSNs, the OpenAlex work's source, PubMed's NLM id),
and the entry's venue name is resolved to them through registries that index venue names and
their abbreviations (`venue_registry.py`). Two venues are one when their identifier sets meet.

Three outcomes:

    match            the entry's venue and the record's venue share an identifier
    mismatch         both resolved confidently, the record's identifiers came from the record
                     itself, both sides hold an identifier of a common kind, and none is shared
    not comparable   anything else; both names are reported so a person can compare them

Name normalization only picks candidates: a registry's name for a venue is accepted as the
cited one when the two are equal once case, punctuation, LaTeX, accents, years, ordinals and
volume numbers are folded away. No string rule decides a mismatch.
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field

from citations.text import name_fold, strip_markup

MATCH = "match"
MISMATCH = "mismatch"
NOT_COMPARABLE = "not comparable"

#: The character a registry deposits where it could not decode one. A name carrying it cannot
#: be read, so it is never looked up.
GARBLED = "�"

#: English function words, which titles carry or drop freely (`The Annals of Statistics`).
STOP = frozenset({"a", "an", "and", "at", "for", "in", "of", "on", "the", "to"})

#: Reasons a venue is not comparable, so a report and a test can name them.
NO_ENTRY_VENUE = "the entry names no venue"
NO_RECORD_VENUE = "the record names no venue identifier"
PREPRINT = "the record is a preprint"
ENTRY_PREPRINT = "the entry cites a preprint server"
WORKSHOP = "a workshop against a main track"
UNRESOLVED = "no registry knows the entry's venue by this name"
AMBIGUOUS = "the entry's venue name fits several registry venues"
REFUSED = "a registry lookup failed, so the venue could not be checked"
NO_COMMON_KIND = "the two sides hold no serial identifier (ISSN, NLM, DBLP) of a common kind"
INDIRECT = "the record's venue was identified by its name, not by an identifier it carries"
ONE_NAME = "registries file both venues under one name, with different identifiers"
GARBLED_NAME = "a venue name is garbled"


class Resolution(BaseModel):
    """One side's venue as registries identify it."""

    model_config = ConfigDict(frozen=True)

    status: str = "resolved"
    """`resolved`, `unresolved`, `ambiguous`, `refused` or `none`."""

    ids: frozenset[str] = frozenset()
    """`issn:0028-0836`, `openalex:S137773608`, `wikidata:Q180445`, `nlm:0410462`,
    `dblp:conf/nips`."""

    links: frozenset[str] = frozenset()
    """Wikidata items the venue's items point at as the same venue under another item: a
    proceedings series' conference, a journal's former title. Followed one hop only, so two
    sibling journals linked to one parent are never one venue."""

    series: frozenset[str] = frozenset()
    """Wikidata series the venue's items are part of. Two editions of one conference share it
    and are one venue."""

    label: str = ""
    """The registry's own name for the venue, shown beside the cited one."""

    names: frozenset[str] = frozenset()
    """Every name registries give the venue, folded. Two venues whose registries share a name
    are not called different, whatever their identifiers: a renamed journal or a historical
    title is often two registry records under one name."""

    direct: bool = False
    """The identifiers came from the record itself rather than from resolving a name."""

    repository: bool = False
    """A registry types the venue as a preprint server or repository."""

    candidates: list[str] = Field(default_factory=list)
    """The registry names a venue name fit, where it fit more than one."""

    options: list[Resolution] = Field(default_factory=list)
    """Where the name fit several registry venues, each of them. One that shares an identifier
    with the record's venue is a match; none of them is ever a mismatch."""


class VenueCheck(BaseModel):
    """The verdict on one entry's venue."""

    model_config = ConfigDict(frozen=True)

    outcome: str
    """`match`, `mismatch` or `not comparable`."""

    ours: str = ""
    """The venue the entry names."""

    theirs: str = ""
    """The venue the record names."""

    ours_registry: str = ""
    """The registry's name for the entry's venue, where it resolved."""

    theirs_registry: str = ""
    """The registry's name for the record's venue, where one is known."""

    why: str = ""
    """The identifier shared, or what made the venues not comparable."""

    ours_ids: list[str] = Field(default_factory=list)
    theirs_ids: list[str] = Field(default_factory=list)

    def line(self) -> str:
        """One line naming both venues, for a person to compare by eye."""
        if self.outcome == MISMATCH:
            return f"venue: ours {self.ours!r} vs registry {self.theirs!r}"
        return f"venue: ours {self.ours!r} / registry {self.theirs!r} ({self.outcome}: {self.why})"


# ----------------------------------------------------------------------------- normalization

#: LaTeX accent commands and the combining marks they write, so `f{\\"u}r` is searched as `für`.
LATEX_ACCENTS = {
    '"': "\u0308",
    "'": "\u0301",
    "`": "\u0300",
    "^": "\u0302",
    "~": "\u0303",
    "=": "\u0304",
    ".": "\u0307",
    "u": "\u0306",
    "v": "\u030c",
    "H": "\u030b",
    "c": "\u0327",
    "r": "\u030a",
}
_ACCENT = re.compile(r"\{?\\([\"'`^~=.uvHcr])\s*\{?([A-Za-z])\}?\}?")


def latex_to_unicode(text: str) -> str:
    """LaTeX accents written as the letters they make, then the rest of the markup removed."""
    text = _ACCENT.sub(lambda m: m.group(2) + LATEX_ACCENTS[m.group(1)], text or "")
    return unicodedata.normalize("NFC", strip_markup(text))


def fold(text: str) -> str:
    """A venue name as compared: folded case, accents, punctuation and LaTeX, with years,
    ordinals, volume numbers and function words removed."""
    text = strip_markup(text)
    words = []
    after_volume = False
    for word in name_fold(text).split():
        if word in ("volume", "vol", "part"):
            after_volume = True
            continue
        if after_volume and (word.isdigit() or word in ("i", "ii", "iii", "iv", "v")):
            after_volume = False
            continue
        after_volume = False
        if word in STOP or re.fullmatch(r"\d+(st|nd|rd|th)?", word):
            continue
        words.append(word)
    return " ".join(words)


def forms(text: str) -> list[str]:
    """The name with LaTeX removed, without what it carries in parentheses, without its
    numbers, and what is in the parentheses: `2016 IEEE Conference on Computer Vision and
    Pattern Recognition (CVPR)` is searched as the full title, as the title without its year,
    and as `CVPR`."""
    text = " ".join(latex_to_unicode(text).split())
    bare = re.sub(r"\s*\([^()]*\)", "", text)
    # A volume or year number is searched without: `Advances in Neural Information
    # Processing Systems 33` is the series' 33rd volume.
    numberless = " ".join(re.sub(r"\b\d+(st|nd|rd|th)?\b", " ", bare).split())
    out = [text, bare, numberless, *re.findall(r"\(([^()]*)\)", text)]
    return [f for f in dict.fromkeys(f.strip(" ,:;-") for f in out) if f and fold(f)]


def is_workshop(text: str) -> bool:
    """A workshop volume, which a registry files beside or under its main conference."""
    return bool({"workshop", "workshops"} & set(name_fold(text).split()))


def same_name(cited: str, registry_names: list[str]) -> bool:
    """The cited name is one of the registry's names for a venue, once folded."""
    want = {fold(f) for f in forms(cited)}
    return any(fold(f) in want for n in registry_names for f in forms(n))


#: Identifiers of a serial or a conference series, which a mismatch may rest on. A Wikidata
#: item or an OpenAlex source can be one edition, or one of several records of the same
#: journal, so those confirm a venue and never contradict one.
SERIAL = frozenset({"issn", "nlm", "dblp"})


def folded_names(names) -> frozenset[str]:
    """Every folded form of these registry names."""
    return frozenset(fold(f) for n in names for f in forms(n) if fold(f))


def kinds(ids: frozenset[str]) -> frozenset[str]:
    return frozenset(i.split(":", 1)[0] for i in ids)


# ----------------------------------------------------------------------------------- verdict


def _shared(entry: Resolution, record: Resolution) -> frozenset[str]:
    """Identifiers that make the two one venue: one side's own against the other's own or
    linked, or a series both are part of."""
    return (
        (entry.ids & (record.ids | record.links))
        | ((entry.ids | entry.links) & record.ids)
        | (entry.series & record.series)
    )


def decide(ours: str, theirs: str, entry: Resolution, record: Resolution) -> VenueCheck:
    """The verdict, from what registries say each side's venue is.

    Pure: the lookups happen before this, in `venue_registry`. A mismatch needs the entry's
    venue resolved to exactly one registry venue, the record's identifiers carried by the
    record itself, an identifier kind both sides hold, and no identifier in common.
    """

    def verdict(outcome: str, why: str) -> VenueCheck:
        return VenueCheck(
            outcome=outcome,
            ours=ours,
            theirs=theirs,
            ours_registry=entry.label,
            theirs_registry=record.label,
            why=why,
            ours_ids=sorted(entry.ids),
            theirs_ids=sorted(record.ids),
        )

    if not ours.strip():
        return verdict(NOT_COMPARABLE, NO_ENTRY_VENUE)
    if GARBLED in ours:
        return verdict(NOT_COMPARABLE, GARBLED_NAME)
    if record.repository:
        return verdict(NOT_COMPARABLE, PREPRINT)
    if is_workshop(ours) != is_workshop(theirs):
        return verdict(NOT_COMPARABLE, WORKSHOP)

    shared = _shared(entry, record)
    if shared:
        return verdict(MATCH, f"shared identifier {sorted(shared)[0]}")
    for option in entry.options:
        shared = _shared(option, record)
        if shared:
            label = f" ({option.label})" if option.label else ""
            return verdict(
                MATCH,
                f"shared identifier {sorted(shared)[0]}, with one of {len(entry.options)} "
                f"registry venues of this name{label}",
            )

    if entry.repository:
        return verdict(NOT_COMPARABLE, ENTRY_PREPRINT)
    if not record.ids:
        return verdict(NOT_COMPARABLE, REFUSED if record.status == "refused" else NO_RECORD_VENUE)
    reasons = {"unresolved": UNRESOLVED, "ambiguous": AMBIGUOUS, "refused": REFUSED}
    if entry.status in reasons:
        why = reasons[entry.status]
        if entry.candidates:
            why += ": " + "; ".join(entry.candidates)
        return verdict(NOT_COMPARABLE, why)
    if record.status == "refused":
        return verdict(NOT_COMPARABLE, REFUSED)
    if not record.direct:
        return verdict(NOT_COMPARABLE, INDIRECT)
    if not (kinds(entry.ids) & kinds(record.ids) & SERIAL):
        return verdict(NOT_COMPARABLE, NO_COMMON_KIND)
    if entry.names & record.names:
        return verdict(NOT_COMPARABLE, f"{ONE_NAME}: {sorted(entry.names & record.names)[0]!r}")
    return verdict(MISMATCH, "no identifier in common")


__all__ = [
    "MATCH",
    "MISMATCH",
    "NOT_COMPARABLE",
    "Resolution",
    "VenueCheck",
    "decide",
    "fold",
    "forms",
    "is_workshop",
    "same_name",
]
