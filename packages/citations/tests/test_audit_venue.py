"""A real paper cited at the wrong venue passed every check `audit` made.

The venue is now compared like the year. The cost of being wrong is not symmetric: a venue is
written a dozen ways for one meeting, and a check that cries wrong at `NeurIPS` against
`Advances in Neural Information Processing Systems` buries the one entry that is actually at
the wrong journal. So there are three outcomes, and `not comparable` is never a disagreement.

The last test audits 60 real, correctly cited references offline, against the registry and
search answers fetched for them once, and expects no venue disagreement. The cached bodies are
trimmed to the fields `audit` reads (reference lists, abstracts and the like removed) and
re-enveloped; the URLs and every field read are as fetched on 2026-10-14.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from citations import audit as A
from citations import venue as V

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "audit_venue"


def record(**kw) -> A.RegistryRecord:
    return A.RegistryRecord(source="crossref", **kw)


def venue_problems(entry: A.Entry, rec: A.RegistryRecord) -> list[str]:
    return [p for p in A.compare(entry, rec) if p.startswith("venue")]


# --- the three outcomes --------------------------------------------------------------------


def test_a_journal_and_its_abbreviation_match():
    entry = A.Entry(key="k", venue="Nat. Commun.", venue_kind="journal")
    rec = record(venues=["Nature Communications"], venue_kind="journal")
    assert A.venue_check(entry, rec).outcome == V.MATCH
    assert venue_problems(entry, rec) == []


def test_a_real_paper_at_the_wrong_journal_is_a_mismatch_naming_both():
    entry = A.Entry(key="k", venue="Nature", venue_kind="journal")
    rec = record(venues=["Nature Communications", "Nat Commun"], venue_kind="journal")
    assert A.venue_check(entry, rec).outcome == V.MISMATCH
    assert venue_problems(entry, rec) == [
        "venue: ours 'Nature' vs registry 'Nature Communications'"
    ]


@pytest.mark.parametrize(
    "ours,theirs",
    [
        ("ICML", "Neural Information Processing Systems"),
        (
            "ACL",
            "Proceedings of the 2019 Conference of the North American Chapter of the "
            "Association for Computational Linguistics: Human Language Technologies",
        ),
        ("ICCV", "2016 IEEE Conference on Computer Vision and Pattern Recognition (CVPR)"),
        ("Bioinformatics", "Nucleic Acids Research"),
    ],
)
def test_two_different_venues_are_a_mismatch(ours, theirs):
    check = V.decide([ours], [theirs], "proceedings", "")
    assert check.outcome == V.MISMATCH, check.why


@pytest.mark.parametrize(
    "ours,theirs,why",
    [
        ("", "Nature", "the entry names no venue"),
        ("Nature", "", "the record names no venue"),
        (
            "SIGMOD",
            "Proceedings of the 2016 International Conference on Management of Data",
            "an abbreviation the alias table does not expand",
        ),
        (
            "Proc. Conf. Empirical Methods in NLP",
            "Proceedings of the 2020 Conference on Empirical Methods in Natural Language "
            "Processing (EMNLP)",
            "the names partly agree",
        ),
    ],
)
def test_what_cannot_be_settled_is_not_comparable(ours, theirs, why):
    check = V.decide([ours], [theirs], "proceedings", "proceedings")
    assert (check.outcome, check.why) == (V.NOT_COMPARABLE, why)


def test_not_comparable_is_never_a_disagreement():
    entry = A.Entry(key="k", title="T", venue="SIGMOD", doi="10/x")
    rec = record(
        title="T", venues=["Proceedings of the 2016 International Conference on Management of Data"]
    )
    assert A.venue_check(entry, rec).outcome == V.NOT_COMPARABLE
    assert A.compare(entry, rec) == []


# --- abbreviations ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ours,theirs",
    [
        ("J. Mach. Learn. Res.", "Journal of Machine Learning Research"),
        (
            "Proc. Natl. Acad. Sci. U.S.A.",
            "Proceedings of the National Academy of Sciences of the United States of America",
        ),
        ("PNAS", "Proceedings of the National Academy of Sciences"),
        ("N. Engl. J. Med.", "New England Journal of Medicine"),
        ("NEJM", "The New England Journal of Medicine"),
        ("Ann. Statist.", "The Annals of Statistics"),
        ("JASA", "Journal of the American Statistical Association"),
        ("IEEE TPAMI", "IEEE Transactions on Pattern Analysis and Machine Intelligence"),
        (
            "J. R. Stat. Soc. B",
            "Journal of the Royal Statistical Society Series B: Statistical Methodology",
        ),
        (
            "Journal of the Royal Statistical Society: Series B (Methodological)",
            "Journal of the Royal Statistical Society Series B: Statistical Methodology",
        ),
        ("Science", "Science (New York, N.Y.)"),
    ],
)
def test_a_journal_abbreviation_matches_the_title(ours, theirs):
    check = V.decide([ours], [theirs], "journal", "journal")
    assert check.outcome == V.MATCH, check.why


@pytest.mark.parametrize(
    "ours,theirs",
    [
        ("NeurIPS", "Advances in Neural Information Processing Systems"),
        ("NIPS", "Neural Information Processing Systems"),
        (
            "Advances in Neural Information Processing Systems 33",
            "Neural Information Processing Systems",
        ),
        ("Adv. Neural Inf. Process. Syst.", "Neural Information Processing Systems"),
        ("ICML", "Proceedings of the 37th International Conference on Machine Learning"),
        ("ICLR", "International Conference on Learning Representations"),
        ("5th International Conference on Learning Representations", "ICLR"),
        ("CVPR", "2016 IEEE Conference on Computer Vision and Pattern Recognition (CVPR)"),
        (
            "Proceedings of NAACL-HLT",
            "Proceedings of the 2019 Conference of the North American "
            "Chapter of the Association for Computational Linguistics: Human Language "
            "Technologies, Volume 1 (Long and Short Papers)",
        ),
        (
            "EMNLP",
            "Proceedings of the 2014 Conference on Empirical Methods in Natural Language "
            "Processing (EMNLP)",
        ),
        ("AAAI", "Proceedings of the AAAI Conference on Artificial Intelligence"),
        (
            "Thirty-Eighth AAAI Conference on Artificial Intelligence",
            "Proceedings of the AAAI Conference on Artificial Intelligence",
        ),
    ],
)
def test_a_conference_acronym_matches_its_full_title(ours, theirs):
    check = V.decide([ours], [theirs], "proceedings", "proceedings")
    assert check.outcome == V.MATCH, check.why


def test_an_acm_event_acronym_deposited_only_under_event_is_read(tmp_path, monkeypatch):
    body = json.dumps(
        {
            "message": {
                "type": "proceedings-article",
                "container-title": [
                    "Proceedings of the 22nd ACM SIGKDD International Conference on Knowledge "
                    "Discovery and Data Mining"
                ],
                "event": {
                    "name": "KDD '16: The 22nd ACM SIGKDD International Conference",
                    "acronym": "KDD '16",
                },
            }
        }
    )
    monkeypatch.setattr(A, "fetch", lambda url, cache, name: body)
    rec = A.from_crossref("10.1145/2939672.2939785", tmp_path)
    assert "KDD '16" in rec.venues
    assert rec.venue_kind == "proceedings"
    entry = A.Entry(key="k", venue="KDD", venue_kind="proceedings")
    assert A.venue_check(entry, rec).outcome == V.MATCH


def test_a_springer_volume_title_is_read_beside_its_series():
    rec = record(venues=["Lecture Notes in Computer Science", "Computer Vision – ECCV 2020"])
    entry = A.Entry(key="k", venue="European Conference on Computer Vision (ECCV)")
    assert A.venue_check(entry, rec).outcome == V.MATCH


def test_a_series_on_the_entry_is_a_second_name_and_never_a_conflict():
    entry = A.Entry(
        key="k",
        venue="Proceedings of the 38th ICML",
        series="Proceedings of Machine Learning Research",
    )
    rec = record(venues=["International Conference on Machine Learning"])
    assert A.venue_check(entry, rec).outcome == V.MATCH


# --- preprints -------------------------------------------------------------------------------


def test_an_arxiv_record_is_never_a_venue_mismatch_by_itself():
    entry = A.Entry(key="k", venue="ICML", venue_kind="proceedings")
    rec = A.RegistryRecord(source="datacite", venues=["arXiv"], venue_kind="preprint")
    check = A.venue_check(entry, rec)
    assert (check.outcome, check.why) == (V.NOT_COMPARABLE, V.PREPRINT_RECORD)
    assert venue_problems(entry, rec) == []


def test_an_entry_citing_the_preprint_is_not_compared_with_the_published_venue():
    for ours in ("arXiv preprint arXiv:1907.11692", "CoRR", "bioRxiv"):
        check = V.decide([ours], ["Neural Information Processing Systems"], "journal", "")
        assert (check.outcome, check.why) == (V.NOT_COMPARABLE, "the entry cites a preprint")


def test_a_preprint_record_is_compared_once_another_service_names_the_venue(tmp_path, monkeypatch):
    feed = (
        "<feed><entry><id>http://arxiv.org/abs/1706.03762v7</id>"
        "<published>2017-06-12T00:00:00Z</published>"
        "<title>Attention Is All You Need</title>"
        "<author><name>Ashish Vaswani</name></author></entry></feed>"
    )
    monkeypatch.setattr(A.resolve, "get", lambda url, **kw: feed if "arxiv.org" in url else None)
    monkeypatch.setattr(A.time, "sleep", lambda _: None)
    arxiv = A.RegistryRecord(
        source="datacite",
        title="Attention Is All You Need",
        years=["2017"],
        venues=["arXiv"],
        venue_kind="preprint",
    )
    monkeypatch.setattr(A, "from_datacite", lambda doi, cache: arxiv)
    asked = []

    def elsewhere(names):
        def lookup(doi, cache):
            asked.append(doi)
            return names

        return lookup

    def run(venue):
        entry = A.Entry(
            key="k",
            title="Attention Is All You Need",
            authors=["Vaswani, Ashish"],
            year="2017",
            venue=venue,
        )
        return A.audit([entry], tmp_path / "cache").entries["k"]

    monkeypatch.setattr(
        A, "other_venue_names", elsewhere(["Neural Information Processing Systems"])
    )
    assert run("NeurIPS").venue.outcome == V.MATCH
    wrong = run("ICML")
    assert wrong.status == "mismatch"
    assert wrong.problems == [
        "venue: ours 'ICML' vs registry 'Neural Information Processing Systems'"
    ]
    assert asked == ["10.48550/arXiv.1706.03762"] * 2

    monkeypatch.setattr(A, "other_venue_names", elsewhere([]))
    nobody = run("ICML")
    assert (nobody.status, nobody.venue.why) == ("ok", V.PREPRINT_RECORD)


# --- workshop and main track -----------------------------------------------------------------


@pytest.mark.parametrize(
    "ours,theirs",
    [
        (
            "ICML Workshop on Human Interpretability in Machine Learning",
            "International Conference on Machine Learning",
        ),
        (
            "CVPR",
            "2020 IEEE/CVF Conference on Computer Vision and Pattern Recognition Workshops (CVPRW)",
        ),
        (
            "Findings of the Association for Computational Linguistics: EMNLP 2020",
            "Proceedings of the 2020 Conference on Empirical Methods in Natural Language "
            "Processing (EMNLP)",
        ),
    ],
)
def test_a_workshop_against_the_main_track_is_not_comparable(ours, theirs):
    check = V.decide([ours], [theirs], "proceedings", "proceedings")
    assert check.outcome == V.NOT_COMPARABLE
    assert "track" in check.why


def test_a_workshop_against_its_own_proceedings_matches():
    check = V.decide(
        ["IEEE Conference on Computer Vision and Pattern Recognition Workshops"],
        ["2014 IEEE Conference on Computer Vision and Pattern Recognition Workshops"],
        "proceedings",
        "proceedings",
    )
    assert check.outcome == V.MATCH


# --- reported like any other field -----------------------------------------------------------


def test_a_venue_mismatch_fails_the_audit_like_a_wrong_year(tmp_path, monkeypatch, capsys):
    rec = record(title="T", years=["2020"], venues=["Nature Communications"], venue_kind="journal")
    monkeypatch.setattr(A, "from_crossref", lambda doi, cache: rec)
    monkeypatch.setattr(A, "other_venue_names", lambda doi, cache: [])
    entry = A.Entry(
        key="k", title="T", year="2020", venue="Nature", venue_kind="journal", doi="10.1038/x"
    )

    report = A.audit([entry], tmp_path / "cache")

    assert report.entries["k"].status == "mismatch"
    assert A.render(report, quiet=False) == 1
    out = capsys.readouterr().out
    assert "venue: ours 'Nature' vs registry 'Nature Communications'" in out
    assert "        1  venue" in out


def test_other_names_are_asked_for_only_before_a_mismatch(tmp_path, monkeypatch):
    rec = record(
        title="T", venues=["2016 IEEE Conference on Computer Vision and Pattern Recognition (CVPR)"]
    )
    monkeypatch.setattr(A, "from_crossref", lambda doi, cache: rec)
    asked = []
    monkeypatch.setattr(A, "other_venue_names", lambda doi, cache: asked.append(doi) or [])
    entries = [A.Entry(key="k", title="T", venue="CVPR", doi="10.1109/x")]

    assert A.audit(entries, tmp_path / "cache").entries["k"].venue.outcome == V.MATCH
    assert asked == [], "an agreeing venue cost a request"


def test_another_service_s_name_for_the_venue_rescues_a_would_be_mismatch(tmp_path, monkeypatch):
    # Series C of the Royal Statistical Society's journal was titled `Applied Statistics`, and
    # OpenAlex files it under that name too. Crossref's title alone reads as another journal.
    rec = record(
        title="T",
        venues=["Journal of the Royal Statistical Society Series C: Applied Statistics"],
        venue_kind="journal",
    )
    monkeypatch.setattr(A, "from_crossref", lambda doi, cache: rec)
    entry = A.Entry(
        key="k", title="T", venue="Applied Statistics", venue_kind="journal", doi="10.2307/x"
    )

    monkeypatch.setattr(A, "other_venue_names", lambda doi, cache: [])
    assert A.audit([entry], tmp_path / "cache").entries["k"].status == "mismatch"

    monkeypatch.setattr(A, "other_venue_names", lambda doi, cache: ["Applied Statistics"])
    verdict = A.audit([entry], tmp_path / "cache").entries["k"]
    assert (verdict.status, verdict.venue.outcome) == ("ok", V.MATCH)


# --- reading a bibliography ------------------------------------------------------------------


def test_a_bib_entry_s_venue_fields_are_read(tmp_path):
    f = tmp_path / "refs.bib"
    f.write_text(
        "@article{j, title = {A}, journal = {Nature}, eprint = {1234.5678},"
        " archivePrefix = {arXiv}}\n"
        "@inproceedings{c, title = {B}, booktitle = {Proceedings of ICML},"
        " series = {Proceedings of Machine Learning Research}}\n"
        "@misc{p, title = {C}, howpublished = {arXiv preprint arXiv:1907.11692}}\n"
        "@book{b, title = {D}, publisher = {Springer}}\n"
    )
    got = {e.key: (e.venue, e.venue_kind, e.series) for e in A.entries_from_bib(f)}
    assert got == {
        "j": ("Nature", "journal", ""),
        "c": ("Proceedings of ICML", "proceedings", "Proceedings of Machine Learning Research"),
        "p": ("", "preprint", ""),
        "b": ("", "", ""),
    }


# --- precision on real references ------------------------------------------------------------


def _offline(monkeypatch):
    def refuse(*a, **kw):
        raise A.NETWORK_ERRORS[0]("offline")

    def throttled(url, *a, **kw):
        raise A.resolve.Throttled(url)

    monkeypatch.setattr(A.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(A.resolve, "get", throttled)
    monkeypatch.setattr(A.time, "sleep", lambda _: None)


def test_no_correctly_cited_real_reference_is_flagged_for_its_venue(monkeypatch):
    _offline(monkeypatch)
    entries = A.entries_from_bib(FIXTURE / "references.bib")
    assert len(entries) >= 40

    report = A.audit(entries, FIXTURE / "cache")

    flagged = {
        k: v.problems
        for k, v in report.entries.items()
        if any(p.startswith("venue") for p in v.problems)
    }
    assert flagged == {}
    expected = json.loads((FIXTURE / "report.json").read_text())
    got = {k: v.model_dump(mode="json") for k, v in report.entries.items()}
    assert got == expected["entries"]
    outcomes = [v.venue.outcome for v in report.entries.values() if v.venue]
    assert outcomes.count(V.MATCH) >= 40
