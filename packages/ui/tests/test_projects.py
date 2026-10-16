"""The projects the drawer lists: remembered in the user's config folder, and
switched between in one server."""

from __future__ import annotations

import functools
import http.server
import json
import os
import pathlib
import subprocess
import sysconfig
import threading
import time
import urllib.error
import urllib.request

import pytest
from repro_ui import graph, projects, runs, server

TOKEN = "drawer-token"


def test_a_project_is_remembered_once_newest_first_with_nothing_but_when(tmp_path, own_config):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    projects.opened(a)
    time.sleep(1.1)
    projects.opened(b)
    assert [e["path"] for e in projects.read()] == [str(b.resolve()), str(a.resolve())]
    time.sleep(1.1)
    projects.opened(a)
    (first, second) = projects.read()
    assert (first["path"], second["path"]) == (str(a.resolve()), str(b.resolve()))
    stored = json.loads(projects.config_file().read_text())["projects"]
    assert all(set(e) == {"path", "opened_at"} for e in stored), "nothing else is stored"
    assert projects.config_file() == own_config / "reproducible-science" / "ui-projects.json"
    assert not list(tmp_path.rglob("ui-projects.json")), "nothing is written into a project"


def test_an_unreadable_file_reads_as_no_projects(own_config):
    path = projects.config_file()
    path.parent.mkdir(parents=True)
    for body in ("not json", "[]", '{"projects": [1, {"path": 2}, {"nopath": true}]}'):
        path.write_text(body)
        assert projects.read() == []


def test_the_title_is_the_manuscripts_and_absent_without_one(tmp_path):
    (tmp_path / "paper.tex").write_text(
        "% \\title{commented out}\n\\title[Short]{Reproducible Science: Machine-Checkable\n"
        "Claims\\thanks{Draft.} from N\\\"ust's {\\em Preregistration}}\n\\begin{document}\n"
    )
    assert (
        projects.title_of(tmp_path, "paper.tex")
        == "Reproducible Science: Machine-Checkable Claims from Nüst's Preregistration"
    )
    (tmp_path / "plain.tex").write_text("\\section{No title here}")
    assert projects.title_of(tmp_path, "plain.tex") is None
    assert projects.title_of(tmp_path, None) is None
    assert projects.title_of(tmp_path, "missing.tex") is None


def test_a_card_says_whether_the_project_was_checked(project, tmp_path):
    entry = {"path": str(project), "opened_at": ""}
    never = projects.summary(entry, server.data_dir, project)
    assert (never["claims"], never["name"], never["current"], never["title"]) == (
        None,
        "project",
        True,
        None,
    )
    graph.build(project, server.data_dir(project) / "graph.json", check=True, fetch=False)
    checked = projects.summary(entry, server.data_dir, tmp_path)
    assert (checked["claims"]["verified"], checked["claims"]["total"], checked["current"]) == (
        1,
        1,
        False,
    )


def serve(project: pathlib.Path, static: pathlib.Path):
    graph.build(project, server.data_dir(project) / "graph.json", check=False, fetch=False)
    static.mkdir(exist_ok=True)
    (static / "index.html").write_text("<!doctype html><html><head></head></html>")
    handler = type(
        "DrawerHandler",
        (server.Handler,),
        {
            "project": project,
            "groups": None,
            "data": server.data_dir(project),
            "fetch": False,
            "token": TOKEN,
        },
    )
    httpd = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(handler, directory=str(static))
    )
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def call(url: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode(),
        method="GET" if body is None else "POST",
        headers={}
        if body is None
        else {"Content-Type": "application/json", server.TOKEN_HEADER: TOKEN},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_the_page_switches_project_in_one_server_and_a_run_in_the_other_keeps_going(
    tmp_path, tools
):
    a, b = tmp_path / "a", tmp_path / "b"
    for folder in (a, b):
        folder.mkdir()
        tools.write_project(folder, with_step=True)
        projects.opened(folder)
    httpd, url = serve(a, tmp_path / "static")
    try:
        status, body = call(f"{url}/api/projects")
        listed = {pathlib.Path(p["path"]).name: p for p in body["projects"]}
        assert status == 200 and set(listed) == {"a", "b"}
        assert "starred" not in listed["a"]
        assert (listed["a"]["current"], listed["b"]["current"]) == (True, False)

        # A run in a, going while the page moves to b.
        going = runs.start(a, server.data_dir(a), ["sleep", "30"], ["results"])
        status, body = call(f"{url}/api/projects/open", {"path": str(b.resolve())})
        assert (status, body["project"]) == (200, str(b.resolve()))
        _, g = call(f"{url}/graph.json")
        assert g["project_dir"] == str(b.resolve())
        assert call(f"{url}/api/runs")[1]["runs"] == []
        assert runs.alive(going), "the run in the other project goes on"
        status, _ = call(f"{url}/api/projects/open", {"path": str(a.resolve())})
        assert status == 200
        assert [r["run_id"] for r in call(f"{url}/api/runs")[1]["runs"]] == [going["run_id"]]
        assert runs.stop(server.data_dir(a), going["run_id"])

        for path in (str(tmp_path), "/etc", str(tmp_path / "c"), 3):
            assert call(f"{url}/api/projects/open", {"path": path})[0] == 404, path
        assert (
            call(f"{url}/api/projects/star", {"path": str(b.resolve()), "starred": True})[0] == 404
        )
    finally:
        httpd.shutdown()


def test_switching_needs_this_pages_token(tmp_path, tools):
    a = tmp_path / "a"
    a.mkdir()
    tools.write_project(a, with_step=False)
    projects.opened(a)
    httpd, url = serve(a, tmp_path / "static")
    try:
        req = urllib.request.Request(
            f"{url}/api/projects/open",
            data=json.dumps({"path": str(a.resolve())}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=30)
            raise AssertionError("refused")
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        httpd.shutdown()


@pytest.mark.parametrize(
    ("tex", "title"),
    [
        ("\\title{Main\\thanks{a {b} c} Rest}", "Main Rest"),
        ("\\title{A\\\\[2pt] B}", "A B"),
        ("\\title{The $\\alpha$ test}", "The test"),
        ("\\title{\\texorpdfstring{$x$}{x} rule}", "x rule"),
        ("\\title{A\\\\% a comment\nB}", "A B"),
        ("\\iffalse \\title{Old} \\fi \\title{New}", "New"),
        ("\\title{Never closed", None),
        ("\\title{50\\% \\& more}", "50% & more"),
    ],
)
def test_odd_latex_in_a_title(tmp_path, tex, title):
    (tmp_path / "p.tex").write_text(tex)
    assert projects.title_of(tmp_path, "p.tex") == title


def test_a_manuscript_outside_the_project_is_never_read(tmp_path):
    (tmp_path / "outside.tex").write_text("\\title{Not this project's}")
    (tmp_path / "p").mkdir()
    assert projects.title_of(tmp_path / "p", "../outside.tex") is None


def test_one_folder_is_one_project_whatever_its_unicode_form_and_however_often_listed(own_config):
    path = projects.config_file()
    path.parent.mkdir(parents=True)
    nfc, nfd = "/w/café", "/w/café"
    path.write_text(
        json.dumps(
            {
                "projects": [
                    {"path": nfd, "opened_at": "2026-01-01"},
                    {"path": nfc, "opened_at": "2026-02-01"},
                    {"path": "/w/x", "opened_at": "2026-01-03"},
                    {"path": "/w/x", "opened_at": "2026-01-02"},
                ]
            }
        )
    )
    assert [(e["path"], e["opened_at"]) for e in projects.read()] == [
        (nfc, "2026-02-01"),
        ("/w/x", "2026-01-03"),
    ]


def test_a_list_this_cannot_read_is_never_written_over(tmp_path, own_config):
    path = projects.config_file()
    path.parent.mkdir(parents=True)
    path.write_text("{ not json, but someone's list")
    with pytest.raises(projects.Unreadable):
        projects.opened(tmp_path)
    assert path.read_text() == "{ not json, but someone's list"


def test_processes_remembering_at_once_lose_nothing(tmp_path, own_config):
    # Each write waits a moment first, so the processes' reads and writes overlap: without the
    # lock across processes, one's write drops what another added meanwhile.
    script = (
        "import os, pathlib, time\n"
        "from repro_ui import projects\n"
        "write = projects.write\n"
        "projects.write = lambda entries: (time.sleep(0.2), write(entries))\n"
        "for f in os.environ['FOLDERS'].split('\\n'):\n"
        "    projects.opened(pathlib.Path(f))\n"
    )
    python = str(pathlib.Path(sysconfig.get_path("scripts")) / "python")
    folders = []
    for i in range(12):
        (tmp_path / f"p{i}").mkdir()
        folders.append(str(tmp_path / f"p{i}"))
    procs = [
        subprocess.Popen(
            [python, "-c", script], env={**os.environ, "FOLDERS": "\n".join(folders[k::4])}
        )
        for k in range(4)
    ]
    assert [p.wait(timeout=120) for p in procs] == [0] * 4
    assert sorted(e["path"] for e in projects.read()) == sorted(
        str(pathlib.Path(f).resolve()) for f in folders
    )


def test_a_card_falls_back_to_the_check_history_without_the_pages_report(project, tools):
    tools.git(project, "init", "-q")
    graph.build(project, server.data_dir(project) / "graph.json", check=True, fetch=False)
    (server.data_dir(project) / "verify-report.json").unlink()
    found = projects.claims_of(project, server.data_dir(project))
    assert (found["verified"], found["total"]) == (1, 1)
    assert set(found) == {"verified", "total"}, "no date of the last check yet"


def test_a_project_whose_repro_yaml_is_malformed_is_listed_unavailable_beside_the_others(
    tmp_path, tools
):
    good, bad = tmp_path / "good", tmp_path / "bad"
    for folder in (good, bad):
        folder.mkdir()
        tools.write_project(folder, with_step=False)
        projects.opened(folder)
    (bad / "repro.yaml").write_text("- a\n- list\n")
    listed = {pathlib.Path(p["path"]).name: p for p in projects.summaries(server.data_dir, good)}
    assert (listed["good"]["available"], listed["bad"]["available"]) == (True, False)


def test_a_folder_never_opened_is_refused_even_holding_repro_yaml_and_a_stale_tab_is_told(
    tmp_path, tools
):
    a, stranger = tmp_path / "a", tmp_path / "stranger"
    for folder in (a, stranger):
        folder.mkdir()
        tools.write_project(folder, with_step=False)
    projects.opened(a)
    httpd, url = serve(a, tmp_path / "static")
    try:
        assert call(f"{url}/api/projects/open", {"path": str(stranger.resolve())})[0] == 404
        req = urllib.request.Request(
            f"{url}/api/refresh",
            data=b"{}",
            method="POST",
            headers={
                "Content-Type": "application/json",
                server.TOKEN_HEADER: TOKEN,
                server.PROJECT_HEADER: str(stranger.resolve()),
            },
        )
        try:
            urllib.request.urlopen(req, timeout=60)
            raise AssertionError("a page showing another project was let through")
        except urllib.error.HTTPError as e:
            assert (e.code, json.loads(e.read())["error"]) == (409, server.SWITCHED)
    finally:
        httpd.shutdown()


def test_a_list_that_cannot_be_written_never_stops_a_switch(tmp_path, tools, own_config):
    a, b = tmp_path / "a", tmp_path / "b"
    for folder in (a, b):
        folder.mkdir()
        tools.write_project(folder, with_step=False)
        projects.opened(folder)
    httpd, url = serve(a, tmp_path / "static")
    folder = projects.config_file().parent
    folder.chmod(0o500)
    try:
        status, body = call(f"{url}/api/projects/open", {"path": str(b.resolve())})
        assert (status, body["project"]) == (200, str(b.resolve()))
        assert call(f"{url}/api/health")[1]["project"] == str(b.resolve())
    finally:
        folder.chmod(0o700)
        httpd.shutdown()
