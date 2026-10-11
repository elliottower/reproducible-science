"""`results annotate`: a stated link from named bytes to something outside the ledger."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from results import ledger

LINK = ("--kind", "wandb:artifact", "--ref", "lab/study/model:v3")
SHA256 = "sha256:" + "0123456789abcdef" * 4


def run_cli(*args, cwd, env=None):
    base = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC"))}
    return subprocess.run(
        [sys.executable, "-m", "results.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**base, **(env or {})},
    )


def project(tmp_path):
    run_cli("init", cwd=tmp_path)
    (tmp_path / "model.pt").write_text("weights\n")
    return tmp_path


def ledger_bytes(tmp_path):
    return (tmp_path / ".results" / "ledger.jsonl").read_bytes()


def last_event(tmp_path):
    return ledger.read_ledger(tmp_path / ".results" / "ledger.jsonl")[-1]


def test_an_annotation_records_the_digest_of_the_subject_and_the_target(tmp_path):
    project(tmp_path)
    r = run_cli("annotate", "model.pt", *LINK, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    event = last_event(tmp_path)
    assert {k: v for k, v in event.items() if k not in ("seq", "timestamp", "prev_hash")} == {
        "event": "annotation",
        "subjects": [
            {
                "path": "model.pt",
                "sha256": ledger.sha256_of_file(tmp_path / "model.pt"),
                "kind": "file",
            }
        ],
        "target": {"kind": "wandb:artifact", "ref": "lab/study/model:v3"},
        "status": "linked, not checked",
        "note": "",
    }
    assert "linked, not checked: the ledger records that this link was stated" in r.stdout
    assert "Nothing was fetched or compared." in r.stdout


def test_by_note_and_location_are_recorded_as_typed(tmp_path):
    project(tmp_path)
    run_cli(
        "annotate",
        "model.pt",
        "--kind",
        "doi:dataset",
        "--ref",
        "10.5281/zenodo.1234567",
        "--by",
        "A. Reader",
        "--note",
        "the checkpoint behind Table 2",
        "--location",
        "Table 2",
        cwd=tmp_path,
    )
    event = last_event(tmp_path)
    assert event["target"] == {"kind": "doi:dataset", "ref": "10.5281/zenodo.1234567"}
    assert event["by"] == "A. Reader"
    assert event["note"] == "the checkpoint behind Table 2"
    assert event["location"] == "Table 2"


@pytest.mark.parametrize(
    "kind", ["wandb", "wandb:", ":artifact", "WandB:artifact", "wandb:art ifact", "a:b:c", "a/b:c"]
)
def test_a_malformed_kind_writes_nothing(tmp_path, kind):
    project(tmp_path)
    before = ledger_bytes(tmp_path)
    r = run_cli("annotate", "model.pt", "--kind", kind, "--ref", "x", cwd=tmp_path)
    assert r.returncode == 1
    assert "namespace:type" in r.stdout
    assert ledger_bytes(tmp_path) == before


@pytest.mark.parametrize(
    "kind", ["osf:node", "url:page", "zenodo:record", "hf:dataset", "x-1.y:z_2"]
)
def test_any_well_formed_kind_is_accepted(tmp_path, kind):
    project(tmp_path)
    r = run_cli("annotate", "model.pt", "--kind", kind, "--ref", "x", cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert last_event(tmp_path)["target"]["kind"] == kind


def test_kind_and_ref_are_required(tmp_path):
    project(tmp_path)
    before = ledger_bytes(tmp_path)
    for dropped in ("--kind", "--ref"):
        at = LINK.index(dropped)
        args = LINK[:at] + LINK[at + 2 :]
        r = run_cli("annotate", "model.pt", *args, cwd=tmp_path)
        assert r.returncode == 2, dropped
        assert dropped in r.stderr
    blank = run_cli("annotate", "model.pt", "--kind", "url:page", "--ref", "  ", cwd=tmp_path)
    assert blank.returncode == 1
    assert ledger_bytes(tmp_path) == before


def test_a_path_that_is_not_a_file_writes_nothing(tmp_path):
    project(tmp_path)
    before = ledger_bytes(tmp_path)
    r = run_cli("annotate", "absent.pt", *LINK, cwd=tmp_path)
    assert r.returncode == 1
    assert ledger_bytes(tmp_path) == before


def test_no_session_is_recorded_even_inside_claude_code(tmp_path):
    project(tmp_path)
    env = {
        "CLAUDECODE": "1",
        "CLAUDE_CODE_EXECPATH": "/somewhere/claude/versions/2.1.295",
        "CLAUDE_CODE_SESSION_ID": "0f0f0f0f-aaaa-bbbb-cccc-121212121212",
    }
    r = run_cli("annotate", "model.pt", *LINK, "--by", "A. Reader", cwd=tmp_path, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    event = last_event(tmp_path)
    assert not {"session", "model", "harness", "harness_version", "session_id"} & set(event)
    line = ledger_bytes(tmp_path).splitlines()[-1].decode()
    for leaked in ("Claude", "2.1.295", "0f0f0f0f", "session", "harness", 'model"'):
        assert leaked not in line, leaked


def test_a_well_formed_digest_is_stored_as_stated(tmp_path):
    project(tmp_path)
    for stated in (SHA256, "md5:" + "ab" * 16, "blake3:" + "CD" * 20):
        r = run_cli("annotate", "model.pt", *LINK, "--digest", stated, cwd=tmp_path)
        assert r.returncode == 0, r.stdout + r.stderr
        assert last_event(tmp_path)["target"]["digest"] == stated
    assert last_event(tmp_path)["subjects"][0]["sha256"] != stated.split(":")[1]


@pytest.mark.parametrize(
    "digest",
    ["0123456789abcdef" * 4, "sha256:" + "0" * 63, "sha256:" + "g" * 64, "sha256:", "md5:abc"],
)
def test_a_malformed_digest_writes_nothing(tmp_path, digest):
    project(tmp_path)
    before = ledger_bytes(tmp_path)
    r = run_cli("annotate", "model.pt", *LINK, "--digest", digest, cwd=tmp_path)
    assert r.returncode == 1
    assert "algorithm:hex" in r.stdout
    assert ledger_bytes(tmp_path) == before


def test_verify_reports_an_annotated_file_that_changed_as_stale_and_does_not_fail(tmp_path):
    project(tmp_path)
    run_cli("annotate", "model.pt", *LINK, "--by", "A. Reader", cwd=tmp_path)
    recorded = ledger.sha256_of_file(tmp_path / "model.pt")

    current = run_cli("verify", "--files", cwd=tmp_path)
    assert current.returncode == 0, current.stdout
    assert "annotations (linked, not checked):" in current.stdout
    assert "wandb:artifact  lab/study/model:v3  [A. Reader]" in current.stdout
    assert "current      model.pt" in current.stdout
    assert "STALE" not in current.stdout

    (tmp_path / "model.pt").write_text("other weights\n")
    now = ledger.sha256_of_file(tmp_path / "model.pt")
    stale = run_cli("verify", "--files", cwd=tmp_path)
    assert stale.returncode == 0, stale.stdout
    assert "STALE        model.pt" in stale.stdout
    assert f"annotated {recorded[:16]}…, now {now[:16]}…" in stale.stdout
    assert "1 annotated file(s) are no longer the bytes the link was stated of" in stale.stdout

    (tmp_path / "model.pt").unlink()
    missing = run_cli("verify", "--files", cwd=tmp_path)
    assert missing.returncode == 0, missing.stdout
    assert "MISSING      model.pt" in missing.stdout


def test_an_annotation_is_not_a_seal(tmp_path):
    project(tmp_path)
    run_cli("annotate", "model.pt", *LINK, cwd=tmp_path)
    (tmp_path / "model.pt").write_text("other weights\n")
    run_cli("annotate", "model.pt", *LINK, cwd=tmp_path)
    r = run_cli("verify", "--files", cwd=tmp_path)
    assert r.returncode == 0, r.stdout
    assert "RESEALED" not in r.stdout
    assert "CHANGED" not in r.stdout
    assert "  ok " not in r.stdout


def test_without_files_verify_lists_the_annotation_and_says_the_subject_was_not_checked(tmp_path):
    project(tmp_path)
    run_cli(
        "annotate", "model.pt", *LINK, "--digest", SHA256, "--location", "Table 2", cwd=tmp_path
    )
    r = run_cli("verify", cwd=tmp_path)
    assert r.returncode == 0, r.stdout
    assert "annotations (linked, not checked):" in r.stdout
    assert "wandb:artifact  lab/study/model:v3" in r.stdout
    assert f"digest as stated: {SHA256}" in r.stdout
    assert "appears in: Table 2" in r.stdout
    assert "not checked  model.pt" in r.stdout


def test_the_chain_stays_intact_with_annotations_among_the_other_events(tmp_path):
    project(tmp_path)
    lp = tmp_path / ".results" / "ledger.jsonl"
    run_cli("seal", "model.pt", cwd=tmp_path)
    run_cli("annotate", "model.pt", *LINK, cwd=tmp_path)
    run_cli("run", "model.pt", "--run-id", "r1", cwd=tmp_path)
    run_cli("annotate", "model.pt", "--kind", "osf:node", "--ref", "abc12", cwd=tmp_path)
    run_cli("claim", "accuracy 0.91", "--run-id", "r1", cwd=tmp_path)
    assert ledger.verify(lp) == (ledger.ChainStatus.INTACT, [])
    assert [e["event"] for e in ledger.read_ledger(lp)] == [
        "init",
        "seal",
        "annotation",
        "run",
        "annotation",
        "claim",
    ]
    r = run_cli("verify", "--files", cwd=tmp_path)
    assert r.returncode == 0, r.stdout
    assert "all checks passed." in r.stdout

    tampered = lp.read_text().replace("lab/study/model:v3", "lab/study/model:v4")
    lp.write_text(tampered)
    assert ledger.verify(lp)[0] is ledger.ChainStatus.EDITED
