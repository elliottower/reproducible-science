"""OSF integration: plan parsing, token discovery, .env management."""

from __future__ import annotations

import pytest
from prereg import cli, osf, plan, template


def test_parse_plan_extracts_title_and_sections():
    text = template.render("My experiment", "2026-01-01")
    title, sections = osf._parse_plan(text)
    assert title == "My experiment"
    assert "Research questions or hypotheses" in sections
    assert "Inference criteria" in sections


def test_parse_plan_strips_status_lines():
    text = template.render("test", "2026-01-01")
    _, sections = osf._parse_plan(text)
    for content in sections.values():
        assert "**Status:**" not in content
        assert "**Plan sha256:**" not in content
        assert "**Frozen:**" not in content


def test_parse_plan_stops_at_log():
    text = template.render("test", "2026-01-01")
    text += "\nsome extra content after log\n"
    _, sections = osf._parse_plan(text)
    for content in sections.values():
        assert "some extra content after log" not in content


def test_token_from_env_file(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("OSF_TOKEN=test_token_123\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OSF_TOKEN", raising=False)
    assert osf._token() == "test_token_123"


def test_token_from_env_var(monkeypatch):
    monkeypatch.setenv("OSF_TOKEN", "env_var_token")
    assert osf._token() == "env_var_token"


def test_env_var_takes_precedence(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("OSF_TOKEN=file_token\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OSF_TOKEN", "env_token")
    assert osf._token() == "env_token"


def test_token_ignores_comments(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("# OSF_TOKEN=old\nOSF_TOKEN=real\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OSF_TOKEN", raising=False)
    assert osf._token() == "real"


def test_token_strips_quotes(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("OSF_TOKEN='quoted_token'\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OSF_TOKEN", raising=False)
    assert osf._token() == "quoted_token"


def test_setup_token_creates_env_and_gitignore(tmp_path, monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda _: "my_secret_token")
    env_path = osf.setup_token(tmp_path)
    assert env_path == tmp_path / ".env"
    assert "OSF_TOKEN=my_secret_token" in env_path.read_text()
    assert ".env" in (tmp_path / ".gitignore").read_text()


def test_setup_token_appends_to_existing_gitignore(tmp_path, monkeypatch):
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    monkeypatch.setattr("getpass.getpass", lambda _: "tok")
    osf.setup_token(tmp_path)
    gi = (tmp_path / ".gitignore").read_text()
    assert "*.pyc" in gi
    assert ".env" in gi


def test_setup_token_replaces_existing_token(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("OTHER=foo\nOSF_TOKEN=old\nANOTHER=bar\n")
    monkeypatch.setattr("getpass.getpass", lambda _: "new")
    osf.setup_token(tmp_path)
    text = (tmp_path / ".env").read_text()
    assert "OSF_TOKEN=new" in text
    assert "OTHER=foo" in text
    assert "ANOTHER=bar" in text
    assert "OSF_TOKEN=old" not in text


def test_heading_map_covers_all_template_questions():
    for q, _ in template.QUESTIONS:
        assert q in osf.HEADING_TO_QUESTION, f"template question not in OSF mapping: {q}"


def _push_template_plan(tmp_path, monkeypatch, extra: str = "") -> dict:
    """Run `prereg new`, then push its output with the network replaced; return the body sent.

    `extra` is inserted as plan content, above the log line.
    """
    monkeypatch.chdir(tmp_path)
    assert cli.main(["new", "study"]) == 0
    text = (tmp_path / "study" / "PREREG.md").read_text().replace(plan.MARK, extra + plan.MARK)
    sent: dict = {}

    def fake_request(method, path, token, body=None):
        sent[(method, path)] = body
        return {"data": {"id": "draft1"}}

    schema = {q: f"key-{i}" for i, q in enumerate(filter(None, osf.HEADING_TO_QUESTION.values()))}
    monkeypatch.setattr(osf, "_token", lambda: "t")
    monkeypatch.setattr(osf, "_fetch_schema", lambda token: schema)
    monkeypatch.setattr(osf, "_request", fake_request)
    assert osf.push_draft(text) == ("draft1", "https://osf.io/draft1")
    return sent[("POST", "/draft_registrations/")]


def test_a_plan_made_by_prereg_new_is_not_rejected(tmp_path, monkeypatch):
    """The four `- File upload` headings map to None on purpose and were rejected as unmapped,
    so no plan the template produced could be pushed."""
    body = _push_template_plan(tmp_path, monkeypatch)
    assert body["data"]["type"] == "draft_registrations"


def test_a_heading_the_table_does_not_know_is_still_rejected(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="'Decision rule'"):
        _push_template_plan(tmp_path, monkeypatch, extra="\n## Decision rule\n\np < 0.05\n")
