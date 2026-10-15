"""A real paper cited at the wrong venue passed every check `audit` made.

The venue is compared by identifier. The record's venue is the ISSNs and source ids its
registries give it; the entry's venue name is resolved to the same kinds of identifier through
registries that index venue names and abbreviations. Only an identifier comparison may say
match or mismatch, and a mismatch needs serial identifiers (ISSN, NLM, DBLP) on both sides.
Everything else is not comparable, with both names shown.

The fixture tests audit real, correctly cited references offline, against the registry answers
fetched for them once; the cached bodies are trimmed to the fields read and re-enveloped.
"""

from __future__ import annotations

import json
import pathlib
import urllib.parse

import pytest
from citations import audit as A
from citations import venue as V
from citations import venue_registry as R
from citations.services import crossref_venue_ids, openalex_venue_ids

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "audit_venue"


def res(*ids, status="resolved", direct=False, **kw) -> V.Resolution:
    return V.Resolution(status=status, ids=frozenset(ids), direct=direct, **kw)


NATURE = res("issn:0028-0836", "issn:1476-4687", "wikidata:Q180445", label="Nature")
NAT_COMMUN = res("issn:2041-1723", "wikidata:Q573880", label="Nature Communications", direct=True)


# --- the decision ------------------------------------------------------------------------


def test_a_shared_identifier_is_a_match():
    check = V.decide("Nat. Commun.", "Nature Communications", NAT_COMMUN, NAT_COMMUN)
    assert check.outcome == V.MATCH
    assert check.why.startswith("shared identifier")


def test_disjoint_serial_identifiers_on_a_direct_record_are_a_mismatch_naming_both():
    check = V.decide("Nature", "Nature Communications", NATURE, NAT_COMMUN)
    assert check.outcome == V.MISMATCH
    assert (check.ours_registry, check.theirs_registry) == ("Nature", "Nature Communications")
    assert check.line() == "venue: ours 'Nature' vs registry 'Nature Communications'"


def test_a_record_identified_only_by_its_name_is_never_a_mismatch():
    indirect = NAT_COMMUN.model_copy(update={"direct": False})
    check = V.decide("Nature", "Nature Communications", NATURE, indirect)
    assert (check.outcome, check.why) == (V.NOT_COMPARABLE, V.INDIRECT)


def test_two_registry_records_of_one_journal_name_are_not_called_different():
    # Gödel 1931: the entry's name resolves to Wikidata's historical record of the journal,
    # Crossref's ISSN to the continuing one, and both are filed under the same title.
    name = V.folded_names(["Monatshefte für Mathematik und Physik"])
    entry = res("issn:1812-8076", "wikidata:Q96716169", names=name)
    record = res("issn:0026-9255", "wikidata:Q1944084", names=name, direct=True)
    check = V.decide(
        'Monatshefte f{\\"u}r Mathematik und Physik',
        "Monatshefte für Mathematik und Physik",
        entry,
        record,
    )
    assert check.outcome == V.NOT_COMPARABLE
    assert check.why.startswith(V.ONE_NAME)


def test_a_record_found_by_title_search_can_confirm_and_never_contradict():
    # Krizhevsky 2012: a title search reached the 2017 reprint in Communications of the ACM.
    reprint = res(
        "issn:0001-0782",
        "dblp:journals/cacm",
        direct=True,
        searched=True,
        label="Communications of the ACM",
    )
    neurips = res("issn:1049-5258", label="Advances in Neural Information Processing Systems")
    check = V.decide("NeurIPS", "Communications of the ACM", neurips, reprint)
    assert (check.outcome, check.why) == (V.NOT_COMPARABLE, V.SEARCHED)
    assert V.decide("CACM", "Communications of the ACM", reprint, reprint).outcome == V.MATCH


def test_wikidata_or_openalex_ids_alone_never_make_a_mismatch():
    # Either can be one edition of a conference, or one of several records of one journal.
    entry = res("wikidata:Q1", "openalex:S1")
    record = res("wikidata:Q2", "openalex:S2", direct=True)
    check = V.decide("A", "B", entry, record)
    assert (check.outcome, check.why) == (V.NOT_COMPARABLE, V.NO_COMMON_KIND)


@pytest.mark.parametrize(
    "status,why",
    [("unresolved", V.UNRESOLVED), ("ambiguous", V.AMBIGUOUS), ("refused", V.REFUSED)],
)
def test_an_entry_venue_that_did_not_resolve_is_not_comparable(status, why):
    entry = V.Resolution(status=status)
    check = V.decide("Proc. Somewhere", "Nature Communications", entry, NAT_COMMUN)
    assert check.outcome == V.NOT_COMPARABLE
    assert check.why.startswith(why)


def test_a_refused_record_lookup_is_not_comparable():
    record = NAT_COMMUN.model_copy(update={"status": "refused"})
    check = V.decide("Nature", "Nature Communications", NATURE, record)
    assert (check.outcome, check.why) == (V.NOT_COMPARABLE, V.REFUSED)


def test_an_ambiguous_name_matches_through_whichever_venue_the_record_is():
    options = [
        res("issn:2213-2244", label="Developmental Cell"),
        res("issn:0092-8674", label="Cell"),
    ]
    entry = V.Resolution(
        status="ambiguous", options=options, candidates=["Cell", "Developmental Cell"]
    )
    record = res("issn:0092-8674", direct=True, label="Cell")
    assert V.decide("Cell", "Cell", entry, record).outcome == V.MATCH
    other = res("issn:1097-4164", direct=True, label="Molecular Cell")
    assert V.decide("Cell", "Molecular Cell", entry, other).outcome == V.NOT_COMPARABLE


def test_a_link_is_followed_one_hop_and_siblings_stay_apart():
    parent = "wikidata:Q100"
    a = res("issn:1111-1111", "wikidata:Q1", links=frozenset({parent}))
    b = res("issn:2222-2222", "wikidata:Q2", links=frozenset({parent}), direct=True)
    assert V.decide("Phys. Rev. A", "Physical Review B", a, b).outcome == V.MISMATCH
    successor = res("issn:3333-3333", "wikidata:Q3", links=frozenset({"wikidata:Q1"}), direct=True)
    assert V.decide("Old title", "New title", a, successor).outcome == V.MATCH


def test_two_editions_of_one_conference_series_are_one_venue():
    series = frozenset({"wikidata:Q47"})
    entry = res("wikidata:Q2013", series=series)
    record = res("wikidata:Q2019", "openalex:S2019", series=series, direct=True)
    assert V.decide("NAACL 2013", "NAACL 2019", entry, record).outcome == V.MATCH


def test_preprints_workshops_garbled_names_and_missing_venues_are_not_comparable():
    preprint = res("issn:2331-8422", direct=True, repository=True, label="arXiv")
    assert V.decide("NeurIPS", "arXiv", NATURE, preprint).why == V.PREPRINT
    server = NATURE.model_copy(update={"repository": True})
    assert V.decide("arXiv", "Nature", server, NAT_COMMUN).why == V.ENTRY_PREPRINT
    assert V.decide("CVPR", "CVPR Workshops", NATURE, NAT_COMMUN).why == V.WORKSHOP
    assert V.decide("Z. f�r Physik", "Z. Phys.", NATURE, NAT_COMMUN).why == V.GARBLED_NAME
    assert V.decide("", "Nature", NATURE, NAT_COMMUN).why == V.NO_ENTRY_VENUE
    assert V.decide("Nature", "", NATURE, res(direct=True)).why == V.NO_RECORD_VENUE


def test_not_comparable_names_both_venues_for_a_person_to_read():
    check = V.decide(
        "Comput. Netw.", "Computer Networks", V.Resolution(status="unresolved"), NAT_COMMUN
    )
    assert check.line() == (
        "venue: ours 'Comput. Netw.' / registry 'Computer Networks' "
        f"(not comparable: {V.UNRESOLVED})"
    )


# --- normalization picks candidates and nothing else ------------------------------------------


@pytest.mark.parametrize(
    "cited,registry",
    [
        ('Zeitschrift f{\\"u}r Physik', "Zeitschrift für Physik"),
        ("The Annals of Statistics", "Annals of Statistics"),
        (
            "Proceedings of the 38th International Conference on Machine Learning",
            "Proceedings of the International Conference on Machine Learning",
        ),
        ("Ｎａｔｕｒｅ", "Nature"),
    ],
)
def test_generic_normalization_folds_markup_case_numbers_and_function_words(cited, registry):
    assert V.same_name(cited, [registry])


def test_normalization_never_equates_two_different_titles():
    assert not V.same_name("Nature", ["Nature Communications"])
    assert not V.same_name("Nat. Commun.", ["Nature Communications"])


# --- resolving a name through registries ------------------------------------------------------


def _claim(value):
    v = {"id": value} if value.startswith("Q") else value
    return [{"mainsnak": {"datavalue": {"value": v}}}]


def _item(label, aliases=(), **claims):
    return {
        "labels": {"en": {"value": label}},
        "aliases": {"en": [{"value": a} for a in aliases]},
        "claims": {p: _claim(v) for p, v in claims.items()},
    }


class Registries:
    """Answers `venue_registry` lookups from dicts, as a cache would."""

    def __init__(self, search=None, iso4=None, entities=None, by_ids=None, sources=None, refuse=()):
        self.search = search or {}
        self.iso4 = iso4 or {}
        self.entities = entities or {}
        self.by_ids = by_ids or []
        self.sources = sources or {}
        self.refuse = set(refuse)
        self.asked: list[str] = []

    def __call__(self, url: str, name: str):
        self.asked.append(url)
        parts = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(parts.query))
        host = parts.hostname or ""
        if host in self.refuse:
            return None
        if host == "www.wikidata.org":
            if q.get("action") == "wbsearchentities":
                return {"search": [{"id": i} for i in self.search.get(q["search"], [])]}
            if q.get("action") == "query":
                term = q["srsearch"]
                hits = self.iso4.get(term, []) if "P1160" in term else self.by_ids
                return {"query": {"search": [{"title": t} for t in hits]}}
            ids = q["ids"].split("|")
            return {"entities": {i: self.entities[i] for i in ids if i in self.entities}}
        if parts.path == "/sources":
            return {"results": self.sources.get(q["search"], [])}
        return {}


def test_a_name_resolves_to_the_one_venue_whose_registry_names_include_it():
    reg = Registries(
        search={"Nat. Commun.": ["Q573880", "Q87"]},
        entities={
            "Q573880": _item(
                "Nature Communications", ["Nat. Commun."], P236="2041-1723", P10283="S64187185"
            ),
            # A namesake with no venue identifier is not a venue: a person, a file format.
            "Q87": _item("Nat. Commun.", ["Nat. Commun."]),
        },
    )
    got = R.resolve_name(reg, "Nat. Commun.")
    assert got.status == "resolved"
    assert {"issn:2041-1723", "openalex:S64187185", "wikidata:Q573880"} <= got.ids


def test_an_openalex_topic_id_on_wikidata_is_not_a_venue_id():
    reg = Registries(
        search={"Nature": ["Q180445", "Q1207505"]},
        entities={
            "Q180445": _item("Nature", P236="0028-0836"),
            "Q1207505": _item("quality", ["nature"], P10283="T10001"),
        },
    )
    assert R.resolve_name(reg, "Nature").status == "resolved"


def test_a_conference_and_its_proceedings_series_are_one_venue():
    reg = Registries(
        search={"NeurIPS": ["Q1961016", "Q15767446"]},
        entities={
            "Q1961016": _item(
                "Conference on Neural Information Processing Systems",
                ["NeurIPS"],
                P8926="conf/nips",
            ),
            "Q15767446": _item(
                "Advances in Neural Information Processing Systems",
                ["NeurIPS"],
                P236="1049-5258",
                P4745="Q1961016",
            ),
        },
    )
    got = R.resolve_name(reg, "NeurIPS")
    assert got.status == "resolved"
    assert {"dblp:conf/nips", "issn:1049-5258"} <= got.ids


def test_an_iso4_abbreviation_is_found_by_its_statement():
    reg = Registries(
        iso4={'haswbstatement:"P1160=Comput. Netw."': ["Q5157456"]},
        entities={"Q5157456": _item("Computer Networks", P1160="Comput. Netw.", P236="1389-1286")},
    )
    assert "issn:1389-1286" in R.resolve_name(reg, "Comput. Netw.").ids


def test_two_unrelated_venues_of_one_name_are_ambiguous_and_keep_both():
    reg = Registries(
        search={"ICLR": ["Q1", "Q2"]},
        entities={
            "Q1": _item(
                "International Conference on Learning Representations", ["ICLR"], P8926="conf/iclr"
            ),
            "Q2": _item("International Cybersecurity Law Review", ["ICLR"], P236="2662-9720"),
        },
    )
    got = R.resolve_name(reg, "ICLR")
    assert got.status == "ambiguous"
    assert len(got.options) == 2


def test_the_name_as_cited_is_tried_before_the_acronym_inside_it():
    full = "International Conference on Learning Representations (ICLR)"
    reg = Registries(
        search={
            full: ["Q1"],
            "International Conference on Learning Representations": ["Q1"],
            "ICLR": ["Q1", "Q2"],
        },
        entities={
            "Q1": _item(
                "International Conference on Learning Representations", ["ICLR"], P8926="conf/iclr"
            ),
            "Q2": _item("International Cybersecurity Law Review", ["ICLR"], P236="2662-9720"),
        },
    )
    got = R.resolve_name(reg, full)
    assert (got.status, got.label) == (
        "resolved",
        "International Conference on Learning Representations",
    )


def test_a_refused_lookup_is_a_resolution_that_failed_not_one_that_found_nothing():
    reg = Registries(refuse={"www.wikidata.org"})
    assert R.resolve_name(reg, "Nature").status == "refused"


def test_an_issn_in_the_entry_is_used_without_a_name_lookup():
    reg = Registries(by_ids=["Q180445"], entities={"Q180445": _item("Nature", P236="0028-0836")})
    got = R.resolve_name(reg, "Some Name", issn="0028-0836")
    assert "issn:0028-0836" in got.ids
    assert not any("wbsearchentities" in u for u in reg.asked)


def test_a_book_series_issn_only_links_and_never_identifies_the_venue():
    reg = Registries(
        by_ids=["Q1"], entities={"Q1": _item("Lecture Notes in Computer Science", P236="0302-9743")}
    )
    got = R.identify(reg, frozenset(), frozenset({"issn:0302-9743"}))
    assert not got.ids
    assert "issn:0302-9743" in got.links


def test_a_venue_is_typed_as_a_repository_only_when_asked_and_a_refusal_unsettles_it():
    arxiv = res("openalex:S4306400194", "issn:2331-8422", label="arXiv")
    reg = Registries()
    reg.sources = {}

    def ask(url, name):
        if urllib.parse.urlsplit(url).path.endswith("/S4306400194"):
            return {
                "id": "https://openalex.org/S4306400194",
                "type": "repository",
                "display_name": "arXiv",
            }
        return reg(url, name)

    assert R.typed(ask, arxiv).repository
    refused = R.typed(lambda url, name: None, arxiv)
    assert refused.status == "refused"


def test_crossref_issns_name_a_journal_for_an_article_and_a_series_for_a_chapter():
    article = {"type": "journal-article", "ISSN": ["2041-1723"]}
    chapter = {"type": "book-chapter", "ISSN": ["0302-9743", "1611-3349"]}
    assert crossref_venue_ids(article) == (["issn:2041-1723"], [])
    assert crossref_venue_ids(chapter) == ([], ["issn:0302-9743", "issn:1611-3349"])
    lncs = {
        "primary_location": {
            "source": {
                "id": "https://openalex.org/S106296714",
                "issn_l": "0302-9743",
                "type": "book series",
            }
        }
    }
    assert openalex_venue_ids(lncs) == ([], ["openalex:S106296714", "issn:0302-9743"])


# --- in an audit -----------------------------------------------------------------------------


def record(**kw) -> A.RegistryRecord:
    return A.RegistryRecord(source="crossref", **kw)


def _registries(monkeypatch, entry: V.Resolution, theirs: V.Resolution | None = None):
    monkeypatch.setattr(A, "resolve_name", lambda ask, name, issn="": entry)
    if theirs is not None:
        monkeypatch.setattr(
            A, "identify", lambda ask, ids, series=frozenset(), label="", repository=False: theirs
        )


def test_a_venue_mismatch_fails_the_audit_like_a_wrong_year(tmp_path, monkeypatch, capsys):
    rec = record(
        title="T",
        years=["2020"],
        venue="Nature Communications",
        venues=["Nature Communications"],
        venue_kind="journal",
        venue_ids=["issn:2041-1723"],
    )
    monkeypatch.setattr(A, "from_crossref", lambda doi, cache: rec)
    _registries(monkeypatch, NATURE, NAT_COMMUN)
    entry = A.Entry(key="k", title="T", year="2020", venue="Nature", doi="10.1038/x")

    report = A.audit([entry], tmp_path / "cache")

    assert report.entries["k"].status == "mismatch"
    assert A.render(report, quiet=False) == 1
    out = capsys.readouterr().out
    assert "venue: ours 'Nature' vs registry 'Nature Communications'" in out


def test_a_venue_not_compared_is_printed_with_both_names(tmp_path, monkeypatch, capsys):
    rec = record(
        title="T",
        venue="Computer Networks",
        venues=["Computer Networks"],
        venue_ids=["issn:1389-1286"],
        venue_kind="journal",
    )
    monkeypatch.setattr(A, "from_crossref", lambda doi, cache: rec)
    _registries(
        monkeypatch,
        V.Resolution(status="refused"),
        res("issn:1389-1286", direct=True, label="Computer Networks"),
    )
    entry = A.Entry(key="k", title="T", venue="Comput. Netw.", doi="10.1016/x")

    report = A.audit([entry], tmp_path / "cache")

    verdict = report.entries["k"]
    assert verdict.venue is not None
    assert (verdict.status, verdict.venue.outcome) == ("ok", V.NOT_COMPARABLE)
    assert A.render(report, quiet=False) == 0
    assert "venue: ours 'Comput. Netw.' / registry 'Computer Networks'" in capsys.readouterr().out


def test_a_preprint_record_found_through_a_preprint_search_answer_is_not_compared(
    tmp_path, monkeypatch
):
    # The answer that found the arXiv id carried arXiv's own source ids, which once read as
    # the venue of a NeurIPS paper and made a mismatch.
    arxiv = A.RegistryRecord(
        source="datacite",
        title="Language Models are Few-Shot Learners",
        years=["2020"],
        venue="arXiv",
        venues=["arXiv"],
        venue_kind="preprint",
    )
    monkeypatch.setattr(A, "from_datacite", lambda doi, cache: arxiv)
    found = A.Candidate(
        title="Language Models are Few-Shot Learners",
        surnames=frozenset({"brown"}),
        year=2020,
        venue="arXiv",
        venues=("arXiv",),
        venue_kind="preprint",
        venue_ids=("openalex:S4306400194", "issn:2331-8422"),
        identifier=("arxiv", "2005.14165"),
    )
    monkeypatch.setattr(A, "find", lambda e, cache: (found, "openalex", ["openalex"], []))
    _registries(monkeypatch, res("issn:1049-5258", label="NeurIPS"))
    entry = A.Entry(
        key="k",
        title="Language Models are Few-Shot Learners",
        authors=["Brown, Tom B."],
        year="2020",
        venue="Advances in Neural Information Processing Systems",
    )

    verdict = A.audit([entry], tmp_path / "cache").entries["k"]

    assert verdict.venue is not None
    assert (verdict.venue.outcome, verdict.venue.why) == (V.NOT_COMPARABLE, V.PREPRINT)


def test_an_entry_series_is_compared_only_when_it_names_no_venue(tmp_path, monkeypatch):
    rec = record(
        title="T",
        venue="Lecture Notes in Computer Science",
        venues=["Lecture Notes in Computer Science"],
        venue_ids=["issn:0302-9743"],
    )
    monkeypatch.setattr(A, "from_crossref", lambda doi, cache: rec)
    asked = []

    def resolve(ask, name, issn=""):
        asked.append(name)
        return V.Resolution(status="unresolved")

    monkeypatch.setattr(A, "resolve_name", resolve)
    monkeypatch.setattr(A, "identify", lambda *a, **k: res("issn:0302-9743", direct=True))
    entries = [
        A.Entry(key="a", title="T", venue="MICCAI 2016", series="LNCS", doi="10.1007/x"),
        A.Entry(key="b", title="T", series="LNCS", doi="10.1007/y"),
    ]
    A.audit(entries, tmp_path / "cache")
    assert asked == ["MICCAI 2016", "LNCS"]


def test_a_bib_entry_s_venue_fields_are_read(tmp_path):
    f = tmp_path / "refs.bib"
    f.write_text(
        "@article{j, title = {A}, journal = {Nature}, issn = {0028-0836}}\n"
        "@inproceedings{c, title = {B}, booktitle = {Proceedings of ICML},"
        " series = {Proceedings of Machine Learning Research}}\n"
    )
    got = {e.key: (e.venue, e.venue_kind, e.series, e.issn) for e in A.entries_from_bib(f)}
    assert got == {
        "j": ("Nature", "journal", "", "0028-0836"),
        "c": ("Proceedings of ICML", "proceedings", "Proceedings of Machine Learning Research", ""),
    }


def test_a_wikidata_request_says_where_it_comes_from_and_carries_no_address(tmp_path, monkeypatch):
    sent = {}

    def get(url, as_json, tries=4, headers=None):
        sent[urllib.parse.urlsplit(url).hostname] = headers
        return "{}"

    monkeypatch.setattr(A.resolve, "get", get)
    monkeypatch.setattr(A.time, "sleep", lambda _: None)
    ask = A.asker(tmp_path / "cache")
    ask("https://www.wikidata.org/w/api.php?action=wbsearchentities&search=x", "w.json")
    ask("https://api.openalex.org/sources?search=x", "o.json")
    assert sent["www.wikidata.org"] == {"User-Agent": A.WIKIDATA_AGENT}
    assert "@" not in A.WIKIDATA_AGENT
    assert sent["api.openalex.org"] is None


# --- precision on real references, offline ---------------------------------------------------


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
    assert len(entries) >= 60

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


PAIRS = json.loads((FIXTURE / "journal_pairs.json").read_text())


def _pair(a: str, b: str) -> V.VenueCheck:
    ask = A.asker(FIXTURE / "pairs_cache")
    return V.decide(a, b, R.resolve_name(ask, a), R.resolve_name(ask, b))


def test_journal_pairs_resolve_offline_as_recorded_and_none_is_a_mismatch(monkeypatch):
    _offline(monkeypatch)
    got = {}
    for group in ("same_journal", "german_same", "german_distinct", "new_fields"):
        for a, b in PAIRS[group]:
            got[f"{group}: {a} || {b}"] = _pair(a, b).outcome
    recorded = json.loads((FIXTURE / "journal_pairs_results.json").read_text())
    assert got == recorded["outcomes"]
    assert V.MISMATCH not in got.values(), "a name pair alone is never a mismatch"
    assert not any(v == V.MATCH for k, v in got.items() if k.startswith("german_distinct")), (
        "two distinct German journals were read as one"
    )
