"""One way to fold text for comparison, used everywhere a name or title is matched.

There were two. `audit.fold` normalized to NFKD and dropped combining marks, so Kästner became
`kastner`. `services.norm` kept only `[a-z0-9 ]`, so the same name became `kstner` -- the
accented letter deleted rather than resolved. The second gated identifier lookup, which means
a correct paper was rejected for any author with an accent in their surname.

Two conventions for writing an umlaut are both in use and neither is wrong:

    Hölscher-Obermaier    ->  holscher      the accent dropped
                          ->  hoelscher     the German expansion

Crossref carries one, a BibTeX file often carries the other, and no single normalization
matches both. `variants()` returns every form a name might be written in, and two names agree
when their variant sets intersect.
"""
from __future__ import annotations

import html
import re
import unicodedata

#: Letters that expand to two in German transliteration. Applied before combining marks are
#: stripped, so both readings survive.
EXPANSIONS = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "ae", "Ö": "oe", "Ü": "ue",
              "ß": "ss", "æ": "ae", "œ": "oe", "å": "aa", "ø": "oe"}


def _strip_markup(text: str) -> str:
    """Remove HTML entities, tags and LaTeX commands, leaving the words.

    Crossref deposits italics as tags and sometimes escapes them twice, so a stored title can
    literally contain `&amp;lt;i&amp;gt;`. None of that is part of the title.
    """
    text = html.unescape(html.unescape(text or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\s*", "", text)
    # An accent is a backslash-punctuation pair: {\'o} is one letter, not two. Deleting the
    # mark leaves the letter; leaving it splits the name in two once punctuation folds away.
    text = re.sub(r"\\[^a-zA-Z0-9\s]", "", text)
    return text.replace("{", "").replace("}", "").replace("\\", "")


def fold(text: str) -> str:
    """Lowercase, unaccented, punctuation-free. The canonical form for comparison."""
    text = _strip_markup(text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def expand(text: str) -> str:
    """The same, with umlauts and ligatures written out as the two letters they stand for."""
    text = _strip_markup(text)
    for char, pair in EXPANSIONS.items():
        text = text.replace(char, pair)
    return fold(text)


def variants(text: str) -> frozenset[str]:
    """Every form this text might be written in. Empty input gives an empty set."""
    return frozenset(v for v in (fold(text), expand(text)) if v)


def tokens(text: str) -> tuple[str, ...]:
    """A name as folded word tokens. A hyphenated name is two tokens, an accent is none."""
    return tuple(fold(text).split())


def surname(author: str) -> str:
    """The family name out of either `Family, Given` or `Given Family`."""
    if not author:
        return ""
    return fold(author.split(",")[0] if "," in author else author.split()[-1])


def surname_variants(author: str) -> frozenset[str]:
    """Every form the family name might be written in."""
    if not author:
        return frozenset()
    return variants(author.split(",")[0] if "," in author else author.split()[-1])


__all__ = ["fold", "expand", "variants", "tokens", "surname", "surname_variants",
           "EXPANSIONS"]
