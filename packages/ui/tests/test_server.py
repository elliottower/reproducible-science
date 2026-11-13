"""The server's endpoints, over HTTP, against a real project."""

from __future__ import annotations

import functools
import hashlib
import http.server
import json
import os
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
import yaml
from repro_ui import export, graph, runs, server

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


def wait_for(check, seconds: float = 90):
    """Poll `check` until it returns something truthy, and return that."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        found = check()
        if found:
            return found
        time.sleep(0.2)
    raise AssertionError("timed out")


def run_named(served: str, run_id: str) -> dict:
    _, body = get(f"{served}/api/runs")
    return next(r for r in body["runs"] if r["run_id"] == run_id)


def test_a_run_started_from_the_page_is_read_back_as_running_then_done(served, project):
    status, body = post(f"{served}/api/reproduce", {"only": ["results"]})
    assert status == 200
    run = body["run"]
    assert run["only"] == ["results"] and run["record_before"] == 0
    done = wait_for(lambda: (r := run_named(served, run["run_id"]))["state"] == "done" and r)
    assert [(s["id"], s["state"]) for s in done["steps"]] == [("results", "reproduced")]
    assert "results" in done["log"], "the log holds what repro reproduce printed"
    assert (project / ".repro" / "reproductions.jsonl").read_text().count("\n") == 1


def test_a_run_goes_on_when_the_server_that_started_it_stops(project, tmp_path):
    httpd = serve(project, tmp_path)
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    status, _ = post(f"{url}/api/reproduce", {"only": None})
    assert status == 200
    httpd.shutdown()
    httpd.server_close()
    record = project / ".repro" / "reproductions.jsonl"
    wait_for(lambda: record.exists() and record.read_text().count("\n") == 1)


def test_a_step_with_a_live_run_cannot_be_started_again_and_stop_ends_it_as_interrupted(
    served, project, tmp_path
):
    data = tmp_path / "data"
    marker = runs.start(project, data, ["sleep", "60"], ["results"])
    for only in (["results"], None):
        status, body = post(f"{served}/api/reproduce", {"only": only})
        assert (status, body["run"]) == (409, marker["run_id"])
    assert run_named(served, marker["run_id"])["state"] == "running"
    assert post(f"{served}/api/stop", {"run": "not-a-run"})[0] == 404
    assert post(f"{served}/api/stop", {"run": marker["run_id"]})[0] == 200
    wait_for(lambda: run_named(served, marker["run_id"])["state"] == "interrupted")
    assert not (project / ".repro" / "reproductions.jsonl").exists()


def test_a_run_whose_process_is_gone_is_done_when_the_record_holds_it_and_interrupted_otherwise(
    project, tmp_path
):
    data = tmp_path / "data"
    # Markers left by another server: processes this one never started, and that have ended.
    gone = subprocess.Popen(["true"])
    gone.wait()
    folder = runs.folder(data)
    folder.mkdir(parents=True)
    for run_id, only in (("20260101T000000-aaaaaa", ["results"]), ("20260101T000001-bbbbbb", None)):
        (folder / f"{run_id}.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "pid": gone.pid,
                    "only": only,
                    "started_at": "",
                    "record_before": 0,
                }
            )
        )
    assert {r["run_id"]: r["state"] for r in runs.listed(project, data)} == {
        "20260101T000000-aaaaaa": "interrupted",
        "20260101T000001-bbbbbb": "interrupted",
    }
    record = project / ".repro"
    record.mkdir()
    step = {"regeneration_id": "results", "state": "reproduced", "duration_seconds": 0.1}
    (record / "reproductions.jsonl").write_text(
        json.dumps({"ended_at": "2026-01-01T00:00:02+00:00", "regenerations": [step]}) + "\n"
    )
    states = {r["run_id"]: r for r in runs.listed(project, data)}
    assert states["20260101T000000-aaaaaa"]["state"] == "done"
    assert states["20260101T000000-aaaaaa"]["steps"][0]["id"] == "results"
    assert states["20260101T000001-bbbbbb"]["state"] == "done"


def embedded(page: str) -> dict:
    start = page.index('<script type="application/json" id="repro-graph">')
    body = page[start:].split(">", 1)[1].split("</script>", 1)[0]
    return json.loads(body)


def test_the_export_is_one_file_with_the_data_and_no_token(served, project, tmp_path):
    req = urllib.request.Request(f"{served}/api/export")
    with urllib.request.urlopen(req) as r:
        page = r.read().decode()
        assert r.headers["Content-Disposition"] == 'attachment; filename="project.html"'
    assert TOKEN not in page and "repro-ui-token" not in page
    assert '<meta name="repro-ui-static" content="1" />' in page
    _, g = get(f"{served}/graph.json")
    assert embedded(page) == {**g, "project_dir": None}


def test_embedded_data_cannot_end_its_script_element():
    data = json.dumps({"text": "</script><script>alert(1)</script><!-- x"}).encode()
    assert "</script><script>" not in export.embedded_json(data)
    assert json.loads(export.embedded_json(data)) == json.loads(data)


def test_repro_ui_export_writes_the_file_to_a_folder_or_to_the_name_given(
    project, tmp_path, monkeypatch
):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "assets" / "index-x.js").write_text("console.log('</script>')")
    (static / "assets" / "index-x.css").write_text("body{}")
    (static / "index.html").write_text(
        "<!doctype html><html><head><title>repro ui</title>"
        '<script type="module" crossorigin src="./assets/index-x.js"></script>'
        '<link rel="stylesheet" crossorigin href="./assets/index-x.css"></head>'
        '<body><div id="root"></div></body></html>'
    )
    monkeypatch.setattr(server, "DIST", static)
    assert server.main([str(project), "--export", str(tmp_path / "site"), "--offline"]) == 0
    assert server.main([str(project), "--export", str(tmp_path / "one.html"), "--offline"]) == 0
    for page in (
        (tmp_path / "site" / "index.html").read_text(),
        (tmp_path / "one.html").read_text(),
    ):
        assert "<\\/script>" in page and "./assets/" not in page
        assert "<style>body{}</style>" in page and "<title>project</title>" in page
        assert embedded(page)["project_name"] == "project"


def two_steps(project: pathlib.Path) -> None:
    """A second rebuild step beside `results`, so a run of one step differs from a run of all."""
    (project / "double.py").write_text(
        "import json\njson.dump({'double': 12}, open('double.json', 'w'))\n"
    )
    (project / "double.json").write_text(json.dumps({"double": 12}))
    manifest = yaml.safe_load((project / "repro.yaml").read_text())
    digest = lambda p: {"algorithm": "sha256", "value": hashlib.sha256(p.read_bytes()).hexdigest()}  # noqa: E731
    manifest["artifacts"] += [
        {
            "id": "double-code",
            "path": "double.py",
            "media_type": "text/x-python",
            "digest": digest(project / "double.py"),
        },
        {
            "id": "double",
            "path": "double.json",
            "media_type": "application/json",
            "digest": digest(project / "double.json"),
        },
    ]
    manifest["regenerations"].append(
        {
            "id": "double",
            "command": ["python3", "double.py"],
            "inputs": [{"artifact": "double-code", "digest": digest(project / "double.py")}],
            "output": {"artifact": "double", "digest": digest(project / "double.json")},
        }
    )
    (project / "repro.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))


def test_a_run_of_one_step_runs_only_that_step_and_a_later_run_reads_its_own_record(
    project, tmp_path
):
    two_steps(project)
    httpd = serve(project, tmp_path)
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        for n, only in enumerate((["double"], ["results"]), start=1):
            status, body = post(f"{url}/api/reproduce", {"only": only})
            assert status == 200 and body["run"]["record_before"] == n - 1
            run_id = body["run"]["run_id"]
            done = wait_for(
                lambda run_id=run_id: (r := run_named(url, run_id))["state"] == "done" and r
            )
            assert [s["id"] for s in done["steps"]] == only
            record = (project / ".repro" / "reproductions.jsonl").read_text().splitlines()
            assert len(record) == n
            ran = [
                r["regeneration_id"]
                for r in json.loads(record[-1])["regenerations"]
                if r["state"] != "not_rerun"
            ]
            assert ran == only
            assert (tmp_path / "data" / "runs" / f"{body['run']['run_id']}.log").is_file()
        assert post(f"{url}/api/reproduce", {})[0] == 400, "a body without only starts nothing"
    finally:
        httpd.shutdown()


def test_stop_ends_the_whole_process_group_including_what_the_step_started(project, tmp_path):
    data = tmp_path / "data"
    child = tmp_path / "child.pid"
    marker = runs.start(
        project, data, ["sh", "-c", f"sleep 600 & echo $! > {child}; wait"], ["results"]
    )
    pid = int(wait_for(lambda: child.exists() and child.read_text().strip()))
    assert runs.stop(data, marker["run_id"])

    def gone(p: int) -> bool:
        try:
            os.kill(p, 0)
        except ProcessLookupError:
            return True
        return False

    try:
        wait_for(lambda: gone(pid) and not runs.alive(marker), 15)
    finally:
        if not gone(pid):
            os.kill(pid, 9)
    (listed,) = runs.listed(project, data)
    assert listed["state"] == "interrupted"


def test_a_run_reads_nothing_from_a_terminal(project, tmp_path):
    data = tmp_path / "data"
    marker = runs.start(project, data, ["sh", "-c", "cat; echo stdin-closed"], None)
    wait_for(lambda: not runs.alive(marker), 20)
    assert "stdin-closed" in (data / "runs" / f"{marker['run_id']}.log").read_text()


def test_a_process_that_took_a_runs_id_is_never_read_as_the_run_nor_stopped(project, tmp_path):
    data = tmp_path / "data"
    stranger = subprocess.Popen(["sleep", "60"], start_new_session=True)
    try:
        folder = runs.folder(data)
        folder.mkdir(parents=True)
        run_id = "20200101T000000-abcdef"
        (folder / f"{run_id}.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "pid": stranger.pid,
                    "only": ["results"],
                    "started_at": "2020-01-01T00:00:00+00:00",
                    "record_before": 0,
                    "process_started": "Wed Jan  1 00:00:00 2020",
                }
            )
        )
        (listed,) = runs.listed(project, data)
        assert listed["state"] == "interrupted"
        assert not runs.stop(data, run_id)
        assert stranger.poll() is None, "the stranger was not signalled"
        started = runs.start(
            project, data, ["true"], ["results"]
        )  # not blocked by the stale marker
        assert started["run_id"] != run_id
    finally:
        stranger.kill()
        stranger.wait()


def test_markers_that_are_not_markers_are_skipped_and_never_followed_out_of_the_folder(
    project, tmp_path
):
    data = tmp_path / "data"
    folder = runs.folder(data)
    folder.mkdir(parents=True)
    (tmp_path / "outside.log").write_text("outside")
    bad = {
        "20260101T000000-000001": [],
        "20260101T000000-000002": {
            "run_id": "20260101T000000-000002",
            "only": None,
            "record_before": 0,
        },
        "20260101T000000-000003": {
            "run_id": "20260101T000000-000003",
            "pid": "x",
            "only": None,
            "record_before": 0,
        },
        "20260101T000000-000004": {
            "run_id": "../../outside",
            "pid": 1,
            "only": None,
            "record_before": 0,
        },
        "20260101T000000-000005": {
            "run_id": "20260101T000000-000005",
            "pid": 1,
            "only": "results",
            "record_before": 0,
        },
    }
    for name, body in bad.items():
        (folder / f"{name}.json").write_text(json.dumps(body))
    assert runs.listed(project, data) == []
    runs.prune(data)
    assert (tmp_path / "outside.log").read_text() == "outside"
    assert runs.start(project, data, ["true"], None)["run_id"]


def test_a_presubmit_check_lists_numbers_no_claim_accounts_for(project, tmp_path):
    (project / "paper.txt").write_text(
        "We count the values. The total is 6. We drew 4321 samples.\n"
    )
    g = graph.build(
        project, tmp_path / "out" / "graph.json", check=True, fetch=False, presubmit=True
    )
    del g
    found = json.loads((tmp_path / "out" / "graph.json").read_text())["presubmit"]
    assert found["numbers_read"] is True
    assert [n["text"] for n in found["unbound"]] == ["4321"]
    assert (found["unpinned"], found["unsealed"]) == ([], [])
    graph.build(project, tmp_path / "out" / "graph.json", check=False, fetch=False)
    kept = json.loads((tmp_path / "out" / "graph.json").read_text())["presubmit"]
    assert kept["unbound_count"] == 1, "a refresh keeps the last Pre-submit check"


def test_the_export_does_not_carry_the_projects_folder_on_this_machine(served, project):
    with urllib.request.urlopen(f"{served}/api/export") as r:
        page = r.read().decode()
    assert embedded(page)["project_dir"] is None
    assert str(project) not in page
