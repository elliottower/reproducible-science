"""`freeze --osf`, `register` and `link`: a draft is pushed unattended, nothing is registered or
linked unless a person typed the phrase, and everything that reaches OSF is in the log."""

from __future__ import annotations

import datetime
import hashlib
import io
import os
import re
import subprocess
import sys
import urllib.error

import pytest
from prereg import cli, confirm, osf, plan, sidelog
from provenance_core.gitref import clean_env

CONTEXT = b"Shared context for every plan in this project.\n"
DRAFT = {
    "data": {
        "id": "draft1",
        "relationships": {"branched_from": {"data": {"id": "node1", "type": "draft_nodes"}}},
    }
}
UPLOAD_LINK = "https://files.osf.io/v1/resources/node1/providers/osfstorage/"
SUBJECTS = {
    "Artificial Intelligence and Robotics": "subjAI",
    "Science and Technology Studies": "subjSTS",
    "Other Science and Technology Studies": "subjOther",
}


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, env=clean_env(), check=True, capture_output=True)


def _commit(cwd, message="commit"):
    _git("add", "-A", cwd=cwd)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", message, cwd=cwd)


@pytest.fixture
def study(tmp_path, monkeypatch, fake_osf):
    """A committed plan made by `prereg new`, a shared CONTEXT.md beside it, and OSF answering
    the draft, the file upload, the registration and the link."""
    _git("init", "-q", cwd=tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cli._main(["new", "study"]) == 0
    (tmp_path / "CONTEXT.md").write_bytes(CONTEXT)
    _commit(tmp_path, "plan")
    monkeypatch.chdir(tmp_path / "study")

    fake_osf.on("POST", r"/draft_registrations/$", DRAFT)
    fake_osf.on(
        "GET",
        r"/draft_nodes/node1/files/providers/osfstorage/$",
        {"data": {"links": {"upload": UPLOAD_LINK}}},
    )
    fake_osf.on(
        "PUT",
        r"^https://files\.osf\.io/v1/resources/node1/",
        lambda call: {
            "data": {
                "attributes": {
                    "extra": {"hashes": {"sha256": hashlib.sha256(call.body).hexdigest()}}
                }
            }
        },
    )
    fake_osf.on(
        "POST",
        r"/registrations/\?",
        {"data": {"id": "reg01", "links": {"html": "https://osf.io/reg01/"}}},
    )
    fake_osf.on(
        "POST",
        r"/registrations/reg01/view_only_links/",
        {"data": {"id": "vol1", "attributes": {"key": "k3y", "anonymous": True}}},
    )
    fake_osf.on(
        "GET", r"/draft_registrations/[^/]+/$", {"data": {"attributes": {"title": "study"}}}
    )
    fake_osf.on("PATCH", r"/draft_registrations/[^/]+/$", {"data": {}})
    fake_osf.on("PATCH", r"/relationships/subjects/$", {"data": []})
    fake_osf.on("GET", r"/users/me/registrations/", {"data": []})

    def subjects(call):
        # OSF's filter is a substring match, so the lookup has to pick the exact name itself.
        text = re.search(r"filter%5Btext%5D=([^&]+)", call.url).group(1).replace("+", " ")
        hits = [(n, i) for n, i in SUBJECTS.items() if text.casefold() in n.casefold()]
        return {"data": [{"id": i, "attributes": {"text": n}} for n, i in hits]}

    fake_osf.on("GET", r"/providers/registrations/osf/subjects/", subjects)
    fake_osf.on(
        "GET",
        r"/licenses/\?",
        {
            "data": [
                {"id": "lic_ccby", "attributes": {"name": "CC-By Attribution 4.0 International"}}
            ]
        },
    )
    monkeypatch.setattr(osf, "RETRY_WAIT", 0)
    return tmp_path / "study"


@pytest.fixture
def tty(monkeypatch):
    """What the person types at the terminal, and what they were shown."""
    shown = io.StringIO()
    answer = {"line": ""}

    class Writer(io.StringIO):
        def close(self):  # keep what was shown readable after the `with` closes it
            shown.write(self.getvalue())
            super().close()

    def open_tty():
        return io.StringIO(answer["line"] + "\n"), Writer()

    monkeypatch.setattr(confirm, "_open_tty", open_tty)

    class Terminal:
        @staticmethod
        def types(line: str) -> None:
            answer["line"] = line

        @staticmethod
        def shown() -> str:
            return shown.getvalue()

    return Terminal


def _plan(study):
    return (study / "PREREG.md").read_text()


def _digest(study):
    digest = cli.frozen_digest(study / "PREREG.md")
    assert digest is not None
    return digest


def _entries(study):
    return cli._entries(study / "PREREG.md")


def _edit(path, text: str) -> None:
    """Write over a frozen plan: a freeze leaves it read-only."""
    path.chmod(0o644)
    path.write_text(text)


def _freeze_and_push(study, tty, *extra: str) -> int:
    del tty  # a draft is pushed without asking; the fixture stays so the tests read alike
    rc = cli._main(["freeze", "--osf", "--attach", "../CONTEXT.md", *extra])
    _commit(study.parent, "freeze")
    return rc


def _no_terminal(monkeypatch, tmp_path):
    """The real `_open_tty`, pointed at a terminal that does not exist: an agent's shell."""
    monkeypatch.setattr(confirm, "TTY", str(tmp_path / "no-such-terminal"))


# --- freeze --osf --------------------------------------------------------------------------


def test_freeze_pushes_the_draft_and_logs_each_attachment_with_its_hash(study, tty, fake_osf):
    assert _freeze_and_push(study, tty) == 0

    entries = _entries(study)
    assert any(f"osf draft draft1 of plan {_digest(study)[:16]}" in e for e in entries)
    expected = hashlib.sha256(CONTEXT).hexdigest()
    assert any(f"osf attached CONTEXT.md sha256 {expected}" in e for e in entries)

    [put] = fake_osf.calls_to("PUT", r"files\.osf\.io")
    assert put.body == CONTEXT, "the bytes hashed must be the bytes sent"
    assert "kind=file" in put.url and "name=CONTEXT.md" in put.url
    assert cli._main(["check"]) == 0, "the OSF entries must extend the log's chain, not break it"


def test_a_draft_is_pushed_with_no_terminal(study, monkeypatch, fake_osf, tmp_path):
    """A draft is private and deletable, so an agent's shell can push one unattended."""
    _no_terminal(monkeypatch, tmp_path)
    assert cli._main(["freeze", "--osf", "--attach", "../CONTEXT.md"]) == 0
    assert fake_osf.calls_to("POST", r"/draft_registrations/$")
    assert any("osf draft draft1" in e for e in _entries(study))


def test_the_metadata_page_is_filled_from_the_flags(study, tty, fake_osf, capsys):
    assert (
        _freeze_and_push(
            study,
            tty,
            "--subject", "Artificial Intelligence and Robotics",
            "--subject", "Science and Technology Studies",
            "--description", "What the study compares.",
            "--tag", "AI incidents",
            "--tag", "preregistration",
            "--category", "hypothesis",
            "--copyright-holder", "A. Author",
            "--title-prefix", "EXPT01: ",
        )
        == 0
    )  # fmt: skip
    [patch] = fake_osf.calls_to("PATCH", r"/draft_registrations/draft1/$")
    data = patch.json["data"]
    assert data["attributes"] == {
        "title": "EXPT01: study",
        "description": "What the study compares.",
        "tags": ["AI incidents", "preregistration"],
        "category": "hypothesis",
        "node_license": {"year": plan.today()[:4], "copyright_holders": ["A. Author"]},
    }
    assert data["relationships"]["license"]["data"] == {"type": "licenses", "id": "lic_ccby"}
    [subjects] = fake_osf.calls_to("PATCH", r"/draft_registrations/draft1/relationships/subjects/")
    assert [d["id"] for d in subjects.json["data"]] == ["subjAI", "subjSTS"], (
        "a substring hit such as 'Other Science and Technology Studies' must not be taken"
    )
    assert "no subject" not in capsys.readouterr().out


def test_a_push_without_a_prefix_still_sends_the_plan_title(study, tty, fake_osf):
    """OSF ignores the title in the POST that creates a draft, so only the PATCH sets it."""
    assert _freeze_and_push(study, tty) == 0
    [patch] = fake_osf.calls_to("PATCH", r"/draft_registrations/draft1/$")
    assert patch.json["data"]["attributes"] == {"title": "study"}


def test_a_push_with_no_subject_warns_that_osf_will_not_register_it(study, tty, capsys):
    assert _freeze_and_push(study, tty) == 0
    assert "OSF refuses to register a draft without one" in capsys.readouterr().out


def test_an_unknown_subject_is_refused_before_anything_is_written(study, fake_osf):
    before = _plan(study)
    assert cli._main(["freeze", "--osf", "--subject", "Astrology"]) == 1
    assert fake_osf.writes == []
    assert _plan(study) == before


def test_an_unknown_category_is_refused_before_anything_is_written(study, fake_osf):
    before = _plan(study)
    assert cli._main(["freeze", "--osf", "--category", "misc"]) == 1
    assert fake_osf.writes == []
    assert _plan(study) == before


def test_metadata_flags_without_osf_are_refused(study):
    with pytest.raises(SystemExit):
        cli._main(["freeze", "--subject", "Artificial Intelligence and Robotics"])


def test_a_plan_that_cannot_map_is_refused_before_anyone_is_asked(study, tty, fake_osf):
    p = study / "PREREG.md"
    p.write_text(
        p.read_text().replace("## Randomization", "## Decision rule\n\np<.05\n\n## Randomization")
    )
    _commit(study.parent, "odd heading")
    before = _plan(study)
    assert cli._main(["freeze", "--osf"]) == 1
    assert tty.shown() == ""
    assert fake_osf.writes == []
    assert _plan(study) == before


def test_an_upload_osf_hashes_differently_is_not_logged_as_attached(study, tty, fake_osf):
    fake_osf.on(
        "PUT",
        r"files\.osf\.io",
        {"data": {"attributes": {"extra": {"hashes": {"sha256": "0" * 64}}}}},
    )
    assert _freeze_and_push(study, tty) == 1
    assert not any("osf attached" in e for e in _entries(study))
    assert any("osf draft draft1" in e for e in _entries(study)), "the draft does exist"


def test_attach_without_osf_is_refused(study):
    with pytest.raises(SystemExit):
        cli._main(["freeze", "--attach", "../CONTEXT.md"])


def test_a_missing_attachment_is_refused_before_anything_is_written(study, fake_osf):
    before = _plan(study)
    assert cli._main(["freeze", "--osf", "--attach", "../MISSING.md"]) == 1
    assert fake_osf.calls == []
    assert _plan(study) == before


def test_a_push_a_registration_and_a_link_write_nothing_into_the_plan(study, tty, fake_osf):
    before = (study / "PREREG.md").read_bytes()
    _registered(study, tty)
    tty.types("link reg01")
    assert cli._main(["link", "--anonymous", "--access", "results seen"]) == 0

    assert (study / "PREREG.md").read_bytes() == before
    logged = (study / "PREREG.log").read_text()
    for event in (
        "osf draft draft1",
        "osf attached CONTEXT.md",
        "osf registration reg01",
        "osf view-only link vol1",
    ):
        assert event in logged
    assert cli._main(["check"]) == 0


def test_a_plan_frozen_without_a_draft_is_pushed_later_and_not_frozen_again(study, fake_osf):
    assert cli._main(["freeze"]) == 0
    record = (study / ".prereg" / "PREREG.md.json").read_bytes()

    assert cli._main(["freeze", "--osf"]) == 1, (
        "the push is logged now, so it must say what was seen"
    )
    assert fake_osf.writes == []
    assert cli._main(["freeze", "--osf", "--access", "no results seen"]) == 0

    assert (study / ".prereg" / "PREREG.md.json").read_bytes() == record
    [entry] = [e for e in _entries(study) if "osf draft" in e]
    assert f"osf draft draft1 of plan {_digest(study)[:16]}" in entry and "no results seen" in entry
    assert cli._main(["freeze", "--osf", "--access", "no results seen"]) == 1
    assert len(fake_osf.calls_to("POST", r"/draft_registrations/$")) == 1
    assert cli._main(["check"]) == 0


def test_a_changed_plan_is_not_pushed(study, fake_osf):
    assert cli._main(["freeze"]) == 0
    p = study / "PREREG.md"
    _edit(p, p.read_text().replace("## Randomization", "## Randomization\n\nBy coin."))
    assert cli._main(["freeze", "--osf", "--access", "nothing run"]) == 1
    assert fake_osf.writes == []


# --- register ------------------------------------------------------------------------------


def test_register_needs_an_explicit_embargo_or_immediate(study, tty, fake_osf):
    assert _freeze_and_push(study, tty) == 0
    with pytest.raises(SystemExit):
        cli._main(["register", "--access", "nothing run"])
    with pytest.raises(SystemExit):
        cli._main(["register", "--immediate", "--embargo", "2030-01-01", "--access", "nothing run"])
    assert fake_osf.calls_to("POST", r"/registrations/") == []


def test_register_under_embargo_sends_the_logged_draft_and_logs_the_result(study, tty, fake_osf):
    assert _freeze_and_push(study, tty) == 0
    tty.types("register draft1")
    assert cli._main(["register", "--embargo", "2030-01-01", "--access", "no results seen"]) == 0

    [call] = fake_osf.calls_to("POST", r"/registrations/")
    assert "version=2.20" in call.url
    assert call.json["data"]["attributes"] == {
        "draft_registration_id": "draft1",
        "embargo_end_date": "2030-01-01T00:00:00",
    }
    last = _entries(study)[-1]
    assert "osf registration reg01 from draft draft1, embargo until 2030-01-01" in last
    assert "https://osf.io/reg01/" in last
    assert "no results seen" in last
    shown = tty.shown()
    assert _digest(study) in shown and "draft1" in shown and "CONTEXT.md" in shown
    assert cli._main(["check"]) == 0


def test_register_immediate_sends_no_embargo(study, tty, fake_osf):
    assert _freeze_and_push(study, tty) == 0
    tty.types("register draft1")
    assert cli._main(["register", "--immediate", "--access", "nothing run"]) == 0
    [call] = fake_osf.calls_to("POST", r"/registrations/")
    assert call.json["data"]["attributes"]["embargo_end_date"] is None
    assert "immediate" in _entries(study)[-1]


def test_register_with_the_wrong_phrase_sends_nothing(study, tty, fake_osf):
    assert _freeze_and_push(study, tty) == 0
    tty.types("register draft2")
    entries = _entries(study)
    assert cli._main(["register", "--immediate", "--access", "nothing run"]) == 1
    assert fake_osf.calls_to("POST", r"/registrations/") == []
    assert _entries(study) == entries


def test_register_with_no_terminal_sends_nothing(study, tty, monkeypatch, fake_osf, tmp_path):
    assert _freeze_and_push(study, tty) == 0
    _no_terminal(monkeypatch, tmp_path)
    entries = _entries(study)
    assert cli._main(["register", "--immediate", "--access", "nothing run"]) == 1
    assert fake_osf.calls_to("POST", r"/registrations/") == []
    assert _entries(study) == entries


def test_register_does_not_read_the_phrase_from_stdin(study, tty, monkeypatch, fake_osf, capsys):
    """Piping the phrase is exactly what an unattended process would do."""
    assert _freeze_and_push(study, tty) == 0
    monkeypatch.setattr(sys, "stdin", io.StringIO("register draft1\n" * 5))
    tty.types("")
    assert cli._main(["register", "--immediate", "--access", "nothing run"]) == 1
    assert fake_osf.calls_to("POST", r"/registrations/") == []
    assert "cancelled" in capsys.readouterr().out


def test_register_reads_the_token_only_after_the_phrase(study, tty, monkeypatch, fake_osf):
    """Reading a pipe-backed token asks the person to approve; a cancelled command must not."""
    assert _freeze_and_push(study, tty) == 0
    reads = []
    monkeypatch.setattr(osf, "require_token", lambda: reads.append(1) or "t")
    tty.types("no")
    assert cli._main(["register", "--immediate", "--access", "nothing run"]) == 1
    assert reads == []


def test_register_refuses_a_plan_changed_since_the_freeze(study, tty, fake_osf):
    assert _freeze_and_push(study, tty) == 0
    p = study / "PREREG.md"
    _edit(p, p.read_text().replace("## Randomization", "## Randomization\n\nBy coin."))
    tty.types("register draft1")
    assert cli._main(["register", "--immediate", "--access", "nothing run"]) == 1
    assert fake_osf.calls_to("POST", r"/registrations/") == []


def test_register_refuses_a_draft_made_from_an_earlier_freeze(
    study, tty, fake_osf, frozen_in_place
):
    """After a forced re-freeze the plan the hash describes is not the one on OSF.

    Only a plan frozen in place can be re-frozen, so this starts from one."""
    p = study / "PREREG.md"
    p.write_bytes(frozen_in_place)
    _commit(study.parent, "frozen in place")
    assert cli._main(["freeze", "--force", "--osf", "--access", "nothing run"]) == 0
    assert any("osf draft draft1" in e for e in _entries(study))
    p.write_text(p.read_text().replace("## Randomization", "## Randomization\n\nBy coin."))
    _commit(study.parent, "edit")
    assert cli._main(["freeze", "--force", "--access", "nothing run"]) == 0
    tty.types("register draft1")
    assert cli._main(["register", "--immediate", "--access", "nothing run"]) == 1
    assert fake_osf.calls_to("POST", r"/registrations/") == []


def test_register_refuses_without_a_logged_draft(study, fake_osf):
    assert cli._main(["freeze"]) == 0
    assert cli._main(["register", "--immediate", "--access", "nothing run"]) == 1
    assert fake_osf.calls == []


def test_register_refuses_a_draft_already_registered(study, tty, fake_osf):
    assert _freeze_and_push(study, tty) == 0
    tty.types("register draft1")
    assert cli._main(["register", "--immediate", "--access", "nothing run"]) == 0
    assert cli._main(["register", "--immediate", "--access", "nothing run"]) == 1
    assert len(fake_osf.calls_to("POST", r"/registrations/")) == 1


def test_register_prints_osfs_refusal_and_logs_nothing(study, tty, fake_osf, capsys):
    assert _freeze_and_push(study, tty) == 0
    fake_osf.on(
        "POST",
        r"/registrations/\?",
        (400, {"errors": [{"detail": "Registration must have at least one subject"}]}),
    )
    entries = _entries(study)
    tty.types("register draft1")
    assert cli._main(["register", "--immediate", "--access", "nothing run"]) == 1
    assert "at least one subject" in capsys.readouterr().out
    assert _entries(study) == entries


def test_an_embargo_in_the_past_is_refused_before_asking(study, tty, fake_osf):
    assert _freeze_and_push(study, tty) == 0
    tty.types("register draft1")
    assert cli._main(["register", "--embargo", "2001-01-01", "--access", "nothing run"]) == 1
    assert fake_osf.calls_to("POST", r"/registrations/") == []


def _listed(reg_id="reg01", title="study", minutes=0):
    created = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) + datetime.timedelta(
        minutes=minutes
    )
    return {"id": reg_id, "attributes": {"title": title, "date_created": created.isoformat()}}


def test_a_502_that_registered_anyway_is_recovered_not_retried(study, tty, fake_osf, capsys):
    """OSF answered 502 to the POST while creating the registration. Retrying got 403."""
    assert _freeze_and_push(study, tty) == 0
    fake_osf.on("POST", r"/registrations/\?", (502, {"errors": [{"detail": "Bad Gateway"}]}))
    fake_osf.on("GET", r"/users/me/registrations/", {"data": [_listed("t6ns4")]})
    tty.types("register draft1")
    assert cli._main(["register", "--immediate", "--access", "nothing run"]) == 0
    assert len(fake_osf.calls_to("POST", r"/registrations/")) == 1, "found, so not sent again"
    last = _entries(study)[-1]
    assert "osf registration t6ns4 from draft draft1, immediate" in last
    assert "found after OSF error 502" in last
    assert cli._main(["check"]) == 0


def test_a_502_that_did_not_register_is_retried(study, tty, fake_osf):
    assert _freeze_and_push(study, tty) == 0
    answers = iter([(502, {}), (502, {})])

    def flaky(call):
        answer = next(answers, None)
        if answer is None:
            return {"data": {"id": "reg01", "links": {"html": "https://osf.io/reg01/"}}}
        raise urllib.error.HTTPError(call.url, answer[0], "error", {}, io.BytesIO(b"{}"))

    fake_osf.on("POST", r"/registrations/\?", flaky)
    tty.types("register draft1")
    assert cli._main(["register", "--immediate", "--access", "nothing run"]) == 0
    assert len(fake_osf.calls_to("POST", r"/registrations/")) == 3
    assert "osf registration reg01 from draft draft1" in _entries(study)[-1]
    assert "found after" not in _entries(study)[-1]


def test_an_old_registration_with_the_same_title_is_not_taken_for_this_one(study, tty, fake_osf):
    assert _freeze_and_push(study, tty) == 0
    fake_osf.on("POST", r"/registrations/\?", (502, {}))
    fake_osf.on("GET", r"/users/me/registrations/", {"data": [_listed("old01", minutes=-90)]})
    entries = _entries(study)
    tty.types("register draft1")
    assert cli._main(["register", "--immediate", "--access", "nothing run"]) == 1
    assert len(fake_osf.calls_to("POST", r"/registrations/")) == osf.ATTEMPTS
    assert _entries(study) == entries


def test_a_400_is_reported_at_once_and_not_retried(study, tty, fake_osf):
    assert _freeze_and_push(study, tty) == 0
    fake_osf.on("POST", r"/registrations/\?", (400, {"errors": [{"detail": "no subject"}]}))
    tty.types("register draft1")
    assert cli._main(["register", "--immediate", "--access", "nothing run"]) == 1
    assert len(fake_osf.calls_to("POST", r"/registrations/")) == 1
    assert fake_osf.calls_to("GET", r"/users/me/registrations/") == []


@pytest.fixture
def three_plans(tmp_path, monkeypatch, fake_osf, study):
    """Three frozen plans side by side, each with its own draft."""
    del study
    for name in ("b", "c"):
        assert cli._main(["new", str(tmp_path / name)]) == 0
    _commit(tmp_path, "more plans")
    drafts = iter(["draft1", "draft2", "draft3"])
    fake_osf.on(
        "POST",
        r"/draft_registrations/$",
        lambda call: {
            "data": {
                "id": next(drafts),
                "relationships": {"branched_from": {"data": {"id": "node1"}}},
            }
        },
    )
    for name in ("study", "b", "c"):
        monkeypatch.chdir(tmp_path / name)
        assert cli._main(["freeze", "--osf"]) == 0
    _commit(tmp_path, "freeze")
    regs = iter(["reg01", "reg02", "reg03"])
    fake_osf.on(
        "POST",
        r"/registrations/\?",
        lambda call: {"data": {"id": next(regs), "links": {}}},
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _batch_phrase(*ids):
    digest = hashlib.sha256(",".join(ids).encode()).hexdigest()[:8]
    return f"register {len(ids)} plans {digest}"


def test_one_phrase_registers_every_plan_below(three_plans, tty, fake_osf):
    tty.types(_batch_phrase("draft2", "draft3", "draft1"))  # b, c, study: sorted by path
    assert cli._main(["register", "--all", "--immediate", "--access", "nothing run"]) == 0
    sent = [c.json["data"]["attributes"]["draft_registration_id"] for c in fake_osf.calls_to(
        "POST", r"/registrations/\?")]  # fmt: skip
    assert sorted(sent) == ["draft1", "draft2", "draft3"]
    shown = tty.shown()
    assert all(d in shown for d in ("draft1", "draft2", "draft3"))
    for name in ("study", "b", "c"):
        assert "osf registration reg0" in sidelog.entries(three_plans / name / "PREREG.md")[-1]
    assert cli._main(["check"]) == 0


def test_the_single_plan_phrase_does_not_confirm_a_batch(three_plans, tty, fake_osf):
    tty.types("register draft1")
    assert cli._main(["register", "--all", "--immediate", "--access", "nothing run"]) == 1
    assert fake_osf.calls_to("POST", r"/registrations/") == []


def test_a_batch_with_one_changed_plan_sends_nothing(three_plans, tty, fake_osf):
    p = three_plans / "c" / "PREREG.md"
    _edit(p, p.read_text().replace("## Randomization", "## Randomization\n\nBy coin."))
    tty.types(_batch_phrase("draft2", "draft3", "draft1"))
    assert cli._main(["register", "--all", "--immediate", "--access", "nothing run"]) == 1
    assert fake_osf.calls_to("POST", r"/registrations/") == []
    assert tty.shown() == "", "nobody is asked to confirm a batch that cannot go through"


def test_a_batch_rerun_skips_the_plans_already_registered(three_plans, tty, fake_osf):
    tty.types(_batch_phrase("draft2", "draft3", "draft1"))
    assert cli._main(["register", "--all", "--immediate", "--access", "nothing run"]) == 0
    _commit(three_plans, "registered")
    assert cli._main(["register", "--all", "--immediate", "--access", "nothing run"]) == 1
    assert len(fake_osf.calls_to("POST", r"/registrations/\?")) == 3


# --- link ----------------------------------------------------------------------------------


def _registered(study, tty):
    assert _freeze_and_push(study, tty) == 0
    tty.types("register draft1")
    assert cli._main(["register", "--embargo", "2030-01-01", "--access", "nothing run"]) == 0


def test_an_anonymous_link_is_created_and_logged_without_its_key(study, tty, fake_osf, capsys):
    _registered(study, tty)
    tty.types("link reg01")
    assert (
        cli._main(["link", "--anonymous", "--name", "NeurIPS review", "--access", "results seen"])
        == 0
    )

    [call] = fake_osf.calls_to("POST", r"/view_only_links/")
    assert "version=2.20" in call.url
    assert call.json["data"]["attributes"] == {"anonymous": True, "name": "NeurIPS review"}
    last = _entries(study)[-1]
    assert "osf view-only link vol1 on reg01, anonymous" in last and "results seen" in last
    assert "osf view-only link vol1" in (study / "PREREG.log").read_text()
    assert "k3y" not in (study / "PREREG.log").read_text(), (
        "the key opens the registration; it stays out of the log"
    )
    assert "https://osf.io/reg01/?view_only=k3y" in capsys.readouterr().out
    assert cli._main(["check"]) == 0


def test_a_named_link_sends_anonymous_false(study, tty, fake_osf):
    _registered(study, tty)
    tty.types("link reg01")
    assert cli._main(["link", "--access", "results seen"]) == 0
    [call] = fake_osf.calls_to("POST", r"/view_only_links/")
    assert call.json["data"]["attributes"] == {"anonymous": False}
    assert "named" in _entries(study)[-1]


def test_a_link_with_the_wrong_phrase_sends_nothing(study, tty, fake_osf):
    _registered(study, tty)
    tty.types("link reg02")
    assert cli._main(["link", "--anonymous", "--access", "results seen"]) == 1
    assert fake_osf.calls_to("POST", r"/view_only_links/") == []


def test_a_link_with_no_terminal_sends_nothing(study, tty, monkeypatch, fake_osf, tmp_path):
    _registered(study, tty)
    _no_terminal(monkeypatch, tmp_path)
    assert cli._main(["link", "--anonymous", "--access", "results seen"]) == 1
    assert fake_osf.calls_to("POST", r"/view_only_links/") == []


def test_a_link_needs_a_logged_registration(study, fake_osf):
    assert cli._main(["link", "--anonymous", "--access", "results seen"]) == 1
    assert fake_osf.calls == []


def test_the_real_terminal_path_is_read_and_must_match_exactly(monkeypatch):
    """`_open_tty` unmocked, against a real pseudo-terminal standing in for /dev/tty."""
    for typed, accepted in (("register abc", True), ("register abx", False), ("", False)):
        controller, terminal = os.openpty()
        try:
            monkeypatch.setattr(confirm, "TTY", os.ttyname(terminal))
            os.write(controller, typed.encode() + b"\n")
            if accepted:
                confirm.confirm(["summary"], "register abc")
            else:
                with pytest.raises(confirm.NotConfirmed):
                    confirm.confirm(["summary"], "register abc")
        finally:
            os.close(controller)
            os.close(terminal)
