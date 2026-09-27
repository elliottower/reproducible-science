"""Concurrent writes to one claims file, one bibliography, one record set, and the caches.

Every write here reads a file, computes a whole new document from what it read, and writes that
document back. Two callers that read the same document each write back their own change and the
second erases the first, with both reporting success: `citations pin` loses a quotation from a
claims file that the next `verify` then passes, `citations add` loses a BibTeX entry it has
already reported as appended, and a bulk `tags` write loses a tag across every record it touched.
Nothing has to go wrong for this -- a pre-commit hook beside a manual run, or an agent driving two
of these commands at once, is enough.

The truncating write is the second failure. `write_text` empties the file and fills it after, so
a reader arriving in between sees half a document, and a run killed in that window destroys the
file that saving after every hit exists to protect. On a pinned source artifact it is worse than
a lost file: the claims file still records the digest of the whole document, so the short file
left behind comes out of the next `citations verify` as a hash mismatch, which reads as tampering
with a source nobody touched.
"""

from __future__ import annotations

import json
import os
import pathlib
import threading

import pytest
import yaml
from citations import (
    add,
    audit,
    bibtex,
    build,
    config,
    lint,
    paperclip,
    pin,
    projects,
    resolve,
    tags,
)

PREAMBLE = "A generalization is invariant if it continues to hold. "


def _passage(i: int) -> str:
    return f"passage number {i} sits in the source and nowhere else"


def _paper(tmp_path: pathlib.Path, passages: int, already: int = 0) -> pathlib.Path:
    """A claims file carrying `already` claims, beside a source holding `passages` passages.

    The file starts populated because the window this is about is the read: a caller holds a
    snapshot of the whole document while it computes the next one, and a file with a few hundred
    claims in it takes long enough to parse that two callers reliably hold the same snapshot.
    """
    body = PREAMBLE + " ".join(f"{_passage(i)}." for i in range(passages))
    (tmp_path / "source.txt").write_text(body + "\n")
    claims = tmp_path / "claims"
    claims.mkdir()
    f = claims / "woodward.yaml"
    f.write_text(
        yaml.safe_dump(
            {
                "source": {"citation": "woodward", "local": "source.txt"},
                "claims": {
                    f"old{i}": {"quotes": [{"exact": f"a passage recorded earlier, number {i}"}]}
                    for i in range(already)
                },
            },
            sort_keys=False,
        )
    )
    return f


def _run(workers: int, body) -> list[BaseException]:
    failures: list[BaseException] = []
    barrier = threading.Barrier(workers)

    def worker(n: int) -> None:
        barrier.wait(timeout=30)
        try:
            body(n)
        except BaseException as e:
            failures.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    return failures


def _while_reading(read, writes) -> tuple[list, list[BaseException]]:
    """Everything `read` observed while `writes` ran, and what reading raised."""
    seen: list = []
    raised: list[BaseException] = []
    stop = threading.Event()

    def read_repeatedly() -> None:
        while not stop.is_set():
            try:
                seen.append(read())
            except BaseException as e:
                raised.append(e)
                return

    reader = threading.Thread(target=read_repeatedly, daemon=True)
    reader.start()
    try:
        writes()
    finally:
        stop.set()
        reader.join(timeout=60)
    return seen, raised


def _library(tmp_path: pathlib.Path, records: int, tag_names: list[str]) -> pathlib.Path:
    lib = tmp_path / "lib"
    (lib / "records").mkdir(parents=True)
    (lib / "tags.yaml").write_text(yaml.safe_dump({"tags": dict.fromkeys(tag_names, "")}))
    for i in range(records):
        (lib / "records" / f"r{i:03d}.yaml").write_text(
            yaml.safe_dump({"slug": f"r{i:03d}", "title": f"work {i}", "cited_by": {"p": {}}})
        )
    return lib


def _entry(key: str, i: int, doi: bool = True) -> str:
    """One BibTeX entry. Without a DOI an audit over it reaches no registry."""
    fields = [
        f"  author  = {{Name{i}, Given and Other, Someone}}",
        f"  title   = {{{{Work number {i}}}}}",
        "  journal = {A Journal of Some Kind}",
        "  year    = {2020}",
    ]
    if doi:
        fields.append(f"  doi     = {{10.1234/{i:04d}}}")
    return f"@article{{{key},\n" + ",\n".join(fields) + "\n}\n"


def _bib(tmp_path: pathlib.Path, works: int) -> pathlib.Path:
    """A bibliography already carrying `works` entries.

    Populated for the same reason `_paper` is: `add` reads and parses the whole file before it
    appends, so a file with a few hundred entries in it takes long enough that two callers
    reliably hold the same bytes.
    """
    bib = tmp_path / "references.bib"
    bib.write_text("\n".join(_entry(f"old{i}", i) for i in range(works)))
    return bib


def _claim_file(tmp_path: pathlib.Path, already: int) -> pathlib.Path:
    """A claims file carrying `already` hand-written quotations under a Paperclip source block."""
    path = tmp_path / "claims" / "doc.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        paperclip.HEADER
        + yaml.safe_dump(
            {
                "source": {"citation": "doc", "local": "sources/paperclip/doc.txt"},
                "claims": {
                    f"hand{i}": {
                        "quotes": [{"exact": f"a passage written out by hand, number {i}"}]
                    }
                    for i in range(already)
                },
            },
            sort_keys=False,
        )
    )
    return path


class _Served:
    """A Paperclip that hands back one document, so nothing here needs a key or a network."""

    name = "served"

    def __init__(self, text: str) -> None:
        self._text = text

    def fetch(self, identifier: str) -> paperclip.Document:
        return paperclip.Document(identifier=identifier, document_id="doc-1", text=self._text)

    def repo(self, name: str):
        raise NotImplementedError


def _no_space(_src, _dst):
    """`os.replace` on a full disk: the last step of an atomic write, failing.

    Standing in for the crash, the SIGKILL and the full disk alike. A plain `write_text` has
    already truncated the file by the time any of the three arrives; a replace that never lands
    leaves the old contents where they were.
    """
    raise OSError(28, "No space left on device")


def _bib_library(tmp_path: pathlib.Path, works: int) -> pathlib.Path:
    lib = tmp_path / "lib"
    (lib / "records").mkdir(parents=True)
    (lib / "references.bib").write_text(
        "\n".join(
            f"@article{{k{i},\n"
            f"  title = {{Work number {i}}},\n"
            f"  author = {{Name{i}, Given and Other, Someone}},\n"
            f"  year = {{2020}},\n"
            f"  journal = {{A Journal of Some Kind}},\n"
            f"  doi = {{10.1234/{i:04d}}}\n}}\n"
            for i in range(works)
        )
    )
    (lib / "papers.yaml").write_text(yaml.safe_dump({"papers": {"one": {"bib": "references.bib"}}}))
    return lib


def test_concurrent_pins_lose_no_quotation(tmp_path):
    claims = _paper(tmp_path, passages=16, already=300)

    failures = _run(16, lambda n: pin.main([str(claims), "--id", f"c{n}", "--quote", _passage(n)]))

    assert failures == []
    doc = yaml.safe_load(claims.read_text())
    assert sorted(doc["claims"]) == sorted(
        [f"c{n}" for n in range(16)] + [f"old{i}" for i in range(300)]
    )
    assert [q["exact"] for q in doc["claims"]["c7"]["quotes"]] == [_passage(7)]


def test_a_claims_file_taking_a_pin_never_shrinks_on_disk(tmp_path):
    claims = _paper(tmp_path, passages=40, already=300)
    start = len(claims.read_bytes())

    def write() -> None:
        for n in range(40):
            pin.main([str(claims), "--id", f"c{n}", "--quote", _passage(n)])

    seen, raised = _while_reading(lambda: len(claims.read_bytes()), write)

    assert raised == []
    assert seen
    # The file only gains claims, so anything shorter than it started is a write caught between
    # the truncate and the fill -- the state in which a killed `pin` leaves the whole file.
    assert [size for size in seen if size < start] == []
    doc = yaml.safe_load(claims.read_text())
    assert doc["source"]["citation"] == "woodward"
    assert all("exact" in q for c in doc["claims"].values() for q in c["quotes"])


def test_one_identifier_written_concurrently_is_taken_once(tmp_path):
    claims = _paper(tmp_path, passages=8, already=300)

    failures = _run(8, lambda n: pin.main([str(claims), "--id", "same", "--quote", _passage(n)]))

    assert all(isinstance(e, pin.PinRefused) for e in failures)
    assert len(failures) == 7
    doc = yaml.safe_load(claims.read_text())
    assert len(doc["claims"]) == 301
    assert doc["claims"]["same"]["quotes"][0]["exact"].startswith("passage number ")


def test_concurrent_bulk_tag_writes_keep_every_tag(tmp_path):
    names = [f"t{n}" for n in range(8)]
    lib = _library(tmp_path, records=60, tag_names=names)

    failures = _run(len(names), lambda n: tags.apply(lib, names[n], cited_by="p"))

    assert failures == []
    for record in sorted((lib / "records").glob("*.yaml")):
        assert yaml.safe_load(record.read_text())["tags"] == names


def test_a_rename_racing_a_bulk_tag_write_does_not_interleave(tmp_path):
    lib = _library(tmp_path, records=120, tag_names=["t"])

    def body(n: int) -> None:
        if n == 0:
            projects.rename(lib, "p", "q")
        else:
            tags.apply(lib, "t", cited_by="p")

    failures = _run(2, body)

    assert failures == []
    loaded = [yaml.safe_load(p.read_text()) for p in sorted((lib / "records").glob("*.yaml"))]
    assert all(list(r["cited_by"]) == ["q"] for r in loaded)
    # The tag write read every record either before the rename or after it. A count in between
    # is the two bulk writes interleaving over the same files.
    assert sum(1 for r in loaded if r.get("tags") == ["t"]) in (0, len(loaded))


def test_a_reader_never_sees_half_a_record(tmp_path, monkeypatch, capsys):
    lib = _bib_library(tmp_path, works=80)
    monkeypatch.setenv("CITATIONS_HOME", str(lib))
    build.main([])
    files = sorted((lib / "records").glob("*.yaml"))
    assert len(files) == 80

    def read() -> tuple[bytes, ...]:
        return tuple(p.read_bytes() for p in files)

    def rebuild() -> None:
        for _ in range(4):
            build.main([])

    whole = read()
    seen, raised = _while_reading(read, rebuild)
    capsys.readouterr()

    assert raised == []
    assert seen
    assert [sum(len(f) for f in state) for state in seen if state != whole] == []
    assert yaml.safe_load(files[0].read_text())["slug"] == files[0].stem


def test_a_reader_never_sees_half_an_overlay(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    (lib / "records").mkdir(parents=True)
    monkeypatch.setenv("CITATIONS_HOME", str(lib))
    overlay = {
        f"doi-10-1234-{i:04d}": {"url": f"https://doi.org/10.1234/{i:04d}", "doi": f"10.1234/{i}"}
        for i in range(600)
    }
    resolve.save_overlay(overlay)
    enrichment = lib / "enrichment.yaml"
    whole = enrichment.read_bytes()

    def rewrite() -> None:
        for _ in range(20):
            resolve.save_overlay(overlay)

    seen, raised = _while_reading(enrichment.read_bytes, rewrite)

    assert raised == []
    assert seen
    # The lengths, so a failure names what was on disk rather than printing the file.
    assert [len(state) for state in seen if state != whole] == []
    assert len(resolve.load_overlay()) == len(overlay)


def test_concurrent_adds_lose_no_bibliography_entry(tmp_path, capsys):
    bib = _bib(tmp_path, works=300)
    entries = []
    for n in range(12):
        f = tmp_path / f"new{n}.bib"
        f.write_text(_entry(f"new{n}", 1000 + n))
        entries.append(f)

    failures = _run(12, lambda n: add.main([str(bib), "--entry-file", str(entries[n])]))
    capsys.readouterr()

    assert failures == []
    keys = [key for _kind, key, _body in bibtex.entries(bibtex.read(bib))]
    assert sorted(keys) == sorted([f"old{i}" for i in range(300)] + [f"new{n}" for n in range(12)])
    assert add.unclosed(bibtex.read(bib)) is None


def test_one_citation_key_added_concurrently_is_taken_once(tmp_path, capsys):
    bib = _bib(tmp_path, works=300)
    entry = tmp_path / "entry.bib"
    entry.write_text(_entry("repeated", 1000))
    codes: list[int] = []

    failures = _run(8, lambda n: codes.append(add.main([str(bib), "--entry-file", str(entry)])))
    capsys.readouterr()

    assert failures == []
    # One caller appends and the other seven find the key taken. The duplicate check reads the
    # file, so unlocked all eight read a bibliography that does not define the key yet.
    assert sorted(codes) == [0, 1, 1, 1, 1, 1, 1, 1]
    keys = [key for _kind, key, _body in bibtex.entries(bibtex.read(bib))]
    assert keys.count("repeated") == 1
    assert len(keys) == 301


def test_concurrent_claim_file_writes_lose_no_hand_written_quotation(tmp_path):
    path = _claim_file(tmp_path, already=300)
    source = {"citation": "doc", "local": "sources/paperclip/doc.txt", "sha256": "0" * 64}

    def body(n: int) -> None:
        paperclip.write_claim_file(
            path, source, {f"imported{n}": {"statement": f"a claim, number {n}", "quotes": []}}
        )

    failures = _run(12, body)

    assert failures == []
    doc = yaml.safe_load(path.read_text())
    assert sorted(doc["claims"]) == sorted(
        [f"hand{i}" for i in range(300)] + [f"imported{n}" for n in range(12)]
    )
    assert doc["source"]["sha256"] == "0" * 64


def test_a_refetched_source_artifact_survives_a_write_that_never_lands(tmp_path, monkeypatch):
    out_dir = tmp_path / "sources" / "paperclip"
    out_dir.mkdir(parents=True)
    artifact = out_dir / "10-1101-x.txt"
    artifact.write_text("the document as it was pinned, and as its recorded sha256 describes it\n")
    whole = artifact.read_bytes()

    monkeypatch.setattr(os, "replace", _no_space)
    with pytest.raises(OSError):
        paperclip.resolve_document("10.1101/x", out_dir, client=_Served("a refetched document\n"))

    # The digest already in the claims file is over these bytes. A short file left under that
    # digest comes out of the next `verify` as a hash mismatch, which reads as tampering.
    assert artifact.read_bytes() == whole
    assert [p.name for p in out_dir.iterdir()] == [artifact.name]


def test_papers_yaml_survives_a_write_that_never_lands(tmp_path, monkeypatch):
    config.save(
        config.LibraryConfig(papers={"one": config.PaperConfig(bib="a/refs.bib")}), tmp_path
    )
    whole = config.config_path(tmp_path).read_bytes()

    monkeypatch.setattr(os, "replace", _no_space)
    with pytest.raises(OSError):
        config.save(
            config.LibraryConfig(papers={"two": config.PaperConfig(bib="b/refs.bib")}), tmp_path
        )

    assert config.config_path(tmp_path).read_bytes() == whole
    assert list(config.load(tmp_path).papers) == ["one"]


def test_an_audit_report_survives_a_write_that_never_lands(tmp_path, monkeypatch, capsys):
    # Neither entry carries a DOI or a PMID, so the audit resolves nothing and asks no registry.
    bib = tmp_path / "references.bib"
    bib.write_text(_entry("k0", 0, doi=False) + "\n" + _entry("k1", 1, doi=False))
    out = tmp_path / "reports" / "audit.json"
    out.parent.mkdir()
    out.write_text('{"entries": {}, "where": "the audit run before this one"}\n')

    monkeypatch.setattr(os, "replace", _no_space)
    with pytest.raises(OSError):
        audit.main(["--bib", str(bib), "--json", str(out)])
    capsys.readouterr()

    assert json.loads(out.read_text())["where"] == "the audit run before this one"


def test_a_reader_never_sees_half_a_cache(tmp_path):
    path = tmp_path / "authors.yaml"
    cache = {
        f"doi:10.1234/{i:04d}": {"source": "crossref", "authors": [f"Name{i}, Given"]}
        for i in range(600)
    }
    lint.save_cache(path, cache)
    whole = path.read_bytes()

    def rewrite() -> None:
        for _ in range(20):
            lint.save_cache(path, cache)

    seen, raised = _while_reading(path.read_bytes, rewrite)

    assert raised == []
    assert seen
    assert [len(state) for state in seen if state != whole] == []
    assert len(lint.load_cache(path)) == len(cache)
