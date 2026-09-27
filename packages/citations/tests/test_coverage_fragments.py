"""An ellipsis quotation asserts every fragment, so every fragment has to be decided.

A fragment under `MIN_FRAGMENT` occurs somewhere in almost any document, so finding one there
establishes nothing. It is therefore searched for only in a window beside a long fragment's match,
on the side the quotation puts it. Dropping it instead and answering from the fragments that remain
reported coverage of text that was never examined, and `coverage --strict` exited 0 on a quotation
whose first half appeared in neither the pinned quote nor the source. Refusing every quotation
carrying a short fragment sent `"we find ... "` and `"the model ... "` openings to `unresolvable`,
which is a reason to stop running `--strict`.
"""

from __future__ import annotations

import pathlib

from citations import coverage as C
from citations.models import ClaimFile


def claim_file(name: str, *quotes: str) -> ClaimFile:
    cf = ClaimFile.model_validate(
        {
            "source": {"citation": name, "local": "", "sha256": "x" * 64},
            "claims": {"c1": {"statement": "s", "quotes": [{"exact": q} for q in quotes]}},
        }
    )
    return cf.model_copy(update={"path": pathlib.Path(f"{name}.yaml")})


def only(tex: str) -> C.Quotation:
    got = C.quotations(tex)
    assert len(got) == 1, f"expected one quotation, got {len(got)}"
    return got[0]


def finding(tex: str, *pinned: str) -> C.Finding:
    return C.cover(only(tex), C.pinned_spans([claim_file("s", *pinned)]))


PINNED = "the calibration error falls to 0.031 under the new schedule"


# --- a short fragment is decided where its anchor puts it ---------------------------------------


def test_a_short_fragment_absent_beside_its_anchor_is_uncovered():
    # The original bug: this came back `covered` on the strength of its second half. `uncovered`
    # rather than `unresolvable` because the fragment was looked for -- in the 300 folded
    # characters before the long fragment's match, which is where the quotation puts it -- and is
    # not there. Nothing about the search was skipped, so the answer is absence.
    got = finding(f"``no effect ... {PINNED}''", PINNED)
    assert got.status == "uncovered"


def test_a_short_fragment_immediately_beside_its_anchor_is_covered():
    got = finding(f"``no effect ... {PINNED}''", f"we saw no effect on {PINNED}")
    assert got.status == "covered"


def test_a_common_short_opening_is_decided_rather_than_refused():
    # "we find ... " openings are frequent enough that refusing them all is a reason to stop
    # running --strict.
    got = finding(f"``we find ... {PINNED}''", f"we find that {PINNED}")
    assert got.status == "covered"


def test_a_short_fragment_beyond_the_window_is_uncovered():
    far = "no effect " + "x" * (C.ANCHOR_WINDOW + 1) + " " + PINNED
    assert finding(f"``no effect ... {PINNED}''", far).status == "uncovered"


def test_a_short_fragment_inside_the_window_is_covered():
    near = "no effect " + "x" * (C.ANCHOR_WINDOW - 20) + " " + PINNED
    assert finding(f"``no effect ... {PINNED}''", near).status == "covered"


def test_a_short_fragment_on_the_wrong_side_of_its_anchor_is_uncovered():
    # The quotation writes "no effect" before the long fragment. A source that says it afterwards
    # is not the source the quotation describes.
    got = finding(f"``no effect ... {PINNED}''", f"{PINNED} and we saw no effect")
    assert got.status == "uncovered"


def test_an_anchor_that_repeats_is_tried_at_every_occurrence():
    # The quotation asserts that some occurrence of the long fragment has the short one beside it,
    # not that the first one does.
    twice = f"{PINNED} and elsewhere no effect on {PINNED}"
    assert finding(f"``no effect ... {PINNED}''", twice).status == "covered"


# --- what no window can be built for is still undecided ----------------------------------------


def test_a_wholly_short_quotation_is_still_unresolvable():
    got = finding("``the model''", PINNED)
    assert got.status == "unresolvable"


def test_two_short_fragments_in_a_row_leave_one_with_nothing_to_anchor_to():
    got = finding(f"``we find ... the model ... {PINNED}''", f"we find the model {PINNED}")
    assert got.status == "unresolvable"


def test_the_reason_names_the_fragment_that_could_not_be_anchored():
    got = finding(f"``we find ... the model ... {PINNED}''", f"we find the model {PINNED}")
    assert "we find" in got.detail


# --- a quotation whose every fragment is long is unaffected -------------------------------------


def test_a_quotation_whose_every_fragment_is_long_enough_is_still_covered():
    got = finding(
        f"``the schedule was revised and ... {PINNED}''",
        f"the schedule was revised and then {PINNED}",
    )
    assert got.status == "covered"


def test_a_quotation_whose_every_fragment_is_long_and_absent_is_still_uncovered():
    got = finding(
        f"``the schedule was never revised ... {PINNED}''",
        f"the schedule was revised and then {PINNED}",
    )
    assert got.status == "uncovered"


def test_long_fragments_are_not_held_to_the_window_or_to_their_order():
    # The window places a short fragment only. Two long fragments each establish themselves, and
    # a source may write them far apart or in the other order.
    reordered = f"{PINNED}. " + "x" * (C.ANCHOR_WINDOW * 2) + " the schedule was revised and then"
    got = finding(f"``the schedule was revised and ... {PINNED}''", reordered)
    assert got.status == "covered"


# --- attribution asks the same question of the artifact ----------------------------------------


def test_attribution_makes_the_same_call_on_an_absent_short_fragment():
    # With a key in the window, so the answer comes from the fragments rather than from the
    # earlier guard that ends the question when no source is cited nearby.
    q = only(f"``no effect ... {PINNED}'' \\citep{{s}}")
    assert q.keys == ("s",)
    by_key = {"s": C.comparable(f"the paper reports that {PINNED}")}
    assert C.attribute(q, by_key, set()).status == "uncovered"


def test_attribution_covers_a_short_fragment_beside_its_anchor():
    q = only(f"``no effect ... {PINNED}'' \\citep{{s}}")
    by_key = {"s": C.comparable(f"the paper reports no effect and {PINNED}")}
    assert C.attribute(q, by_key, set()).status == "covered"


def test_attribution_leaves_an_unanchorable_fragment_undecided():
    q = only(f"``we find ... the model ... {PINNED}'' \\citep{{s}}")
    by_key = {"s": C.comparable(f"we find the model {PINNED}")}
    assert C.attribute(q, by_key, set()).status == "unresolvable"


def test_attribution_still_covers_a_quotation_whose_fragments_are_all_long():
    q = only(f"``the schedule was revised and ... {PINNED}'' \\citep{{s}}")
    by_key = {"s": C.comparable(f"the schedule was revised and then {PINNED}")}
    assert C.attribute(q, by_key, set()).status == "covered"
