"""A stand-in for OSF at the one place the package touches the network: `urlopen`.

Replacing `urlopen` rather than the module's own helpers means the URL, the query string, the
headers and the body a test sees are the ones that would have been sent.
"""

from __future__ import annotations

import io
import json
import pathlib
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import pytest

SCHEMA_BLOCKS = pathlib.Path(__file__).parent / "data" / "osf_preregistration_schema_blocks.json"


@dataclass
class Call:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None

    @property
    def json(self) -> dict:
        return json.loads(self.body or b"null")


@dataclass
class FakeOSF:
    """Routes by (method, regex on the URL). A route's value is a dict to return, a callable
    taking the `Call` and returning one, or an `(status, body)` tuple to raise as an HTTP
    error."""

    routes: list[tuple[str, str, object]] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)

    def on(self, method: str, pattern: str, response: object) -> None:
        self.routes.insert(0, (method, pattern, response))

    def calls_to(self, method: str, pattern: str) -> list[Call]:
        return [c for c in self.calls if c.method == method and re.search(pattern, c.url)]

    @property
    def writes(self) -> list[Call]:
        return [c for c in self.calls if c.method != "GET"]

    def urlopen(self, req: urllib.request.Request, timeout: float | None = None):
        data = req.data if isinstance(req.data, bytes) or req.data is None else bytes(req.data)
        call = Call(req.get_method(), req.full_url, dict(req.header_items()), data)
        self.calls.append(call)
        for method, pattern, response in self.routes:
            if method == call.method and re.search(pattern, call.url):
                if isinstance(response, tuple):
                    status, body = response
                    raise urllib.error.HTTPError(
                        call.url, status, "error", {}, io.BytesIO(json.dumps(body).encode())
                    )
                if callable(response):
                    response = response(call)
                return io.BytesIO(json.dumps(response).encode())
        raise AssertionError(f"unexpected request: {call.method} {call.url}")


@pytest.fixture
def fake_osf(monkeypatch) -> FakeOSF:
    fake = FakeOSF()
    fake.on(
        "GET", r"/schemas/registrations/[^/]+/schema_blocks/", json.loads(SCHEMA_BLOCKS.read_text())
    )
    monkeypatch.setattr(urllib.request, "urlopen", fake.urlopen)
    monkeypatch.setenv("OSF_TOKEN", "test-token")
    return fake
