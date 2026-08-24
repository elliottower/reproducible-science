"""A DOI that resolves says nothing about the metadata sitting beside it.

Every other check in this library takes the identifier as the thing to test: does it exist,
does it still resolve, is the quotation pinned to it real. The failure these pin is the one
that passes all of that -- a correct DOI carrying an author list belonging to nobody on the
paper. It resolves, the link is live, the quotations are genuine, and the reference is wrong.
"""

from __future__ import annotations

from citations import audit as A


def record(**kw) -> A.RegistryRecord:
    return A.RegistryRecord(source="crossref", **kw)


def names(*pairs):
    return [(A.tokens(f), A.tokens(g)) for f, g in pairs]


# --- the failure the command exists for ------------------------------------------------------

REAL = record(
    title="Genome-wide association study of circulating interleukin 6 levels",
    years=["2012"],
    volume="21",
    pages="5056-5065",
    authors=names(("Naitza", "Silvia"), ("Porcu", "Eleonora"), ("Steri", "Maristella")),
)


def test_a_fabricated_author_list_on_a_correct_doi_is_caught():
    entry = A.Entry(
        key="interleukin2012",
        title=REAL.title,
        authors=["Chen, Wei", "Zhang, Li", "Kumar, Rajesh"],
        year="2012",
        volume="21",
        pages="5056--5065",
        doi="10.1093/hmg/dds213",
    )
    problems = A.compare(entry, REAL)
    assert problems, "every field but the names agreed, which is how this survives a DOI check"
    assert all("surname" in p for p in problems)


def test_the_same_entry_with_the_real_names_is_clean():
    entry = A.Entry(
        key="interleukin2012",
        title=REAL.title,
        authors=["Naitza, Silvia", "Porcu, Eleonora", "Steri, Maristella"],
        year="2012",
        volume="21",
        pages="5056--5065",
        doi="10.1093/hmg/dds213",
    )
    assert A.compare(entry, REAL) == []


def test_resolving_and_matching_are_different_questions():
    """The entry has an identifier and the identifier fetched. Neither makes it correct."""
    entry = A.Entry(
        key="k", title=REAL.title, authors=["Chen, Wei"], year="2012", doi="10.1093/hmg/dds213"
    )
    assert entry.identified
    assert A.compare(entry, REAL)


# --- truncation, which looks like completeness -------------------------------------------------


def test_a_list_that_stops_early_with_no_marker_is_flagged():
    src = record(authors=names(("Smith", "A"), ("Jones", "B"), ("Patel", "C"), ("Wu", "D")))
    entry = A.Entry(key="k", authors=["Smith, A", "Jones, B"], doi="10/x")
    assert any("stops at 2 of 4" in p for p in A.compare(entry, src))


def test_the_same_list_with_and_others_is_not_flagged():
    src = record(authors=names(("Smith", "A"), ("Jones", "B"), ("Patel", "C"), ("Wu", "D")))
    entry = A.Entry(key="k", authors=["Smith, A", "Jones, B", "others"], doi="10/x")
    assert A.compare(entry, src) == []


def test_more_names_than_the_registry_has_is_flagged():
    src = record(authors=names(("Smith", "A")))
    entry = A.Entry(key="k", authors=["Smith, A", "Jones, B"], doi="10/x")
    assert any("2 names" in p for p in A.compare(entry, src))


# --- what is not a disagreement ----------------------------------------------------------------


def test_a_bibtex_accent_matches_the_unicode_it_encodes():
    # The accent is a backslash-punctuation pair. Left in, it splits the name in two once
    # punctuation folds to a space, and every accented author reads as a mismatch.
    assert A.tokens("Munaf{\\'o}") == A.tokens("Munafò") == ("munafo",)
    assert A.tokens("Gon{\\c{c}}alves") == A.tokens("Gonçalves") == ("goncalves",)
    assert A.tokens("Glade-Bender") == A.tokens("Glade Bender") == ("glade", "bender")


def test_an_abbreviated_given_name_matches_the_name_it_abbreviates():
    # Records write P. T. where a registry writes Peter T. Comparing those in full reports
    # every such author, which is most of them, and buries the fabricated lists.
    ours = (A.tokens("Nelson"), A.tokens("P. T."))
    theirs = (A.tokens("Nelson"), A.tokens("Peter T."))
    assert A.disagreement(ours, theirs) is None


def test_two_records_abbreviating_different_halves_of_one_name_agree():
    """Marcos B. Ferraz and M. Bosi Ferraz: both abbreviate, and both mean M.B."""
    ours = (A.tokens("Ferraz"), A.tokens("Marcos B."))
    theirs = (A.tokens("Ferraz"), A.tokens("M. Bosi"))
    assert A.disagreement(ours, theirs) is None


def test_an_initial_the_registry_does_not_have_is_still_reported():
    ours = (A.tokens("Kumar"), A.tokens("S. R. K."))
    theirs = (A.tokens("Kumar"), A.tokens("Suvir K."))
    assert "given name" in A.disagreement(ours, theirs)


def test_two_first_names_sharing_an_initial_are_not_the_same_person():
    """Reducing a whole given name to initials would make these agree. They are two people."""
    for mine, theirs in [
        ("Andrew J. S.", "Alastair J. S."),
        ("Shannon C.", "Suzanne C."),
        ("Madeline", "Madhuri"),
    ]:
        said = A.disagreement(
            (A.tokens("Burgess"), A.tokens(mine)), (A.tokens("Burgess"), A.tokens(theirs))
        )
        assert said and "given name" in said, f"{mine} vs {theirs} passed"


def test_an_abbreviated_middle_name_beside_a_matching_first_name_agrees():
    ours = (A.tokens("Minikel"), A.tokens("Coco C."))
    theirs = (A.tokens("Minikel"), A.tokens("Coco Chengliang"))
    assert A.disagreement(ours, theirs) is None


def test_a_middle_name_only_one_side_carries_is_not_a_disagreement():
    ours = (A.tokens("Ference"), A.tokens("Brian A."))
    theirs = (A.tokens("Ference"), A.tokens("Brian"))
    assert A.disagreement(ours, theirs) is None


def test_a_generational_suffix_is_not_a_surname_mismatch():
    ours = (A.tokens("White"), A.tokens("Charles L."))
    theirs = (A.tokens("White III"), A.tokens("Charles L."))
    assert A.disagreement(ours, theirs) is None


def test_a_particle_filed_under_the_other_field_is_not_a_surname_mismatch():
    # Del Tredici, Kelly against Tredici, Kelly Del -- one name, two filings.
    ours = (A.tokens("Del Tredici"), A.tokens("Kelly"))
    theirs = (A.tokens("Tredici"), A.tokens("Kelly Del"))
    assert A.disagreement(ours, theirs) is None


def test_a_different_person_with_a_particle_is_still_a_mismatch():
    ours = (A.tokens("Del Tredici"), A.tokens("Kelly"))
    theirs = (A.tokens("Tredici"), A.tokens("Marco"))
    assert "surname" in A.disagreement(ours, theirs)


def test_a_registry_initial_against_a_printed_given_name_is_not_an_error():
    src = record(authors=names(("Ference", "B")))
    entry = A.Entry(key="k", authors=["Ference, Brian A."], doi="10/x")
    assert A.compare(entry, src) == []


def test_initials_that_actually_disagree_are_reported():
    src = record(authors=names(("Ference", "B")))
    entry = A.Entry(key="k", authors=["Ference, Marta"], doi="10/x")
    assert any("given name" in p for p in A.compare(entry, src))


def test_given_names_that_disagree_in_full_are_reported():
    src = record(authors=names(("Ference", "Brian")))
    entry = A.Entry(key="k", authors=["Ference, Bernard"], doi="10/x")
    assert any("given name" in p for p in A.compare(entry, src))


def test_an_online_first_year_is_accepted_against_either_date():
    # published-online 2019, published-print 2020: both are the paper's year.
    src = record(years=["2020", "2019"])
    assert A.compare(A.Entry(key="k", year="2019", doi="10/x"), src) == []
    assert A.compare(A.Entry(key="k", year="2020", doi="10/x"), src) == []
    assert A.compare(A.Entry(key="k", year="2018", doi="10/x"), src)


def test_an_abbreviated_end_page_is_not_a_page_mismatch():
    # PubMed writes 1214-24 for 1214-1224, so only the start page is comparable.
    assert (
        A.compare(A.Entry(key="k", pages="1214--1224", doi="10/x"), record(pages="1214-24")) == []
    )


def test_a_different_start_page_is_a_page_mismatch():
    assert any(
        "pages" in p
        for p in A.compare(
            A.Entry(key="k", pages="1214--1224", doi="10/x"), record(pages="2114-24")
        )
    )


def test_markup_a_registry_deposited_in_the_title_is_not_a_title_mismatch():
    # Crossref stores italics as tags and sometimes escapes them twice, so the stored
    # string is literally "&amp;lt;i&amp;gt;". None of that is a disagreement about the title.
    src = record(title="Effect of statins on &amp;lt;i&amp;gt;LDLR&amp;lt;/i&amp;gt; expression")
    entry = A.Entry(key="k", title="Effect of statins on LDLR expression", doi="10/x")
    assert A.compare(entry, src) == []


def test_an_entity_encoded_greek_letter_matches_the_letter_itself():
    src = record(title="TNF-&alpha; and interleukin 6")
    entry = A.Entry(key="k", title="TNF-\u03b1 and interleukin 6", doi="10/x")
    assert A.compare(entry, src) == []


def test_a_field_absent_on_either_side_is_not_a_disagreement():
    """A registry that deposited no volume has not contradicted the volume we hold."""
    assert A.compare(A.Entry(key="k", volume="21", pages="5", doi="10/x"), record()) == []
    assert A.compare(A.Entry(key="k", doi="10/x"), record(volume="21", pages="5")) == []


# --- a subtitle-only title is a different report from a wrong one -------------------------------


def test_a_title_the_registry_continues_is_reported_as_a_prefix():
    src = record(title="Low-density lipoproteins cause disease. 1. Evidence from genetics")
    entry = A.Entry(key="k", title="Low-density lipoproteins cause disease", doi="10/x")
    problems = A.compare(entry, src)
    assert len(problems) == 1
    assert "prefix" in problems[0]


def test_an_unrelated_title_is_not_reported_as_a_prefix():
    src = record(title="Cerebral small vessel disease and cognitive decline")
    entry = A.Entry(key="k", title="Serum urate and coronary heart disease", doi="10/x")
    problems = A.compare(entry, src)
    assert len(problems) == 1
    assert "prefix" not in problems[0]


# --- reading a bibliography ---------------------------------------------------------------------

BIB = """
@article{naitza2012,
  title   = {Genome-wide association study of circulating interleukin 6 levels},
  author  = {Naitza, Silvia and Porcu, Eleonora and others},
  journal = {Human Molecular Genetics},
  year    = {2012},
  volume  = {21},
  pages   = {5056--5065},
  doi     = {10.1093/hmg/dds213}
}

@book{rothman2008,
  title  = {Modern Epidemiology},
  author = {Rothman, Kenneth J.},
  year   = {2008}
}
"""


def test_a_bib_entry_is_read_whole(tmp_path):
    f = tmp_path / "refs.bib"
    f.write_text(BIB)
    entries = {e.key: e for e in A.entries_from_bib(f)}
    assert set(entries) == {"naitza2012", "rothman2008"}
    e = entries["naitza2012"]
    assert e.doi == "10.1093/hmg/dds213"
    assert e.venue == "Human Molecular Genetics"
    assert e.authors == ["Naitza, Silvia", "Porcu, Eleonora", "others"]


def test_an_entry_with_no_identifier_is_not_reported_as_matching(tmp_path):
    f = tmp_path / "refs.bib"
    f.write_text(BIB)
    entries = [e for e in A.entries_from_bib(f) if e.key == "rothman2008"]
    report = A.audit(entries, tmp_path / "cache")
    assert report.entries["rothman2008"].status == "no identifier", (
        "nothing checked it, so it is neither clean nor dirty"
    )


def test_an_identifier_that_did_not_fetch_is_not_reported_as_matching(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "from_crossref", lambda doi, cache: None)
    monkeypatch.setattr(A, "from_pubmed", lambda pmid, cache: None)
    entry = A.Entry(key="k", title="anything", doi="10.1234/gone")
    report = A.audit([entry], tmp_path / "cache")
    assert report.entries["k"].status == "unresolved"


def test_a_cached_response_is_reused_rather_than_refetched(tmp_path, monkeypatch):
    """The cache is what makes a report reproducible from what was fetched, not from the network."""

    def refuse(*a, **kw):
        raise AssertionError("went to the network with a cached payload present")

    monkeypatch.setattr(A.urllib.request, "urlopen", refuse)
    cache = tmp_path / "cache"
    cache.mkdir()
    body = '{"message": {"title": ["A title"], "author": [{"family": "Smith", "given": "Ann"}]}}'
    _write_cache(
        cache, "crossref_10_1234_x.json", "https://api.crossref.org/works/10.1234%2Fx", body
    )
    got = A.from_crossref("10.1234/x", cache)
    assert got.title == "A title"
    assert got.authors == [(("smith",), ("ann",))]


def _write_cache(cache, name, url, body):
    """An envelope of the shape `fetch` writes, so a test exercises the real cache path."""
    import hashlib
    import json

    (cache / name).write_text(
        json.dumps(
            {
                "cache_version": A.CACHE_VERSION,
                "url": url,
                "fetched_at": "2026-01-01T00:00:00Z",
                "sha256": hashlib.sha256(body.encode()).hexdigest(),
                "body": body,
            }
        )
    )


def test_a_hand_written_cache_file_is_not_a_response(tmp_path, monkeypatch):
    """`.audit-cache/` sits beside the bibliography and gets committed. When an entry was the
    response body alone, a fabricated record -- a real DOI carrying an invented title -- could
    be made to verify offline, with no network touched."""
    reached = []

    def record(*a, **kw):
        reached.append(True)
        raise A.NETWORK_ERRORS[0]("offline")

    monkeypatch.setattr(A.urllib.request, "urlopen", record)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "crossref_10_1038_s41586_021_03819_3.json").write_text(
        '{"message": {"title": ["A Completely Invented Title Nobody Wrote"],'
        ' "author": [{"family": "Nobody", "given": "N"}]}}'
    )
    A.from_crossref("10.1038/s41586-021-03819-3", cache)
    assert reached, "a bare file was trusted as a fetched response"


def test_a_cache_entry_cannot_answer_a_different_request(tmp_path, monkeypatch):
    reached = []

    def record(*a, **kw):
        reached.append(True)
        raise A.NETWORK_ERRORS[0]("offline")

    monkeypatch.setattr(A.urllib.request, "urlopen", record)
    cache = tmp_path / "cache"
    cache.mkdir()
    body = '{"message": {"title": ["Some other work"]}}'
    _write_cache(
        cache, "crossref_10_1234_x.json", "https://api.crossref.org/works/10.9999%2Fother", body
    )
    A.from_crossref("10.1234/x", cache)
    assert reached, "an entry recorded for one URL answered another"


# --- exit codes ---------------------------------------------------------------------------------


def test_a_run_with_nothing_to_check_is_not_a_pass():
    assert A.render(A.AuditReport(where="library /nowhere"), quiet=False) == 2


def test_a_clean_run_exits_zero():
    rep = A.AuditReport(
        where="library /x", entries={"a": A.EntryAudit(status="ok", checked_against="crossref")}
    )
    assert A.render(rep, quiet=False) == 0
    assert rep.ok


def test_an_unresolved_entry_keeps_the_run_from_passing():
    rep = A.AuditReport(where="library /x", entries={"a": A.EntryAudit(status="unresolved")})
    assert A.render(rep, quiet=False) == 1
    assert not rep.ok, "no measurement was made, so it is not a pass"


def test_a_library_record_marked_et_al_is_not_reported_as_truncated():
    # A bibliography writes "and others"; a library record sets et_al. A check that
    # reads only the first calls every correctly-marked record incomplete.
    src = A.RegistryRecord(
        source="crossref",
        title="T",
        years=["2020"],
        authors=[(("smith",), ("ann",)), (("jones",), ("bo",)), (("khan",), ("li",))],
    )
    short = A.Entry(key="k", title="T", authors=["Smith, Ann"], year="2020", et_al=True)
    assert not [p for p in A.compare(short, src) if "stops at" in p]

    unmarked = A.Entry(key="k", title="T", authors=["Smith, Ann"], year="2020")
    assert [p for p in A.compare(unmarked, src) if "stops at" in p]
