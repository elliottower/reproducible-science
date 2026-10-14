"""`--strict` fails on a not found unless the author checked the entry by hand, and never on a
lookup that failed.

A not found is a book, a report or a thesis, or a reference to a work that does not exist, and
the report cannot tell those apart, so strict refuses it until a person has looked. A failed
lookup is neither: the registry did not answer, and blaming the citation for that sends the
author after a defect that is not there.
"""

from __future__ import annotations

import email.message
import hashlib
import io
import json
import urllib.error

import pytest
from citations import audit as A
from citations.exceptions import CitationsError

TITLE = "Genome-wide association study of circulating interleukin 6 levels"
DOI = "10.1093/hmg/dds213"

EMPTY_SEARCH = {
    "semanticscholar.org": '{"data": []}',
    "api.crossref.org/works?": '{"message": {"items": []}}',
    "api.openalex.org/works?": '{"results": []}',
    "export.arxiv.org": "<feed></feed>",
}

WORK = json.dumps(
    {
        "message": {
            "title": [TITLE],
            "issued": {"date-parts": [[2012]]},
            "author": [
                {"family": "Naitza", "given": "Silvia"},
                {"family": "Porcu", "given": "Eleonora"},
            ],
        }
    }
)

BANNED = ("fake", "fabricat", "hallucinat")


def http_error(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, f"HTTP {code}", email.message.Message(), None)


def serve(monkeypatch, routes: dict[str, object]) -> list[str]:
    """Answer every request from `routes`: the first key found in the URL wins. A value is a
    body, an int for an HTTP status, or an exception to raise. An unrouted URL is a 404."""
    asked: list[str] = []

    def urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        asked.append(url)
        answer = next((v for k, v in routes.items() if k in url), 404)
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, int):
            raise http_error(url, answer)
        return io.BytesIO(str(answer).encode())

    monkeypatch.setattr(A.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(A.time, "sleep", lambda _: None)
    return asked


def bib(tmp_path, *entries: str):
    path = tmp_path / "references.bib"
    path.write_text("\n".join(entries))
    return path


def unidentified(key: str = "naitza2012") -> str:
    return f"@article{{{key},\n  title = {{{TITLE}}},\n  author = {{Naitza, Silvia}},\n  year = {{2012}}\n}}\n"


def identified(key: str = "naitza2012", author: str = "Naitza, Silvia") -> str:
    return (
        f"@article{{{key},\n  title = {{{TITLE}}},\n  author = {{{author}}},\n"
        f"  year = {{2012}},\n  doi = {{{DOI}}}\n}}\n"
    )


def run(tmp_path, path, *flags: str) -> tuple[int, dict]:
    out = tmp_path / "report.json"
    code = A.main(
        ["--bib", str(path), "--cache", str(tmp_path / "cache"), "--json", str(out), *flags]
    )
    return code, json.loads(out.read_text())


# --- not found ----------------------------------------------------------------------------------


def test_not_found_fails_strict_and_passes_by_default(tmp_path, monkeypatch, capsys):
    serve(monkeypatch, EMPTY_SEARCH)
    path = bib(tmp_path, unidentified())

    assert run(tmp_path, path)[0] == 0
    code, report = run(tmp_path, path, "--strict")

    assert code == 1
    assert report["entries"]["naitza2012"]["status"] == "not found"
    assert "naitza2012  title search (" in capsys.readouterr().out


def test_an_identifier_every_registry_answers_404_for_fails_strict_as_not_found(
    tmp_path, monkeypatch
):
    serve(monkeypatch, {"api.crossref.org/works/": 404, "api.datacite.org": 404})
    path = bib(tmp_path, identified())

    code, report = run(tmp_path, path, "--strict")

    assert code == 1
    verdict = report["entries"]["naitza2012"]
    assert (verdict["status"], verdict["not_found_by"]) == ("not found", "identifier")


# --- the list of entries checked by hand --------------------------------------------------------


def test_a_listed_key_passes_strict_and_is_still_reported_not_found(tmp_path, monkeypatch, capsys):
    serve(monkeypatch, EMPTY_SEARCH)
    path = bib(tmp_path, unidentified())
    (tmp_path / "references.checked.txt").write_text("naitza2012  # thesis, checked 2026-10-14\n")

    code, report = run(tmp_path, path, "--strict")

    assert code == 0
    verdict = report["entries"]["naitza2012"]
    assert (verdict["status"], verdict["checked_by_hand"]) == ("not found", True)
    assert "naitza2012  title search (" in capsys.readouterr().out


def test_a_listed_key_is_printed_as_not_found_marked_as_checked(tmp_path, monkeypatch, capsys):
    serve(monkeypatch, EMPTY_SEARCH)
    path = bib(tmp_path, unidentified(), unidentified("other2012"))
    (tmp_path / "references.checked.txt").write_text("naitza2012\n")

    code, _ = run(tmp_path, path, "--strict")

    printed = capsys.readouterr().out.splitlines()
    assert code == 1, "the unlisted not found still fails"
    assert any(x.startswith("  naitza2012") and x.endswith("(marked as checked)") for x in printed)
    assert not any(x.startswith("  other2012") and "marked" in x for x in printed)


def test_a_listed_key_with_a_field_mismatch_still_fails_strict(tmp_path, monkeypatch, capsys):
    serve(monkeypatch, {"api.crossref.org/works/": WORK})
    path = bib(tmp_path, identified(author="Chen, Wei"))
    (tmp_path / "references.checked.txt").write_text("naitza2012\n")

    code, report = run(tmp_path, path, "--strict")

    assert code == 1
    verdict = report["entries"]["naitza2012"]
    assert (verdict["status"], verdict["checked_by_hand"]) == ("mismatch", True)
    assert (
        "warning: naitza2012 is on the list, but a registry has it (mismatch)"
        in capsys.readouterr().out
    )


def test_a_listed_key_that_is_not_in_the_bibliography_is_warned_about(
    tmp_path, monkeypatch, capsys
):
    serve(monkeypatch, {"api.crossref.org/works/": WORK})
    path = bib(tmp_path, identified())
    (tmp_path / "references.checked.txt").write_text("naitza2012\nghost2020\n")

    _, report = run(tmp_path, path)

    assert report["checked_list"]["stale"] == ["ghost2020"]
    printed = capsys.readouterr().out
    assert "1 listed key(s) not in what was audited" in printed
    assert "    ghost2020" in printed


def test_the_list_files_hash_is_in_the_json_report(tmp_path, monkeypatch):
    serve(monkeypatch, EMPTY_SEARCH)
    path = bib(tmp_path, unidentified())
    listed = tmp_path / "hand.txt"
    listed.write_text("# checked by hand\nnaitza2012\n")

    _, report = run(tmp_path, path, "--checked", str(listed))

    assert report["checked_list"]["sha256"] == hashlib.sha256(listed.read_bytes()).hexdigest()
    assert report["checked_list"]["path"] == str(listed)
    assert report["checked_list"]["keys"] == ["naitza2012"]


def test_no_list_beside_the_bibliography_records_none(tmp_path, monkeypatch):
    serve(monkeypatch, EMPTY_SEARCH)

    _, report = run(tmp_path, bib(tmp_path, unidentified()))

    assert report["checked_list"] is None


def test_a_named_list_that_does_not_exist_is_refused(tmp_path, monkeypatch):
    serve(monkeypatch, EMPTY_SEARCH)
    with pytest.raises(CitationsError, match="no such file"):
        run(tmp_path, bib(tmp_path, unidentified()), "--checked", str(tmp_path / "missing.txt"))


def test_two_keys_on_one_line_are_refused_rather_than_half_read(tmp_path):
    listed = tmp_path / "references.checked.txt"
    listed.write_text("naitza2012 other2012\n")
    with pytest.raises(CitationsError, match=":1: one key per line"):
        A.read_checked(listed)


# --- a lookup that failed is not a not found ----------------------------------------------------

FAILURES = [401, 403, 429, 500, 502, 503, TimeoutError("timed out"), ConnectionResetError()]


@pytest.mark.parametrize("failure", FAILURES, ids=repr)
def test_a_registry_that_failed_is_could_not_check_and_exits_2(tmp_path, monkeypatch, failure):
    serve(monkeypatch, {"api.crossref.org/works/": failure, "api.datacite.org": failure})
    path = bib(tmp_path, identified())

    assert run(tmp_path, path)[0] == 0
    code, report = run(tmp_path, path, "--strict")

    verdict = report["entries"]["naitza2012"]
    assert verdict["status"] == "could not check"
    assert verdict["refused"] == ["crossref", "datacite"]
    assert code == 2


@pytest.mark.parametrize("failure", FAILURES, ids=repr)
def test_search_services_that_failed_are_could_not_check_and_exit_2(tmp_path, monkeypatch, failure):
    serve(monkeypatch, dict.fromkeys(EMPTY_SEARCH, failure))
    path = bib(tmp_path, unidentified())

    code, report = run(tmp_path, path, "--strict")

    assert report["entries"]["naitza2012"]["status"] == "could not check"
    assert code == 2


def test_a_registry_404_beside_a_refusal_is_not_a_not_found(tmp_path, monkeypatch):
    """Crossref said no; DataCite did not answer, and may be the registry that holds it."""
    serve(monkeypatch, {"api.crossref.org/works/": 404, "api.datacite.org": 503})

    code, report = run(tmp_path, bib(tmp_path, identified()), "--strict")

    assert report["entries"]["naitza2012"]["status"] == "could not check"
    assert code == 2


def test_a_semantic_scholar_403_is_not_a_search_that_answered(tmp_path, monkeypatch):
    serve(monkeypatch, {**EMPTY_SEARCH, "semanticscholar.org": 403})

    _, report = run(tmp_path, bib(tmp_path, unidentified()))

    assert report["entries"]["naitza2012"]["searched"] == ["crossref", "openalex", "arxiv"]


def test_a_disagreement_outranks_a_failed_lookup(tmp_path, monkeypatch):
    serve(monkeypatch, {"api.crossref.org/works/10.1093": WORK, "10.9999": 503})
    other = identified("other2020").replace(DOI, "10.9999/x")
    path = bib(tmp_path, identified(author="Chen, Wei"), other)

    code, report = run(tmp_path, path, "--strict")

    assert {k: v["status"] for k, v in report["entries"].items()} == {
        "naitza2012": "mismatch",
        "other2020": "could not check",
    }
    assert code == 1


# --- wording ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "routes",
    [EMPTY_SEARCH, {"api.crossref.org/works/": 404}, dict.fromkeys(EMPTY_SEARCH, 503)],
    ids=["search", "identifier", "failed"],
)
def test_the_report_never_calls_an_entry_fake(tmp_path, monkeypatch, capsys, routes):
    serve(monkeypatch, routes)
    path = bib(tmp_path, unidentified(), identified("doi2012"))
    (tmp_path / "references.checked.txt").write_text("naitza2012\nghost\n")

    _, report = run(tmp_path, path, "--strict")

    said = (capsys.readouterr().out + json.dumps(report)).lower()
    assert not [word for word in BANNED if word in said]
