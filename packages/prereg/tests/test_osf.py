"""OSF integration: plan parsing, token discovery, .env management."""

from __future__ import annotations

from prereg import osf, template


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
