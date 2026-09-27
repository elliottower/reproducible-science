"""OSF integration: plan parsing, token discovery, .env management."""

from __future__ import annotations

import re

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


def _template_plan(tmp_path, monkeypatch, answers: dict[str, str] | None = None, extra="") -> str:
    """The text `prereg new` writes, with `answers` put under their headings and `extra`
    inserted above the log line."""
    monkeypatch.chdir(tmp_path)
    assert cli.main(["new", "study"]) == 0
    text = (tmp_path / "study" / "PREREG.md").read_text()
    for heading, content in (answers or {}).items():
        text, n = re.subn(
            rf"(## {re.escape(heading)}\n).*?(?=\n## |\n---)",
            rf"\g<1>{content}\n",
            text,
            count=1,
            flags=re.S,
        )
        assert n == 1, heading
    return text.replace(plan.MARK, extra + plan.MARK)


def _pushed(fake_osf) -> dict:
    [call] = fake_osf.calls_to("POST", r"/draft_registrations/")
    return call.json["data"]["attributes"]["registration_responses"]


def test_every_mapped_heading_has_a_key_in_the_live_schema(fake_osf):
    """`_fetch_schema` read `attributes.schema.blocks`, which carries no response keys, so the
    map came back empty and every section with content was refused as unmapped. The fixture
    is the schema's `schema_blocks` as OSF serves them, with each 24-hex group key replaced by
    a short alias: gitleaks reads those keys as credentials."""
    schema = osf._fetch_schema("t")
    for question in filter(None, osf.HEADING_TO_QUESTION.values()):
        assert question in schema, question
    assert schema["Inference criteria"] == osf.Question("344-77", "long-text-input", ())
    assert schema["Foreknowledge of data or evidence"].kind == "single-select-input"
    assert len(schema["Foreknowledge of data or evidence"].options) == 8


def test_a_plan_made_by_prereg_new_is_not_rejected(tmp_path, monkeypatch, fake_osf):
    """The four `- File upload` headings map to None on purpose and were rejected as unmapped,
    so no plan the template produced could be pushed."""
    fake_osf.on("POST", r"/draft_registrations/$", {"data": {"id": "draft1"}})
    assert osf.push_draft(_template_plan(tmp_path, monkeypatch))[0] == "draft1"
    # The template's italic prompts are questions, not answers; none of them is sent.
    assert _pushed(fake_osf) == {}


def test_a_heading_the_table_does_not_know_is_still_rejected(tmp_path, monkeypatch, fake_osf):
    text = _template_plan(tmp_path, monkeypatch, extra="\n## Decision rule\n\np < 0.05\n")
    with pytest.raises(RuntimeError, match="'Decision rule'"):
        osf.push_draft(text)
    assert fake_osf.writes == []


def test_answers_go_under_the_schemas_own_keys(tmp_path, monkeypatch, fake_osf):
    fake_osf.on("POST", r"/draft_registrations/$", {"data": {"id": "draft1"}})
    text = _template_plan(
        tmp_path,
        monkeypatch,
        {
            "Inference criteria": "H1 holds if rho > 0.3.",
            "Foreknowledge of data or evidence": "Data does not yet exist.",
            "Study type": "- Descriptive study\n- Simulation study",
            "Blinding of experimental treatments": "N/A — no treatment.",
        },
    )
    osf.push_draft(text)
    sent = _pushed(fake_osf)
    assert sent["344-77"] == "H1 holds if rho > 0.3."
    assert sent["344-4"].startswith("Data does not yet exist. No part of the data")
    assert [s.split(":")[0] for s in sent["344-17"]] == ["Descriptive study", "Simulation study"]
    assert "344-32" not in sent, "a select question answered N/A is left unanswered"


def test_prose_under_a_multiple_choice_heading_is_refused_before_anything_is_sent(
    tmp_path, monkeypatch, fake_osf
):
    text = _template_plan(
        tmp_path, monkeypatch, {"Foreknowledge of data or evidence": "We ran a pilot on 20 items."}
    )
    with pytest.raises(RuntimeError, match="multiple-choice") as e:
        osf.push_draft(text)
    assert "Data does not yet exist." in str(e.value), "the refusal must list the options"
    assert fake_osf.writes == []


def test_an_ambiguous_prefix_is_refused(tmp_path, monkeypatch, fake_osf):
    text = _template_plan(
        tmp_path, monkeypatch, {"Foreknowledge of data or evidence": "Data exists but"}
    )
    with pytest.raises(RuntimeError, match="more than one"):
        osf.push_draft(text)


def test_an_http_error_carries_osfs_explanation(tmp_path, monkeypatch, fake_osf):
    fake_osf.on(
        "POST",
        r"/draft_registrations/$",
        (400, {"errors": [{"detail": "For your registration the 'Study type' field is odd"}]}),
    )
    with pytest.raises(osf.OSFError, match=r"\(400\).*'Study type' field is odd"):
        osf.push_draft(_template_plan(tmp_path, monkeypatch))


def test_a_failed_schema_fetch_is_an_error_not_a_traceback(tmp_path, monkeypatch, fake_osf):
    fake_osf.on("GET", r"schema_blocks", (401, {"errors": [{"detail": "bad token"}]}))
    with pytest.raises(RuntimeError, match=r"401.*bad token"):
        osf.push_draft(_template_plan(tmp_path, monkeypatch))
