"""The server's endpoints, over HTTP, against a real project."""

from __future__ import annotations

import functools
import http.server
import json
import subprocess
import threading
import urllib.error
import urllib.request

import pytest
from repro_ui import graph, server


@pytest.fixture
def served(project, tmp_path):
    data = tmp_path / "data"
    graph.build(project, data / "graph.json", check=False, fetch=False)
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>page</title>")
    handler = type(
        "TestHandler",
        (server.Handler,),
        {"project": project, "groups": None, "data": data, "fetch": False},
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
        headers={"Content-Type": "application/json"},
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
