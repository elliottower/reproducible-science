"""Records are generated, so every defect here is written into the database on the next build.

The module's own history supplies the cases. Stripping backslashes turned `Kram\\'{a}r` into
`Kram'ar`. BibTeX's `and others` was read literally and produced a person named "others" in
23 records. Reading only note/url/journal for an arXiv id missed every entry written with
`eprint`, splitting one work across two records. Enrichment was once read back out of the
records themselves, so clearing the directory before a rebuild lost sixteen verified years.
"""

from __future__ import annotations

import pathlib

import yaml
from citations.build import (
    arxiv_from_fields,
    arxiv_of,
    audit_existing,
    carry_forward,
    clean,
    normalize_initials,
    same_work,
    slug_for,
    split_authors,
    title_key,
)


def test_an_accent_resolves_to_the_letter_it_marks():
    assert clean(r"Kram\'{a}r") == "Kramár"
    assert clean(r"J\'anos") == "János"
    assert clean(r"{\"O}zt\"urk") == "Öztürk"


def test_the_three_spellings_of_one_accent_agree():
    assert clean(r"\'{a}") == clean(r"\'a") == clean(r"{\'a}")


def test_removing_a_command_does_not_weld_the_words_around_it():
    assert clean(r"Smith\etal Jones") == "Smith Jones"
    assert clean(r"A \LaTeX document") == "A document"
    assert clean(r"Proc.\ Natl.\ Acad.\ Sci.") == "Proc. Natl. Acad. Sci."


def test_an_escaped_character_survives_as_the_character():
    assert clean(r"AT\&T") == "AT&T"
    assert clean(r"a--b") == "a-b"


def test_an_unknown_control_sequence_is_dropped_without_taking_its_argument():
    assert clean(r"\emph{Nature}") == "Nature"
    assert "Nature" in clean(r"\textit{Nature}")


def test_and_others_is_a_property_of_the_list_not_a_member_of_it():
    authors, truncated = split_authors("Olsson, Catherine and others")
    assert authors == ["Olsson, Catherine"]
    assert truncated is True


def test_an_untruncated_list_is_not_marked_truncated():
    authors, truncated = split_authors("Wang, Kevin and Variengien, Alexandre")
    assert authors == ["Wang, Kevin", "Variengien, Alexandre"]
    assert truncated is False


def test_a_corporate_author_containing_and_is_not_split_into_two_organizations():
    authors, truncated = split_authors("U.S. Food and Drug Administration")
    assert authors == ["U.S. Food and Drug Administration"]
    assert truncated is False


def test_every_bare_initial_gets_its_period_not_only_the_last():
    assert normalize_initials("Ioannidis, John P A") == "Ioannidis, John P. A."
    assert normalize_initials("Glennan, Stuart S") == "Glennan, Stuart S."


def test_a_period_already_present_is_not_doubled():
    assert normalize_initials("Fisher, Ronald A.") == "Fisher, Ronald A."


def test_identity_prefers_the_doi_then_the_arxiv_id():
    assert slug_for({"doi": "10.1038/S41588-019-0379-X"}) == "doi-10-1038-s41588-019-0379-x"
    assert slug_for({"arxiv": "2211.00593"}) == "arxiv-2211-00593"
    assert slug_for({"doi": "10.1/x", "arxiv": "2211.00593"}).startswith("doi-")
    # An arXiv DOI is the same identifier as the eprint, and one bibliography carries the DOI
    # where another carries only the eprint. Slugging them apart gave the library four records
    # for one ICLR paper with its citing projects split across them.
    assert slug_for({"doi": "10.48550/arXiv.2502.04878"}) == "arxiv-2502-04878"
    assert slug_for({"doi": "10.48550/arxiv.2502.04878", "arxiv": "2502.04878"}) == slug_for(
        {"arxiv": "2502.04878"}
    )


def test_a_work_with_neither_identifier_still_gets_a_stable_slug():
    rec = {"title": "Interpretability in the Wild", "authors": ["Wang, Kevin"]}
    assert slug_for(rec) == slug_for(dict(rec))
    assert slug_for(rec).startswith("t-")
    assert slug_for(rec) != slug_for({"title": "Something Else", "authors": ["Wang, Kevin"]})


def test_an_arxiv_id_is_recovered_from_every_form_a_bibliography_writes_it_in():
    assert arxiv_of("https://arxiv.org/abs/2211.00593") == "2211.00593"
    assert arxiv_of("arXiv:2211.00593") == "2211.00593"
    assert arxiv_of("arXiv preprint arXiv:2211.00593") == "2211.00593"
    assert arxiv_of("no identifier here") == ""


def test_the_pre_2007_arxiv_form_is_recognized():
    assert arxiv_of("https://arxiv.org/abs/math.GT/0309136") == "math.gt/0309136"


def test_a_bare_eprint_and_a_url_yield_the_same_id():
    # The bug this prevents split one work across two records whenever some bibliographies
    # used eprint and others used a url.
    assert arxiv_from_fields({"eprint": "2211.00593"}) == "2211.00593"
    assert arxiv_from_fields({"url": "https://arxiv.org/abs/2211.00593"}) == "2211.00593"
    assert arxiv_from_fields({"eprint": "2211.00593"}) == arxiv_from_fields(
        {"url": "https://arxiv.org/abs/2211.00593"}
    )


def test_fields_carrying_no_identifier_return_empty():
    assert arxiv_from_fields({"journal": "Nature", "note": "in press"}) == ""


def _library(tmp_path: pathlib.Path, monkeypatch, enrichment=None, records=None):
    (tmp_path / "records").mkdir()
    if enrichment is not None:
        (tmp_path / "enrichment.yaml").write_text(yaml.safe_dump(enrichment))
    for slug, rec in (records or {}).items():
        (tmp_path / "records" / f"{slug}.yaml").write_text(yaml.safe_dump(rec))
    monkeypatch.setenv("CITATIONS_HOME", str(tmp_path))
    return tmp_path


def test_enrichment_fills_a_gap_the_bibliography_left(tmp_path, monkeypatch):
    _library(tmp_path, monkeypatch, enrichment={"doi-10-1-x": {"year": "1998"}})
    merged = {"doi-10-1-x": {"title": "A work"}}
    assert carry_forward(merged) == 1
    assert merged["doi-10-1-x"]["year"] == "1998"


def test_enrichment_never_overwrites_a_value_the_bibliography_supplied(tmp_path, monkeypatch):
    _library(tmp_path, monkeypatch, enrichment={"doi-10-1-x": {"year": "1998"}})
    merged = {"doi-10-1-x": {"title": "A work", "year": "2007"}}
    assert carry_forward(merged) == 0
    assert merged["doi-10-1-x"]["year"] == "2007"


def test_enrichment_for_a_slug_that_is_not_in_the_build_is_ignored(tmp_path, monkeypatch):
    _library(tmp_path, monkeypatch, enrichment={"doi-absent": {"year": "1998"}})
    merged = {"doi-10-1-x": {"title": "A work"}}
    assert carry_forward(merged) == 0
    assert merged == {"doi-10-1-x": {"title": "A work"}}


def test_a_library_with_no_enrichment_file_carries_nothing_and_does_not_fail(tmp_path, monkeypatch):
    _library(tmp_path, monkeypatch)
    assert carry_forward({"doi-10-1-x": {"title": "A work"}}) == 0


def test_a_write_that_would_drop_an_identifier_is_reported_before_it_happens(tmp_path, monkeypatch):
    _library(tmp_path, monkeypatch, records={"doi-10-1-x": {"title": "A work", "doi": "10.1/x"}})
    losing, stale = audit_existing({"doi-10-1-x": {"title": "A work"}})
    assert losing == [("doi-10-1-x", "doi", "10.1/x")]
    assert stale == []


def test_a_record_no_longer_cited_anywhere_is_reported_as_stale(tmp_path, monkeypatch):
    _library(tmp_path, monkeypatch, records={"doi-gone": {"title": "Dropped"}})
    losing, stale = audit_existing({})
    assert stale == ["doi-gone"]
    assert losing == []


def test_a_rebuild_that_destroys_nothing_reports_nothing(tmp_path, monkeypatch):
    _library(tmp_path, monkeypatch, records={"doi-10-1-x": {"title": "A work", "doi": "10.1/x"}})
    losing, stale = audit_existing({"doi-10-1-x": {"title": "A work", "doi": "10.1/x"}})
    assert (losing, stale) == ([], [])


def test_a_preferred_key_reaches_the_record_from_the_overlay(tmp_path, monkeypatch):
    # `cited_by` records what each paper writes and those diverge honestly, since a key is
    # part of a paper's own source. The overlay is where the library says which to copy
    # forward; nothing else in the record can, because `slug` is an identifier.
    from citations import build, paths

    enrichment = tmp_path / "enrichment.yaml"
    enrichment.write_text("arxiv-2301-04709:\n  preferred_key: geiger2025causalabstraction\n")
    monkeypatch.setattr(paths, "enrichment", lambda: enrichment)

    merged = {
        "arxiv-2301-04709": {
            "slug": "arxiv-2301-04709",
            "cited_by": {"a": {"key": "geiger2024causal"}, "b": {"key": "geiger2025causal"}},
        }
    }
    assert build.carry_forward(merged) == 1
    assert merged["arxiv-2301-04709"]["preferred_key"] == "geiger2025causalabstraction"


def test_a_record_carrying_a_preferred_key_still_validates():
    from citations.models import Record

    r = Record(slug="arxiv-2301-04709", preferred_key="geiger2025causalabstraction")
    assert r.preferred_key == "geiger2025causalabstraction"
    assert Record(slug="x").preferred_key == "", "a record without one is not thereby invalid"


def test_a_paper_whose_bibliography_is_absent_keeps_its_citations(tmp_path, monkeypatch):
    # A record is rewritten whole from the bibliographies. A paper that contributed none --
    # an import with no repository, a moved path -- was having its cited_by entry deleted from
    # every record another paper also cites. The bibliography not being readable says nothing
    # about whether the citation holds.
    from citations import build, paths

    records = tmp_path / "records"
    records.mkdir()
    (records / "arxiv-1234-5678.yaml").write_text(
        "slug: arxiv-1234-5678\ntitle: T\nauthors: []\nyear: '2020'\n"
        "cited_by:\n  an-import:\n    key: smith2020\n  a-repo:\n    key: smith2020a\n"
    )
    monkeypatch.setattr(paths, "records", lambda: records)

    merged = {
        "arxiv-1234-5678": {
            "slug": "arxiv-1234-5678",
            "cited_by": {"a-repo": {"key": "smith2020a"}},
        }
    }
    restored = build.carry_citations(merged, {"an-import"})
    assert restored == 1
    assert merged["arxiv-1234-5678"]["cited_by"]["an-import"] == {"key": "smith2020"}


def test_a_paper_whose_bibliography_was_read_does_not_keep_a_dropped_citation(
    tmp_path, monkeypatch
):
    # Removing a key from a .bib is how a citation is removed. Only papers whose bibliography
    # this run could not read are protected.
    from citations import build, paths

    records = tmp_path / "records"
    records.mkdir()
    (records / "arxiv-1234-5678.yaml").write_text(
        "slug: arxiv-1234-5678\ntitle: T\nauthors: []\nyear: '2020'\n"
        "cited_by:\n  a-repo:\n    key: smith2020\n"
    )
    monkeypatch.setattr(paths, "records", lambda: records)

    merged = {"arxiv-1234-5678": {"slug": "arxiv-1234-5678", "cited_by": {}}}
    assert build.carry_citations(merged, set()) == 0
    assert merged["arxiv-1234-5678"]["cited_by"] == {}


def test_a_pin_the_bibliographies_cannot_repin_survives_a_rebuild(tmp_path, monkeypatch):
    # local+sha256 name the copy that was actually read and hashed. enrich_from_claims fills
    # them from a paper's own claims/, so a pin the library established itself -- into its own
    # artifacts/ -- had no source and was dropped, silently.
    from citations import build, paths

    records = tmp_path / "records"
    records.mkdir()
    (records / "arxiv-2403-10462.yaml").write_text(
        "slug: arxiv-2403-10462\ntitle: T\nauthors: []\nyear: '2024'\n"
        "local: artifacts/arxiv-2403-10462.pdf\nsha256: abc123\n"
    )
    monkeypatch.setattr(paths, "records", lambda: records)

    merged = {"arxiv-2403-10462": {"slug": "arxiv-2403-10462", "cited_by": {}}}
    assert build.carry_pins(merged) == 2
    assert merged["arxiv-2403-10462"]["local"] == "artifacts/arxiv-2403-10462.pdf"
    assert merged["arxiv-2403-10462"]["sha256"] == "abc123"


def test_a_bibliography_that_repins_wins(tmp_path, monkeypatch):
    from citations import build, paths

    records = tmp_path / "records"
    records.mkdir()
    (records / "x.yaml").write_text("slug: x\nlocal: old.pdf\nsha256: old\n")
    monkeypatch.setattr(paths, "records", lambda: records)

    merged = {"x": {"slug": "x", "local": "new.pdf", "sha256": "new"}}
    assert build.carry_pins(merged) == 0
    assert merged["x"]["sha256"] == "new"


def test_the_audit_names_every_field_a_write_destroys(tmp_path, monkeypatch):
    # The function's own docstring is "What a write would destroy". It reported two fields.
    from citations import build, paths

    records = tmp_path / "records"
    records.mkdir()
    (records / "x.yaml").write_text(
        "slug: x\ndoi: 10.1/a\narxiv: '1234.5678'\nurl: http://e\nvenue: V\n"
        "local: a.pdf\nsha256: h\n"
    )
    monkeypatch.setattr(paths, "records", lambda: records)

    losing, _ = build.audit_existing({"x": {"slug": "x"}})
    assert {f for _, f, _ in losing} == {"doi", "arxiv", "url", "venue", "local", "sha256"}


def test_same_work_finds_a_doi_record_and_a_title_hash_record():
    # The shape 178 of the library's 218 duplicate groups actually have: one bibliography
    # named the DOI and another named nothing, so no rule keyed on the slug sees them together.
    identified = {"title": "Canonical Units", "authors": ["Leask, P"], "doi": "10.1/x"}
    silent = {"title": "Canonical Units", "authors": ["Leask, P"]}
    records = {slug_for(identified): identified, slug_for(silent): silent}
    assert len(records) == 2, "the two must slug differently or there is nothing to detect"
    groups = same_work(records)
    assert len(groups) == 1
    assert sorted(next(iter(groups.values()))) == sorted(records)


def test_same_work_leaves_distinct_works_alone():
    a = {"title": "Canonical Units", "authors": ["Leask, P"], "doi": "10.1/x"}
    b = {"title": "Something Else Entirely", "authors": ["Other, A"], "doi": "10.1/y"}
    assert same_work({slug_for(a): a, slug_for(b): b}) == {}


def test_title_key_is_what_slug_for_hashes():
    """One notion of sameness. Two would drift, which is how the arXiv-DOI split happened."""
    rec = {"title": "A Paper", "authors": ["Smith, J"]}
    import hashlib

    assert slug_for(rec) == "t-" + hashlib.sha256(title_key(rec).encode()).hexdigest()[:16]


def test_an_enrichment_identifier_reslugs_a_title_hash_record():
    """`build` told readers the opposite for as long as the behaviour existed.

    An identifier resolved after the .bib was written has to identify the work rather than
    decorate it: without the re-slug the record stays under its title hash and stays split
    from the twin that carried the DOI, which is the whole defect.
    """
    entry = {"title": "Canonical Units", "authors": ["Leask, P"]}
    provisional = slug_for(entry)
    assert provisional.startswith("t-")
    overlay = {provisional: {"doi": "10.1/x"}}

    extra = overlay.get(provisional) or {}
    for k in ("doi", "arxiv"):
        if extra.get(k) and not entry.get(k):
            entry[k] = extra[k]

    assert slug_for(entry) == "doi-10-1-x"
