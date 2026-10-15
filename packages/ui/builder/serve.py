"""Serve the lineage view for one project, with a re-check endpoint.

    uv run --no-project --with pyyaml==6.0.2 python builder/serve.py <project> [--port 5190]

Serves web/dist on localhost only. POST /api/refresh re-reads the
project's records (`repro stale`, `results verify`, `prereg check`, the ledger and the check history)
and writes nothing to the project. POST /api/verify also runs `repro verify`, which records the check
in the project's history. Either rewrites graph.json; the page then reloads it.
GET /api/health tells the page that re-checking is available, so the button stays hidden when the
same files are served by a plain static host.

POST /api/fix-request appends {id, created_at, project, subject, kind, prompt} to
~/.claude/repro-fixes/queue.jsonl, which the repro-fixes Claude Code mod watches: a session working
in that project shows the request above its prompt and loads the prompt into the box on request.
It never starts an agent or runs anything.

POST /api/reproduce with {"only": [step ids]} or {"only": null} runs `repro reproduce` for those
rebuild steps, or for all of them. That executes the commands repro.yaml declares, so the page asks
before calling it. `repro reproduce` appends the re-run to the project's .repro/reproductions.jsonl;
the graph is then rebuilt from the records.
"""

import argparse
import datetime
import functools
import http.server
import json
import pathlib
import subprocess
import threading
import time
import urllib.parse
import uuid

import build_graph
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "web" / "dist"
# The server's own data, outside the build output: `vite build` copies web/public over dist and
# would replace a graph.json written there with an older one.
DATA = ROOT / ".data"
QUEUE = pathlib.Path.home() / ".claude" / "repro-fixes" / "queue.jsonl"
MAX_PROMPT = 8000
MAX_FILE = 2_000_000
REPRODUCE_TIMEOUT = 3600


class Handler(http.server.SimpleHTTPRequestHandler):
    project: pathlib.Path
    groups: pathlib.Path | None
    lock = threading.Lock()

    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/api/health":
            return self._json(200, {"recheck": True, "project": str(self.project)})
        if self.path.startswith("/api/file?"):
            return self._file(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("path", [""])[0])
        if self.path.split("?")[0] == "/graph.json":
            self.send_response(200)
            data = (DATA / "graph.json").read_bytes()
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()

    def _file(self, rel: str) -> None:
        """A file the records name (a run's output, or a file the manifest pins), read-only, from
        inside the project. Anything else is refused, so this cannot read the rest of the disk."""
        graph = json.loads((DATA / "graph.json").read_text())
        named = {o for r in graph.get("tabs", {}).get("results", {}).get("runs", []) for o in r["outputs"]}
        named |= {n["path"] for n in graph["nodes"] if n.get("type") == "artifact" and n.get("path")}
        target = (self.project / rel).resolve()
        if rel not in named or not target.is_relative_to(self.project) or not target.is_file():
            return self._json(404, {"ok": False, "error": "not a file the records name"})
        if target.stat().st_size > MAX_FILE:
            return self._json(200, {"ok": False, "error": f"{target.stat().st_size:,} bytes; too large to show here"})
        return self._json(200, {"ok": True, "text": target.read_text(errors="replace")})

    def _fix_request(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(min(length, 64_000)) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"ok": False, "error": "body is not JSON"})
        prompt, subject, kind = body.get("prompt"), body.get("subject"), body.get("kind")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
            return self._json(400, {"ok": False, "error": "prompt missing or too long"})
        if kind not in {"claim", "stale"} or not isinstance(subject, str):
            return self._json(400, {"ok": False, "error": "kind or subject missing"})
        request = {
            "id": uuid.uuid4().hex[:12],
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "project": str(self.project),
            "subject": subject[:200],
            "kind": kind,
            "prompt": prompt,
        }
        QUEUE.parent.mkdir(parents=True, exist_ok=True)
        with QUEUE.open("a") as f:
            f.write(json.dumps(request) + "\n")
        self._json(200, {"ok": True, "id": request["id"]})

    def _reproduce(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(min(length, 64_000)) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"ok": False, "error": "body is not JSON"})
        only = body.get("only")
        declared = {r["id"] for r in yaml.safe_load((self.project / "repro.yaml").read_text()).get("regenerations", [])}
        if only is not None and (not isinstance(only, list) or not only or not set(only) <= declared):
            return self._json(400, {"ok": False, "error": "only must be null or a list of declared step ids"})
        command = ["repro", "reproduce", "--format", "json", *[x for i in (only or []) for x in ("--only", i)],
                   str(self.project / "repro.yaml")]
        if not self.lock.acquire(blocking=False):
            return self._json(409, {"ok": False, "error": "a check is already running"})
        try:
            started = time.monotonic()
            out = subprocess.run(command, cwd=self.project, capture_output=True, text=True,
                                 timeout=REPRODUCE_TIMEOUT, check=False)
            build_graph.build(self.project, DATA / "graph.json", self.groups, check=False)
            try:
                states = [r.get("state") for r in json.loads(out.stdout)["reproduction"].get("regenerations", [])]
            except (json.JSONDecodeError, KeyError, AttributeError):
                states = []
            self._json(200, {"ok": bool(states), "exit_code": out.returncode,
                             "seconds": round(time.monotonic() - started, 2),
                             "counts": {k: states.count(k) for k in set(states)},
                             "error": "" if states else (out.stderr or out.stdout).strip()[-800:]})
        except subprocess.TimeoutExpired:
            self._json(200, {"ok": False, "error": f"stopped after {REPRODUCE_TIMEOUT} seconds"})
        except Exception as e:  # reported to the page
            self._json(500, {"ok": False, "error": str(e)})
        finally:
            self.lock.release()

    def do_POST(self) -> None:
        if self.path == "/api/fix-request":
            return self._fix_request()
        if self.path == "/api/reproduce":
            return self._reproduce()
        if self.path not in {"/api/refresh", "/api/verify"}:
            return self._json(404, {"error": "not found"})
        if not self.lock.acquire(blocking=False):
            return self._json(409, {"error": "a check is already running"})
        try:
            started = time.monotonic()
            summary = build_graph.build(self.project, DATA / "graph.json", self.groups, check=self.path == "/api/verify")
            self._json(200, {"ok": True, "seconds": round(time.monotonic() - started, 2), "summary": summary})
        except Exception as e:  # reported to the page, which shows it beside the button
            self._json(500, {"ok": False, "error": str(e)})
        finally:
            self.lock.release()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", type=pathlib.Path)
    ap.add_argument("--port", type=int, default=5190)
    ap.add_argument("--groups", type=pathlib.Path)
    a = ap.parse_args()
    Handler.project = a.project.resolve()
    Handler.groups = a.groups
    print(build_graph.build(Handler.project, DATA / "graph.json", a.groups, check=False))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), functools.partial(Handler, directory=str(DIST)))
    print(f"http://localhost:{a.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
