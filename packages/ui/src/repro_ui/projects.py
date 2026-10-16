"""The projects `repro ui` has been run in, for the page's project drawer.

Kept in one small JSON file in the user's config folder, never in a repository:

    $XDG_CONFIG_HOME/reproducible-science/ui-projects.json   (~/.config/... by default)

Each entry is a project folder, when the page last opened it, and whether it is starred. What a
drawer card shows about a project (its title, its claims) is read from the project and from the
page's own data for it when the drawer asks, so nothing here goes stale.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import datetime
import fcntl
import json
import os
import pathlib
import re
import tempfile
import threading
import unicodedata

from repro_ui import graph as build_graph

#: Serializes writes to the file between the threads of one server; `locked` adds a file lock
#: for the other `repro ui` processes on the machine.
_lock = threading.Lock()


class Unreadable(Exception):
    """The file exists and is not a list of projects; it is never written over."""


def config_file() -> pathlib.Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(pathlib.Path.home() / ".config")
    return pathlib.Path(base) / "reproducible-science" / "ui-projects.json"


def norm(path: str) -> str:
    """One spelling per folder: the same name typed in two Unicode forms is one project."""
    return unicodedata.normalize("NFC", path)


def entries_in(text: str) -> list[dict]:
    """The projects a file's text lists, one per folder (the newest kept), newest opened first.
    Raises Unreadable where the text is not such a list."""
    try:
        data = json.loads(text)
    except ValueError:
        raise Unreadable from None
    if not isinstance(data, dict) or not isinstance(data.get("projects", []), list):
        raise Unreadable
    seen: dict[str, dict] = {}
    for e in data.get("projects", []):
        if not (isinstance(e, dict) and isinstance(e.get("path"), str)):
            continue
        entry = {
            "path": norm(e["path"]),
            "opened_at": e.get("opened_at") if isinstance(e.get("opened_at"), str) else "",
            "starred": e.get("starred") is True,
        }
        if entry["path"] not in seen or entry["opened_at"] > seen[entry["path"]]["opened_at"]:
            seen[entry["path"]] = entry
    return sorted(seen.values(), key=lambda e: e["opened_at"], reverse=True)


def read() -> list[dict]:
    """Every remembered project, newest opened first. A missing or unreadable file reads as none."""
    try:
        return entries_in(config_file().read_text())
    except (OSError, Unreadable):
        return []


@contextlib.contextmanager
def locked():
    """Hold the list for a read, change and write: this server's threads and, through a lock file
    beside the list, every other `repro ui` on the machine."""
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock, open(path.with_name(path.name + ".lock"), "a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(guard, fcntl.LOCK_UN)


def current_entries() -> list[dict]:
    """The list, for a change to it. Raises Unreadable rather than let a write lose the stars of
    a file this cannot read."""
    try:
        text = config_file().read_text()
    except FileNotFoundError:
        return []
    return entries_in(text)


def write(entries: list[dict]) -> None:
    """Replace the list through a temporary file of its own, so writers never share one."""
    path = config_file()
    fd, partial = tempfile.mkstemp(prefix=path.name + ".", suffix=".partial", dir=path.parent)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps({"projects": entries}, indent=1))
    os.replace(partial, path)


def opened(project: pathlib.Path) -> None:
    """Remember that the page opened `project` now, keeping its star. Raises OSError or
    Unreadable where the list cannot be written; the caller goes on without it."""
    key = norm(str(project.resolve()))
    with locked():
        entries = current_entries()
        before = next((e for e in entries if e["path"] == key), None)
        entries = [e for e in entries if e["path"] != key]
        entries.insert(
            0,
            {
                "path": key,
                "opened_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
                "starred": bool(before and before["starred"]),
            },
        )
        write(entries)


def star(path: str, starred: bool) -> bool:
    """Star or unstar a remembered project. False where `path` is not one."""
    with locked():
        entries = current_entries()
        hit = next((e for e in entries if e["path"] == norm(path)), None)
        if hit is None:
            return False
        hit["starred"] = starred
        write(entries)
    return True


def known(path: str) -> pathlib.Path | None:
    """`path` as a project folder, only where it is a remembered one that still holds repro.yaml."""
    if not any(e["path"] == norm(path) for e in read()):
        return None
    folder = pathlib.Path(path)
    return folder if (folder / "repro.yaml").is_file() else None


TITLE = re.compile(r"\\title\s*(?:\[[^\]]*\])?\s*\{")


def argument(src: str, start: int) -> int:
    """The index just past the brace group that opens at `start - 1`, by counting braces, or
    the end of `src` where the group never closes."""
    i, depth = start, 1
    while i < len(src) and depth:
        if src[i] == "\\":
            i += 2
            continue
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    return i if not depth else len(src) + 1


def drop_command(src: str, name: str, keep: int | None = None) -> str:
    """`src` with every `\\name{...}{...}` removed, its braces counted; with `keep`, replaced by
    that argument's text instead (1-based)."""
    out, pos = [], 0
    pattern = re.compile(r"\\" + name + r"\s*\{")
    while m := pattern.search(src, pos):
        out.append(src[pos : m.start()])
        end = min(argument(src, m.end()), len(src))
        args = [src[m.end() : end - 1]]
        if keep and keep > 1:
            while len(args) < keep and end < len(src) and src[end] == "{":
                nxt = min(argument(src, end + 1), len(src))
                args.append(src[end + 1 : nxt - 1])
                end = nxt
        if keep:
            out.append(args[keep - 1] if len(args) >= keep else "")
        pos = end
    out.append(src[pos:])
    return "".join(out)


def title_of(project: pathlib.Path, manuscript: str | None) -> str | None:
    """The manuscript's \\title, as text, or None where there is none to read."""
    if not manuscript:
        return None
    path = (project / manuscript).resolve()
    if not path.is_relative_to(project.resolve()):
        return None
    try:
        src = path.read_text(errors="replace")
    except OSError:
        return None
    # A comment runs from a % that no backslash escapes: one after `\\\\` (a line break) counts.
    src = re.sub(r"(?<!\\)((?:\\\\)*)%.*", r"\1", src)
    src = re.sub(r"\\iffalse\b.*?\\fi\b", "", src, flags=re.DOTALL)
    m = TITLE.search(src)
    if not m:
        return None
    end = argument(src, m.end())
    if end > len(src):  # never closed
        return None
    raw = src[m.end() : end - 1]
    for name in ("thanks", "footnote"):
        raw = drop_command(raw, name)
    raw = drop_command(raw, "texorpdfstring", keep=2)
    raw = re.sub(r"\\\\(\[[^\]]*\])?", " ", raw)
    raw = build_graph.latex_text(raw).replace("$", "")
    raw = re.sub(r"\\[a-zA-Z]+\*?", "", raw).replace("{", "").replace("}", "").replace("~", " ")
    text = re.sub(r"\s+", " ", raw).strip()
    return text or None


def claims_of(folder: pathlib.Path, data: pathlib.Path) -> dict | None:
    """The project's claims as its last check found them: from the report the page keeps for it,
    else from the last entry of its check history. None where it was never checked."""
    verified_ = lambda outcomes: all(o == "verified" for o in outcomes)  # noqa: E731
    checks = build_graph.read_checks(folder)
    when = checks[-1].get("timestamp") if checks else None
    try:
        report = json.loads((data / "verify-report.json").read_text())["report"]
        by_claim = [
            [
                "verified" if d["comparison"] == "match" and d["execution"] == "completed" else "no"
                for d in c["decisions"]
            ]
            for c in report["claims"]
        ]
    except (OSError, ValueError, KeyError, TypeError):
        if not checks:
            return None
        grouped: dict[str, list[str]] = {}
        for a in checks[-1].get("assertions", []):
            grouped.setdefault(a.get("claim_id", ""), []).append(a.get("outcome", ""))
        by_claim = list(grouped.values())
    return {
        "verified": sum(1 for outcomes in by_claim if verified_(outcomes)),
        "total": len(by_claim),
        "checked_at": when,
    }


def summaries(data_dir, current: pathlib.Path) -> list[dict]:
    """Every remembered project as the drawer shows it, read side by side. One the page cannot
    read is listed as unavailable rather than hiding the others."""

    def one(entry: dict) -> dict:
        try:
            return summary(entry, data_dir, current)
        except Exception:  # a project's own files are malformed: list it, unavailable
            return {
                "path": entry["path"],
                "name": pathlib.Path(entry["path"]).name,
                "title": None,
                "opened_at": entry["opened_at"],
                "starred": entry["starred"],
                "current": False,
                "available": False,
                "claims": None,
            }

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(one, read()))


def summary(entry: dict, data_dir, current: pathlib.Path) -> dict:
    """What the drawer shows of one project: its title, its name, whether it is the one viewed,
    and its claims as of its last check, or that it was never checked. Read-only."""
    folder = pathlib.Path(entry["path"])
    manifest_ok = (folder / "repro.yaml").is_file()
    manuscript = None
    if manifest_ok:
        try:
            manifest = build_graph.yaml.safe_load((folder / "repro.yaml").read_text()) or {}
            manuscript = next(
                (
                    a.get("path")
                    for a in manifest.get("artifacts", [])
                    if a.get("id") == "manuscript"
                ),
                None,
            )
        except (OSError, build_graph.yaml.YAMLError):
            manifest_ok = False
    remote = build_graph.remote_of(folder) if folder.is_dir() else None
    name = remote["name"] if remote else folder.name
    claims = claims_of(folder, data_dir(folder)) if folder.is_dir() else None
    return {
        "path": entry["path"],
        "name": name,
        "title": title_of(folder, manuscript) if manifest_ok else None,
        "opened_at": entry["opened_at"],
        "starred": entry["starred"],
        "current": folder.resolve() == current.resolve(),
        "available": manifest_ok,
        "claims": claims,
    }
