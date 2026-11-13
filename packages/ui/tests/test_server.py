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
import urllib.parse
import urllib.request

import pytest
from repro_ui import graph, server

TOKEN = "launch-token"


def serve(project: pathlib.Path, tmp_path: pathlib.Path):
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
    return httpd


@pytest.fixture
def served(project, tmp_path):
    httpd = serve(project, tmp_path)
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def served_kept(kept, tmp_path):
    httpd = serve(kept, tmp_path)
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


def stream(url: str, body: dict) -> tuple[int, list[dict]]:
    """POST and read the answer one JSON object per line, as the page does."""
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", server.TOKEN_HEADER: TOKEN},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, [json.loads(line) for line in r.read().decode().splitlines() if line]


def test_re_running_a_step_streams_its_output_then_what_it_recorded(served, project):
    status, events = stream(f"{served}/api/reproduce", {"only": ["results"]})
    assert status == 200
    lines, (done,) = (
        [e["line"] for e in events if "line" in e],
        [e for e in events if e.get("done")],
    )
    assert lines[0] == "$ repro reproduce --only results"
    assert len(lines) > 1, "nothing that repro reproduce printed reached the page"
    assert (done["ok"], done["counts"]) == (True, {"reproduced": 1})
    ((step_id, state, seconds),) = [(s["id"], s["state"], s["seconds"]) for s in done["steps"]]
    assert (step_id, state) == ("results", "reproduced") and seconds >= 0
    assert events[-1] == done, "the result comes last"
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


def test_a_request_from_another_site_changes_nothing(served, project):
    run = json.dumps({"only": None}).encode()
    # What a page on another site can send: its own Origin, or a body that is not declared JSON.
    for headers in (
        {"Content-Type": "application/json", "Origin": "https://evil.example"},
        {"Content-Type": "text/plain"},
    ):
        assert raw(f"{served}/api/reproduce", "POST", run, headers) == 403
        assert raw(f"{served}/api/verify", "POST", b"{}", headers) == 403
    assert not (project / ".repro" / "reproductions.jsonl").exists()
    # The page itself sends JSON from this server's own address, and is let through.
    own = {
        "Content-Type": "application/json",
        "Origin": served.replace("127.0.0.1", "localhost"),
        server.TOKEN_HEADER: TOKEN,
    }
    assert raw(f"{served}/api/refresh", "POST", b"{}", own) == 200


def test_a_domain_rebound_to_this_server_reads_nothing(served):
    port = served.rsplit(":", 1)[1]
    for path in (
        "/api/health",
        "/graph.json",
        "/api/file?path=results.json",
        "/api/diff?issue=results-changed&path=data.json",
        "/",
    ):
        assert raw(f"{served}{path}", headers={"Host": f"attacker.example:{port}"}) == 403, path


def test_a_malformed_request_is_answered_and_refused(served):
    json_headers = {"Content-Type": "application/json", server.TOKEN_HEADER: TOKEN}
    assert raw(f"{served}/api/reproduce", "POST", b"[1, 2]", json_headers) == 400
    assert raw(f"{served}/api/reproduce", "POST", b'{"only": [{}]}', json_headers) == 400
    assert raw(
        f"{served}/api/reproduce", "POST", b"{}", {**json_headers, "Content-Length": "abc"}
    ) in (400, 411)
    assert raw(f"{served}/api/reproduce", "POST", b'"a string"', json_headers) == 400


def test_the_endpoint_that_queued_requests_for_claude_code_is_gone(served):
    headers = {"Content-Type": "application/json", server.TOKEN_HEADER: TOKEN}
    body = json.dumps({"prompt": "p", "subject": "s", "kind": "claim"}).encode()
    assert raw(f"{served}/api/fix-request", "POST", body, headers) == 404


def test_json_nested_too_deep_to_parse_is_refused(served):
    headers = {"Content-Type": "application/json", server.TOKEN_HEADER: TOKEN}
    deep = b"[" * 20_000 + b"]" * 20_000
    assert raw(f"{served}/api/reproduce", "POST", b'{"a": ' + deep + b"}", headers) == 400


def test_a_body_over_the_cap_is_refused_unread(served):
    headers = {"Content-Type": "application/json", server.TOKEN_HEADER: TOKEN}
    big = b'{"prompt": "' + b"x" * (server.MAX_BODY + 10) + b'"}'
    assert raw(f"{served}/api/reproduce", "POST", big, headers) == 413


def test_a_body_shorter_than_its_declared_length_does_not_hold_the_server(served):
    host, port = served.removeprefix("http://").split(":")
    request = (
        f"POST /api/reproduce HTTP/1.1\r\nHost: {host}:{port}\r\n"
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


def test_a_post_without_this_launchs_token_is_refused_and_the_page_carries_it(served, project):
    run = json.dumps({"only": ["results"]}).encode()
    for token in (None, "a-guess"):
        headers = {"Content-Type": "application/json"} | (
            {server.TOKEN_HEADER: token} if token else {}
        )
        req = urllib.request.Request(
            f"{served}/api/reproduce", data=run, method="POST", headers=headers
        )
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(req, timeout=30)
        assert refused.value.code == 403
        # Said so the reader knows what to do: an old tab carries the previous launch's token.
        assert json.loads(refused.value.read())["error"] == "This page is out of date: reload it."
    assert not (project / ".repro" / "reproductions.jsonl").exists()
    _, page = get(f"{served}/")
    assert f'<meta name="repro-ui-token" content="{TOKEN}" />' in page


def test_a_request_not_from_this_page_says_so_rather_than_reload(served):
    for headers in (
        {
            "Content-Type": "application/json",
            "Origin": "https://evil.example",
            server.TOKEN_HEADER: TOKEN,
        },
        {"Content-Type": "text/plain", server.TOKEN_HEADER: TOKEN},
    ):
        req = urllib.request.Request(
            f"{served}/api/refresh", data=b"{}", method="POST", headers=headers
        )
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(req, timeout=30)
        assert refused.value.code == 403
        assert json.loads(refused.value.read())["error"] == server.NOT_OURS


def test_a_page_that_goes_away_mid_run_still_gets_the_run_recorded_and_shown(served, project):
    host, port = served.removeprefix("http://").split(":")
    body = json.dumps({"only": ["results"]}).encode()
    request = (
        f"POST /api/reproduce HTTP/1.1\r\nHost: {host}:{port}\r\n"
        f"Content-Type: application/json\r\n{server.TOKEN_HEADER}: {TOKEN}\r\n"
        f"Content-Length: {len(body)}\r\n\r\n"
    ).encode() + body
    with socket.create_connection((host, int(port)), timeout=15) as conn:
        conn.sendall(request)
        assert conn.recv(64).startswith(b"HTTP/1.0 200")
    # The page is gone. The run goes on to the end, is recorded, and the data is rebuilt.
    record = project / ".repro" / "reproductions.jsonl"
    assert server.Handler.lock.acquire(timeout=90), "the run never released the lock"
    server.Handler.lock.release()
    assert record.read_text().count("\n") == 1
    _, g = get(f"{served}/graph.json")
    assert g["tabs"]["reproduce"]["steps"][0]["state"] == "current"
    status, _ = post(f"{served}/api/refresh", {})
    assert status == 200, "the lock was released"


def test_a_failure_after_the_run_ends_the_stream_with_a_result_not_a_lost_connection(
    served, project, monkeypatch
):
    def broken(*args, **kwargs):
        raise RuntimeError("graph.json could not be written")

    monkeypatch.setattr(graph, "build", broken)
    status, events = stream(f"{served}/api/reproduce", {"only": ["results"]})
    (done,) = [e for e in events if e.get("done")]
    assert (status, done["ok"]) == (200, False)
    assert "reading its record failed" in done["error"] and "could not be written" in done["error"]
    assert done["seconds"] >= 0
    assert (project / ".repro" / "reproductions.jsonl").read_text().count("\n") == 1


def test_a_diff_the_issues_name_is_served_and_nothing_else_is(served_kept, kept):
    q = urllib.parse.urlencode
    status, body = get(
        f"{served_kept}/api/diff?{q({'issue': 'results-changed', 'path': 'data.json'})}"
    )
    assert status == 200
    assert '+{"values": [1, 2, 3, 4]}' in body["diff"].splitlines()
    status, body = get(
        f"{served_kept}/api/diff?{q({'issue': 'prereg-changed', 'path': 'PREREG.md'})}"
    )
    assert (status, body["commit"]) == (
        200,
        json.loads((kept / ".prereg" / "PREREG.md.json").read_text())["commit"],
    )

    (kept.parent / "secret.txt").write_text("not the page's to show")
    for issue, path in [
        ("results-changed", "../secret.txt"),
        ("results-changed", "/etc/hosts"),
        ("results-changed", "repro.yaml"),
        ("results-changed", "data.json\x00"),
        ("prereg-changed", "data.json"),
        ("", ""),
    ]:
        status, body = get(f"{served_kept}/api/diff?{q({'issue': issue, 'path': path})}")
        assert (status, body["ok"]) == (404, False), (issue, path)
    assert raw(f"{served_kept}/api/diff", "GET") == 404


def test_the_diff_endpoint_changes_nothing_in_the_project(served_kept, kept):
    def state() -> dict[str, bytes]:
        return {
            str(f.relative_to(kept)): f.read_bytes()
            for f in kept.rglob("*")
            if f.is_file() and ".git" not in f.relative_to(kept).parts
        }

    before = state()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=kept, capture_output=True, text=True
    ).stdout
    for path in ("data.json", "blob.bin", "scratch.txt"):
        status, _ = get(f"{served_kept}/api/diff?issue=results-changed&path={path}")
        assert status == 200
    assert state() == before
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=kept, capture_output=True, text=True
        ).stdout
        == head
    )
