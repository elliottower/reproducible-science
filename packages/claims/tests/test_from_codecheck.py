"""A CODECHECK configuration file, read into a draft manifest and its open items.

Every configuration file and register here is written in the test, in the shape the
specification (https://codecheck.org.uk/spec/config/2.0/) and the register's `register.json`
give, and names no real certificate. Nothing touches the network: a fetch is a function handed
the addresses it is asked for.
"""

from __future__ import annotations

import hashlib
import json

import pytest
import yaml
from claims.cli import main
from claims.manifest import load
from claims.open_items import DRAFT_NAME, ITEMS_NAME, ClaimState, Need, read, tally
from claims.origins import OriginUnreadableError
from claims.sources import SIDECAR
from claims.sources.codecheck import CodecheckError, from_codecheck

CONFIGURATION = """\
%YAML 1.1
---
version: https://codecheck.org.uk/spec/config/2.0/
manifest:
  - file: results/table2.csv
    comment: Table 2 in the paper
  - file: figures/fig1.png
    comment: Figure 1
  - file: results/extra.json
    comment: diagnostics, not in the paper
  - file: results/missing.csv
  - file: ../outside.csv
    comment: Table 3
paper:
  title: "An invented study of invented things"
  authors:
    - name: Josiah Carberry
      ORCID: 0000-0002-1825-0097
  reference: https://doi.org/10.5555/invented
codechecker:
  - name: A. Checker
report: https://doi.org/10.5555/invented-report
summary: Everything ran.
certificate: 2099-017
"""

TABLE = "model,auc\nlasso,0.912\n"
FIGURE = b"\x89PNG\r\n\x1a\n"


def bundle(root, configuration: str = CONFIGURATION):
    (root / "results").mkdir(parents=True)
    (root / "figures").mkdir()
    (root / "results" / "table2.csv").write_text(TABLE)
    (root / "results" / "extra.json").write_text('{"seconds": 3}\n')
    (root / "figures" / "fig1.png").write_bytes(FIGURE)
    (root / "codecheck.yml").write_text(configuration)
    return root


def test_each_output_is_an_artifact_and_each_value_output_a_claim_with_two_items(tmp_path):
    source = bundle(tmp_path / "bundle")
    out = tmp_path / "out"
    reading = from_codecheck(str(source / "codecheck.yml"), out)

    manifest = load(out / DRAFT_NAME)
    pins = {artifact.id: artifact.digest for artifact in manifest.artifacts}
    assert set(pins) == {
        "results/table2.csv",
        "figures/fig1.png",
        "results/extra.json",
        "results/missing.csv",
    }
    assert pins["results/table2.csv"].value == hashlib.sha256(TABLE.encode()).hexdigest()
    assert pins["figures/fig1.png"].value == hashlib.sha256(FIGURE).hexdigest()
    assert pins["results/missing.csv"] is None
    table = manifest.artifact("results/table2.csv")
    assert (out / table.path).resolve() == (source / "results" / "table2.csv").resolve()

    assert [(claim.id, claim.text, claim.evidence) for claim in manifest.claims] == [
        ("results-table2-csv", "Table 2 in the paper", ()),
        ("results-missing-csv", "results/missing.csv", ()),
    ]
    assert {passed.file: passed.reason for passed in reading.passed_over} == {
        "figures/fig1.png": "a figure, from which no backend reads a value",
        "results/extra.json": "its comment says it is not in the paper",
        "../outside.csv": "not a relative path inside the bundle",
    }

    items = read(out / ITEMS_NAME)
    assert [(item.claim, item.need) for item in items.items] == [
        ("results-table2-csv", Need.PASSAGE),
        ("results-table2-csv", Need.VALUE),
        ("results-missing-csv", Need.PASSAGE),
        ("results-missing-csv", Need.VALUE),
    ]
    assert items.items[0].context["tables"] == ["2"]
    assert items.items[0].context["paper_reference"] == "https://doi.org/10.5555/invented"
    assert items.items[0].candidates == ()
    assert items.source.digest == hashlib.sha256(CONFIGURATION.encode()).hexdigest()
    # Outside the working directory, so named by its file name and never by an absolute path.
    assert items.source.path == "codecheck.yml"
    assert items.source.format.endswith("https://codecheck.org.uk/spec/config/2.0/")


def test_the_draft_is_never_named_or_marked_as_a_certificate(tmp_path):
    source = bundle(tmp_path / "bundle")
    from_codecheck(str(source / "codecheck.yml"), tmp_path / "out")

    draft = (tmp_path / "out" / DRAFT_NAME).read_text()
    assert "2099-017" not in draft
    assert "certificate" not in draft.lower()
    assert yaml.safe_load(draft)["project"] == "An invented study of invented things"


def test_the_reader_binds_nothing_alone_so_every_claim_is_left_open(tmp_path):
    source = bundle(tmp_path / "bundle")
    from_codecheck(str(source / "codecheck.yml"), tmp_path / "out")

    found = tally(tmp_path / "out" / ITEMS_NAME)
    assert found.claims[ClaimState.READER] == 0
    assert found.claims[ClaimState.OPEN] == 2
    assert found.left_open_by_reader == 2
    assert found.items["open"] == 4


def test_a_check_that_declares_no_output_files_writes_no_claim(tmp_path):
    configuration = (
        "version: https://codecheck.org.uk/spec/config/2.0/\n"
        "manifest:\n"
        "  - comment: The estimates were printed and compared with Table 2.\n"
    )
    source = tmp_path / "bundle"
    source.mkdir()
    (source / "codecheck.yml").write_text(configuration)
    reading = from_codecheck(str(source / "codecheck.yml"), tmp_path / "out")

    assert (reading.artifacts, reading.claims, reading.items) == (0, 0, 0)
    assert [passed.reason for passed in reading.passed_over] == [
        "the check declares no output files"
    ]


def test_a_file_without_a_manifest_list_is_refused_and_nothing_is_written(tmp_path):
    (tmp_path / "codecheck.yml").write_text("paper:\n  title: x\n")
    with pytest.raises(CodecheckError, match="manifest"):
        from_codecheck(str(tmp_path / "codecheck.yml"), tmp_path / "out")
    assert not (tmp_path / "out").exists()


def register(path, *entries: tuple[str, str]):
    rows = [
        {
            "Certificate ID": certificate,
            "Repository": repository,
            "Repository Link": f"https://github.com/{repository.split('::')[1].split('|')[0]}",
            "Type": "community",
        }
        for certificate, repository in entries
    ]
    path.write_text(json.dumps(rows))
    return path


def test_an_identifier_is_read_from_the_bundle_folder_the_register_names(tmp_path):
    clone = tmp_path / "clone"
    bundle(clone / "reports" / "08")
    listed = register(
        tmp_path / "register.json",
        ("2099-016", "github::someone/other"),
        ("2099-017", "github::someone/reviews|reports/08"),
    )
    pinned = hashlib.sha256(listed.read_bytes()).hexdigest()

    reading = from_codecheck(
        "2099-017", tmp_path / "out", register=listed, register_sha256=pinned, bundle=clone
    )

    items = read(tmp_path / "out" / ITEMS_NAME)
    assert items.source.path == "2099-017"
    assert items.source.pins == {"register.json": pinned}
    assert reading.pinned == 3
    manifest = load(tmp_path / "out" / DRAFT_NAME)
    assert manifest.provenance.repository == "https://github.com/someone/reviews"


def test_a_register_that_is_not_the_pinned_one_is_refused(tmp_path):
    listed = register(tmp_path / "register.json", ("2099-017", "github::someone/reviews"))
    with pytest.raises(CodecheckError, match="pinned"):
        from_codecheck(
            "2099-017",
            tmp_path / "out",
            register=listed,
            register_sha256="0" * 64,
            bundle=tmp_path,
        )
    assert not (tmp_path / "out").exists()


def test_an_identifier_needs_a_register(tmp_path):
    with pytest.raises(CodecheckError, match="--register"):
        from_codecheck("2099-017", tmp_path / "out")


def test_a_fetch_reads_the_file_at_the_commit_the_default_branch_points_to(tmp_path):
    commit = "a" * 40
    raw = f"https://raw.githubusercontent.com/someone/reviews/{commit}/reports/08/codecheck.yml"
    served = {
        "https://api.github.com/repos/someone/reviews/commits/HEAD": json.dumps(
            {"sha": commit}
        ).encode(),
        raw: CONFIGURATION.encode(),
    }
    asked: list[str] = []

    def fetch(url: str) -> bytes:
        asked.append(url)
        if url not in served:
            raise OriginUnreadableError(f"{url} answered 404 Not Found")
        return served[url]

    listed = register(
        tmp_path / "register.json", ("2099-017", "github::someone/reviews|reports/08")
    )
    reading = from_codecheck("2099-017", tmp_path / "out", register=listed, fetch=fetch)

    assert asked == list(served)
    items = read(tmp_path / "out" / ITEMS_NAME)
    assert items.source.url == raw
    manifest = load(tmp_path / "out" / DRAFT_NAME)
    assert manifest.provenance.commit == commit
    # No copy of the bundle is on disk, so nothing is pinned.
    assert reading.pinned == 0


def test_a_repository_not_on_github_is_not_fetched(tmp_path):
    listed = register(tmp_path / "register.json", ("2099-017", "osf::ZTC7M"))
    with pytest.raises(CodecheckError, match="--bundle"):
        from_codecheck("2099-017", tmp_path / "out", register=listed, fetch=lambda url: b"")


def test_from_codecheck_prints_what_it_wrote_as_json(tmp_path, capsys):
    source = bundle(tmp_path / "bundle")
    out = tmp_path / "out"
    code = main(
        ["from-codecheck", str(source / "codecheck.yml"), "-o", str(out), "--format", "json"]
    )

    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert (printed["artifacts"], printed["pinned"], printed["claims"], printed["items"]) == (
        4,
        3,
        2,
        4,
    )


def snapshot(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_nothing_is_written_into_the_bundle_and_the_configuration_is_untouched(tmp_path):
    source = bundle(tmp_path / "bundle")
    before = snapshot(source)
    from_codecheck(str(source / "codecheck.yml"), tmp_path / "out")

    assert snapshot(source) == before
    assert not (source / SIDECAR).exists()


def test_a_key_given_twice_is_refused_and_nothing_is_written(tmp_path):
    source = bundle(tmp_path / "bundle", CONFIGURATION + "summary: Something else ran.\n")
    with pytest.raises(CodecheckError, match="'summary' is given twice"):
        from_codecheck(str(source / "codecheck.yml"), tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_a_link_out_of_the_bundle_is_not_followed_or_pinned(tmp_path):
    source = bundle(tmp_path / "bundle")
    (tmp_path / "secret.csv").write_text("model,auc\nlasso,0.5\n")
    (source / "results" / "table2.csv").unlink()
    (source / "results" / "table2.csv").symlink_to(tmp_path / "secret.csv")

    written = from_codecheck(str(source / "codecheck.yml"), tmp_path / "out")

    manifest = load(tmp_path / "out" / DRAFT_NAME)
    assert manifest.artifact("results/table2.csv").digest is None
    assert [claim.id for claim in manifest.claims] == ["results-missing-csv"]
    assert [(n.file, n.reason) for n in written.not_checked] == [
        ("results/table2.csv", "a link to a file outside the bundle, which is not followed")
    ]


def test_a_git_lfs_pointer_is_reported_not_checked_and_never_pinned(tmp_path):
    source = bundle(tmp_path / "bundle")
    (source / "results" / "table2.csv").write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:4d7a214614ab2935c943f9e0ff69d22eadbb8f32b1258daaa5e2ca24d17e2393\n"
        "size 12345\n"
    )
    written = from_codecheck(str(source / "codecheck.yml"), tmp_path / "out")

    manifest = load(tmp_path / "out" / DRAFT_NAME)
    assert manifest.artifact("results/table2.csv").digest is None
    assert "results-table2-csv" not in {claim.id for claim in manifest.claims}
    assert [n.file for n in written.not_checked] == ["results/table2.csv"]
    assert "Git LFS pointer" in written.not_checked[0].reason


def test_a_register_folder_outside_the_clone_is_refused(tmp_path):
    listed = register(tmp_path / "register.json", ("2099-017", "github::someone/reviews|../x"))
    with pytest.raises(CodecheckError, match="outside"):
        from_codecheck("2099-017", tmp_path / "out", register=listed, bundle=tmp_path / "clone")


def test_each_output_not_on_disk_is_named_with_why(tmp_path):
    source = bundle(tmp_path / "bundle")
    written = from_codecheck(str(source / "codecheck.yml"), tmp_path / "out")
    assert [(m.file, m.reason) for m in written.unpinned] == [
        (
            "results/missing.csv",
            "not in the bundle at results/missing.csv, so it is declared without a pin",
        )
    ]
    assert written.pinned == 3


def test_the_text_output_names_each_unpinned_file(tmp_path, capsys):
    source = bundle(tmp_path / "bundle")
    assert main(["from-codecheck", str(source / "codecheck.yml"), "-o", str(tmp_path / "out")]) == 0
    assert "not pinned: results/missing.csv: not in the bundle" in capsys.readouterr().out


SHAPES = """\
version: https://codecheck.org.uk/spec/config/2.0/
manifest:
  - results/bare.csv
  - file: t.csv
    comment: [Table 2, in the supplement]
  - file: ./t.csv
paper:
  title: [An invented, study]
  reference: >
    https://doi.org/10.5555/invented
"""


def test_entries_and_fields_the_specification_does_not_shape_are_read_or_named(tmp_path):
    source = tmp_path / "bundle"
    source.mkdir()
    (source / "t.csv").write_text(TABLE)
    (source / "codecheck.yml").write_text(SHAPES)
    written = from_codecheck(str(source / "codecheck.yml"), tmp_path / "out")

    passed = {p.file: p.reason for p in written.passed_over}
    assert passed["results/bare.csv"].startswith("a bare entry, not a mapping with `file`")
    assert passed["t.csv"] == "listed twice"
    manifest = load(tmp_path / "out" / DRAFT_NAME)
    assert [a.id for a in manifest.artifacts] == ["t.csv"]
    assert [c.text for c in manifest.claims] == ["Table 2; in the supplement"]
    assert manifest.project == "An invented; study"
    item = read(tmp_path / "out" / ITEMS_NAME).items[0]
    assert item.context["tables"] == ["2"]
    assert item.context["paper_reference"] == "https://doi.org/10.5555/invented"


@pytest.mark.parametrize(
    ("added", "said"),
    [
        ("x: " + "[" * 5000 + "]" * 5000 + "\n", "nested deeper than 64"),
        ("x: &a [1, 2]\ny: *a\n", "an alias"),
    ],
    ids=["deep", "alias"],
)
def test_a_hostile_configuration_file_is_refused_not_crashed_on(tmp_path, added, said):
    source = bundle(tmp_path / "bundle", CONFIGURATION + added)
    with pytest.raises(CodecheckError, match=said):
        from_codecheck(str(source / "codecheck.yml"), tmp_path / "out")
