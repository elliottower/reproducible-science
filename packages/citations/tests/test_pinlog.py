"""A claims file and its source edited together leave a trace in the pin log.

The attack: pin a quotation, then change a sentence in the source, write the new sha256 into
the claims file and pin a passage only the edited source holds. Every check passed, because the
file on disk matched the pin and the pin was the one the file named. `citations pin` now appends
each pin to `pins.jsonl`, and `verify` reports a claims file naming other bytes than it was first
pinned against, quotations no pin recorded, and lines git history shows taken out of the log.

A claims file whose source is absent, as every source is on a clone, is held to what can be
checked without it: a sha256 of the right shape, a DOI of the right shape, and a log line.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess

import pytest
import yaml
from citations import pin, pinlog
from citations import verify as V
from citations.cli import main

TEXT = "Abstract. The intervention did not improve recall in older adults at any dose tested.\n"
EDITED = "Abstract. The intervention reliably improved recall in older adults at every dose.\n"
HONEST = "The intervention did not improve recall in older adults"
FABRICATED = "The intervention reliably improved recall in older adults"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setenv("CITATIONS_NO_CACHE", "1")
    monkeypatch.setenv("REPRO_NO_HINT", "1")
    V.clear_caches()


def git(folder: pathlib.Path, *args: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", *args], cwd=folder, check=True, env=env, capture_output=True)


def commit(folder: pathlib.Path, message: str) -> None:
    git(folder, "add", "claims")
    git(folder, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", message)


def project(tmp_path: pathlib.Path, text: str = TEXT) -> pathlib.Path:
    (tmp_path / "sources").mkdir()
    (tmp_path / "claims").mkdir()
    (tmp_path / "sources" / "smith.txt").write_text(text)
    claims = tmp_path / "claims" / "smith.yaml"
    claims.write_text(
        yaml.safe_dump(
            {
                "source": {
                    "citation": "smith",
                    "local": "sources/smith.txt",
                    "sha256": hashlib.sha256(text.encode()).hexdigest(),
                },
                "claims": {},
            }
        )
    )
    return claims


def account(tmp_path: pathlib.Path, *flags: str) -> tuple[int, dict]:
    wrote = tmp_path / "out.json"
    code = main(["verify", "--claims", str(tmp_path / "claims"), "--json", str(wrote), *flags])
    return code, json.loads(wrote.read_text())


def said(found: dict, key: str) -> list[str]:
    return [f["finding"] for f in found[key]]


def test_a_pin_is_logged_with_the_sha256_it_was_taken_against(tmp_path):
    claims = project(tmp_path)
    assert pin.main([str(claims), "--id", "c1", "--quote", HONEST]) == 0
    (line,) = pinlog.read(claims.parent)
    assert line["file"] == "smith.yaml" and line["claim"] == "c1"
    assert line["sha256"] == hashlib.sha256(TEXT.encode()).hexdigest()
    assert line["quote"] == pinlog.quote_digest(HONEST)
    assert HONEST not in (claims.parent / pinlog.LOG).read_text()


def test_editing_the_source_and_its_sha256_together_shows_as_pinned_again(tmp_path, capsys):
    claims = project(tmp_path)
    assert pin.main([str(claims), "--id", "c1", "--quote", HONEST]) == 0
    # The attack: the source and the sha256 in the claims file changed together.
    (tmp_path / "sources" / "smith.txt").write_text(EDITED)
    doc = yaml.safe_load(claims.read_text())
    doc["source"]["sha256"] = hashlib.sha256(EDITED.encode()).hexdigest()
    doc["claims"] = {}
    claims.write_text(yaml.safe_dump(doc))
    V.clear_caches()
    assert pin.main([str(claims), "--id", "c2", "--quote", FABRICATED]) == 0
    assert "was first pinned against" in capsys.readouterr().out
    code, found = account(tmp_path)
    assert code == 0
    first = hashlib.sha256(TEXT.encode()).hexdigest()[:12]
    assert any(f"first pinned at {first}" in s for s in said(found, "findings"))


def test_a_quotation_written_by_hand_into_a_logged_file_is_marked(tmp_path):
    claims = project(tmp_path)
    assert pin.main([str(claims), "--id", "c1", "--quote", HONEST]) == 0
    doc = yaml.safe_load(claims.read_text())
    doc["claims"]["c2"] = {"quotes": [{"exact": "recall in older adults at any dose tested"}]}
    claims.write_text(yaml.safe_dump(doc))
    _, found = account(tmp_path)
    assert "1 quotation(s) no `citations pin` recorded in pins.jsonl" in said(found, "findings")


def test_lines_taken_out_of_a_committed_log_fail_by_default(tmp_path):
    git(tmp_path, "init", "-q")
    claims = project(tmp_path)
    assert pin.main([str(claims), "--id", "c1", "--quote", HONEST]) == 0
    commit(tmp_path, "pin")
    (claims.parent / pinlog.LOG).write_text("")
    code, found = account(tmp_path)
    assert code == 1
    assert any("taken out of the log" in s for s in said(found, "tampered"))


def test_a_git_revert_of_a_pin_commit_is_a_note_with_the_way_back(tmp_path):
    git(tmp_path, "init", "-q")
    claims = project(tmp_path)
    assert pin.main([str(claims), "--id", "c0", "--quote", HONEST[:30]]) == 0
    commit(tmp_path, "first pin")
    assert pin.main([str(claims), "--id", "c1", "--quote", HONEST]) == 0
    commit(tmp_path, "pin")
    git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "revert", "--no-edit", "HEAD")
    code, found = account(tmp_path)
    assert code == 0
    assert found["tampered"] == []
    assert any(
        "taken out by a revert of" in s and "append the line" in s for s in said(found, "findings")
    )


@pytest.mark.parametrize("citation", ["smith", "smith2026"])
def test_renaming_the_claims_file_does_not_hide_a_repin(tmp_path, citation):
    claims = project(tmp_path)
    assert pin.main([str(claims), "--id", "c1", "--quote", HONEST]) == 0
    (tmp_path / "sources" / "smith.txt").write_text(EDITED + TEXT)
    doc = yaml.safe_load(claims.read_text())
    doc["source"]["sha256"] = hashlib.sha256((EDITED + TEXT).encode()).hexdigest()
    doc["source"]["citation"] = citation
    claims.write_text(yaml.safe_dump(doc))
    renamed = claims.rename(claims.with_name("smith_v2.yaml"))
    V.clear_caches()
    assert pin.main([str(renamed), "--id", "c2", "--quote", FABRICATED]) == 0
    _, found = account(tmp_path)
    first = hashlib.sha256(TEXT.encode()).hexdigest()[:12]
    assert any(f"first pinned at {first}" in s for s in said(found, "findings"))


def test_a_log_two_branches_added_to_is_not_rewritten(tmp_path):
    git(tmp_path, "init", "-q")
    claims = project(tmp_path)
    assert pin.main([str(claims), "--id", "c1", "--quote", HONEST]) == 0
    commit(tmp_path, "pin")
    assert (
        pin.main(
            [str(claims), "--id", "c2", "--quote", "Abstract. The intervention did not improve"]
        )
        == 0
    )
    commit(tmp_path, "another pin")
    assert pinlog.rewritten(claims.parent) == []
    assert account(tmp_path, "--strict")[0] == 0


def absent(tmp_path: pathlib.Path, sha256: str, doi: str) -> None:
    claims = tmp_path / "claims"
    claims.mkdir(exist_ok=True)
    (claims / "fake.yaml").write_text(
        yaml.safe_dump(
            {
                "source": {
                    "citation": "fake",
                    "local": "sources/fake.pdf",
                    "sha256": sha256,
                    "doi": doi,
                },
                "claims": {"c1": {"quotes": [{"exact": "a passage no source on disk holds"}]}},
            }
        )
    )


def test_a_fabricated_record_of_an_absent_source_fails_strict(tmp_path):
    claims = project(tmp_path)
    assert pin.main([str(claims), "--id", "c1", "--quote", HONEST]) == 0
    absent(tmp_path, "not-a-digest", "doi-of-nothing")
    code, found = account(tmp_path)
    assert code == 0  # a source absent on a clone is not a failure by default
    strict = said(found, "strict_findings")
    assert any("is not 64 hexadecimal digits" in s for s in strict)
    assert any("does not have the shape 10.NNNN/suffix" in s for s in strict)
    assert "1 quotation(s) no `citations pin` recorded in pins.jsonl" in said(found, "findings")
    assert account(tmp_path, "--strict")[0] == 1


def test_an_absent_source_with_no_pin_log_is_said_once(tmp_path):
    absent(tmp_path, "a" * 64, "10.1234/abc.5")
    _, found = account(tmp_path)
    assert found["strict_findings"] == []
    assert any("no pin log" in s for s in said(found, "findings"))


@pytest.mark.parametrize(
    ("doi", "wrong"),
    [
        ("10.1234/abc", False),
        ("https://doi.org/10.1038/s41586-020-2649-2", False),
        ("doi:10.48550/arXiv.2301.04709", False),
        ("10.1/x", True),
        ("not a doi", True),
    ],
)
def test_the_shape_of_a_doi(doi, wrong):
    assert bool(pinlog.doi_shape(doi)) is wrong
