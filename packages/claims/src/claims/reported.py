"""Whether a `reported` value is the number the claim and the manuscript print.

An assertion compares `reported` with what a file stores, and nothing compared `reported` with
the sentence it stands for. A manifest reporting 0.4213, for a claim whose text and manuscript
both print 0.9913, verified under every policy: the file held 0.4213, and the number a reader
sees was never read. Each note here is a warning on the decision, which a policy grades.

**Agreement.** A printed number and `reported` agree where either, rounded to the decimal
places of the other, is the other, as printed or as a percentage of it or a fraction of it:
`92.7` agrees with `0.92655`, and `1,593` with `1593`. The claim's text, and the passages its
own quotations read from the manuscript, are compared only where they print a number at all:
a claim stating a conclusion and offering a count as support prints none.

**Precision and tolerance.** A comparison at printed precision verifies `0.0` against a stored
`0.0491`, and an absolute tolerance of `0.5` verifies `0.95` against `0.712`. Neither is a
mismatch, and either lets a manuscript print almost anything; each is noted where a stored
value was read. `claims.policy.REPORTED_SAID` says each note in words.
"""

from __future__ import annotations

import decimal

from claims.models import (
    AggregateEvidence,
    Claim,
    ComparisonMode,
    Decision,
    Evidence,
    ProseLocator,
    ValueEvidence,
    Warning_,
)
from claims.numbers import printed

#: A tolerance larger than this share of the value it bounds is noted.
LOOSE = decimal.Decimal("0.1")

#: Two significant digits is the floor below which a printed precision is noted.
MIN_SIGNIFICANT = 2

THRESHOLD = decimal.Decimal("0.05")

SCALES = (decimal.Decimal(1), decimal.Decimal(100), decimal.Decimal("0.01"))


def _decimal(text: str | None) -> decimal.Decimal | None:
    try:
        found = decimal.Decimal(text) if text is not None else None
    except decimal.InvalidOperation:
        return None
    return found if found is not None and found.is_finite() else None


def _places(value: decimal.Decimal) -> int:
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _rounds_to(value: decimal.Decimal, target: decimal.Decimal) -> bool:
    quantum = decimal.Decimal(1).scaleb(-_places(target))
    with decimal.localcontext() as context:
        context.prec = 60
        for scale in SCALES:
            for mode in (decimal.ROUND_HALF_UP, decimal.ROUND_HALF_EVEN):
                try:
                    if (value * scale).quantize(quantum, rounding=mode) == target:
                        return True
                except decimal.InvalidOperation:
                    continue
    return False


def agrees(reported: decimal.Decimal, shown: decimal.Decimal) -> bool:
    """Whether a printed number and `reported` name one value at the coarser precision."""
    return _rounds_to(reported, shown) or _rounds_to(shown, reported)


def values(text: str) -> list[decimal.Decimal]:
    """The numbers a text prints, read as `claims.numbers` reads a manuscript."""
    return [found for number in printed(text) if (found := _decimal(number.value)) is not None]


def _read_from_text(evidence: Evidence) -> bool:
    """Whether the value is read from prose, which makes it the printed number already."""
    return isinstance(evidence, ValueEvidence) and isinstance(evidence.locator, ProseLocator)


def notes(
    claim: Claim, evidence: Evidence, decision: Decision, passages: list[str]
) -> list[Warning_]:
    """The notes for one assertion. `passages` are the quotations the claim reads from its
    manuscript."""
    reported = _decimal(getattr(evidence, "reported", None))
    if reported is None or _read_from_text(evidence):
        return []
    found: list[Warning_] = []
    said = values(claim.text)
    if said and not any(agrees(reported, shown) for shown in said):
        found.append(Warning_.REPORTED_NOT_IN_CLAIM)
    quoted = [shown for passage in passages for shown in values(passage)]
    if quoted and not any(agrees(reported, shown) for shown in quoted):
        found.append(Warning_.REPORTED_NOT_IN_MANUSCRIPT)

    mode = getattr(evidence, "mode", ComparisonMode.PRINTED_PRECISION)
    stored = (
        _decimal(decision.computed if isinstance(evidence, AggregateEvidence) else None)
        or _decimal(decision.converted)
        or _decimal(decision.extracted)
    )
    if mode is ComparisonMode.PRINTED_PRECISION and stored is not None and stored != reported:
        significant = len(reported.normalize().as_tuple().digits) if reported else 0
        if significant < MIN_SIGNIFICANT:
            found.append(Warning_.COARSE_PRECISION)
        if (
            decision.conversion is None
            and 0 <= stored <= 1
            and 0 <= reported <= 1
            and (stored < THRESHOLD) != (reported < THRESHOLD)
        ):
            found.append(Warning_.ROUNDING_CROSSES_THRESHOLD)
    tolerance = _decimal(getattr(evidence, "tolerance", None))
    if tolerance is not None and tolerance > 0:
        if mode is ComparisonMode.ABSOLUTE and reported and tolerance > LOOSE * abs(reported):
            found.append(Warning_.LOOSE_TOLERANCE)
        elif mode is ComparisonMode.RELATIVE and tolerance > LOOSE:
            found.append(Warning_.LOOSE_TOLERANCE)
    return found


__all__ = ["agrees", "notes", "values"]
