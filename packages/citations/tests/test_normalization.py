"""What `fold` and `skeleton` may absorb, and what they must never absorb.

Every case here is a passage that failed in the corpus. The two directions are not
symmetrical: absorbing too little reports a passage as absent from a document that contains
it, and absorbing too much resolves a quotation against a source that says something else.
The second is the one this file mostly guards, because a checker that finds everything is
indistinguishable from no checker at all.
"""

from __future__ import annotations

import pytest
from citations.verify import fold, skeleton


@pytest.mark.parametrize(
    ("quoted", "extracted"),
    [
        # A renderer typesets `naive` with a dotless i under a combining diaeresis, which is
        # how LaTeX writes it; the quotation carries the precomposed letter. Seven quotations
        # from one paper failed on this alone.
        ("a naïve circuit", "a naı̈ve circuit"),
        # The dotless i on its own, which no normalization form reaches: NFKC and NFKD both
        # leave it exactly as it was, so a font substituting the glyph extracts a word that
        # matches no honest quotation of it.
        ("a significant finding", "a sıgnıfıcant fındıng"),
        # Compatibility ligatures.
        ("the first classifier", "the ﬁrst classiﬁer"),
        # Publishers emit U+2010, visually identical to the ASCII hyphen.
        ("patients-in-waiting", "patients‐in‐waiting"),
    ],
)
def test_fold_absorbs_what_a_renderer_changed(quoted, extracted):
    assert fold(quoted) == fold(extracted)


@pytest.mark.parametrize(
    ("quoted", "extracted"),
    [
        ("prefix-matching", "prefixmatching"),  # broken across a line in the document
        ("non- sparse", "nonsparse"),  # broken across a line in the quotation
        ("side-by- side", "side-byside"),
        ("an 8-head model", "an 8head model"),  # a digit on the left
        ("pythia-1.4b", "pythia1.4b"),  # a digit on the right
        ("p_ioi.", "pioi ."),  # a subscript the extractor flattened
    ],
)
def test_skeleton_absorbs_a_hyphen_that_joins_one_word(quoted, extracted):
    assert skeleton(quoted) == skeleton(extracted)


@pytest.mark.parametrize(
    ("quoted", "extracted", "why"),
    [
        ("delta was -0.42", "delta was 0.42", "a sign is not a hyphen"),
        ("vec('king') - vec('man')", "vec('king') vec('man')", "spaced subtraction"),
        ("a - b", "a b", "a spaced operator"),
        ("range 5-3", "range 53", "digits on both sides: a range and a subtraction agree"),
        ("p < 0.05", "p = 0.05", "a reversed inequality"),
        ("we trained 50", "we trained 5", "a number cut short"),
    ],
)
def test_skeleton_never_folds_two_different_claims_together(quoted, extracted, why):
    assert skeleton(quoted) != skeleton(extracted), why


def test_the_sign_flip_that_the_bound_exists_for():
    """Deleting every hyphen is what this rule is written to avoid.

    `mechanistic-validity` folded with `re.sub(r"-", "", s)`, so a quotation claiming a
    negative resolved against a source stating the positive -- in its primary matcher, not a
    fallback. The rule here requires a word character on the left, which a minus never has.
    """
    assert skeleton("the effect was -0.42") != skeleton("the effect was 0.42")
    assert skeleton("a drop of -12 points") != skeleton("a drop of 12 points")
