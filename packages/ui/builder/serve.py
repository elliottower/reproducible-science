"""Serve the lineage view for one project, with a re-check endpoint.

    uv run --no-project --with pyyaml==6.0.2 python builder/serve.py <project> [--port 5190]

Serves web/dist on localhost only. POST /api/recheck runs `repro verify` and `repro stale` over
the project again (through build_graph.build) and rewrites graph.json; the page then reloads it.
GET /api/health tells the page that re-checking is available, so the button stays hidden when the
same files are served by a plain static host.
"""

import argparse
import functools
import http.server
import json
import pathlib
import threading
import time

import build_graph

DIST = pathlib.Path(__file__).resolve().parent.parent / "web" / "dist"


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
        if self.path.split("?")[0] == "/graph.json":
            self.send_response(200)
            data = (DIST / "graph.json").read_bytes()
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path != "/api/recheck":
            return self._json(404, {"error": "not found"})
        if not self.lock.acquire(blocking=False):
            return self._json(409, {"error": "a check is already running"})
        try:
            started = time.monotonic()
            summary = build_graph.build(self.project, DIST / "graph.json", self.groups)
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
    print(build_graph.build(Handler.project, DIST / "graph.json", a.groups))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), functools.partial(Handler, directory=str(DIST)))
    print(f"http://localhost:{a.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
