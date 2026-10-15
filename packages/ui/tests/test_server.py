"""The server's endpoints, over HTTP, against a real project."""

from __future__ import annotations

import functools
import http.server
import json
import pathlib
import socket
import subprocess
import sysconfig
import threading
import time
import urllib.error
import urllib.request

import pytest
from repro_ui import graph, server

TOKEN = "launch-token"


@pytest.fixture
def served(project, tmp_path):
    data = tmp_path / "data"
    graph.build(project, data / "graph.json", check=False, fetch=False)
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text(
        "<!doctype html><html><head><title>page</title></head></html>"
    )
    handler = type(
        "TestHandler",
        (server.Handler,),
        {"project": project, "groups": None, "data": data, "fetch": False, "token": TOKEN},
    )
    httpd = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(handler, directory=str(static))
    )
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def get(url: str) -> tuple[int, dict | str]:
    try:
        with urllib.request.urlopen(url) as r:
            body = r.read().decode()
            return r.status, json.loads(body) if r.headers.get(
                "Content-Type"
            ) == "application/json" else body
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def post(url: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", server.TOKEN_HEADER: TOKEN},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def test_a_file_the_manifest_pins_is_readable_and_nothing_outside_the_records_is(served, project):
    status, body = get(f"{served}/api/file?path=results.json")
    assert (status, body["text"]) == (200, (project / "results.json").read_text())
    (project.parent / "secret.txt").write_text("not the page's to show")
    for path in ("../secret.txt", "/etc/hosts", "repro.yaml"):
        status, body = get(f"{served}/api/file?path={path}")
        assert status == 404, path


def test_a_step_the_manifest_does_not_declare_is_refused_and_nothing_runs(served, project):
    status, _ = post(f"{served}/api/reproduce", {"only": ["not-a-step"]})
    assert status == 400
    assert not (project / ".repro" / "reproductions.jsonl").exists()


def test_re_running_a_step_records_it_and_the_page_shows_it_reproduced(served, project):
    status, body = post(f"{served}/api/reproduce", {"only": ["results"]})
    assert (status, body["ok"], body["counts"]) == (200, True, {"reproduced": 1})
    assert (project / ".repro" / "reproductions.jsonl").read_text().count("\n") == 1
    _, g = get(f"{served}/graph.json")
    (step,) = g["tabs"]["reproduce"]["steps"]
    assert step["state"] == "current"
    assert step["history"][0]["state"] == "reproduced"


def test_the_page_is_served_from_the_built_files(served):
    status, body = get(f"{served}/")
    assert status == 200 and "<title>page</title>" in body


def test_a_folder_with_no_manifest_is_refused_before_anything_is_built(tmp_path, capsys):
    assert server.main([str(tmp_path), "--no-browser"]) == 2
    assert "no repro.yaml" in capsys.readouterr().out


def test_the_data_of_a_project_in_git_is_kept_inside_its_git_directory(project):
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    assert server.data_dir(project) == (project / ".git").resolve() / "repro" / "ui"


def raw(url: str, method: str = "GET", body: bytes = b"", headers: dict | None = None) -> int:
    req = urllib.request.Request(
        url, data=body if method == "POST" else None, method=method, headers=headers or {}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_a_request_from_another_site_changes_nothing(served, project, tmp_path, monkeypatch):
    queue = tmp_path / "queue.jsonl"
    monkeypatch.setattr(server, "QUEUE", queue)
    fix = json.dumps({"prompt": "run this", "subject": "s", "kind": "claim"}).encode()
    run = json.dumps({"only": None}).encode()
    # What a page on another site can send: its own Origin, or a body that is not declared JSON.
    for headers in (
        {"Content-Type": "application/json", "Origin": "https://evil.example"},
        {"Content-Type": "text/plain"},
    ):
        assert raw(f"{served}/api/fix-request", "POST", fix, headers) == 403
        assert raw(f"{served}/api/reproduce", "POST", run, headers) == 403
        assert raw(f"{served}/api/verify", "POST", b"{}", headers) == 403
    assert not queue.exists()
    assert not (project / ".repro" / "reproductions.jsonl").exists()
    # The page itself sends JSON from this server's own address, and is let through.
    own = {
        "Content-Type": "application/json",
        "Origin": served.replace("127.0.0.1", "localhost"),
        server.TOKEN_HEADER: TOKEN,
    }
    assert raw(f"{served}/api/fix-request", "POST", fix, own) == 200
    assert queue.read_text().count("\n") == 1


def test_a_domain_rebound_to_this_server_reads_nothing(served):
    port = served.rsplit(":", 1)[1]
    for path in ("/api/health", "/graph.json", "/api/file?path=results.json", "/"):
        assert raw(f"{served}{path}", headers={"Host": f"attacker.example:{port}"}) == 403, path


def test_a_malformed_request_is_answered_and_refused(served):
    json_headers = {"Content-Type": "application/json", server.TOKEN_HEADER: TOKEN}
    assert raw(f"{served}/api/reproduce", "POST", b"[1, 2]", json_headers) == 400
    assert raw(f"{served}/api/reproduce", "POST", b'{"only": [{}]}', json_headers) == 400
    assert raw(
        f"{served}/api/reproduce", "POST", b"{}", {**json_headers, "Content-Length": "abc"}
    ) in (400, 411)
    assert raw(f"{served}/api/fix-request", "POST", b'"a string"', json_headers) == 400


def test_a_fix_request_whose_kind_is_not_a_string_is_refused(served, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "QUEUE", tmp_path / "queue.jsonl")
    headers = {"Content-Type": "application/json", server.TOKEN_HEADER: TOKEN}
    body = json.dumps({"prompt": "p", "subject": "s", "kind": ["claim"]}).encode()
    assert raw(f"{served}/api/fix-request", "POST", body, headers) == 400
    assert not (tmp_path / "queue.jsonl").exists()


def test_json_nested_too_deep_to_parse_is_refused(served):
    headers = {"Content-Type": "application/json", server.TOKEN_HEADER: TOKEN}
    deep = b"[" * 20_000 + b"]" * 20_000
    assert raw(f"{served}/api/fix-request", "POST", b'{"a": ' + deep + b"}", headers) == 400


def test_a_body_over_the_cap_is_refused_unread(served):
    headers = {"Content-Type": "application/json", server.TOKEN_HEADER: TOKEN}
    big = b'{"prompt": "' + b"x" * (server.MAX_BODY + 10) + b'"}'
    assert raw(f"{served}/api/fix-request", "POST", big, headers) == 413


def test_a_body_shorter_than_its_declared_length_does_not_hold_the_server(served):
    host, port = served.removeprefix("http://").split(":")
    request = (
        f"POST /api/fix-request HTTP/1.1\r\nHost: {host}:{port}\r\n"
        f"Content-Type: application/json\r\n{server.TOKEN_HEADER}: {TOKEN}\r\n"
        "Content-Length: 60000\r\n\r\n{}"
    ).encode()
    started = time.monotonic()
    with socket.create_connection((host, int(port)), timeout=15) as conn:
        conn.sendall(request)
        reply = conn.recv(4096)
    assert time.monotonic() - started < 12
    assert reply.startswith(b"HTTP/1.0 408") or reply == b""
    # And the server still answers the next request.
    status, _ = get(f"{served}/api/health")
    assert status == 200


def test_the_commands_the_page_runs_are_the_ones_installed_beside_it():
    path = graph.tool("repro")
    assert path == str(pathlib.Path(sysconfig.get_path("scripts")) / "repro")
    assert graph.tool("not-a-command-anywhere") == "not-a-command-anywhere"


def test_a_post_without_this_launchs_token_is_refused_and_the_page_carries_it(
    served, tmp_path, monkeypatch
):
    queue = tmp_path / "queue.jsonl"
    monkeypatch.setattr(server, "QUEUE", queue)
    fix = json.dumps({"prompt": "p", "subject": "s", "kind": "claim"}).encode()
    for token in (None, "a-guess"):
        headers = {"Content-Type": "application/json"} | (
            {server.TOKEN_HEADER: token} if token else {}
        )
        assert raw(f"{served}/api/fix-request", "POST", fix, headers) == 403
    assert not queue.exists()
    _, page = get(f"{served}/")
    assert f'<meta name="repro-ui-token" content="{TOKEN}" />' in page
