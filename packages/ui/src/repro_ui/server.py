"""Serve the page for one project on localhost: `repro ui`, or `repro-ui`.

    repro ui [project] [--port 5190] [--offline] [--no-browser]

Serves the built page on localhost only. POST /api/refresh re-reads the
project's records (`repro stale`, `results verify --files`, `prereg check`, the ledger and the check history)
and writes nothing to the project. POST /api/verify also runs `repro verify`, which records the check
in the project's history. Either rewrites graph.json; the page then reloads it.
GET /api/health tells the page that re-checking is available, so the button stays hidden when the
same files are served by a plain static host. GET /api/diff?issue=<id>&path=<path> shows the
recorded bytes of a file an issue names (a frozen plan, a sealed file) against the file now, read
with `git show` from the commit the record names; any other path is refused.

POST /api/reproduce with {"only": [step ids]} or {"only": null} runs `repro reproduce` for those
rebuild steps, or for all of them. That executes the commands repro.yaml declares, so the page asks
before calling it. The answer streams as it happens, one JSON object per line: {"line": text} for
each line `repro reproduce` prints, then {"done": true, ...} with what the re-run recorded. `repro
reproduce` appends the re-run to the project's .repro/reproductions.jsonl; the graph is then rebuilt
from the records.

Every request must name this server by a loopback address. Every POST must also come from this
server's own page: JSON, from its own origin, carrying the token the server put in the page it
served at launch. A page on another site, or a domain rebound to this address, is refused.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import hmac
import http.server
import json
import os
import pathlib
import secrets
import subprocess
import threading
import time
import urllib.parse
import webbrowser

import yaml

from repro_ui import graph as build_graph

#: The built page, which every wheel carries.
DIST = pathlib.Path(__file__).resolve().parent / "static"
#: The header a POST carries the launch token in.
TOKEN_HEADER = "X-Repro-UI-Token"
#: The largest request body read. A larger declared length is refused unread.
MAX_BODY = 64_000
MAX_FILE = 2_000_000
REPRODUCE_TIMEOUT = 3600
#: What a refused POST says: a stale token, or a request that is not from this server's page.
OUT_OF_DATE = "This page is out of date: reload it."
NOT_OURS = "Refused: not a request from this page."


def data_dir(project: pathlib.Path) -> pathlib.Path:
    """Where the page's data and caches for `project` are kept: inside its git directory, beside
    the record of checks `repro verify` keeps there, so nothing appears in the working tree and
    nothing is committed. A project outside git gets a folder in the user's cache instead."""
    git_dir = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    if git_dir.returncode == 0 and git_dir.stdout.strip():
        return pathlib.Path(git_dir.stdout.strip()) / "repro" / "ui"
    key = hashlib.sha256(str(project).encode()).hexdigest()[:16]
    return pathlib.Path.home() / ".cache" / "reproducible-science-ui" / key


class RequestRefused(Exception):
    """A request body that is refused, with the status to answer it with."""

    def __init__(self, status: int, error: str) -> None:
        super().__init__(error)
        self.status = status
        self.error = error


class Handler(http.server.SimpleHTTPRequestHandler):
    project: pathlib.Path
    groups: pathlib.Path | None
    data: pathlib.Path
    fetch: bool = True
    #: Made at launch and written into the page this server serves; a POST must carry it back.
    token: str = ""
    lock = threading.Lock()
    #: Seconds a request may leave its socket idle. A body shorter than the length it declared
    #: would otherwise hold its thread until the client goes away.
    timeout = 5

    def log_message(self, format: str, *args: object) -> None:  # one line per request is noise
        pass

    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _local(self) -> bool:
        """Whether the request names this server by a loopback address, as the page does."""
        return self._refusal() is None

    def _refusal(self) -> str | None:
        """Why the request is refused, or None where it is not: it must name this server by a
        loopback address, as the page does.

        A page on another site can make the browser send requests here. Refusing a `Host` that
        is not `127.0.0.1` or `localhost` at this port stops a rebound domain from reading
        anything; for a request that changes something, the `Origin` the browser sets must be
        this server too, and the body must be sent as JSON, which no form and no simple
        cross-site request can do without the browser asking first."""
        port = self.server.server_address[1]
        ours = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in ours:
            return NOT_OURS
        if self.command != "POST":
            return None
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{h}" for h in ours}:
            return NOT_OURS
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            return NOT_OURS
        sent = self.headers.get(TOKEN_HEADER) or ""
        if not (self.token and hmac.compare_digest(sent, self.token)):
            # The only refusal an ordinary user meets: a tab opened before the server restarted
            # carries the previous launch's token.
            return OUT_OF_DATE
        return None

    def _body(self) -> dict:
        """The request's JSON object. Raises RequestRefused where it is not one, where its
        declared length is too large to read (413), or where it does not arrive in time."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise RequestRefused(400, "Content-Length is not a number") from None
        if length < 0:
            raise RequestRefused(400, "Content-Length is negative")
        if length > MAX_BODY:
            raise RequestRefused(413, f"a body over {MAX_BODY:,} bytes is not read")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except TimeoutError:
            raise RequestRefused(408, "the body did not arrive") from None
        except (ValueError, RecursionError):
            raise RequestRefused(400, "body is not JSON") from None
        if not isinstance(body, dict):
            raise RequestRefused(400, "body is not a JSON object")
        return body

    def do_GET(self) -> None:
        if not self._local():
            return self._json(403, {"ok": False, "error": "not this server's address"})
        if self.path.split("?")[0] in {"/", "/index.html"}:
            return self._page()
        if self.path == "/api/health":
            return self._json(200, {"recheck": True, "project": str(self.project)})
        if self.path.startswith("/api/file?"):
            return self._file(
                urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("path", [""])[0]
            )
        if self.path.startswith("/api/diff?"):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._diff(query.get("issue", [""])[0], query.get("path", [""])[0])
        if self.path.split("?")[0] == "/graph.json":
            self.send_response(200)
            data = (self.data / "graph.json").read_bytes()
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()

    def _page(self) -> None:
        """The page, with this launch's token in it for the page to send back on every POST."""
        html = (pathlib.Path(self.directory) / "index.html").read_text()
        meta = f'<meta name="repro-ui-token" content="{self.token}" />'
        data = html.replace("<head>", f"<head>\n    {meta}", 1).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file(self, rel: str) -> None:
        """A file the records name (a run's output, or a file the manifest pins), read-only, from
        inside the project. Anything else is refused, so this cannot read the rest of the disk."""
        graph = json.loads((self.data / "graph.json").read_text())
        named = {
            o
            for r in graph.get("tabs", {}).get("results", {}).get("runs", [])
            for o in r["outputs"]
        }
        named |= {
            n["path"] for n in graph["nodes"] if n.get("type") == "artifact" and n.get("path")
        }
        target = (self.project / rel).resolve()
        if rel not in named or not target.is_relative_to(self.project) or not target.is_file():
            return self._json(404, {"ok": False, "error": "not a file the records name"})
        if target.stat().st_size > MAX_FILE:
            return self._json(
                200,
                {
                    "ok": False,
                    "error": f"{target.stat().st_size:,} bytes; too large to show here",
                },
            )
        return self._json(200, {"ok": True, "text": target.read_text(errors="replace")})

    def _diff(self, issue: str, rel: str) -> None:
        """The recorded bytes of a file against the file now, for an item of the issues list in
        graph.json: a plan against its frozen commit, a sealed file against the commit holding
        the sealed bytes. Read-only. A path the issues list does not name is refused."""
        try:
            graph = json.loads((self.data / "graph.json").read_text())
            body = build_graph.issue_diff(self.project, graph, issue, rel)
        except build_graph.NotNamed:
            return self._json(404, {"ok": False, "error": "not a file the records name"})
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            return self._json(500, {"ok": False, "error": f"could not read the file: {e}"})
        return self._json(200, body)

    def _reproduce(self, body: dict) -> None:
        only = body.get("only")
        declared = {
            r.get("id")
            for r in yaml.safe_load((self.project / "repro.yaml").read_text()).get(
                "regenerations", []
            )
        }
        if only is not None and (
            not isinstance(only, list)
            or not only
            or not all(isinstance(i, str) for i in only)
            or not set(only) <= declared
        ):
            return self._json(
                400,
                {"ok": False, "error": "only must be null or a list of declared step ids"},
            )
        if not self.lock.acquire(blocking=False):
            return self._json(409, {"ok": False, "error": "a check is already running"})
        try:
            self._stream_reproduce(only)
        finally:
            self.lock.release()

    def _stream_reproduce(self, only: list[str] | None) -> None:
        """Run `repro reproduce` and send each line it prints as it prints it, then what the
        re-run recorded. The response has no length, so the connection closes when it ends.

        A page that goes away mid-run (a reload, a closed tab) does not stop the run: it goes on to
        the end, is recorded, and the page's data is rebuilt, so the next load shows it."""
        args = ["reproduce", *[x for i in (only or []) for x in ("--only", i)]]
        record = self.project / ".repro" / "reproductions.jsonl"
        before = record.read_text().count("\n") if record.exists() else 0
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.close_connection = True
        gone = False

        def send(event: dict) -> None:
            nonlocal gone
            if gone:
                return
            try:
                self.wfile.write((json.dumps(event) + "\n").encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                gone = True

        send({"line": "$ repro " + " ".join(args)})
        started = time.monotonic()
        try:
            proc = subprocess.Popen(
                [build_graph.tool("repro"), *args, str(self.project / "repro.yaml")],
                cwd=self.project,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        except OSError as e:  # `repro` could not be started at all
            send({"done": True, "ok": False, "error": f"repro could not be started: {e}"})
            return
        # A step that prints nothing still has to stop: the timer kills it, which ends the read.
        watchdog = threading.Timer(REPRODUCE_TIMEOUT, proc.kill)
        watchdog.start()
        try:
            for line in proc.stdout:  # read to the end even once the page has gone
                send({"line": line.rstrip("\n")})
        finally:
            watchdog.cancel()
            exit_code = proc.wait()
        seconds = round(time.monotonic() - started, 2)
        if seconds >= REPRODUCE_TIMEOUT:
            send({"line": f"stopped after {REPRODUCE_TIMEOUT} seconds"})
        try:
            lines = record.read_text().splitlines() if record.exists() else []
            steps = json.loads(lines[-1]).get("regenerations", []) if len(lines) > before else []
            rebuilt = time.monotonic()
            build_graph.build(
                self.project, self.data / "graph.json", self.groups, check=False, fetch=self.fetch
            )
            rebuild_seconds = round(time.monotonic() - rebuilt, 2)
        except Exception as e:  # the re-run ended; say what failed after it, not a lost connection
            send(
                {
                    "done": True,
                    "ok": False,
                    "exit_code": exit_code,
                    "seconds": seconds,
                    "error": f"the re-run ended, but reading its record failed: {e}",
                }
            )
            return
        states = [r.get("state") for r in steps]
        send(
            {
                "done": True,
                "ok": bool(steps),
                "exit_code": exit_code,
                "seconds": seconds,
                "rebuild_seconds": rebuild_seconds,
                "counts": {k: states.count(k) for k in set(states)},
                "steps": [
                    {
                        "id": r.get("regeneration_id"),
                        "state": r.get("state"),
                        "seconds": r.get("duration_seconds"),
                    }
                    for r in steps
                ],
                "error": "" if steps else "repro reproduce recorded no re-run",
            }
        )

    def do_POST(self) -> None:
        refused = self._refusal()
        if refused is not None:
            return self._json(403, {"ok": False, "error": refused})
        try:
            body = self._body()
        except RequestRefused as e:
            self.close_connection = True
            return self._json(e.status, {"ok": False, "error": e.error})
        if self.path == "/api/reproduce":
            return self._reproduce(body)
        if self.path not in {"/api/refresh", "/api/verify"}:
            return self._json(404, {"error": "not found"})
        if not self.lock.acquire(blocking=False):
            return self._json(409, {"error": "a check is already running"})
        try:
            started = time.monotonic()
            summary = build_graph.build(
                self.project,
                self.data / "graph.json",
                self.groups,
                check=self.path == "/api/verify",
                fetch=self.fetch,
            )
            self._json(
                200,
                {
                    "ok": True,
                    "seconds": round(time.monotonic() - started, 2),
                    "summary": summary,
                },
            )
        except Exception as e:  # reported to the page, which shows it beside the button
            self._json(500, {"ok": False, "error": str(e)})
        finally:
            self.lock.release()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="repro ui",
        description="Build the page for a project's records and serve it on localhost.",
    )
    ap.add_argument(
        "project",
        nargs="?",
        default=".",
        type=pathlib.Path,
        help="the folder holding repro.yaml (default: this one)",
    )
    ap.add_argument("--port", type=int, default=5190, help="the port to serve on (default: 5190)")
    ap.add_argument(
        "--groups",
        type=pathlib.Path,
        help="a YAML list of {group, match}: a file whose id matches the pattern goes to that group",
    )
    ap.add_argument(
        "--offline",
        action="store_true",
        help="look up no DOI landing page; only those already cached are linked",
    )
    ap.add_argument("--no-browser", action="store_true", help="print the address and open nothing")
    a = ap.parse_args(argv)
    project = a.project.resolve()
    if not (project / "repro.yaml").is_file():
        print(f"{project}: no repro.yaml here. `repro manifest init` writes one.")
        return 2
    if not (DIST / "index.html").is_file():
        print(
            f"the page is not built: no {DIST / 'index.html'}. In packages/ui/web: npm ci && npm run build"
        )
        return 2
    Handler.project = project
    Handler.groups = a.groups
    Handler.data = data_dir(project)
    Handler.fetch = not a.offline
    Handler.token = secrets.token_urlsafe(24)
    print(f"reading {project} ...")
    build_graph.build(
        project, Handler.data / "graph.json", a.groups, check=False, fetch=Handler.fetch
    )
    try:
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", a.port), functools.partial(Handler, directory=str(DIST))
        )
    except OSError as e:
        print(f"port {a.port}: {e.strerror}. Pass --port to use another.")
        return 2
    url = f"http://localhost:{server.server_address[1]}/"
    print(f"{url}  (Ctrl-C stops it)")
    if not a.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
