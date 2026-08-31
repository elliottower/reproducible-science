"""An identifier that is right says nothing about the names written beside it.

On 2026-08-31 two agents attributed "Mediational E-values" to VanderWeele and Chiba while
quoting the paper's own DOI. A VanderWeele and Chiba paper exists, on another subject in another
journal, so the entry was two real papers written as one and every field named something that
exists. The DOI resolved, the link was live, and nothing in the toolchain read the names back.
The first two tests below are that entry, in both spellings.

The payloads are the ones the registries actually return. Nothing here touches the network.
"""

from __future__ import annotations

import json
import pathlib
import urllib.parse

import pytest
import yaml
from citations import lint, services

# --- the incident ------------------------------------------------------------------------------

#: Crossref for 10.1097/EDE.0000000000001064, trimmed to the fields this check reads.
MEDIATIONAL = {
    "message": {
        "DOI": "10.1097/EDE.0000000000001064",
        "title": ["Mediational E-values"],
        "container-title": ["Epidemiology"],
        "volume": "30",
        "page": "835-837",
        "author": [
            {"given": "Louisa H.", "family": "Smith", "sequence": "first"},
            {"given": "Tyler J.", "family": "VanderWeele", "sequence": "additional"},
        ],
    }
}

MEDIATIONAL_DOI = "10.1097/EDE.0000000000001064"

ARXIV_FEED = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>arXiv Query: search_query=&amp;id_list=1706.03762</title>
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <title>Attention Is All You Need</title>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
  </entry>
</feed>
"""


def crossref(*names: tuple[str, str]) -> dict:
    return {"message": {"author": [{"family": f, "given": g} for f, g in names]}}


@pytest.fixture
def registry(monkeypatch):
    """Registry answers, keyed by the identifier they answer for. The network is never reached.

    The stub sits under `resolve.get`, so every payload goes through the reader that reads the
    real thing: a test that stubbed the reader too would establish nothing about the parse.
    """
    answers: dict[str, object] = {}

    def get(url, as_json=True, tries=4, headers=None):
        for identifier, payload in answers.items():
            quoted = urllib.parse.quote(identifier, safe="")
            if identifier in url or quoted in url:
                return payload
        return None

    monkeypatch.setattr(lint.resolve, "get", get)
    monkeypatch.setattr(lint, "DELAY", 0)
    return answers


def entry(key: str, author: str, **fields: str) -> str:
    lines = [f"  author = {{{author}}}"] + [f"  {k} = {{{v}}}" for k, v in fields.items()]
    return "@article{" + key + ",\n" + ",\n".join(lines) + "\n}\n"


def bib(tmp_path, *entries: str) -> pathlib.Path:
    path = tmp_path / "refs.bib"
    path.write_text("\n".join(entries))
    return path


def mediational(tmp_path, author: str) -> pathlib.Path:
    return bib(
        tmp_path,
        entry(
            "smith2019mediational",
            author,
            title="Mediational E-values",
            journal="Epidemiology",
            year="2019",
            doi=MEDIATIONAL_DOI,
        ),
    )


def kinds(report) -> list[str]:
    return [f.kind for f in report.findings]


def test_the_wrong_authors_under_the_right_doi_are_caught(tmp_path, registry):
    registry[MEDIATIONAL_DOI] = MEDIATIONAL
    path = mediational(tmp_path, "VanderWeele, Tyler J. and Chiba, Yasutaka")

    report = lint.check_authors(path)

    assert report.checked == 1, "the DOI resolved; that is what makes this invisible"
    assert kinds(report) == ["wrong", "wrong"]
    assert "Smith" in report.findings[0].detail
    assert "VanderWeele" in report.findings[1].detail


def test_the_same_entry_with_the_real_names_passes(tmp_path, registry):
    registry[MEDIATIONAL_DOI] = MEDIATIONAL
    path = mediational(tmp_path, "Smith, Louisa H. and VanderWeele, Tyler J.")

    report = lint.check_authors(path)

    assert report.checked == 1
    assert report.findings == [], "a check that flags the correct list catches nothing"


def test_the_finding_names_the_entry_and_the_line_it_sits_on(tmp_path, registry):
    registry[MEDIATIONAL_DOI] = MEDIATIONAL
    path = mediational(tmp_path, "VanderWeele, Tyler J. and Chiba, Yasutaka")

    finding = lint.check_authors(path).findings[0]

    assert finding.key == "smith2019mediational"
    assert finding.line == 1
    assert finding.identifier == f"doi:{MEDIATIONAL_DOI}"
    assert finding.registry == "crossref"


# --- a shortened list, which looks exactly like a complete one -----------------------------------


@pytest.mark.parametrize(
    "author",
    [
        "Smith, Louisa H. and others",
        "Smith, Louisa H. and VanderWeele, Tyler J. and others",
        "Smith, Louisa H., et al.",
        "Smith, Louisa H. and VanderWeele, Tyler J. and et al.",
    ],
)
def test_a_shortened_list_marker_is_flagged(tmp_path, registry, author):
    registry[MEDIATIONAL_DOI] = MEDIATIONAL
    report = lint.check_authors(mediational(tmp_path, author))

    assert "marker" in kinds(report), "this project writes every author the registry lists"


def test_a_marked_list_is_not_also_reported_as_dropped(tmp_path, registry):
    registry[MEDIATIONAL_DOI] = MEDIATIONAL
    report = lint.check_authors(mediational(tmp_path, "Smith, Louisa H. and others"))

    assert kinds(report) == ["marker"], "one defect, reported once"


def test_a_list_that_stops_early_with_no_marker_is_flagged(tmp_path, registry):
    registry["10.1234/four"] = crossref(
        ("Smith", "Ann"), ("Jones", "Bo"), ("Patel", "Cara"), ("Wu", "Dan")
    )
    path = bib(tmp_path, entry("four", "Smith, Ann and Jones, Bo", doi="10.1234/four"))

    report = lint.check_authors(path)

    assert kinds(report) == ["dropped"]
    assert "2 names where the registry lists 4" in report.findings[0].detail
    assert "Patel" in report.findings[0].detail, "say which name the list stops before"


def test_a_hundred_name_ceiling_is_what_a_dropped_list_looks_like(tmp_path, registry):
    """OpenAlex caps authorships at 100, which is where real truncations here came from."""
    everyone = [(f"Family{i}", f"Given{i}") for i in range(120)]
    registry["10.1234/many"] = crossref(*everyone)
    written = " and ".join(f"{f}, {g}" for f, g in everyone[:100])
    path = bib(tmp_path, entry("many", written, doi="10.1234/many"))

    report = lint.check_authors(path)

    assert kinds(report) == ["dropped"]
    assert "100 names where the registry lists 120" in report.findings[0].detail


def test_more_names_than_the_registry_lists_is_flagged(tmp_path, registry):
    registry["10.1234/one"] = crossref(("Smith", "Ann"))
    path = bib(tmp_path, entry("one", "Smith, Ann and Jones, Bo", doi="10.1234/one"))

    assert kinds(lint.check_authors(path)) == ["extra"]


# --- order, which position by position looks like every author being wrong ----------------------


def test_the_same_names_in_another_sequence_are_reported_as_an_order_problem(tmp_path, registry):
    registry[MEDIATIONAL_DOI] = MEDIATIONAL
    path = mediational(tmp_path, "VanderWeele, Tyler J. and Smith, Louisa H.")

    report = lint.check_authors(path)

    assert kinds(report) == ["order"]
    assert "Smith" in report.findings[0].detail


def test_a_wrong_name_is_not_reported_as_an_order_problem(tmp_path, registry):
    registry[MEDIATIONAL_DOI] = MEDIATIONAL
    path = mediational(tmp_path, "Chiba, Yasutaka and Smith, Louisa H.")

    assert "order" not in kinds(lint.check_authors(path))


# --- what must not be flagged, or the check stops being believed --------------------------------


def test_a_diacritic_is_not_a_disagreement(tmp_path, registry):
    registry["10.1234/rna"] = crossref(("Krzyżosiak", "Włodzimierz J."), ("Kozłowski", "Piotr"))
    path = bib(
        tmp_path,
        entry("rna", "Krzyzosiak, Wlodzimierz J. and Kozlowski, Piotr", doi="10.1234/rna"),
    )

    assert lint.check_authors(path).findings == []


def test_both_spellings_of_an_umlaut_are_one_name(tmp_path, registry):
    registry["10.1234/umlaut"] = crossref(("Hölscher-Obermaier", "Jason"))
    for written in ("Holscher-Obermaier, Jason", "Hoelscher-Obermaier, Jason"):
        path = bib(tmp_path, entry("umlaut", written, doi="10.1234/umlaut"))
        assert lint.check_authors(path).findings == [], written


def test_a_particle_the_registry_files_under_the_surname_is_not_a_disagreement(tmp_path, registry):
    # OpenAlex indexes "de Mezer" under Mezer. Both spell one name.
    registry["10.1234/particle"] = crossref(("Mezer", "Anna"))
    for written in ("de Mezer, Anna", "Mezer, Anna", "Anna de Mezer"):
        path = bib(tmp_path, entry("particle", written, doi="10.1234/particle"))
        assert lint.check_authors(path).findings == [], written


def test_a_particle_the_registry_keeps_is_not_a_disagreement(tmp_path, registry):
    registry["10.1234/kept"] = crossref(("van der Waals", "Johannes"))
    path = bib(tmp_path, entry("kept", "Waals, Johannes van der", doi="10.1234/kept"))

    assert lint.check_authors(path).findings == []


def test_a_generational_suffix_is_not_a_disagreement(tmp_path, registry):
    registry["10.1234/suffix"] = crossref(("White", "Charles L."))
    path = bib(tmp_path, entry("suffix", "White III, Charles L.", doi="10.1234/suffix"))

    assert lint.check_authors(path).findings == []


def test_a_bibtex_accent_matches_the_unicode_it_encodes(tmp_path, registry):
    registry["10.1234/accent"] = crossref(("Munafò", "Marcus"), ("Gonçalves", "Ana"))
    path = bib(
        tmp_path,
        entry("accent", "Munaf{\\'o}, Marcus and Gon{\\c{c}}alves, Ana", doi="10.1234/accent"),
    )

    assert lint.check_authors(path).findings == []


def test_a_different_person_with_the_same_particle_is_still_caught(tmp_path, registry):
    """The tolerances above must not cost the check its ability to fail."""
    registry["10.1234/other"] = crossref(("Mezer", "Anna"))
    path = bib(tmp_path, entry("other", "de Vries, Anna", doi="10.1234/other"))

    assert kinds(lint.check_authors(path)) == ["wrong"]


def test_only_family_names_are_compared(tmp_path, registry):
    """A given name that disagrees is `citations audit`'s question; this one is the surname
    sequence, which is what the incident got wrong."""
    registry["10.1234/given"] = crossref(("Smith", "Louisa H."))
    path = bib(tmp_path, entry("given", "Smith, Marta", doi="10.1234/given"))

    assert lint.check_authors(path).findings == []


# --- entries nothing can check ------------------------------------------------------------------


def test_an_entry_with_no_identifier_is_skipped_and_counted(tmp_path, registry):
    path = bib(tmp_path, entry("rothman2008", "Rothman, Kenneth J.", title="Modern Epidemiology"))

    report = lint.check_authors(path)

    assert (report.entries, report.checked, report.skipped) == (1, 0, 0 + 1)
    assert report.findings == [], "nothing examined it, so it is neither clean nor dirty"


def test_the_skipped_count_is_printed(tmp_path, registry, capsys):
    path = bib(tmp_path, entry("rothman2008", "Rothman, Kenneth J."))

    assert lint.author_lists([path], as_json=False) == 0
    assert "1 with no identifier" in capsys.readouterr().out


def test_an_identifier_no_registry_answers_for_is_not_reported_as_agreement(tmp_path, registry):
    path = bib(tmp_path, entry("gone", "Nobody, N", doi="10.1234/gone"))

    report = lint.check_authors(path)

    assert (report.checked, report.unresolved) == (0, 1)
    assert report.findings == []


def test_an_unresolved_entry_says_nothing_was_measured(tmp_path, registry, capsys):
    path = bib(tmp_path, entry("gone", "Nobody, N", doi="10.1234/gone"))

    lint.author_lists([path], as_json=False)

    assert "did not fetch" in capsys.readouterr().out


# --- identifiers, in the several ways a .bib writes them -----------------------------------------


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"doi": "10.1097/EDE.0000000000001064"}, ("doi", "10.1097/EDE.0000000000001064")),
        ({"doi": "https://doi.org/10.1145/3287560"}, ("doi", "10.1145/3287560")),
        ({"doi": "10.48550/arXiv.1706.03762"}, ("arxiv", "1706.03762")),
        ({"eprint": "1706.03762", "archiveprefix": "arXiv"}, ("arxiv", "1706.03762")),
        ({"eprint": "arXiv:1706.03762v3"}, ("arxiv", "1706.03762")),
        ({"url": "https://arxiv.org/abs/1706.03762v7"}, ("arxiv", "1706.03762")),
        ({"title": "no identifier at all"}, ("", "")),
    ],
)
def test_the_identifier_is_read_out_of_the_field_that_carries_it(fields, expected):
    assert lint.identifier_of(fields) == expected


def test_an_arxiv_id_is_checked_against_arxiv(tmp_path, registry):
    registry["1706.03762"] = ARXIV_FEED
    path = bib(
        tmp_path,
        entry("vaswani2017", "Vaswani, Ashish and Shazeer, Noam", eprint="1706.03762"),
    )

    report = lint.check_authors(path)

    assert (report.checked, report.findings) == (1, [])


def test_an_arxiv_id_with_the_wrong_names_is_caught(tmp_path, registry):
    registry["1706.03762"] = ARXIV_FEED
    path = bib(tmp_path, entry("vaswani2017", "Smith, Ann and Jones, Bo", eprint="1706.03762"))

    assert kinds(lint.check_authors(path)) == ["wrong", "wrong"]


# --- the cache, which is what lets this run in a hook --------------------------------------------


def test_a_second_run_needs_no_network(tmp_path, registry, monkeypatch):
    registry[MEDIATIONAL_DOI] = MEDIATIONAL
    path = mediational(tmp_path, "VanderWeele, Tyler J. and Chiba, Yasutaka")
    lint.check_authors(path)

    def refuse(*a, **kw):
        raise AssertionError("went to the network with a resolved list already cached")

    monkeypatch.setattr(lint.resolve, "get", refuse)
    again = lint.check_authors(path)

    assert (again.checked, kinds(again)) == (1, ["wrong", "wrong"])


def test_the_cache_lands_beside_the_bibliography_and_names_who_answered(tmp_path, registry):
    registry[MEDIATIONAL_DOI] = MEDIATIONAL
    path = mediational(tmp_path, "Smith, Louisa H. and VanderWeele, Tyler J.")
    lint.check_authors(path)

    stored = yaml.safe_load((tmp_path / lint.CACHE_NAME).read_text())

    assert stored[f"doi:{MEDIATIONAL_DOI}"]["source"] == "crossref"
    assert stored[f"doi:{MEDIATIONAL_DOI}"]["authors"] == [
        "Smith, Louisa H.",
        "VanderWeele, Tyler J.",
    ]


def test_the_cache_is_written_before_the_run_ends(tmp_path, registry):
    """A run killed halfway keeps what it resolved, the way `resolve` writes enrichment.yaml."""
    registry["10.1234/first"] = crossref(("Smith", "Ann"))
    written: list[str] = []

    class Boom(Exception):
        pass

    path = bib(
        tmp_path,
        entry("first", "Smith, Ann", doi="10.1234/first"),
        entry("second", "Jones, Bo", doi="10.1234/second"),
    )
    original = lint.save_cache

    def watch(cache_path, cache):
        written.append(str(cache_path))
        original(cache_path, cache)

    lint.save_cache = watch
    try:
        lint.check_authors(path)
    finally:
        lint.save_cache = original

    assert written, "nothing was persisted until the whole file had been walked"
    assert yaml.safe_load((tmp_path / lint.CACHE_NAME).read_text())["doi:10.1234/first"]


# --- exit codes ----------------------------------------------------------------------------------


def test_findings_exit_nonzero(tmp_path, registry):
    registry[MEDIATIONAL_DOI] = MEDIATIONAL
    path = mediational(tmp_path, "VanderWeele, Tyler J. and Chiba, Yasutaka")

    assert lint.main(["--authors", str(path)]) == 1


def test_findings_exit_nonzero_under_json_too(tmp_path, registry, capsys):
    # A machine-readable mode that prints findings and exits 0 is a check that cannot fail.
    registry[MEDIATIONAL_DOI] = MEDIATIONAL
    path = mediational(tmp_path, "VanderWeele, Tyler J. and Chiba, Yasutaka")

    assert lint.main(["--authors", str(path), "--json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["checked"] == 1
    assert payload[0]["skipped"] == 0
    assert [f["kind"] for f in payload[0]["findings"]] == ["wrong", "wrong"]


def test_a_clean_file_exits_zero(tmp_path, registry):
    # The negative half: an --authors mode hardwired to fail would pass the test above.
    registry[MEDIATIONAL_DOI] = MEDIATIONAL
    path = mediational(tmp_path, "Smith, Louisa H. and VanderWeele, Tyler J.")

    assert lint.main(["--authors", str(path)]) == 0
    assert lint.main(["--authors", str(path), "--json"]) == 0


def test_authors_consults_neither_papis_nor_a_library(tmp_path, registry, monkeypatch):
    monkeypatch.setattr(lint, "find_papis", lambda: pytest.fail("--authors must not need papis"))
    monkeypatch.setenv("CITATIONS_HOME", str(tmp_path / "nowhere"))
    registry[MEDIATIONAL_DOI] = MEDIATIONAL

    assert lint.main(["--authors", str(mediational(tmp_path, "Smith, Louisa H."))]) == 1


def test_both_bib_modes_run_and_either_can_fail(tmp_path, registry):
    registry[MEDIATIONAL_DOI] = MEDIATIONAL
    clean = mediational(tmp_path, "Smith, Louisa H. and VanderWeele, Tyler J.")
    repeated = tmp_path / "dup.bib"
    repeated.write_text(entry("k", "Alpha, Ann") + "\n" + entry("k", "Alpha, Ann"))

    assert lint.main(["--bib", str(repeated), "--authors", str(clean)]) == 1


def test_asking_for_both_bib_modes_as_json_is_refused(tmp_path, registry, capsys):
    # Two documents printed back to back are not a JSON document.
    path = mediational(tmp_path, "Smith, Louisa H.")

    assert lint.main(["--bib", str(path), "--authors", str(path), "--json"]) == 2
    assert "not both" in capsys.readouterr().out


def test_a_missing_file_is_an_error_rather_than_an_empty_pass(tmp_path):
    with pytest.raises(lint.CitationsError):
        lint.check_authors(tmp_path / "absent.bib")


# --- the payload readers --------------------------------------------------------------------------


def test_the_crossref_reader_keeps_publication_order():
    assert services._crossref_work_authors(MEDIATIONAL) == [
        "Smith, Louisa H.",
        "VanderWeele, Tyler J.",
    ]


def test_a_consortium_deposited_without_a_family_name_still_counts_as_an_author():
    # Dropping it shortens the registry's list by one, which reports the bibliography as
    # carrying a name too many -- the opposite of what is wrong with it.
    payload = {
        "message": {
            "author": [
                {"family": "Smith", "given": "Ann"},
                {"name": "The GTEx Consortium"},
            ]
        }
    }
    assert services._crossref_work_authors(payload) == ["Smith, Ann", "The GTEx Consortium"]


def test_the_openalex_reader_keeps_publication_order():
    payload = {
        "authorships": [
            {"author": {"display_name": "Louisa H. Smith"}},
            {"author": {"display_name": "Tyler J. VanderWeele"}},
        ]
    }
    assert services._openalex_work_authors(payload) == ["Louisa H. Smith", "Tyler J. VanderWeele"]


def test_the_arxiv_reader_takes_the_names_off_the_one_entry():
    assert services._arxiv_work_authors(ARXIV_FEED) == ["Ashish Vaswani", "Noam Shazeer"]


def test_the_arxiv_reader_refuses_a_feed_that_is_not_one_work():
    # id_list names one work. A feed carrying none is arXiv's error document and one carrying
    # several answers a query this did not make; either would compare against the wrong paper.
    assert services._arxiv_work_authors("<feed></feed>") == []
    assert services._arxiv_work_authors(ARXIV_FEED + ARXIV_FEED) == []


def test_an_empty_payload_is_answered_as_nothing_rather_than_as_no_authors():
    assert services._crossref_work_authors({}) == []
    assert services._openalex_work_authors({}) == []
    assert services._arxiv_work_authors("") == []


def test_each_registry_is_asked_only_about_identifiers_it_issues():
    by_name = {r.name: r for r in services.REGISTRIES}
    assert by_name["crossref"].kinds == ("doi",)
    assert by_name["arxiv"].kinds == ("arxiv",)
    assert set(by_name["openalex"].kinds) == {"doi", "arxiv"}
    # The issuing body before the aggregator, for each kind.
    order = [r.name for r in services.REGISTRIES]
    assert order.index("crossref") < order.index("openalex")
    assert order.index("arxiv") < order.index("openalex")
