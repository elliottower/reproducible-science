"""Outbound requests carry a contact address only where the operator set one.

The `User-Agent` and OpenAlex's `mailto` were hardcoded to the author's address, so every lookup
run by anyone using this package announced one person's email to Crossref and OpenAlex, and named
the wrong party as the request's owner.
"""

from __future__ import annotations

from citations import services


def test_no_contact_is_announced_by_default(monkeypatch):
    monkeypatch.delenv(services.CONTACT_ENV, raising=False)
    assert services.user_agent() == "citations/1.0"


def test_no_mailto_is_sent_by_default(monkeypatch):
    monkeypatch.delenv(services.CONTACT_ENV, raising=False)
    assert "mailto" not in services.polite({"per-page": 5})


def test_a_configured_contact_is_announced(monkeypatch):
    monkeypatch.setenv(services.CONTACT_ENV, "someone@example.org")
    assert services.user_agent() == "citations/1.0 (mailto:someone@example.org)"


def test_a_configured_contact_reaches_the_query(monkeypatch):
    monkeypatch.setenv(services.CONTACT_ENV, "someone@example.org")
    assert services.polite({"per-page": 5})["mailto"] == "someone@example.org"


def test_whitespace_is_not_a_contact(monkeypatch):
    monkeypatch.setenv(services.CONTACT_ENV, "   ")
    assert services.user_agent() == "citations/1.0"


def test_polite_does_not_mutate_what_it_is_given(monkeypatch):
    monkeypatch.setenv(services.CONTACT_ENV, "someone@example.org")
    params = {"per-page": 5}
    services.polite(params)
    assert params == {"per-page": 5}


def test_no_address_is_baked_into_the_openalex_url(monkeypatch):
    monkeypatch.delenv(services.CONTACT_ENV, raising=False)
    from citations.models import Record

    rec = Record.model_validate({"slug": "x", "key": "x", "title": "a title", "authors": ["A B"]})
    url = next(s for s in services.SERVICES if s.name == "openalex").url(rec)
    assert "mailto" not in url
