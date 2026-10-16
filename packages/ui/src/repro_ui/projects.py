"""The projects `repro ui` has been run in, for the page's project drawer.

Kept in one small JSON file in the user's config folder, never in a repository:

    $XDG_CONFIG_HOME/reproducible-science/ui-projects.json   (~/.config/... by default)

Each entry is a project folder, when the page last opened it, and whether it is starred. What a
drawer card shows about a project (its title, its claims) is read from the project and from the
page's own data for it when the drawer asks, so nothing here goes stale.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import threading

from repro_ui import graph as build_graph

#: Serializes writes to the file between the threads of one server.
_lock = threading.Lock()


def config_file() -> pathlib.Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(pathlib.Path.home() / ".config")
    return pathlib.Path(base) / "reproducible-science" / "ui-projects.json"


def read() -> list[dict]:
    """Every remembered project, newest opened first. An unreadable file reads as none."""
    try:
        data = json.loads(config_file().read_text())
    except (OSError, ValueError):
        return []
    entries = data.get("projects", []) if isinstance(data, dict) else []
    out = [
        {
            "path": e["path"],
            "opened_at": e.get("opened_at") if isinstance(e.get("opened_at"), str) else "",
            "starred": e.get("starred") is True,
        }
        for e in entries
        if isinstance(e, dict) and isinstance(e.get("path"), str)
    ]
    return sorted(out, key=lambda e: e["opened_at"], reverse=True)


def write(entries: list[dict]) -> None:
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps({"projects": entries}, indent=1))
    partial.replace(path)


def opened(project: pathlib.Path) -> None:
    """Remember that the page opened `project` now, keeping its star."""
    key = str(project.resolve())
    with _lock:
        entries = [e for e in read() if e["path"] != key]
        before = next((e for e in read() if e["path"] == key), None)
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
    with _lock:
        entries = read()
        hit = next((e for e in entries if e["path"] == path), None)
        if hit is None:
            return False
        hit["starred"] = starred
        write(entries)
    return True


def known(path: str) -> pathlib.Path | None:
    """`path` as a project folder, only where it is a remembered one that still holds repro.yaml."""
    if not any(e["path"] == path for e in read()):
        return None
    folder = pathlib.Path(path)
    return folder if (folder / "repro.yaml").is_file() else None


TITLE = re.compile(r"\\title\s*(?:\[[^\]]*\])?\s*\{")


def title_of(project: pathlib.Path, manuscript: str | None) -> str | None:
    """The manuscript's \\title, as text, or None where there is none to read."""
    if not manuscript:
        return None
    try:
        src = (project / manuscript).read_text(errors="replace")
    except OSError:
        return None
    src = re.sub(r"(?<!\\)%.*", "", src)
    m = TITLE.search(src)
    if not m:
        return None
    i, depth = m.end(), 1
    while i < len(src) and depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    raw = build_graph.latex_text(src[m.end() : i - 1])
    raw = re.sub(r"\\\\|\\(?:thanks|footnote)\{[^}]*\}", " ", raw)
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
