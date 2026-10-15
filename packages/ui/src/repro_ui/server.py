"""Serve the page for one project on localhost: `repro ui`, or `repro-ui`.

    repro ui [project] [--port 5190] [--offline] [--no-browser]

Serves the built page on localhost only. POST /api/refresh re-reads the
project's records (`repro stale`, `results verify`, `prereg check`, the ledger and the check history)
and writes nothing to the project. POST /api/verify also runs `repro verify`, which records the check
in the project's history. Either rewrites graph.json; the page then reloads it.
GET /api/health tells the page that re-checking is available, so the button stays hidden when the
same files are served by a plain static host.

POST /api/fix-request appends {id, created_at, project, subject, kind, prompt} to
~/.claude/repro-fixes/queue.jsonl, which the repro Claude Code mod watches: a session working
in that project shows the request above its prompt and loads the prompt into the box on request.
It never starts an agent or runs anything.

POST /api/reproduce with {"only": [step ids]} or {"only": null} runs `repro reproduce` for those
rebuild steps, or for all of them. That executes the commands repro.yaml declares, so the page asks
before calling it. `repro reproduce` appends the re-run to the project's .repro/reproductions.jsonl;
the graph is then rebuilt from the records.

Every request must name this server by a loopback address. Every POST must also come from this
server's own page: JSON, from its own origin, carrying the token the server put in the page it
served at launch. A page on another site, or a domain rebound to this address, is refused.
"""

from __future__ import annotations

import argparse
import datetime
import functools
import hashlib
import hmac
import http.server
import json
import pathlib
import secrets
import subprocess
import threading
import time
import urllib.parse
import uuid
import webbrowser

import yaml

from repro_ui import graph as build_graph

#: The built page, which every wheel carries.
DIST = pathlib.Path(__file__).resolve().parent / "static"
#: The header a POST carries the launch token in.
TOKEN_HEADER = "X-Repro-UI-Token"
QUEUE = pathlib.Path.home() / ".claude" / "repro-fixes" / "queue.jsonl"
MAX_PROMPT = 8000
#: The largest request body read. A larger declared length is refused unread.
MAX_BODY = 64_000
MAX_FILE = 2_000_000
REPRODUCE_TIMEOUT = 3600


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
        """Whether the request names this server by a loopback address, as the page does.

        A page on another site can make the browser send requests here. Refusing a `Host` that
        is not `127.0.0.1` or `localhost` at this port stops a rebound domain from reading
        anything; for a request that changes something, the `Origin` the browser sets must be
        this server too, and the body must be sent as JSON, which no form and no simple
        cross-site request can do without the browser asking first."""
        port = self.server.server_address[1]
        ours = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in ours:
            return False
        if self.command != "POST":
            return True
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{h}" for h in ours}:
            return False
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            return False
        sent = self.headers.get(TOKEN_HEADER) or ""
        return bool(self.token) and hmac.compare_digest(sent, self.token)

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

    def _fix_request(self, body: dict) -> None:
        prompt, subject, kind = (
            body.get("prompt"),
            body.get("subject"),
            body.get("kind"),
        )
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
            return self._json(400, {"ok": False, "error": "prompt missing or too long"})
        if (
            not isinstance(kind, str)
            or kind not in {"claim", "stale"}
            or not isinstance(subject, str)
        ):
            return self._json(400, {"ok": False, "error": "kind or subject missing"})
        request = {
            "id": uuid.uuid4().hex[:12],
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "project": str(self.project),
            "subject": subject[:200],
            "kind": kind,
            "prompt": prompt,
        }
        QUEUE.parent.mkdir(parents=True, exist_ok=True)
        with QUEUE.open("a") as f:
            f.write(json.dumps(request) + "\n")
        self._json(200, {"ok": True, "id": request["id"]})

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
                {
                    "ok": False,
                    "error": "only must be null or a list of declared step ids",
                },
            )
        command = [
            build_graph.tool("repro"),
            "reproduce",
            "--format",
            "json",
            *[x for i in (only or []) for x in ("--only", i)],
            str(self.project / "repro.yaml"),
        ]
        if not self.lock.acquire(blocking=False):
            return self._json(409, {"ok": False, "error": "a check is already running"})
        try:
            started = time.monotonic()
            out = subprocess.run(
                command,
                cwd=self.project,
                capture_output=True,
                text=True,
                timeout=REPRODUCE_TIMEOUT,
                check=False,
            )
            build_graph.build(
                self.project,
                self.data / "graph.json",
                self.groups,
                check=False,
                fetch=self.fetch,
            )
            try:
                states = [
                    r.get("state")
                    for r in json.loads(out.stdout)["reproduction"].get("regenerations", [])
                ]
            except (json.JSONDecodeError, KeyError, AttributeError):
                states = []
            self._json(
                200,
                {
                    "ok": bool(states),
                    "exit_code": out.returncode,
                    "seconds": round(time.monotonic() - started, 2),
                    "counts": {k: states.count(k) for k in set(states)},
                    "error": "" if states else (out.stderr or out.stdout).strip()[-800:],
                },
            )
        except subprocess.TimeoutExpired:
            self._json(
                200,
                {"ok": False, "error": f"stopped after {REPRODUCE_TIMEOUT} seconds"},
            )
        except Exception as e:  # reported to the page
            self._json(500, {"ok": False, "error": str(e)})
        finally:
            self.lock.release()

    def do_POST(self) -> None:
        if not self._local():
            return self._json(403, {"ok": False, "error": "not a request from this page"})
        try:
            body = self._body()
        except RequestRefused as e:
            self.close_connection = True
            return self._json(e.status, {"ok": False, "error": e.error})
        if self.path == "/api/fix-request":
            return self._fix_request(body)
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
