"""A quotation can be in the source and still misstate it.

Each attack here resolved as `found` with no warning: a quotation that drops the negation
before it, one taken from words the source itself quotes, one taken from the reference list,
one matched by folding a superscript flat, and one matched by joining two words into a third.
Every one is now `found` with a warning naming what the source reads there, and `--strict`
fails the ones whose record misstates the source. Each has an honest neighbour beside it that
must stay clean, because a warning on every quotation is no warning.
"""

from __future__ import annotations

import hashlib

import pytest
import yaml
from citations import pin
from citations import verify as V
from citations.cli import main

SOURCE = """Smith et al. 2020. Effects of the protocol on recall.

Abstract. We found no evidence that the treatment reduced mortality in every subgroup we examined.
The intervention did not improve recall in older adults, and the effect in younger adults was small.
Although we did not measure it directly, the dose was stable across the whole of the trial period.
These results suggest that the protein lowers risk in every cohort we studied here.
The model was not able to separate the groups, and the mean shift was 1 2.5 units overall.
The exponent was x² and the rate 10⁻⁵ per year in the reference population.
Higher circulating levels of the protein were associated with lower risk in the discovery cohort.

Discussion. As Jones (2018) argued, "the protocol reliably improves recall in all populations",
but our data do not support that view.

References
Jones, A. (2018). The protocol reliably doubles recall in every cohort. Journal of Memory 12.

Appendix A
The protocol reliably doubles recall in every cohort when sessions are spaced a week apart.
"""


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setenv("CITATIONS_NO_CACHE", "1")
    monkeypatch.setenv("REPRO_NO_HINT", "1")
    V.clear_caches()


@pytest.fixture
def source(tmp_path):
    p = tmp_path / "smith2020.txt"
    p.write_text(SOURCE)
    return p


def check(quote, path):
    r = V.check_one(quote, path)
    assert r.state == "found", r.detail
    return r


# --- Q1: a negation or hedge dropped from the front -------------------------------------------


def test_a_quotation_that_drops_the_negation_before_it_is_warned(source):
    r = check("the treatment reduced mortality in every subgroup we examined", source)
    assert "after negation" in r.warnings
    assert "no evidence that" in r.notes["after negation"]


def test_the_negated_sentence_quoted_whole_is_not_warned(source):
    r = check("We found no evidence that the treatment reduced mortality", source)
    assert "after negation" not in r.warnings


def test_a_negation_in_an_earlier_clause_does_not_govern_the_quotation(source):
    r = check("the dose was stable across the whole of the trial period", source)
    assert "after negation" not in r.warnings
    r = check("the effect in younger adults was small", source)
    assert "after negation" not in r.warnings


def test_a_quotation_that_drops_a_hedge_is_warned_and_strict_does_not_fail_on_it(source):
    r = check("the protein lowers risk in every cohort we studied here", source)
    assert "after hedge" in r.warnings
    assert "after hedge" not in V.STRICT_WARNINGS


def test_a_quotation_that_begins_its_sentence_carries_neither(source):
    r = check("Higher circulating levels of the protein were associated with lower risk", source)
    assert not {"after negation", "after hedge", "quoted in source", "references"} & set(r.warnings)


# --- Q3: someone else's words, quoted inside the source ---------------------------------------


def test_a_passage_inside_quotation_marks_in_the_source_is_warned(source):
    r = check("the protocol reliably improves recall in all populations", source)
    assert "quoted in source" in r.warnings


def test_the_source_reporting_the_quotation_is_not_inside_it(source):
    r = check("but our data do not support that view", source)
    assert "quoted in source" not in r.warnings


# --- Q4: the reference list -------------------------------------------------------------------


def test_a_passage_found_only_in_the_reference_list_is_warned(source):
    r = check("Jones, A. (2018). The protocol reliably doubles recall in every cohort", source)
    assert "references" in r.warnings
    assert "references" in V.STRICT_WARNINGS


def test_an_appendix_after_the_reference_list_is_not_in_it(source):
    r = check("doubles recall in every cohort when sessions are spaced a week apart", source)
    assert "references" not in r.warnings


# --- Q5: superscripts and subscripts folded flat ----------------------------------------------


def test_a_superscript_folded_flat_is_warned(source):
    r = check("The exponent was x2 and the rate 10-5 per year", source)
    assert "superscript" in r.warnings
    assert "x²" in r.notes["superscript"]


def test_the_superscript_quoted_as_the_source_sets_it_is_not_warned(source):
    r = check("The exponent was x² and the rate 10⁻⁵ per year", source)
    assert "superscript" not in r.warnings


# --- Q6: a match that joins two words, or two numbers -----------------------------------------


def test_joining_a_negation_onto_the_next_word_is_not_a_quotation_of_it(source):
    r = check("The model was notable to separate the groups", source)
    assert "joined" in r.warnings
    assert r.notes["joined"] == "source `not able`, quoted `notable`"


def test_splitting_a_word_into_a_negation_is_not_a_quotation_of_it(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("The model was notable for how well it separated the two groups of patients.")
    r = check("The model was not able for how well it separated the two groups", p)
    assert "joined" in r.warnings


def test_joining_two_numbers_is_not_a_quotation_of_either(source):
    r = check("the mean shift was 12.5 units overall", source)
    assert "joined" in r.warnings
    assert r.notes["joined"] == "source `1 2.5`, quoted `12.5`"


@pytest.mark.parametrize(
    ("extracted", "quote"),
    [
        (
            "the logitdifference was large in every layer we ablated",
            "the logit difference was large in every layer",
        ),
        (
            "the logit differ ence was large in every layer we ablated",
            "the logit difference was large in every layer",
        ),
        (
            "by the end the cohort held 12 500 participants across the sites",
            "the cohort held 12500 participants across the sites",
        ),
    ],
)
def test_an_extractor_dropping_or_inserting_a_space_is_not_joined(tmp_path, extracted, quote):
    p = tmp_path / "s.txt"
    p.write_text(extracted)
    r = V.check_one(quote, p)
    assert r.state == "found"
    assert "normalized" in r.warnings
    assert "joined" not in r.warnings


# --- Q14 and the strict set, through the command ----------------------------------------------


def claims_dir(tmp_path, quotes, page=None):
    (tmp_path / "claims").mkdir(exist_ok=True)
    src = tmp_path / "sources"
    src.mkdir(exist_ok=True)
    (src / "smith2020.txt").write_text(SOURCE)
    doc = {
        "source": {
            "citation": "smith2020",
            "local": "sources/smith2020.txt",
            "sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
        },
        "claims": {
            f"c{i}": {"quotes": [{"exact": q, **({"page": page} if page else {})}]}
            for i, q in enumerate(quotes)
        },
    }
    (tmp_path / "claims" / "smith2020.yaml").write_text(yaml.safe_dump(doc))
    return tmp_path / "claims"


def test_strict_fails_a_dropped_negation_and_the_default_does_not(tmp_path, capsys):
    claims = claims_dir(tmp_path, ["the treatment reduced mortality in every subgroup we examined"])
    assert main(["verify", "--claims", str(claims)]) == 0
    out = capsys.readouterr().out
    assert "after negation" in out and "`--strict` fails on after negation" in out
    assert main(["verify", "--claims", str(claims), "--strict"]) == 1
    assert "misstates the source" in capsys.readouterr().out


def test_strict_passes_a_hedge_and_a_quotation_from_quoted_words(tmp_path):
    claims = claims_dir(
        tmp_path,
        [
            "the protein lowers risk in every cohort we studied here",
            "the protocol reliably improves recall in all populations",
        ],
    )
    assert main(["verify", "--claims", str(claims), "--strict"]) == 0


def test_a_wrong_page_fails_strict():
    r = V.Result("found", "not on page 3", ["page"], 1)
    rep = V.Report(checked=1, counts={"found": 1}, problems=[("s:c1", "q", r)])
    assert rep.ok
    assert not rep.strict_ok


def test_the_warning_notes_are_written_to_the_json(tmp_path):
    claims = claims_dir(tmp_path, ["The model was notable to separate the groups"])
    wrote = tmp_path / "out.json"
    main(["verify", "--claims", str(claims), "--json", str(wrote)])
    account = yaml.safe_load(wrote.read_text())
    (one,) = account["warnings"]["joined"]
    assert one["note"] == "source `not able`, quoted `notable`"
    assert "joined" in account["strict_warnings"]


def test_pin_refuses_a_match_that_joins_the_sources_words(tmp_path, capsys):
    claims = claims_dir(tmp_path, [])
    code = pin.main(
        [
            str(claims / "smith2020.yaml"),
            "--id",
            "j",
            "--quote",
            "The model was notable to separate",
        ]
    )
    assert code == 1
    assert "nothing written" in capsys.readouterr().out
    assert "j" not in yaml.safe_load((claims / "smith2020.yaml").read_text())["claims"]
