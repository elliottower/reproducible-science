"""Does the venue an entry names agree with the venue its record gives?

Three outcomes:

    match            a name the entry gives and a name the record gives are one venue
    mismatch         both sides name a venue, and the names are of two different venues
    not comparable   one side names no venue, one side is a preprint server, the entry and the
                     record are on different tracks of one meeting, or the names neither agree
                     nor clearly differ

`not comparable` is never a mismatch, and is not a softer one. A venue is written a dozen ways
for one meeting -- `NeurIPS`, `Proc. NeurIPS 2020`, `Advances in Neural Information Processing
Systems 33` -- and a registry writes it a dozen more. A false alarm on a correct reference costs
more than a missed wrong one, so a mismatch is reported only when the evidence is clear.

Each side may carry several names: the entry its `journal` or `booktitle` and its `series`; the
record its container titles, short titles, event name and acronym, and whatever alternate names
Semantic Scholar and OpenAlex give. Two sides agree when any name on one agrees with any name on
the other, under one of these rules, after case, accents, punctuation, stop words, years,
ordinals and volume numbers are folded away:

    same name       the same words, or the same words once generic ones are set aside
                    (`Proceedings`, `Conference`, `International`, `IEEE`, `ACM` ...)
    abbreviation    word for word, each word a truncation or contraction of the other
                    (`Nat. Commun.` ~ `Nature Communications`, `Proc. Natl. Acad. Sci.`)
    acronym         one name is the initials of the other (`ICML`, `JMLR`, `TPAMI`), or one
                    is an acronym that appears in the other (`KDD` ~ `KDD '16: The 22nd ...`)
    alias           both map to one entry of `ALIASES`, the table below

When none applies, a mismatch still needs one of: both names map to different `ALIASES`
entries, both sides are journals, or the names share less than half their distinctive words.
Two names sharing at least half -- `Proc. Conf. Empirical Methods in NLP` against the full EMNLP
title -- are not comparable rather than different.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from citations.text import name_fold, strip_markup

MATCH = "match"
MISMATCH = "mismatch"
NOT_COMPARABLE = "not comparable"

#: `a` is not here: in a venue name it is nearly always a letter, as in `U.S.A.` or `Series A`.
#: `fur` and `fuer` are German `für`, which an abbreviation drops: `Z. Physik` for
#: `Zeitschrift für Physik`.
STOP = frozenset({"an", "and", "at", "for", "in", "of", "on", "the", "to", "fur", "fuer"})

#: Words that, ending a title, make a journal of its own from a parent's name: `Science
#: Advances`, `Cell Reports`, `BMJ Open`, `JAMA Network Open`, `PNAS Nexus`, `Nature
#: Communications`, `Physical Review Letters`, `PLOS ONE`. Two names whose trailing run of
#: these differs are two venues, whatever else they share. Leading, they do not count:
#: `Advances in Neural Information Processing Systems` is not a derivative of anything.
DERIVATIVE = frozenset(
    {"open", "nexus", "reports", "advances", "communications", "network", "plus", "letters", "one"}
)

#: The character a registry deposits where it could not decode one. A name carrying it cannot
#: be read, so it is never the ground for a mismatch.
GARBLED = "\ufffd"
GARBLED_RECORD = "a venue name is garbled"

#: Words a venue name carries that do not tell one venue from another. Set aside when the
#: distinctive words are compared, kept when initials are read off a name.
GENERIC = frozenset(
    {
        "proceedings",
        "proc",
        "conference",
        "conf",
        "international",
        "intl",
        "annual",
        "meeting",
        "symposium",
        "workshop",
        "workshops",
        "findings",
        "ieee",
        "acm",
        "cvf",
        "series",
        "ser",
        "papers",
        "long",
        "short",
        "main",
        "track",
    }
)

ORDINAL_WORDS = frozenset(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
    "thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth "
    "thirtieth fortieth fiftieth sixtieth twenty thirty forty fifty sixty".split()
)

#: A volume marker and the number or numeral after it: `Volume 1`, `Part II`.
VOLUME_WORDS = frozenset({"volume", "vol", "part", "no"})
NUMERALS = frozenset({"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"})

#: A name carrying any of these is a preprint server or a repository. A record that names only
#: such a venue says nothing about where the work was published, so it is never a mismatch.
#: `corr` is how DBLP files arXiv.
REPOSITORY_WORDS = frozenset(
    {
        "arxiv",
        "biorxiv",
        "medrxiv",
        "chemrxiv",
        "psyarxiv",
        "socarxiv",
        "eartharxiv",
        "edarxiv",
        "ssrn",
        "zenodo",
        "figshare",
        "corr",
        "preprint",
        "preprints",
        "openreview",
        "authorea",
        "osf",
    }
)
REPOSITORY_PHRASES = (("research", "square"), ("cold", "spring", "harbor", "laboratory"))

#: Why a record that names only a preprint server is not comparable. `citations audit` asks
#: other services for the published venue before settling on it.
PREPRINT_RECORD = "the record is a preprint"

#: Why a would-be mismatch is not comparable when a service that keeps a venue's other names
#: did not answer and the mismatch rests on names alone.
UNCONFIRMED = "other names could not be fetched"

#: Mismatches no other name can undo: two venues the alias table holds apart, or two journal
#: titles that agree under no rule.
SETTLED = (
    "different venues",
    "two journal titles that do not agree",
    "a derivative journal against its parent",
)


def settled(check: VenueCheck) -> bool:
    """The mismatch holds whatever other names the venue goes by."""
    return check.outcome == MISMATCH and any(reason in check.why for reason in SETTLED)


#: Series that publish many venues' proceedings. Shown in a mismatch only when nothing more
#: specific is named, because `Lecture Notes in Computer Science` does not say which
#: conference the record is of.
SERIES_NAMES = (
    "Lecture Notes in Computer Science",
    "Lecture Notes in Artificial Intelligence",
    "Lecture Notes in Bioinformatics",
    "Communications in Computer and Information Science",
    "Proceedings of Machine Learning Research",
)

#: Where at least this share of the shorter name's distinctive words is in the longer, two names
#: that matched under no rule are not comparable rather than different.
PARTLY = 0.5


class Alias(BaseModel):
    """One venue under the names it is written by, and where those names come from."""

    model_config = ConfigDict(frozen=True)

    key: str
    names: tuple[str, ...]
    source: str


#: The most common ML, NLP and vision venues, whose names the rules above cannot connect:
#: `NeurIPS` is not the initials of anything, and `NAACL` is not the initials of the full
#: title, which continues `: Human Language Technologies`. Kept small on purpose. A record's
#: own short and alternate names are read first, and an abbreviation absent here is never
#: evidence of a mismatch (`SIGMOD` against a long title is not comparable).
#:
#: Sources, read 2026-10-14: each venue's own proceedings title; where noted, the
#: `publicationVenue.alternate_names` Semantic Scholar returned for a paper of that venue, or
#: the container title Crossref deposits for one. Those records are in the test fixture
#: `tests/fixtures/audit_venue/cache/`.
ALIASES: tuple[Alias, ...] = (
    Alias(
        key="neurips",
        names=(
            "NeurIPS",
            "NIPS",
            "Advances in Neural Information Processing Systems",
            "Neural Information Processing Systems",
            "Adv. Neural Inf. Process. Syst.",
        ),
        source="proceedings.neurips.cc; Semantic Scholar: NeurIPS, NIPS, Neural Inf Process Syst",
    ),
    Alias(
        key="icml",
        names=("ICML", "International Conference on Machine Learning"),
        source="icml.cc; Semantic Scholar: ICML, Int Conf Mach Learn",
    ),
    Alias(
        key="iclr",
        names=("ICLR", "International Conference on Learning Representations"),
        source="iclr.cc; Semantic Scholar: ICLR, Int Conf Learn Represent",
    ),
    Alias(
        key="aistats",
        names=("AISTATS", "International Conference on Artificial Intelligence and Statistics"),
        source="aistats.org, proceedings title",
    ),
    Alias(
        key="uai",
        names=("UAI", "Conference on Uncertainty in Artificial Intelligence"),
        source="auai.org, proceedings title",
    ),
    Alias(
        key="colt",
        names=(
            "COLT",
            "Conference on Learning Theory",
            "Annual Conference on Computational Learning Theory",
        ),
        source="learningtheory.org, proceedings title; the conference's earlier name",
    ),
    Alias(
        key="aaai",
        names=(
            "AAAI",
            "AAAI Conference on Artificial Intelligence",
            "Association for the Advancement of Artificial Intelligence",
        ),
        source="ojs.aaai.org, proceedings title; Semantic Scholar: AAAI, AAAI Conf Artif Intell",
    ),
    Alias(
        key="ijcai",
        names=("IJCAI", "International Joint Conference on Artificial Intelligence"),
        source="ijcai.org, proceedings title",
    ),
    Alias(
        key="kdd",
        names=("KDD", "SIGKDD", "Knowledge Discovery and Data Mining"),
        source="Crossref container title and event acronym (KDD '16) of ACM SIGKDD proceedings",
    ),
    Alias(
        key="acl",
        names=("ACL", "Annual Meeting of the Association for Computational Linguistics"),
        source="aclanthology.org; Crossref container titles of ACL 2002, 2016 and 2020",
    ),
    Alias(
        key="emnlp",
        names=("EMNLP", "Conference on Empirical Methods in Natural Language Processing"),
        source="aclanthology.org; Crossref container titles of EMNLP 2014, 2019 and 2020",
    ),
    Alias(
        key="naacl",
        names=(
            "NAACL",
            "North American Chapter of the Association for Computational Linguistics",
        ),
        source="aclanthology.org; Crossref container titles of NAACL 2018 and 2019",
    ),
    Alias(
        key="eacl",
        names=("EACL", "European Chapter of the Association for Computational Linguistics"),
        source="aclanthology.org, proceedings title",
    ),
    Alias(
        key="coling",
        names=("COLING", "International Conference on Computational Linguistics"),
        source="aclanthology.org, proceedings title",
    ),
    Alias(
        key="tacl",
        names=("TACL", "Transactions of the Association for Computational Linguistics"),
        source="transacl.org; Crossref container title",
    ),
    Alias(
        key="cvpr",
        names=("CVPR", "Computer Vision and Pattern Recognition"),
        source="Crossref container titles of IEEE CVPR 2016 and 2022; Semantic Scholar: CVPR",
    ),
    Alias(
        key="iccv",
        names=("ICCV", "International Conference on Computer Vision"),
        source="Crossref container title of IEEE ICCV 2017; Semantic Scholar: ICCV",
    ),
    Alias(
        key="eccv",
        names=("ECCV", "European Conference on Computer Vision"),
        source="Crossref container title of the Springer ECCV 2020 volume",
    ),
    Alias(
        key="miccai",
        names=(
            "MICCAI",
            "Medical Image Computing and Computer-Assisted Intervention",
            "Medical Image Computing and Computer Assisted Intervention",
        ),
        source="miccai.org; Crossref container title of the Springer MICCAI 2015 volume",
    ),
    Alias(
        key="icassp",
        names=(
            "ICASSP",
            "International Conference on Acoustics, Speech and Signal Processing",
            "International Conference on Acoustics, Speech, and Signal Processing",
        ),
        source="Crossref container title of IEEE ICASSP 2013; Semantic Scholar: ICASSP",
    ),
    Alias(
        key="interspeech",
        names=(
            "Interspeech",
            "Annual Conference of the International Speech Communication Association",
        ),
        source="isca-archive.org, proceedings title",
    ),
    Alias(
        key="sp",
        names=("IEEE S&P", "IEEE Symposium on Security and Privacy", "Oakland"),
        source="ieee-security.org, proceedings title; `Oakland` is its customary name",
    ),
    Alias(
        key="ccs",
        names=(
            "CCS",
            "ACM CCS",
            "ACM SIGSAC Conference on Computer and Communications Security",
            "Conference on Computer and Communications Security",
        ),
        source="sigsac.org, proceedings title",
    ),
    Alias(
        key="usenix-security",
        names=("USENIX Security", "USENIX Security Symposium"),
        source="usenix.org, proceedings title",
    ),
    Alias(
        key="ndss",
        names=("NDSS", "Network and Distributed System Security Symposium"),
        source="ndss-symposium.org, proceedings title",
    ),
    Alias(
        key="jmlr",
        names=("JMLR", "Journal of Machine Learning Research"),
        source="jmlr.org; Semantic Scholar: J Mach Learn Res",
    ),
    Alias(
        key="tmlr",
        names=("TMLR", "Transactions on Machine Learning Research"),
        source="jmlr.org/tmlr",
    ),
    Alias(
        key="pnas",
        names=(
            "PNAS",
            "Proceedings of the National Academy of Sciences",
            "Proceedings of the National Academy of Sciences of the United States of America",
            "Proc. Natl. Acad. Sci. U.S.A.",
        ),
        source="pnas.org; Crossref container and short titles; PubMed journal title",
    ),
    Alias(
        key="pmlr",
        names=(
            "PMLR",
            "Proceedings of Machine Learning Research",
            "JMLR Workshop and Conference Proceedings",
            "JMLR W&CP",
        ),
        source="proceedings.mlr.press, which publishes ICML, AISTATS, COLT and UAI among others",
    ),
)

#: Entries of `ALIASES` that are a publication series rather than one venue. A paper is in
#: PMLR and at ICML at once, so a series never establishes a mismatch.
SERIES = frozenset({"pmlr"})


class Name(BaseModel):
    """One venue name, read into the parts the rules compare."""

    model_config = ConfigDict(frozen=True)

    text: str
    words: tuple[str, ...]
    """Folded words, with stop words, years, ordinals and volume numbers removed."""

    core: tuple[str, ...]
    """`words` without the generic ones. Falls back to `words` where nothing else is left, so
    `Proceedings of the IEEE` still has something to compare."""

    acronyms: frozenset[str]
    """Words written as acronyms in the original, two or more capitals: `NeurIPS`, `AAAI`."""

    track: str
    """`workshop`, `findings` or `main`."""


class VenueCheck(BaseModel):
    """The verdict on one entry's venue."""

    model_config = ConfigDict(frozen=True)

    outcome: str
    """`match`, `mismatch` or `not comparable`."""

    ours: str = ""
    theirs: str = ""
    why: str = ""
    """The rule that matched, or what made the names not comparable."""


# ----------------------------------------------------------------------------------- reading


def _tokens(text: str) -> list[tuple[str, bool]]:
    """(folded word, written as an acronym) pairs, in order."""
    out = []
    for word in re.findall(r"[^\W_]+", strip_markup(text)):
        acronym = sum(c.isupper() for c in word) >= 2
        for token in name_fold(word).split():
            # `ICML2020`, `NeurIPS2019`: the acronym and its year written as one word.
            joined = re.fullmatch(r"([a-z]{2,})(\d{2,4})", token)
            out.append((joined.group(1) if joined else token, acronym))
    return out


def read(text: str) -> Name:
    words: list[str] = []
    acronyms = set()
    after_volume = False
    for token, acronym in _tokens(re.sub(r"\([^()]*\)", " ", text)):
        if token in VOLUME_WORDS:
            after_volume = True
            continue
        if after_volume and (token.isdigit() or token in NUMERALS):
            after_volume = False
            continue
        after_volume = False
        if token in STOP or token in ORDINAL_WORDS:
            continue
        if re.fullmatch(r"\d+(st|nd|rd|th)?", token):
            continue
        words.append(token)
        if acronym:
            acronyms.add(token)
    core = tuple(w for w in words if w not in GENERIC) or tuple(words)
    track = "main"
    # `CVPRW`, `ICCVW`: a workshop volume's acronym, in parentheses or standing alone.
    if {"workshop", "workshops"} & set(words) or re.search(r"(^|\()\s*[A-Z]{3,}W\b", text):
        track = "workshop"
    elif "findings" in words:
        track = "findings"
    return Name(text=text, words=tuple(words), core=core, acronyms=frozenset(acronyms), track=track)


def forms(text: str) -> list[str]:
    """The name, and the shorter names inside it.

    A registry writes `2016 IEEE Conference on Computer Vision and Pattern Recognition (CVPR)`
    and `Journal of the Royal Statistical Society Series B: Statistical Methodology`; an entry
    writes `CVPR` and `Journal of the Royal Statistical Society: Series B`. The acronym in
    parentheses and the part before a colon or comma are each a form the venue goes by.
    """
    text = " ".join(text.split())
    out = [text]
    for inner in re.findall(r"\(([^()]*)\)", text):
        tokens = [t for t, _ in _tokens(inner) if not t.isdigit()]
        if 1 <= len(tokens) <= 2 and all(a for t, a in _tokens(inner) if not t.isdigit()):
            out.append(inner)
    for mark in (":", ","):
        if mark in text:
            out.append(text.split(mark, 1)[0])
    return [f for f in dict.fromkeys(f.strip() for f in out) if f]


def is_repository(text: str) -> bool:
    words = [t for t, _ in _tokens(text)]
    if REPOSITORY_WORDS & set(words):
        return True
    return any(_contains(tuple(words), phrase) for phrase in REPOSITORY_PHRASES)


# --------------------------------------------------------------------------------- the rules


def _contains(hay: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    n = len(needle)
    return n > 0 and any(hay[i : i + n] == needle for i in range(len(hay) - n + 1))


def _abbreviates(short: str, long: str) -> bool:
    """`short` is `long` truncated (`Commun` for `Communications`) or contracted (`Natl` for
    `National`: first and last letters kept, the rest a subsequence)."""
    if short == long or long.startswith(short):
        return True
    if len(short) < 3 or short[0] != long[0] or short[-1] != long[-1]:
        return False
    rest = iter(long[1:])
    return all(c in rest for c in short[1:])


def _word_agrees(a: str, b: str) -> bool:
    return _abbreviates(a, b) or _abbreviates(b, a)


def _spells(word: str, run: tuple[str, ...]) -> bool:
    """`word` is written out by `run`: the letters of `U S A` for `USA`, or the initials of
    `United States America`."""
    return len(run) >= 2 and len(word) == len(run) and word == "".join(w[0] for w in run)


def _aligned(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """Word for word, where one word may also stand for a run of the other's: `USA` against
    `U.S.A.` or against `United States of America`."""
    if not a or not b:
        return False

    def walk(i: int, j: int) -> bool:
        if i == len(a) or j == len(b):
            return i == len(a) and j == len(b)
        if _word_agrees(a[i], b[j]) and walk(i + 1, j + 1):
            return True
        for k in range(2, len(b) - j + 1):
            if _spells(a[i], b[j : j + k]) and walk(i + 1, j + k):
                return True
        for k in range(2, len(a) - i + 1):
            if _spells(b[j], a[i : i + k]) and walk(i + k, j + 1):
                return True
        return False

    return walk(0, 0)


def _derivatives(name: Name) -> tuple[str, ...]:
    """The trailing run of `DERIVATIVE` words, abbreviated or not: `open` in `BMJ Open`,
    `adv` in `Sci. Adv.`. Empty where the name is nothing but such words."""
    words = name.words
    n = len(words)
    # Truncations of three letters or more only: the `a` of `U.S.A.` is not `Advances`, and
    # the contraction rule would read `Res` as `Reports`.
    while n and any(
        words[n - 1] == d or (len(words[n - 1]) >= 3 and d.startswith(words[n - 1]))
        for d in DERIVATIVE
    ):
        n -= 1
    return words[n:] if n else ()


def _parent_and_derivative(a: Name, b: Name) -> bool:
    """One name is the other plus a derivative ending: `BMJ Open` and `BMJ`, `PNAS Nexus` and
    `Proceedings of the National Academy of Sciences`."""
    x, y = _derivatives(a), _derivatives(b)
    if _same_family_member(a, b) or (x and y):
        return False
    stem_a = read(" ".join(a.words[: len(a.words) - len(x)]))
    stem_b = read(" ".join(b.words[: len(b.words) - len(y)]))
    return bool(same(stem_a, stem_b))


def _same_family_member(a: Name, b: Name) -> bool:
    """Neither name carries a derivative ending the other lacks."""
    x, y = _derivatives(a), _derivatives(b)
    return len(x) == len(y) and all(map(_word_agrees, x, y))


def _initials_of(acronym: str, name: Name) -> bool:
    """`acronym` is the initials of a run of `name`'s words that covers every distinctive one."""
    if len(acronym) < 3:
        return False
    words = name.words
    core = [i for i, w in enumerate(words) if w not in GENERIC] or list(range(len(words)))
    for start in range(min(core) + 1):
        for end in range(max(core) + 1, len(words) + 1):
            if "".join(w[0] for w in words[start:end]) == acronym:
                return True
    return False


def same(a: Name, b: Name) -> str:
    """The rule under which two names are one venue, or empty if none applies."""
    if not a.words or not b.words:
        return ""
    # Initials spell a derivative ending too (`PRL`), so they are read before the family rule.
    for x, y in ((a, b), (b, a)):
        if len(x.core) == 1 and _initials_of(x.core[0], y):
            return "acronym"
    if not _same_family_member(a, b):
        return ""
    if a.words == b.words or a.core == b.core:
        return "same name"
    if _aligned(a.words, b.words) or _aligned(a.core, b.core):
        return "abbreviation"
    for x, y in ((a, b), (b, a)):
        if len(x.core) == 1:
            token = x.core[0]
            if token in x.acronyms and token in y.words:
                return "acronym"
    return ""


_ALIAS_NAMES = tuple((alias, read(n)) for alias in ALIASES for n in alias.names)


def keys(name: Name) -> frozenset[str]:
    """Every `ALIASES` entry this name is written as, or contains."""
    found = set()
    for alias, known in _ALIAS_NAMES:
        if not _same_family_member(known, name):
            continue  # `PNAS Nexus` is not PNAS
        if len(known.words) == 1:
            hit = known.words[0] in name.words
        else:
            # Read as one name only on one track: `JMLR Workshop and Conference Proceedings`
            # is PMLR, and its acronym is not the journal's.
            alike = known.track == name.track and bool(same(known, name))
            hit = alike or _contains(name.words, known.words)
        if hit:
            found.add(alias.key)
    if "pmlr" in found:
        # `JMLR W&CP` is the earlier name of PMLR, not the journal.
        found.discard("jmlr")
    return frozenset(found)


def _share(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """The share of the shorter name's distinctive words that agree with a word of the other."""
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if not short:
        return 0.0
    return sum(any(_word_agrees(w, v) for v in long) for w in short) / len(short)


def _findings_conference(text: str) -> str:
    """The conference a Findings volume belongs to: `EMNLP 2020` from `Findings of the
    Association for Computational Linguistics: EMNLP 2020`. Empty where the name gives only the
    series, as `Findings of the ACL` does."""
    if ":" in text:
        return text.split(":", 1)[1].strip()
    rest = re.sub(r"^\s*findings\s+(of\s+)?(the\s+)?", "", text, flags=re.IGNORECASE).strip()
    series = {"acl", "association computational linguistics"}
    return "" if " ".join(read(rest).words) in series else rest


def _specific(names: list[str]) -> str:
    """The first name that is not a series, or the first name where all are."""
    series = [read(n) for n in SERIES_NAMES]
    for n in names:
        if not any(read(n).words == s.words for s in series):
            return n
    return names[0]


def _acronyms_only(names: list[Name]) -> bool:
    """Every name on this side is an abbreviation, which nothing here can expand."""
    return all(set(n.core) <= n.acronyms for n in names)


# ----------------------------------------------------------------------------------- verdict


def decide(
    ours: list[str], theirs: list[str], ours_kind: str = "", theirs_kind: str = ""
) -> VenueCheck:
    """Compare the venue names an entry gives with those its record gives.

    `ours` is the entry's names in order of preference (journal or booktitle, then series);
    the first non-empty one is compared. A mismatch reports it and the record's most specific
    name. A kind is `journal`,
    `proceedings`, `preprint` or empty for unknown; two journals are held to the stricter rule,
    because journal titles are standardized and `Nature` against `Nature Communications` is
    the error, while a conference is written so many ways that partial agreement is not
    evidence of a different one.
    """
    # Only the first name the entry gives is compared, and a later one only where it is empty:
    # an entry's series (`Lecture Notes in Computer Science`) must not vouch for a wrong
    # booktitle.
    ours = [n for n in ours if n and n.strip()][:1]
    theirs = [n for n in theirs if n and n.strip()]
    if not ours:
        return VenueCheck(outcome=NOT_COMPARABLE, why="the entry names no venue")
    first = ours[0]
    if ours_kind == "preprint" or is_repository(first):
        return VenueCheck(outcome=NOT_COMPARABLE, ours=first, why="the entry cites a preprint")
    published = [n for n in theirs if not is_repository(n)]
    garbled = any(GARBLED in n for n in [*ours, *theirs])
    if not published:
        why = PREPRINT_RECORD if theirs else "the record names no venue"
        return VenueCheck(
            outcome=NOT_COMPARABLE, ours=first, theirs=theirs[0] if theirs else "", why=why
        )
    if theirs_kind == "preprint":
        theirs_kind = ""
    record = _specific([n for n in published if GARBLED not in n] or published)

    readable_ours = [n for n in ours if not is_repository(n) and GARBLED not in n]
    readable_theirs = [n for n in published if GARBLED not in n]
    mine = [read(f) for n in readable_ours for f in forms(n)]
    yours = [read(f) for n in readable_theirs for f in forms(n)]

    def verdict(outcome: str, why: str) -> VenueCheck:
        if outcome == MISMATCH and garbled:
            outcome, why = NOT_COMPARABLE, GARBLED_RECORD
        return VenueCheck(outcome=outcome, ours=first, theirs=record, why=why)

    if not mine or not yours:
        return verdict(NOT_COMPARABLE, GARBLED_RECORD)

    # A Findings volume is compared by its conference. `Findings of the ACL: EMNLP 2020` and
    # `Findings of the ACL: ACL-IJCNLP 2021` share every word before the colon.
    if read(first).track == read(record).track == "findings":
        a, b = _findings_conference(first), _findings_conference(record)
        if not a or not b:
            return verdict(NOT_COMPARABLE, "a Findings volume that names no conference")
        inner = decide([a], [b], "proceedings", "proceedings")
        return verdict(inner.outcome, f"findings: {inner.why}")

    # Names are matched within a track: `ICCV Workshops`, one of Semantic Scholar's alternate
    # names for ICCV, is not the main conference.
    for a in mine:
        for b in yours:
            rule = same(a, b) if a.track == b.track else ""
            if rule:
                return verdict(MATCH, f"{rule}: {a.text!r} ~ {b.text!r}")
    for a in mine:
        for b in yours:
            shared = keys(a) & keys(b) if a.track == b.track else frozenset()
            if shared:
                return verdict(MATCH, f"alias: {sorted(shared)[0]}")

    for a in mine:
        for b in yours:
            if a.track == b.track and _parent_and_derivative(a, b):
                return verdict(MISMATCH, "a derivative journal against its parent")

    # A registry files a workshop paper under the main proceedings often enough, and Semantic
    # Scholar merges the versions of a work, that a workshop against a main track is no
    # evidence of a wrong venue.
    my_track, your_track = read(first).track, read(record).track
    if my_track != your_track:
        return verdict(NOT_COMPARABLE, f"{my_track} against {your_track} track")

    my_keys = frozenset().union(*(keys(n) for n in mine))
    your_keys = frozenset().union(*(keys(n) for n in yours))

    # A series is no venue: a paper is in PMLR and at ICML at once.
    if (my_keys - SERIES) and (your_keys - SERIES):
        return verdict(
            MISMATCH,
            f"different venues: {sorted(my_keys - SERIES)} vs {sorted(your_keys - SERIES)}",
        )

    for side, side_keys in ((mine, my_keys), (yours, your_keys)):
        if not side_keys and _acronyms_only(side):
            return verdict(NOT_COMPARABLE, "an abbreviation the alias table does not expand")

    if ours_kind == theirs_kind == "journal":
        return verdict(MISMATCH, "two journal titles that do not agree")

    # An acronym the table knows is compared by what it stands for.
    mine += [known for alias, known in _ALIAS_NAMES if alias.key in my_keys]
    yours += [known for alias, known in _ALIAS_NAMES if alias.key in your_keys]
    share = max(_share(a.core, b.core) for a in mine for b in yours)
    if share >= PARTLY:
        return verdict(NOT_COMPARABLE, "the names partly agree")
    return verdict(MISMATCH, "the names share few distinctive words")


__all__ = [
    "ALIASES",
    "MATCH",
    "MISMATCH",
    "NOT_COMPARABLE",
    "Alias",
    "Name",
    "VenueCheck",
    "decide",
    "forms",
    "is_repository",
    "keys",
    "read",
    "same",
]
