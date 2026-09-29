"""`freeze --osf`, `register` and `link`: nothing reaches OSF unless a person typed the phrase,
and everything that does reach it is in the log."""

from __future__ import annotations

import hashlib
import io
import os
import re
import subprocess
import sys

import pytest
from prereg import cli, confirm, log, osf, plan
from provenance_core.gitref import clean_env

CONTEXT = b"Shared context for every plan in this project.\n"
DRAFT = {
    "data": {
        "id": "draft1",
        "relationships": {"branched_from": {"data": {"id": "node1", "type": "draft_nodes"}}},
    }
}
UPLOAD_LINK = "https://files.osf.io/v1/resources/node1/providers/osfstorage/"


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
    return re.search(r"`([0-9a-f]{64})`", _plan(study)).group(1)


def _entries(study):
    return log.log_lines(_plan(study))


def _push_phrase(study):
    """The phrase `freeze --osf` asks for: the digest the freeze is about to record."""
    frozen = plan.rewrite_status(_plan(study), "0" * 40, "0" * 64, plan.today())
    return f"push {plan.sha256_of(plan.plan_of(frozen))[:12]}"


def _freeze_and_push(study, tty) -> int:
    tty.types(_push_phrase(study))
    rc = cli._main(["freeze", "--osf", "--attach", "../CONTEXT.md"])
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
    assert expected in tty.shown(), "the confirmation must show what will be attached"
    assert cli._main(["check"]) == 0, "the OSF entries must extend the log's chain, not break it"


def test_a_wrong_phrase_sends_nothing_and_freezes_nothing(study, tty, fake_osf):
    before = _plan(study)
    tty.types("yes")
    assert cli._main(["freeze", "--osf", "--attach", "../CONTEXT.md"]) == 1
    assert fake_osf.writes == []
    assert _plan(study) == before, "a cancelled push must leave the plan unfrozen"


def test_with_no_terminal_no_draft_is_pushed(study, monkeypatch, fake_osf, tmp_path):
    _no_terminal(monkeypatch, tmp_path)
    before = _plan(study)
    assert cli._main(["freeze", "--osf", "--attach", "../CONTEXT.md"]) == 1
    assert fake_osf.writes == []
    assert _plan(study) == before


def test_the_push_phrase_on_stdin_is_not_read(study, tty, monkeypatch, fake_osf, capsys):
    """Piping the phrase is exactly what an unattended process would do."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{_push_phrase(study)}\n" * 5))
    tty.types("")
    assert cli._main(["freeze", "--osf"]) == 1
    assert fake_osf.writes == []
    assert "cancelled" in capsys.readouterr().out


def test_the_token_is_read_only_after_the_push_phrase(study, tty, monkeypatch, fake_osf):
    """Reading a pipe-backed token asks the person to approve; a cancelled command must not."""
    reads = []
    monkeypatch.setattr(osf, "require_token", lambda: reads.append(1) or "t")
    tty.types("no")
    assert cli._main(["freeze", "--osf"]) == 1
    assert reads == []
    [schema] = fake_osf.calls_to("GET", r"schema_blocks")
    assert "Authorization" not in schema.headers, "the public schema is read without the token"


def test_a_plan_that_cannot_map_is_refused_before_anyone_is_asked(study, tty, fake_osf):
    p = study / "PREREG.md"
    p.write_text(
        p.read_text().replace("## Randomization", "## Decision rule\n\np<.05\n\n## Randomization")
    )
    _commit(study.parent, "odd heading")
    before = _plan(study)
    assert cli._main(["freeze", "--osf"]) == 1
    assert tty.shown() == "", "nobody should be asked to confirm a push that cannot happen"
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
    p.write_text(p.read_text().replace("## Randomization", "## Randomization\n\nBy coin."))
    tty.types("register draft1")
    assert cli._main(["register", "--immediate", "--access", "nothing run"]) == 1
    assert fake_osf.calls_to("POST", r"/registrations/") == []


def test_register_refuses_a_draft_made_from_an_earlier_freeze(study, tty, fake_osf):
    """After a forced re-freeze the plan the hash describes is not the one on OSF."""
    assert _freeze_and_push(study, tty) == 0
    p = study / "PREREG.md"
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
    assert "k3y" not in _plan(study), "the key opens the registration; it stays out of the file"
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
