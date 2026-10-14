"""An artifact copied from another repository, and whether its pin is the bytes at the origin.

Each test builds a real repository in `tmp_path`, commits a file, and writes a manifest in a
second directory that pins a copy of it and names where it came from.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import subprocess

import pytest
from claims.cli import main
from claims.exceptions import ManifestError
from claims.export.rocrate import from_ro_crate, to_ro_crate
from claims.manifest import load
from claims.models import Digest, Origin
from claims.origins import OriginState, OriginUnreadableError, origins, raw_github_url
from claims.record import check_records

REMOTE = "https://github.com/someone/study"
SOURCE = "results/indices.json"
WHEN = datetime.datetime(2026, 10, 14, 12, 0, tzinfo=datetime.UTC)
SIX = hashlib.sha256(b'{"n": 6}\n').hexdigest()
SEVEN = hashlib.sha256(b'{"n": 7}\n').hexdigest()


def git(*args: str, cwd: pathlib.Path) -> str:
    # A hook's `GIT_DIR` outranks the directory named, so the environment is cleaned first.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    done = subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return done.stdout.strip()


def commit(study: pathlib.Path, path: str, text: str) -> str:
    (study / path).parent.mkdir(parents=True, exist_ok=True)
    (study / path).write_text(text)
    git("add", path, cwd=study)
    git("commit", "-qm", f"write {path}", cwd=study)
    return git("rev-parse", "HEAD", cwd=study)


@pytest.fixture
def study(tmp_path):
    root = tmp_path / "study"
    root.mkdir()
    git("init", "-q", ".", cwd=root)
    return root


def paper(tmp_path: pathlib.Path, copied: str, origin: dict[str, str] | None) -> pathlib.Path:
    """A manifest pinning `copied` as `artifacts/indices.json`, with this origin."""
    root = tmp_path / "paper"
    (root / "artifacts").mkdir(parents=True, exist_ok=True)
    (root / "artifacts" / "indices.json").write_text(copied)
    digest = hashlib.sha256(copied.encode()).hexdigest()
    artifact = {
        "id": "indices",
        "path": "artifacts/indices.json",
        "digest": {"algorithm": "sha256", "value": digest},
    }
    if origin is not None:
        artifact["origin"] = origin
    claim = {
        "id": "n",
        "text": "Six.",
        "evidence": [
            {"kind": "metric", "artifact": "indices", "name": "n", "reported": "6", "pointer": "/n"}
        ],
    }
    (root / "repro.yaml").write_text(json.dumps({"artifacts": [artifact], "claims": [claim]}))
    return root / "repro.yaml"


def only(manifest_path, **kwargs):
    report = origins(load(manifest_path), **kwargs)
    assert len(report.origins) == 1
    return report.origins[0]


# ------------------------------------------------------------------------------- the states


def test_a_copy_of_a_committed_file_is_the_same(tmp_path, study, capsys):
    head = commit(study, SOURCE, '{"n": 6}\n')
    path = paper(tmp_path, '{"n": 6}\n', {"repository": REMOTE, "commit": head, "path": SOURCE})
    check = only(path, clones={REMOTE: study})
    assert check.state is OriginState.SAME
    assert check.at_origin == check.pinned == SIX
    assert check.read_from == str(study)

    assert main(["origins", str(path), "--repo", f"{REMOTE}={study}"]) == 0
    out = capsys.readouterr().out
    assert f"  same           indices: {REMOTE} {head[:12]}:{SOURCE}\n" in out
    assert "1 origins: 1 same, 0 differs, 0 absent, 0 unknown commit, 0 not checked" in out


def test_the_committed_bytes_are_read_and_never_the_working_tree(tmp_path, study):
    head = commit(study, SOURCE, '{"n": 6}\n')
    (study / SOURCE).write_text('{"n": 7}\n')
    path = paper(tmp_path, '{"n": 7}\n', {"repository": REMOTE, "commit": head, "path": SOURCE})
    check = only(path, clones={REMOTE: study})
    assert check.state is OriginState.DIFFERS
    assert check.at_origin == SIX


def test_a_copy_of_other_bytes_differs_and_both_digests_are_printed(tmp_path, study, capsys):
    head = commit(study, SOURCE, '{"n": 6}\n')
    path = paper(tmp_path, '{"n": 7}\n', {"repository": REMOTE, "commit": head, "path": SOURCE})
    assert main(["origins", str(path), "--repo", f"{REMOTE}={study}"]) == 1
    out = capsys.readouterr().out
    assert "  DIFFERS        indices:" in out
    assert f"pinned    {SEVEN}" in out
    assert f"at origin {SIX}" in out


def test_a_path_the_commit_does_not_hold_is_absent(tmp_path, study):
    head = commit(study, SOURCE, '{"n": 6}\n')
    origin = {"repository": REMOTE, "commit": head, "path": "results/other.json"}
    check = only(paper(tmp_path, '{"n": 6}\n', origin), clones={REMOTE: study})
    assert check.state is OriginState.ABSENT
    assert check.at_origin is None

    directory = {"repository": REMOTE, "commit": head, "path": "results"}
    check = only(paper(tmp_path, '{"n": 6}\n', directory), clones={REMOTE: study})
    assert check.state is OriginState.ABSENT
    assert "is a tree, not a file" in check.reason


def test_a_path_added_after_the_named_commit_is_absent_at_it(tmp_path, study):
    first = commit(study, "README", "a study\n")
    commit(study, SOURCE, '{"n": 6}\n')
    origin = {"repository": REMOTE, "commit": first, "path": SOURCE}
    path = paper(tmp_path, '{"n": 6}\n', origin)
    assert only(path, clones={REMOTE: study}).state is OriginState.ABSENT
    assert main(["origins", str(path), "--repo", f"{REMOTE}={study}"]) == 1


def test_a_commit_the_clone_does_not_hold_is_unknown(tmp_path, study, capsys):
    commit(study, SOURCE, '{"n": 6}\n')
    origin = {"repository": REMOTE, "commit": "f" * 40, "path": SOURCE}
    path = paper(tmp_path, '{"n": 6}\n', origin)
    check = only(path, clones={REMOTE: study})
    assert check.state is OriginState.UNKNOWN_COMMIT
    assert main(["origins", str(path), "--repo", f"{REMOTE}={study}"]) == 2
    assert "  UNKNOWN COMMIT indices:" in capsys.readouterr().out


def test_with_no_clone_and_no_fetch_nothing_is_read_and_nothing_passes(tmp_path, study, capsys):
    head = commit(study, SOURCE, '{"n": 6}\n')
    path = paper(tmp_path, '{"n": 6}\n', {"repository": REMOTE, "commit": head, "path": SOURCE})
    check = only(path)
    assert check.state is OriginState.NOT_CHECKED
    assert check.at_origin is None and check.read_from == ""
    assert "(--fetch)" in check.reason

    assert main(["origins", str(path)]) == 2
    out = capsys.readouterr().out
    assert "  NOT CHECKED    indices:" in out
    assert "1 same" not in out


def test_a_clone_named_for_another_repository_is_not_read(tmp_path, study):
    head = commit(study, SOURCE, '{"n": 6}\n')
    path = paper(tmp_path, '{"n": 6}\n', {"repository": REMOTE, "commit": head, "path": SOURCE})
    assert only(path, clones={"https://github.com/someone/else": study}).state is (
        OriginState.NOT_CHECKED
    )
    # The spellings of one repository are one repository.
    assert only(path, clones={f"{REMOTE}.git/": study}).state is OriginState.SAME


def test_a_directory_that_is_not_a_clone_is_not_checked(tmp_path, study):
    head = commit(study, SOURCE, '{"n": 6}\n')
    path = paper(tmp_path, '{"n": 6}\n', {"repository": REMOTE, "commit": head, "path": SOURCE})
    empty = tmp_path / "empty"
    empty.mkdir()
    check = only(path, clones={REMOTE: empty})
    assert check.state is OriginState.NOT_CHECKED
    assert "is not a git repository" in check.reason


def test_a_repository_named_by_a_local_path_is_read_from_there(tmp_path, study):
    head = commit(study, SOURCE, '{"n": 6}\n')
    origin = {"repository": "../study", "commit": head, "path": SOURCE}
    assert only(paper(tmp_path, '{"n": 6}\n', origin)).state is OriginState.SAME
    origin = {"repository": str(study), "commit": head, "path": SOURCE}
    assert only(paper(tmp_path, '{"n": 6}\n', origin)).state is OriginState.SAME


def test_a_file_on_disk_that_is_not_the_pin_is_said_beside_the_origin(tmp_path, study, capsys):
    head = commit(study, SOURCE, '{"n": 6}\n')
    path = paper(tmp_path, '{"n": 6}\n', {"repository": REMOTE, "commit": head, "path": SOURCE})
    (path.parent / "artifacts" / "indices.json").write_text('{"n": 8}\n')
    check = only(path, clones={REMOTE: study})
    assert check.state is OriginState.SAME
    assert check.disk_disagrees
    assert main(["origins", str(path), "--repo", f"{REMOTE}={study}"]) == 0
    assert "note: artifacts/indices.json is not the pinned bytes" in capsys.readouterr().out


def test_no_origin_declared_exits_2(tmp_path, capsys):
    path = paper(tmp_path, '{"n": 6}\n', None)
    assert main(["origins", str(path)]) == 2
    assert "no artifact declares an origin" in capsys.readouterr().out


def test_json_names_each_state_and_both_digests(tmp_path, study, capsys):
    head = commit(study, SOURCE, '{"n": 6}\n')
    path = paper(tmp_path, '{"n": 7}\n', {"repository": REMOTE, "commit": head, "path": SOURCE})
    assert main(["origins", str(path), "--repo", f"{REMOTE}={study}", "--format", "json"]) == 1
    found = json.loads(capsys.readouterr().out)["origins"]["origins"][0]
    assert found["state"] == "differs"
    assert found["origin"] == {"repository": REMOTE, "commit": head, "path": SOURCE}
    assert found["at_origin"] != found["pinned"] == found["on_disk"]


# ------------------------------------------------------------------------------ the network


def test_fetch_reads_github_at_the_commit_through_the_fetcher_given(tmp_path):
    head = "a" * 40
    asked = []

    def fetcher(url: str) -> bytes:
        asked.append(url)
        return b'{"n": 6}\n'

    path = paper(tmp_path, '{"n": 6}\n', {"repository": REMOTE, "commit": head, "path": SOURCE})
    check = only(path, fetcher=fetcher)
    assert asked == [f"https://raw.githubusercontent.com/someone/study/{head}/{SOURCE}"]
    assert check.state is OriginState.SAME and check.read_from == asked[0]

    check = only(path, fetcher=lambda url: b'{"n": 7}\n')
    assert check.state is OriginState.DIFFERS


def test_a_fetch_that_fails_is_not_checked(tmp_path):
    def fetcher(url: str) -> bytes:
        raise OriginUnreadableError(f"{url} answered 404 Not Found")

    head = "a" * 40
    path = paper(tmp_path, '{"n": 6}\n', {"repository": REMOTE, "commit": head, "path": SOURCE})
    check = only(path, fetcher=fetcher)
    assert check.state is OriginState.NOT_CHECKED
    assert "answered 404" in check.reason and check.at_origin is None


def test_a_repository_not_on_github_is_never_fetched(tmp_path):
    def fetcher(url: str) -> bytes:
        raise AssertionError(f"fetched {url}")

    origin = {"repository": "https://gitlab.com/a/b", "commit": "a" * 40, "path": SOURCE}
    check = only(paper(tmp_path, '{"n": 6}\n', origin), fetcher=fetcher)
    assert check.state is OriginState.NOT_CHECKED


@pytest.mark.parametrize(
    "repository",
    [
        "https://github.com/someone/study",
        "https://github.com/someone/study.git",
        "git@github.com:someone/study.git",
        "ssh://git@github.com/someone/study",
    ],
)
def test_each_spelling_of_a_github_repository_reads_one_url(repository):
    origin = Origin(repository=repository, commit="b" * 40, path="a dir/f.json")
    assert raw_github_url(origin) == (
        f"https://raw.githubusercontent.com/someone/study/{'b' * 40}/a%20dir/f.json"
    )


# ------------------------------------------------------------------------- the manifest field


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("commit", "main"),
        ("commit", "a1b2c3d"),
        ("commit", "A" * 40),
        ("path", "../secrets.json"),
        ("path", "results/../../x"),
        ("path", "/etc/passwd"),
        ("path", ""),
    ],
)
def test_an_origin_that_names_no_fixed_bytes_is_refused(tmp_path, field, value):
    origin = {"repository": REMOTE, "commit": "a" * 40, "path": SOURCE, field: value}
    with pytest.raises(ManifestError, match=f"artifacts.0.origin.{field}"):
        load(paper(tmp_path, '{"n": 6}\n', origin))


#: `paper(tmp_path, '{"n": 6}\n', None)` as `model_dump_json` wrote it before the field existed,
#: read off the code on `main` at 12af612.
BEFORE = (
    '{"schema_version":"repro/1","project":"","provenance":null,"artifacts":[{"id":"indices",'
    '"path":"artifacts/indices.json","digest":{"algorithm":"sha256","value":'
    '"bc0dc2dd693eb1667a9646d41b3d2459740e82f71678b03100ff3b78e887399a"},'
    '"media_type":"application/octet-stream"}],"claims":[{"id":"n","text":"Six.","where":null,'
    '"registration":"exploratory","registration_note":"","evidence":[{"artifact":"indices",'
    '"kind":"metric","name":"n","reported":"6","pointer":"/n","mode":"printed_precision",'
    '"tolerance":"0"}]}],"runs":[],"regenerations":[],"set_aside":[]}'
)
DIGEST_BEFORE = "9325e1f7441f6049cde54e4d20318d9e2f7410dc16dc67cbd4ca6fa52c4cfe5b"


def test_a_manifest_without_origins_dumps_and_digests_as_before(tmp_path):
    manifest = load(paper(tmp_path, '{"n": 6}\n', None))
    dumped = manifest.model_dump_json()
    assert dumped == BEFORE
    assert Digest.of_text(dumped).value == DIGEST_BEFORE
    assert '"origin"' not in json.dumps(manifest.model_dump(mode="json"))


def test_a_declared_origin_is_dumped(tmp_path):
    origin = {"repository": REMOTE, "commit": "a" * 40, "path": SOURCE}
    dumped = json.loads(load(paper(tmp_path, '{"n": 6}\n', origin)).model_dump_json())
    assert dumped["artifacts"][0]["origin"] == origin


# ------------------------------------------------------------------------------- the exports


def test_the_record_and_the_crate_carry_the_origin_and_read_it_back(tmp_path):
    origin = {"repository": REMOTE, "commit": "a" * 40, "path": SOURCE}
    records = check_records(load(paper(tmp_path, '{"n": 6}\n', origin)), WHEN)
    assert json.loads(records[0].to_json())["reads"][0]["origin"] == origin
    crate = to_ro_crate(records)
    graph = {entity["@id"]: entity for entity in json.loads(crate)["@graph"]}
    based_on = graph[graph["artifacts/indices.json"]["isBasedOn"]["@id"]]
    assert (based_on["name"], based_on["version"]) == (SOURCE, "a" * 40)
    assert graph[based_on["isPartOf"]["@id"]]["codeRepository"] == REMOTE
    assert from_ro_crate(crate) == records


def test_a_record_without_an_origin_says_nothing_of_one(tmp_path):
    records = check_records(load(paper(tmp_path, '{"n": 6}\n', None)), WHEN)
    assert "origin" not in records[0].to_json()
    assert "isBasedOn" not in to_ro_crate(records)
