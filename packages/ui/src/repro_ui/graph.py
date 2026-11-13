"""Build graph.json, the data behind the page, for one project.

Reads the project's repro.yaml, runs `repro verify --format json` (read-only apart from the check
history it keeps), and reads the results ledger and the local record of checks. `repro verify`
reports the claims and, beside them, staleness, `prereg check`, `results verify --files` and
`citations verify`, so one call gives every section the page shows. A refresh without a check
reuses the last report for the claims and the quotations, and re-reads staleness, the plans and
the ledger with the tools' own commands, which write nothing. Writes one JSON file the page loads.
"""

from __future__ import annotations

import collections
import datetime
import difflib
import hashlib
import json
import pathlib
import re
import subprocess
import sysconfig
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

import yaml

PAPER_GROUPS = {
    "Section": "Paper: body",
    "Table": "Paper: tables",
    "Appendix": "Paper: appendices",
}
MANUSCRIPT_IDS = {"manuscript", "manuscript-text", "appendix", "appendix-text"}
# Worst first, for collapsing several assertions into one outcome per check.
OUTCOME_RANK = ["mismatch", "not_found", "error", "unchecked", "verified"]


def tool(name: str) -> str:
    """The command `name` from the environment this package is installed in, where it is there.

    The page reads the JSON these commands print, so it has to run the version installed beside
    it: a different `repro` earlier on PATH, such as an older tool install, prints another shape.
    Falls back to PATH where the environment has no such script."""
    script = pathlib.Path(sysconfig.get_path("scripts")) / name
    return str(script) if script.is_file() else name


def is_doi_address(url: str) -> bool:
    """Whether `url` is an address at doi.org, by its host rather than by a substring of it."""
    host = urllib.parse.urlparse(url).hostname or ""
    return host in {"doi.org", "dx.doi.org"}


def sha256(path: pathlib.Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def repro_json(project: pathlib.Path, command: str) -> dict:
    out = subprocess.run(
        [tool("repro"), command, "--format", "json", str(project / "repro.yaml")],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    if not out.stdout.strip():
        raise RuntimeError(f"repro {command} wrote nothing: {out.stderr.strip()[:500]}")
    return json.loads(out.stdout)


def section_of(where: str) -> str:
    first = where.split(",")[0].strip()
    m = re.match(r"Section (\d+)", first)
    return f"Section {m.group(1)}" if m else first


def auto_groups(
    artifacts: dict,
    regenerations: list,
    readers: dict[str, set[str]],
    places: dict[str, set[str]],
    overrides: list[dict],
) -> dict[str, str]:
    """Group files with no configuration, the way Dagster groups assets by the code that owns them.

    Joined, in order: a file matching an override's pattern goes to that group; every .tex file and
    the text rendered from it form the manuscript; a file joins the step it feeds, unless it feeds
    more than two; files whose ids share a first word join; a file still alone joins the group
    whose files back claims in the most of the same places in the paper. A group is named for its members'
    common first word, or for its largest member.
    """
    ids = list(artifacts)
    parent = {a: a for a in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    fixed: dict[str, str] = {}
    for a in ids:
        for o in overrides:
            if re.search(o["match"], a):
                fixed[a] = o["group"]
                break

    tex = {a for a in ids if artifacts[a].get("media_type") == "application/x-tex"}
    rendered = {
        r["output"]["artifact"]
        for r in regenerations
        if any(i["artifact"] in tex for i in r["inputs"])
    }
    manuscript = (tex | rendered) - set(fixed)

    outdeg = collections.Counter(i["artifact"] for r in regenerations for i in r["inputs"])
    for r in regenerations:
        out = r["output"]["artifact"]
        for i in r["inputs"]:
            src = i["artifact"]
            if (
                src in parent
                and out in parent
                and not {src, out} & (manuscript | set(fixed))
                and outdeg[src] <= 2
            ):
                union(src, out)
    by_word = collections.defaultdict(list)
    for a in ids:
        if a not in manuscript and a not in fixed:
            by_word[a.split("-")[0]].append(a)
    for members in by_word.values():
        for m in members[1:]:
            union(m, members[0])

    def members_of() -> dict[str, list[str]]:
        out = collections.defaultdict(list)
        for a in ids:
            if a not in manuscript and a not in fixed:
                out[find(a)].append(a)
        return out

    for root, members in list(members_of().items()):
        if len(members) > 1:
            continue
        a = members[0]
        best, score = None, 0
        for other_root, others in members_of().items():
            if other_root == root or len(others) < 2:
                continue
            shared = sum(len(places.get(a, set()) & places.get(o, set())) for o in others)
            if shared > score:
                best, score = other_root, shared
        if best:
            union(a, best)

    names: dict[str, str] = {}
    for root, members in members_of().items():
        words = collections.Counter(m.split("-")[0] for m in members)
        word, n = words.most_common(1)[0]
        names[root] = (
            word
            if n > 1 or len(members) == 1
            else max(members, key=lambda m: len(readers.get(m, ())))
        )
    group = {a: names[find(a)] for a in ids if a not in manuscript and a not in fixed}
    group.update(dict.fromkeys(manuscript, "manuscript"))
    group.update(fixed)
    return group


def read_labels(
    project: pathlib.Path, manuscript_path: str | None
) -> tuple[dict[str, str], dict[str, str]]:
    """From the .aux LaTeX wrote beside the manuscript: label -> number (`tab:timing` -> `15`),
    and table number -> normalized caption text."""
    if not manuscript_path:
        return {}, {}
    aux = (project / manuscript_path).with_suffix(".aux")
    if not aux.is_file():
        return {}, {}
    labels, captions = {}, {}
    for line in aux.read_text(errors="replace").splitlines():
        m = re.match(r"\\newlabel\{([^}]+)\}\{\{([^}]*)\}\{[^}]*\}\{(.*)\}\{[^}]*\}\{\}\}$", line)
        if not m:
            continue
        labels[m.group(1)] = m.group(2)
        if m.group(1).startswith("tab:"):
            captions[m.group(2)] = normalize(m.group(3))
    return labels, captions


def table_texts(
    project: pathlib.Path, tex_paths: list[str], labels: dict[str, str]
) -> dict[str, str]:
    """Table number -> normalized text of the whole table environment (caption and cells), from
    every .tex file the manifest pins. Cells are joined with ` | `, as a text rendering prints them."""
    out: dict[str, str] = {}
    for rel in tex_paths:
        f = project / rel
        if not f.is_file():
            continue
        src = f.read_text(errors="replace")
        for block in re.findall(r"\\begin\{table\*?\}(.*?)\\end\{table\*?\}", src, flags=re.DOTALL):
            m = re.search(r"\\label\{(tab:[^}]+)\}", block)
            if m and m.group(1) in labels:
                out[labels[m.group(1)]] = (
                    out.get(labels[m.group(1)], "") + " " + normalize(block.replace("&", " | "))
                )
    return out


def normalize(tex: str) -> str:
    s = tex.replace("{,}", ",").replace("~", " ").replace("\\relax", "").replace("\\\\", " ")
    s = re.sub(r"\\[a-zA-Z]+\s*", "", s)
    s = re.sub(r"[{}$^]", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def correct_tables(
    claims: list[dict], labels: dict[str, str], captions: dict[str, str]
) -> dict[str, str]:
    """Declared `Table N` -> the table whose caption holds the passages its claims quote.

    A manifest's `where` is written by hand and nothing checks it, so table numbers drift when a
    paper is renumbered. A claim that quotes a caption names its table: vote over those claims."""
    votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for c in claims:
        for part in c.get("where", "").split(","):
            part = part.strip()
            if not part.startswith("Table "):
                continue
            for ev in c.get("evidence", []):
                q = normalize(ev.get("text", "")) if ev.get("kind") == "quote" else ""
                if len(q) < 12:
                    continue
                for num, cap in captions.items():
                    if q in cap:
                        votes[part][num] += 1
    fixed = {}
    for declared, v in votes.items():
        num, _ = v.most_common(1)[0]
        if f"Table {num}" != declared:
            fixed[declared] = f"Table {num}"
    return fixed


def resolve_where(where: str, labels: dict[str, str], fixed: dict[str, str]) -> str:
    """`Table fc-cases` -> `Table 10` where the .aux knows the label, and a drifted table number
    to the table its quoted caption is in; anything else unchanged."""

    def one(part: str) -> str:
        if part.strip() in fixed:
            return fixed[part.strip()]
        m = re.match(r"(Table|Figure|Section|Appendix)\s+(\S+)$", part.strip())
        if not m or re.match(r"^[A-Z0-9.]+$", m.group(2)):
            return part.strip()
        prefix = {
            "Table": "tab:",
            "Figure": "fig:",
            "Section": "sec:",
            "Appendix": "sec:",
        }[m.group(1)]
        num = labels.get(prefix + m.group(2))
        return f"{m.group(1)} {num}" if num else part.strip()

    return ", ".join(one(p) for p in where.split(","))


def worst(outcomes: list[str]) -> str:
    return min(outcomes, key=lambda o: OUTCOME_RANK.index(o) if o in OUTCOME_RANK else 0)


def read_checks(project: pathlib.Path) -> list[dict]:
    git_dir = subprocess.run(
        ["git", "rev-parse", "--git-dir"], cwd=project, capture_output=True, text=True
    )
    candidates = []
    if git_dir.returncode == 0:
        candidates.append((project / git_dir.stdout.strip()) / "repro" / "checks.jsonl")
    candidates.append(project / ".repro" / "checks.jsonl")
    for c in candidates:
        if c.is_file():
            return [json.loads(line) for line in c.read_text().splitlines() if line.strip()]
    return []


def run_text(argv: list[str], cwd: pathlib.Path, timeout: int = 60) -> str | None:
    try:
        return subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


#: Run ids the repro mod leaves out of its counts: rehearsals, not results.
TEST_RUN = re.compile(r"^(smoke|prefreeze|test|dryrun)[_-]")


#: The states of a recorded file `results verify --files` fails on, as `repro verify` reads them.
RESULTS_FAILING = ("changed", "missing", "reverted", "reappeared", "not a tree", "not a file")
#: The states of a registration pinned by a Commit SHA line that `prereg check` passes.
PINNED_STANDING = ("unchanged", "appended", "superseded", "withdrawn")
#: The tool sections `repro verify --format json` writes beside the claims.
TOOL_SECTIONS = ("prereg", "results", "citations")


def tool_account(project: pathlib.Path, argv: list[str]) -> dict:
    """One tool's check run as `repro verify` runs it, for a refresh that runs no `repro verify`:
    what it wrote with `--json`, in the shape of that tool's section of the verify report. Read-only."""
    with tempfile.TemporaryDirectory() as scratch:
        wrote = pathlib.Path(scratch) / "account.json"
        printed = run_text([*argv, "--json", str(wrote)], project)
        account = json.loads(wrote.read_text()) if wrote.is_file() else {}
    return {
        "used": True,
        "outcome": "could not check" if printed is None or not account else "read",
        "account": account,
        "output": printed or "",
    }


def unused() -> dict:
    """A tool section for a record the project does not keep."""
    return {"used": False, "outcome": "nothing to read", "account": {}, "output": ""}


#: How deep below the project `repro verify` looks for a PREREG.md, and the folders it skips.
MARKER_DEPTH = 3
SKIPPED = frozenset({"node_modules", "venv", ".venv", "site-packages", "build", "dist"})


def prereg_used(project: pathlib.Path) -> bool:
    """Whether `repro verify` counts the project as keeping plans: a `.prereg/` at its root, or
    a PREREG.md at most three folders down outside hidden and build folders. The same rule as
    `repro.delegate`, restated because the page imports none of the tools; a refresh that used
    another rule would turn the line over every 30 seconds."""
    if (project / ".prereg").exists():
        return True
    for depth in range(MARKER_DEPTH + 1):
        for f in project.glob("*/" * depth + "PREREG.md"):
            parts = f.relative_to(project).parts
            if f.is_file() and not any(x.startswith(".") or x in SKIPPED for x in parts):
                return True
    return False


def read_sections(verify: dict | None, project: pathlib.Path, manifest: dict, cached: dict) -> dict:
    """Staleness and the three tools' sections, each as `repro verify --format json` writes it.

    From `verify` where a check just ran. Without one (a refresh), staleness comes from `repro
    stale`, the plans from `prereg check` and the ledger from `results verify --files`, each run
    here; the quotations keep what the last `repro verify` found, which `cached` holds, because
    `citations verify` reads every source and a refresh every 30 seconds should not."""
    if verify is not None:
        stale = verify.get("staleness") or {}
        return {
            "staleness": stale.get("report") or NOTHING_STALE,
            **{name: verify.get(name) or unused() for name in TOOL_SECTIONS},
        }
    return {
        "staleness": (
            repro_json(project, "stale")["staleness"]
            if manifest.get("regenerations")
            else NOTHING_STALE
        ),
        "prereg": (
            tool_account(project, [tool("prereg"), "check"]) if prereg_used(project) else unused()
        ),
        "results": (
            tool_account(project, [tool("results"), "verify", "--files"])
            if (project / ".results").exists()
            else unused()
        ),
        # None: not checked since the page's data was first built, which the status line says.
        "citations": cached.get("citations"),
    }


def ledger_runs(ledger: list[dict]) -> tuple[int, int]:
    """Runs the ledger recorded, leaving rehearsals out, and how many had a seal before them."""
    has_seal, runs, sealed = False, 0, 0
    for e in ledger:
        if e.get("event") == "seal":
            has_seal = True
        elif e.get("event") == "run" and not TEST_RUN.match(e.get("run_id") or ""):
            runs += 1
            sealed += has_seal
    return runs, sealed


def pinned_quotes(project: pathlib.Path) -> int | None:
    """Quotations pinned under every `claims` folder, or None where there is no such folder."""
    folders = [
        d
        for d in project.rglob("claims")
        if d.is_dir()
        and ".git" not in d.parts
        and "node_modules" not in d.parts
        and len(d.relative_to(project).parts) <= 4
    ]
    if not folders:
        return None
    return sum(
        len(re.findall(r"^[ \t]*-?[ \t]*exact:", f.read_text(errors="replace"), flags=re.MULTILINE))
        for d in folders
        for f in d.rglob("*")
        if f.is_file()
    )


def status_lines(
    project: pathlib.Path, report: dict, sections: dict, ledger: list[dict], reruns: list[dict]
) -> dict:
    """The counts behind the five status lines, in the order the page shows them: prereg, results,
    citations, claims, repro. Each field has `state` and `ok`: True, False (something is wrong) or
    None (nothing there to check). The page words them."""
    fields: dict[str, dict] = {}

    prereg = sections["prereg"]
    plans = prereg["account"].get("plans", [])
    pinned = prereg["account"].get("commit_pinned", [])
    if not prereg["used"]:
        fields["prereg"] = {"state": "none", "ok": None}
    elif not prereg["account"]:
        fields["prereg"] = {"state": "unread", "ok": False}
    else:
        changed = sum(1 for x in plans if x["frozen"] and x["check"] == "changed") + sum(
            1 for d in pinned if d["status"] == "changed"
        )
        drafts = sum(1 for x in plans if not x["frozen"])
        amendments = sum(1 for x in plans if x["frozen"] and x["check"] == "not frozen")
        # A registration pinned by a Commit SHA line whose log only grew is `appended`, which
        # `prereg check` passes; one that names no commit this repository holds cannot be read.
        unchanged = sum(1 for x in plans if x["frozen"] and x["check"] == "unchanged") + sum(
            1 for d in pinned if d["status"] in PINNED_STANDING
        )
        unknown = sum(1 for d in pinned if d["status"] in ("pending", "unknown commit"))
        fields["prereg"] = {
            "state": "read",
            "plans": len(plans) + len(pinned),
            "frozen": unchanged,
            "changed": changed,
            "drafts": drafts,
            "amendments": amendments,
            "unknown": unknown,
            "ok": not (changed or drafts or amendments or unknown),
        }

    results = sections["results"]
    account = results["account"]
    if not results["used"]:
        fields["results"] = {"state": "none", "ok": None}
    elif "events" not in account:
        fields["results"] = {
            "state": "broken",
            "chain": str(account.get("chain") or "unreadable").replace("_", " "),
            "ok": False,
        }
    else:
        runs, sealed = ledger_runs(ledger)
        changed = sum(1 for f in account.get("files", []) if f["state"] in RESULTS_FAILING)
        fields["results"] = {
            "state": "read",
            "runs": runs,
            "sealed": sealed,
            "changed": changed,
            "ok": not changed and sealed == runs,
        }

    citations = sections["citations"]
    if citations is None:
        n = pinned_quotes(project)
        fields["citations"] = (
            {"state": "none", "ok": None}
            if n is None
            else {"state": "unverified", "pinned": n, "ok": None}
        )
    elif not citations["used"]:
        fields["citations"] = {"state": "none", "ok": None}
    else:
        counts = citations["account"].get("counts", {})
        fields["citations"] = {
            "state": "read" if citations["account"] else "unread",
            "quotes": citations["account"].get("quotes", 0),
            "found": counts.get("found", 0),
            "not_found": counts.get("not found", 0),
            "ok": citations.get("passed", citations["outcome"] == "passed")
            and not counts.get("not found", 0),
        }

    verified = sum(
        1
        for c in report["claims"]
        if all(d["comparison"] == "match" and d["execution"] == "completed" for d in c["decisions"])
    )
    fields["claims"] = {
        "state": "read" if report["claims"] else "none",
        "total": len(report["claims"]),
        "verified": verified,
        "ok": verified == len(report["claims"]) if report["claims"] else None,
    }

    steps = sections["staleness"]["regenerations"]
    states = collections.Counter(r["state"] for r in steps)
    fields["repro"] = {
        "state": "read" if steps else "none",
        "steps": len(steps),
        "current": states["current"],
        "changed": states["stale"],
        "never": states["never_rerun"],
        "last_at": reruns[-1].get("ended_at") if reruns else None,
        "ok": states["current"] == len(steps) if steps else None,
    }
    return fields


def citing_sentences(project: pathlib.Path, tex_paths: list[str]) -> dict[str, list[dict]]:
    """Citation key -> the sentences of the manuscript that cite it, with the section each is in.
    Read from the pinned .tex files, so only the current version is searched. The LaTeX is reduced
    to its text: commands dropped, a citation shown as [key]."""
    out: dict[str, list[dict]] = collections.defaultdict(list)
    cite = re.compile(r"\\cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{([^}]*)\}")
    for file_index, rel in enumerate(tex_paths):
        f = project / rel
        if not f.is_file():
            continue
        src = re.sub(r"(?<!\\)%.*", "", f.read_text(errors="replace"))
        sections = [
            (m.start(), re.sub(r"\\[a-zA-Z]+\{?|[{}]", "", m.group(2)).strip())
            for m in re.finditer(r"\\(section|subsection)\*?\{([^}]*)\}", src)
        ]
        for m in cite.finditer(src):
            start = max(
                src.rfind(". ", 0, m.start()),
                src.rfind("\n\n", 0, m.start()),
                src.rfind("}.", 0, m.start()),
            )
            end_dot = src.find(". ", m.end())
            end_par = src.find("\n\n", m.end())
            end = min(x for x in (end_dot, end_par, len(src)) if x != -1)
            raw = src[start + 2 if start >= 0 else 0 : end + 1]
            text = latex_text(cite.sub(lambda c: "[" + c.group(1) + "]", raw))
            text = re.sub(r"\\(?:emph|textit|textbf|code|tVerify|texttt)\{([^}]*)\}", r"\1", text)
            text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})?", "", text).replace("~", " ")
            text = text.replace("\\%", "%").replace("\\&", "and")
            text = text.replace("\\\\", " ").replace("&", "|")
            text = re.sub(r"[{}$]", "", re.sub(r"\s+", " ", text)).strip(" |")
            section = next((name for pos, name in reversed(sections) if pos < m.start()), "")
            for key in (k.strip() for k in m.group(1).split(",")):
                entry = {"text": text, "section": section, "file": rel}
                if not any(e["text"] == text and e["file"] == rel for e in out[key]):
                    # Where the sentence falls in reading order: which pinned .tex file, then where in it.
                    out[key].append({**entry, "order": [file_index, m.start()]})
    return out


ACCENTS = {
    '"': "\u0308",
    "'": "\u0301",
    "`": "\u0300",
    "^": "\u0302",
    "~": "\u0303",
    "=": "\u0304",
    ".": "\u0307",
    "u": "\u0306",
    "v": "\u030c",
    "H": "\u030b",
    "c": "\u0327",
    "k": "\u0328",
}
LETTERS = {
    "o": "ø",
    "O": "Ø",
    "ae": "æ",
    "AE": "Æ",
    "aa": "å",
    "AA": "Å",
    "ss": "ß",
    "l": "ł",
    "L": "Ł",
    "i": "ı",
}


def latex_text(s: str) -> str:
    """LaTeX accents and special letters as the characters they print: N\\"ust -> Nüst,
    Vicentt\\'{\\i}n -> Vicenttín, {\\o} -> ø. Applied before commands are stripped."""

    def accent(m: re.Match) -> str:
        base = {"\\i": "i", "\\j": "j"}.get(m.group(2), m.group(2))
        return unicodedata.normalize("NFC", base + ACCENTS[m.group(1)])

    # Symbol accents (\\" \\' \\` \\^ \\~ \\= \\.) take the next letter, braced or not. Letter-named
    # accents (\\c \\u \\v \\H \\k) need braces or a space, or \\code would read as \\c plus o.
    s = re.sub(r"\\([\"'`^~=.])\s*\{?(\\[ij]|[A-Za-z])\}?", accent, s)
    s = re.sub(
        r"\\([uvHck])(?:\{(\\[ij]|[A-Za-z])\}|\s+([A-Za-z]))",
        lambda m: unicodedata.normalize(
            "NFC",
            ({"\\i": "i", "\\j": "j"}.get(m.group(2) or m.group(3), m.group(2) or m.group(3)))
            + ACCENTS[m.group(1)],
        ),
        s,
    )
    s = (
        s.replace("\\&", "&")
        .replace("\\#", "#")
        .replace("\\%", "%")
        .replace("\\_", "_")
        .replace("\\$", "$")
    )
    s = re.sub(
        r"\{\\(ae|AE|aa|AA|ss|o|O|l|L)\}|\\(ae|AE|aa|AA|ss|o|O|l|L)(?![A-Za-z])",
        lambda m: LETTERS[m.group(1) or m.group(2)],
        s,
    )
    return s


def parse_bib(paths: list[pathlib.Path]) -> dict[str, dict[str, str]]:
    """Citation key -> its fields, from the .bib files the manuscript names. Braces are balanced by
    counting, so a title like {{Gene name errors}} comes out whole; LaTeX in a field is reduced to text."""
    out: dict[str, dict[str, str]] = {}
    for path in paths:
        if not path.is_file():
            continue
        src = path.read_text(errors="replace")
        for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", src):
            i, depth = m.end(), 1
            while i < len(src) and depth:
                depth += {"{": 1, "}": -1}.get(src[i], 0)
                i += 1
            body, fields = src[m.end() : i - 1], {"type": m.group(1).lower()}
            for f in re.finditer(r"(\w+)\s*=\s*", body):
                j = f.end()
                if j < len(body) and body[j] == "{":
                    k, d = j + 1, 1
                    while k < len(body) and d:
                        d += {"{": 1, "}": -1}.get(body[k], 0)
                        k += 1
                    value = body[j + 1 : k - 1]
                elif j < len(body) and body[j] == '"':
                    k = body.find('"', j + 1)
                    value = body[j + 1 : k]
                else:
                    value = re.match(r"[^,\n]*", body[j:]).group(0)
                value = (
                    re.sub(r"\\[a-zA-Z]+\s*", "", latex_text(value))
                    .replace("{", "")
                    .replace("}", "")
                    .replace("--", "–")
                )
                fields[f.group(1).lower()] = re.sub(r"\s+", " ", value).strip()
            out[m.group(2)] = fields
    return out


def landing_url(url: str, doi: str, cache: dict[str, str], fetch: bool = True) -> str:
    """The page a reader lands on: a doi.org address is resolved once to the publisher's page and
    cached, because a doi.org link says nothing about where it goes. Unresolvable: left as given.
    Without `fetch`, only what is already cached is used and nothing reaches the network."""
    target = url or (f"https://doi.org/{doi}" if doi else "")
    if not target or not is_doi_address(target):
        return target
    if target in cache and not is_doi_address(cache[target]):
        return cache[target]
    if not fetch:
        return target
    # HEAD first; a publisher that refuses it (ACM, OUP, BMC…) often still redirects a GET, of which
    # only the final address is read. A failure is not cached, so the next build tries again.
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(
                target, method=method, headers={"User-Agent": "reproducible-science-ui"}
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                cache[target] = r.geturl()
                return cache[target]
        except urllib.error.HTTPError as e:  # a 403 after the redirect still names the landing page
            if e.url and not is_doi_address(e.url):
                cache[target] = e.url
                return cache[target]
        except Exception:  # timeout, refused connection: try the next method
            continue
    return target


WANDB_URL = re.compile(r"https?://(?:[\w-]+\.)*wandb\.ai/[^\s\"'<>)\]]+")
HISTORY_CAP = 50


REMOTE = re.compile(
    r"^(?:git@([^:]+):|ssh://git@([^/]+)/|https?://(?:[^@/]+@)?([^/]+)/)(.+?)(?:\.git)?/?$"
)


def remote_of(project: pathlib.Path) -> dict | None:
    """The origin remote as the Share menu needs it: the address to clone, the repository's host,
    owner and name, and where the project sits inside the repository. None without a remote.
    `git remote get-url` reads the local config; nothing is fetched. A token in an https address
    is never carried: the clone address is rebuilt from the host and the path."""
    remote = (run_text(["git", "remote", "get-url", "origin"], project) or "").strip()
    m = REMOTE.match(remote)
    if not m:
        return None
    host, path = m.group(1) or m.group(2) or m.group(3), m.group(4)
    if m.group(2):  # ssh://git@host:22/...: the port is ssh's, not the web address's
        host = re.sub(r":\d+$", "", host)
    owner, _, name = path.rpartition("/")
    prefix = (run_text(["git", "rev-parse", "--show-prefix"], project) or "").strip().rstrip("/")
    return {
        "clone": f"https://{host}/{path}.git",
        "host": host,
        "owner": owner,
        "name": name,
        "subdir": prefix,
    }


def commit_url(project: pathlib.Path) -> str | None:
    """`https://github.com/owner/repo/commit/` from the origin remote, or None without one.
    `git remote get-url` reads the local config; nothing is fetched."""
    remote = (run_text(["git", "remote", "get-url", "origin"], project) or "").strip()
    m = re.match(
        r"^(?:git@([^:]+):|ssh://git@([^/]+)/|https?://(?:[^@/]+@)?([^/]+)/)(.+?)(?:\.git)?/?$",
        remote,
    )
    return f"https://{m.group(1) or m.group(2) or m.group(3)}/{m.group(4)}/commit/" if m else None


def find_commits(
    project: pathlib.Path, pairs: set[tuple[str, str]], out_dir: pathlib.Path
) -> dict[tuple[str, str], dict | None]:
    """For each (path, sha256), the oldest commit whose copy of the file has exactly those bytes,
    as {"commit", "time"}, checking at most HISTORY_CAP commits per path; a miss has no "commit".

    Found commits are cached beside graph.json by path and sha256; a miss is cached against HEAD,
    so it is looked for again once the project has new commits."""
    head = (run_text(["git", "rev-parse", "HEAD"], project) or "").strip()
    if not head:  # not a git repository, or one with no commits
        return dict.fromkeys(pairs)
    cache_path = out_dir / "run_commits.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    pending = {
        (path, digest)
        for path, digest in pairs
        if "commit" not in cache.get(f"{path}@{digest}", {})
        and cache.get(f"{path}@{digest}", {}).get("head") != head
    }
    # A path outside the repository (a ledger may record one through a symlink) makes `git log`
    # refuse every path given with it, so such a path is never asked about; nor is one git's
    # line-based batch input cannot carry.
    top_dir = (run_text(["git", "rev-parse", "--show-toplevel"], project) or "").strip()
    pending = {
        (path, digest)
        for path, digest in pending
        if top_dir
        and "\n" not in path
        and (project / path).resolve().is_relative_to(pathlib.Path(top_dir).resolve())
    }
    if pending:
        # One walk of the history for every path still to look up, rather than a `git log` per path.
        paths = sorted({path for path, _ in pending})
        try:
            walked = subprocess.run(
                [
                    "git",
                    "-c",
                    "core.quotePath=false",
                    "log",
                    "--format=@%H %ct",
                    "--name-only",
                    "--no-renames",
                    "--",
                    *paths,
                ],
                cwd=project,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            walked = None
        if walked is None or walked.returncode != 0:
            # Nothing was looked at, so nothing is recorded as missing: the next build asks again.
            return {pair: cache.get(f"{pair[0]}@{pair[1]}") for pair in pairs}
        history: dict[str, list[tuple[str, int]]] = collections.defaultdict(list)
        commit = None
        for line in walked.stdout.splitlines():
            if line.startswith("@"):
                sha, ct = line[1:].split()
                commit = (sha, int(ct))
            elif line.strip() and commit:
                history[line.strip()].append(commit)
        blobs = subprocess.Popen(
            ["git", "cat-file", "--batch"],
            cwd=project,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        top = (run_text(["git", "rev-parse", "--show-prefix"], project) or "").strip()
        for path, digest in sorted(pending):
            hit = {"head": head}
            for sha, ct in list(reversed(history.get(top + path, [])))[
                :HISTORY_CAP
            ]:  # oldest first
                blobs.stdin.write(f"{sha}:./{path}\n".encode())
                blobs.stdin.flush()
                # "<sha> <type> <size>", or "<what was asked> missing" (the commit deleted the
                # file) or "... ambiguous", where what was asked may itself hold spaces.
                header = blobs.stdout.readline().rstrip(b"\n").split(b" ")
                if header[-1] in (b"missing", b"ambiguous") or not header[-1].isdigit():
                    continue
                body = blobs.stdout.read(int(header[-1]))
                blobs.stdout.read(1)
                if hashlib.sha256(body).hexdigest() == digest:
                    hit = {"commit": sha, "time": ct}
                    break
            cache[f"{path}@{digest}"] = hit
        blobs.stdin.close()
        blobs.wait()
        out_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=1))
    return {pair: cache.get(f"{pair[0]}@{pair[1]}") for pair in pairs}


def run_commits(project: pathlib.Path, runs: list[dict], out_dir: pathlib.Path) -> None:
    """Add to each run the commit that holds its outputs (`find_commits`). With several outputs,
    the latest of their commits. A run is `committed` when every output was found."""
    found = find_commits(project, {pair for run in runs for pair in run["_outputs"]}, out_dir)
    base = commit_url(project)
    for run in runs:
        looked = [found.get(pair) or {} for pair in run.pop("_outputs")]
        hits = [f for f in looked if "commit" in f]
        latest = max(hits, key=lambda f: f["time"])["commit"] if hits else None
        run["commit"] = latest
        run["committed"] = bool(looked) and len(hits) == len(looked)
        run["remote_url"] = latest and base and base + latest


def project_relative(project: pathlib.Path, path: str) -> str:
    """`path` as a tool printed it, relative to the project where it lies inside it."""
    p = pathlib.Path(path)
    if p.is_absolute() and p.is_relative_to(project):
        return p.relative_to(project).as_posix()
    return p.as_posix()


def freeze_record(project: pathlib.Path, rel: str) -> dict:
    """What `prereg freeze` recorded of the plan at `rel`, from `.prereg/<name>.json` beside it:
    the commit and the sha256 it froze. Empty where there is no such record."""
    where = (project / rel).parent / ".prereg" / f"{pathlib.Path(rel).name}.json"
    try:
        return json.loads(where.read_text()) if where.is_file() else {}
    except ValueError:
        return {}


def prereg_plans(project: pathlib.Path, section: dict) -> list[dict]:
    """Each plan `prereg check` read, with its freeze record: path, state, commit, frozen_at."""
    out = []
    for plan in section["account"].get("plans", []):
        rel = project_relative(project, plan["path"])
        rec = freeze_record(project, rel)
        out.append(
            {
                "path": rel,
                "frozen": plan["frozen"],
                "check": plan["check"] if plan["frozen"] else "never frozen",
                "commit": rec.get("commit"),
                "sha256": plan.get("sha256") or rec.get("sha256"),
                "frozen_at": rec.get("frozen_at"),
                "amendments": plan.get("amendments", 0),
                "amendment_drafts": plan.get("amendment_drafts", 0),
                "log_entries": plan.get("log_entries", 0),
                "pinned_by": "freeze",
            }
        )
    for doc in section["account"].get("commit_pinned", []):
        out.append(
            {
                "path": project_relative(project, doc["path"]),
                "frozen": True,
                "check": doc["status"],
                "commit": doc.get("commit"),
                "sha256": None,
                "frozen_at": None,
                "pinned_by": "commit line",
            }
        )
    return out


def record_tabs(
    project: pathlib.Path,
    manifest: dict,
    ledger: list[dict],
    sections: dict,
    out_dir: pathlib.Path,
    fetch: bool = True,
) -> dict:
    """What the Prereg, Results, Citations and Reproduce tabs list, read from the records themselves."""
    staleness = sections["staleness"]
    plans = prereg_plans(project, sections["prereg"])

    # results: every run, whether a seal came before it, and the sentences bound with `results claim`.
    runs, sealed_yet, seals = [], False, 0
    for e in ledger:
        if e.get("event") == "seal":
            sealed_yet = True
            seals += 1
        elif e.get("event") == "run":
            runs.append(
                {
                    "run_id": e.get("run_id"),
                    "timestamp": e.get("timestamp"),
                    "note": e.get("note", ""),
                    "outputs": [o["path"] for o in e.get("outputs", [])],
                    "sealed_before": sealed_yet,
                    # A W&B run only where the ledger names one; never looked up or made up.
                    "wandb_url": next(iter(WANDB_URL.findall(json.dumps(e))), None),
                    # Each output with its recorded hash, and whether the file on disk still has it.
                    "files": [
                        {
                            "path": o["path"],
                            "sha256": o["sha256"],
                            "on_disk": sha256(project / o["path"]) == o["sha256"],
                        }
                        for o in e.get("outputs", [])
                    ],
                    "_outputs": [(o["path"], o["sha256"]) for o in e.get("outputs", [])],
                }
            )
    run_commits(project, runs, out_dir)
    # `results annotate` events: a file linked to a record outside the ledger (a W&B run, a DOI, a
    # Zenodo record). The ledger only says the link was stated; nothing here fetches or compares it.
    annotations = [e for e in ledger if e.get("event") == "annotation"]
    bound = [
        {
            "run_id": e.get("run_id"),
            "timestamp": e.get("timestamp"),
            "claim": e.get("claim", ""),
            "location": e.get("location", ""),
        }
        for e in ledger
        if e.get("event") == "claim"
    ]

    # citations: every claims file under a `claims` folder, with its source and quotations, and
    # the sentences of the manuscript that cite it.
    tex_paths = [
        x["path"] for x in manifest["artifacts"] if x.get("media_type") == "application/x-tex"
    ]
    cited_in = citing_sentences(project, tex_paths)
    main_tex = next(
        (project / x["path"] for x in manifest["artifacts"] if x["id"] == "manuscript"),
        None,
    )
    bib_names = (
        re.findall(r"\\bibliography\{([^}]*)\}", main_tex.read_text(errors="replace"))
        if main_tex and main_tex.is_file()
        else []
    )
    bib = (
        parse_bib(
            [main_tex.parent / f"{n.strip()}.bib" for names in bib_names for n in names.split(",")]
        )
        if main_tex
        else {}
    )
    cache_path = out_dir / "landing_urls.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    sources = []
    for d in sorted(project.rglob("claims")):
        if (
            not d.is_dir()
            or ".git" in d.parts
            or "node_modules" in d.parts
            or len(d.relative_to(project).parts) > 4
        ):
            continue
        for f in sorted(d.glob("*.y*ml")):
            try:
                doc = yaml.safe_load(f.read_text()) or {}
            except yaml.YAMLError:
                continue
            src = doc.get("source", {}) or {}
            statements = []
            for sid, c in (doc.get("claims", {}) or {}).items():
                quotes = [
                    {"exact": q.get("exact", ""), "section": q.get("section", "")}
                    for q in (c or {}).get("quotes", []) or []
                    if isinstance(q, dict)
                ]
                statements.append(
                    {
                        "id": sid,
                        "statement": (c or {}).get("statement", ""),
                        "quotes": quotes,
                        "notes": (c or {}).get("notes", ""),
                    }
                )
            sources.append(
                {
                    "file": str(f.relative_to(project)),
                    "citation": src.get("citation", f.stem),
                    "url": src.get("url", ""),
                    "local": src.get("local", ""),
                    "sha256": src.get("sha256", ""),
                    "cited_in": cited_in.get(src.get("citation", f.stem), []),
                    "bib": bib.get(src.get("citation", f.stem), {}),
                    "link": landing_url(
                        src.get("url", ""),
                        bib.get(src.get("citation", f.stem), {}).get("doi", ""),
                        cache,
                        fetch,
                    ),
                    # The DOI's own landing page, which is the publisher's record; the link above
                    # is the copy that was pinned and may be a preprint elsewhere.
                    "doi_link": landing_url(
                        "",
                        bib.get(src.get("citation", f.stem), {}).get("doi", "")
                        or (
                            re.search(r"doi\.org/(10\.[^\s?#]+)", src.get("url", "")) or [None, ""]
                        )[1],
                        cache,
                        fetch,
                    ),
                    "pinned": sum(len(s["quotes"]) for s in statements),
                    "statements": statements,
                }
            )

    # reproduce: every declared rebuild step with its state, and every recorded re-run.
    causes = collections.defaultdict(list)
    observed: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    art_paths = {x["id"]: x.get("path", "") for x in manifest["artifacts"]}
    for f in staleness["findings"]:
        causes[f["regeneration"]].append({"cause": f["cause"], "artifact": f["artifact"]})
        # The bytes the last re-run saw, for a file that changed since: what the step's diff shows.
        if f.get("observed") and art_paths.get(f["artifact"]):
            observed[f["regeneration"]].append((art_paths[f["artifact"]], f["observed"]))
    regen = {r["id"]: r for r in manifest.get("regenerations", [])}
    steps = [
        {
            "id": r["id"],
            "artifact": r["artifact"],
            "state": r["state"],
            "rerun_at": r.get("rerun_at"),
            "command": " ".join(regen.get(r["id"], {}).get("command", [])),
            "causes": causes.get(r["id"], []),
        }
        for r in staleness["regenerations"]
    ]
    rr_path = project / ".repro" / "reproductions.jsonl"
    reruns = []
    step_runs = collections.defaultdict(list)
    if rr_path.exists():
        for line in rr_path.read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                reruns.append(
                    {
                        "started_at": e.get("started_at"),
                        "ended_at": e.get("ended_at"),
                        "tool_version": e.get("tool_version"),
                        "counts": dict(
                            collections.Counter(r.get("state") for r in e.get("regenerations", []))
                        ),
                        "steps": len(e.get("regenerations", [])),
                    }
                )
                for r in e.get("regenerations", []):
                    step_runs[r.get("regeneration_id")].append(
                        {
                            "ended_at": e.get("ended_at"),
                            "tool_version": e.get("tool_version"),
                            "state": r.get("state"),
                            "bytes_identical": r.get("bytes_identical"),
                            "exit_code": r.get("exit_code"),
                            "duration_seconds": r.get("duration_seconds"),
                            "detail": r.get("detail", ""),
                        }
                    )
    # Each step's files by path, and its re-runs newest first, for the step's side panel.
    paths = {x["id"]: x.get("path", "") for x in manifest["artifacts"]}
    for st in steps:
        r = regen.get(st["id"], {})
        st["inputs"] = [
            {"artifact": i["artifact"], "path": paths.get(i["artifact"], "")}
            for i in r.get("inputs", [])
        ]
        st["output_path"] = paths.get(st["artifact"], "")
        st["history"] = list(reversed(step_runs.get(st["id"], [])))[:20]
    # Each changed file a step reads or writes, with the commit holding the bytes its last re-run
    # saw, so the step's panel can show what changed. Served by the diff endpoint as `step:<id>`.
    held = find_commits(project, {pair for pairs in observed.values() for pair in pairs}, out_dir)
    for st in steps:
        st["diffs"] = [
            {
                "label": path,
                "open": {"tab": "reproduce", "path": path, "diff": f"step:{st['id']}"},
                "diff": {
                    "commit": (held.get((path, digest)) or {}).get("commit"),
                    "sha256": digest,
                },
            }
            for path, digest in dict.fromkeys(observed.get(st["id"], []))
        ]
    # Each run's outside links: the annotations naming one of its outputs, marked when they were
    # stated of other bytes than the run wrote.
    for run in runs:
        written = {f["path"]: f["sha256"] for f in run["files"]}
        run["links"] = []
        for e in annotations:
            hit = [x for x in e.get("subjects", []) if x.get("path") in written]
            if not hit:
                continue
            target = e.get("target", {})
            ref = target.get("ref", "")
            doi = (
                re.sub(r"^(doi:|https?://(dx\.)?doi\.org/)", "", ref)
                if (target.get("kind", "").startswith("doi:") or is_doi_address(ref))
                else ""
            )
            url = (
                landing_url("", doi, cache, fetch)
                if doi
                else ref
                if re.match(r"https?://", ref)
                else None
            )
            run["links"].append(
                {
                    "kind": target.get("kind", ""),
                    "ref": ref,
                    "url": url,
                    "note": e.get("note", ""),
                    "by": e.get("by", ""),
                    "status": e.get("status", ""),
                    "timestamp": e.get("timestamp"),
                    "same_bytes": all(written[x["path"]] == x.get("sha256") for x in hit),
                }
            )
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=1))
    return {
        "prereg": {
            "plans": plans,
            "used": sections["prereg"]["used"],
            "output": sections["prereg"]["output"],
        },
        "results": {"runs": runs, "seals": seals, "bound": bound},
        "citations": {"sources": sources},
        "reproduce": {"steps": steps, "reruns": reruns},
    }


def latest_recorded(ledger: list[dict]) -> dict[str, dict]:
    """Path -> the bytes the ledger last recorded for it, from a seal or a run's outputs, and the
    run that recorded them: the run itself, or for a sealed input the first run after the seal."""
    latest: dict[str, dict] = {}
    waiting: list[str] = []
    for e in ledger:
        if e.get("event") == "seal":
            for f in e.get("files", []):
                latest[f["path"]] = {"sha256": f.get("sha256"), "run": None}
                waiting.append(f["path"])
        elif e.get("event") == "run":
            run = {"run_id": e.get("run_id"), "timestamp": e.get("timestamp")}
            for path in waiting:
                if latest[path]["run"] is None:
                    latest[path]["run"] = run
            waiting = []
            for o in e.get("outputs", []):
                latest[o["path"]] = {"sha256": o.get("sha256"), "run": run}
    return latest


def plural_s(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


#: What `citations verify` prints for each quotation it did not find: the claims file's stem and
#: the claim, cut to 30 characters and padded to 32, then the first 44 characters of the quote.
NOT_FOUND_LINE = re.compile(r"^  not found  (.{32})(.*)$")


def squash(text: str) -> str:
    return " ".join(text.split())


def not_found_quotes(output: str, sources: list[dict]) -> list[dict]:
    """The quotations `citations verify` printed as not found, matched to the claims file,
    statement and quote they are in. A line that matches none is kept with what it printed."""
    out = []
    for line in output.splitlines():
        m = NOT_FOUND_LINE.match(line)
        if not m:
            continue
        slug, text = m.group(1).rstrip(), squash(m.group(2))
        hit = next(
            (
                {"source": s, "statement": st["id"], "index": k}
                for s in sources
                for st in s["statements"]
                if f"{pathlib.Path(s['file']).stem}:{st['id']}".startswith(slug)
                for k, q in enumerate(st["quotes"])
                if squash(q["exact"]).startswith(text)
            ),
            None,
        )
        out.append(
            {
                "key": hit["source"]["citation"] if hit else slug.split(":")[0],
                "label": f"{slug}: {text}",
                "quote": (
                    {
                        "file": hit["source"]["file"],
                        "statement": hit["statement"],
                        "index": hit["index"],
                    }
                    if hit
                    else None
                ),
            }
        )
    return out


def broken_pins(output: str, sources: list[dict]) -> list[dict]:
    """The sources `citations verify` printed as changed since they were pinned."""
    out, inside = [], False
    for line in output.splitlines():
        if re.match(r"^\d+ sources? changed since being pinned", line):
            inside = True
            continue
        if inside and line.startswith("  ") and " pinned " in line:
            name = line[2:42].strip()
            s = next((s for s in sources if pathlib.Path(s["file"]).stem.startswith(name)), None)
            out.append({"key": s["citation"] if s else name, "file": s["file"] if s else None})
        elif inside:
            inside = False
    return out


def issues(
    project: pathlib.Path,
    sections: dict,
    ledger: list[dict],
    tabs: dict,
    out_dir: pathlib.Path,
) -> list[dict]:
    """One row per kind of problem prereg, results or citations report. Claims and re-runs are
    never here: each has its own count. A row names its items; an item says where the page opens
    it, and, for a file whose recorded bytes differ from the disk, which commit holds the
    recorded bytes, so the diff endpoint serves only what this list names."""
    rows: list[dict] = []

    def row(rid: str, tool_name: str, title: str, note: str, items: list[dict], fix: bool = True):
        rows.append(
            {"id": rid, "tool": tool_name, "title": title, "note": note, "items": items, "fix": fix}
        )

    prereg = sections["prereg"]
    if prereg["used"] and not prereg["account"]:
        said = [ln for ln in prereg["output"].splitlines() if ln.strip()]
        row(
            "prereg-unread",
            "prereg",
            "the preregistrations could not be read",
            said[-1] if said else "",
            [{"label": "Prereg", "open": {"tab": "prereg"}}],
        )
    plans = tabs["prereg"]["plans"]
    changed = [
        p for p in plans if p["pinned_by"] == "freeze" and p["frozen"] and p["check"] == "changed"
    ]
    if changed:
        row(
            "prereg-changed",
            "prereg",
            f"{changed[0]['path']} changed after it was frozen"
            if len(changed) == 1
            else f"{len(changed)} preregistrations changed after they were frozen",
            "The preregistration on disk is not the text that was frozen.",
            [
                {
                    "label": p["path"],
                    "open": {"tab": "prereg", "diff": "prereg-changed", "path": p["path"]},
                    "diff": {"commit": p["commit"], "sha256": p["sha256"]},
                }
                for p in changed
            ],
        )
    pinned_changed = [
        p for p in plans if p["pinned_by"] == "commit line" and p["check"] == "changed"
    ]
    if pinned_changed:
        row(
            "prereg-pinned-changed",
            "prereg",
            f"{pinned_changed[0]['path']} changed after the commit its Commit SHA line names"
            if len(pinned_changed) == 1
            else f"{len(pinned_changed)} registrations changed after the commits their Commit SHA lines name",
            "The file on disk is not its copy in that commit.",
            [
                {
                    "label": p["path"],
                    "open": {"tab": "prereg", "diff": "prereg-pinned-changed", "path": p["path"]},
                    "diff": {"commit": p["commit"], "sha256": None},
                }
                for p in pinned_changed
            ],
        )
    unknown = [
        p
        for p in plans
        if p["pinned_by"] == "commit line" and p["check"] in ("pending", "unknown commit")
    ]
    if unknown:
        row(
            "prereg-pinned-unknown",
            "prereg",
            f"{unknown[0]['path']}: {unknown[0]['check']}"
            if len(unknown) == 1
            else f"{len(unknown)} registrations name no commit this repository holds",
            "The commit its Commit SHA line names cannot be read here.",
            [{"label": p["path"], "open": {"tab": "prereg"}} for p in unknown],
        )
    drafted = [
        p
        for p in plans
        if p["pinned_by"] == "freeze" and p["frozen"] and p["check"] == "not frozen"
    ]
    if drafted:
        row(
            "prereg-amendment-draft",
            "prereg",
            f"{drafted[0]['path']} has an amendment that is not frozen"
            if len(drafted) == 1
            else f"{len(drafted)} preregistrations have an amendment that is not frozen",
            "An amendment beside the preregistration has no freeze record.",
            [{"label": p["path"], "open": {"tab": "prereg"}} for p in drafted],
        )
    never = [p for p in plans if p["pinned_by"] == "freeze" and not p["frozen"]]
    if never:
        row(
            "prereg-never-frozen",
            "prereg",
            f"{never[0]['path']} was never frozen"
            if len(never) == 1
            else f"{len(never)} preregistrations were never frozen",
            "A draft has no frozen text to compare against.",
            [{"label": p["path"], "open": {"tab": "prereg"}} for p in never],
        )

    results = sections["results"]
    account = results["account"]
    if results["used"] and "events" not in account:
        problems = "; ".join(account.get("problems", [])) or str(account.get("chain") or "")
        row(
            "results-chain",
            "results",
            "the ledger's chain does not verify",
            problems.replace("_", " ")[:300] or "results verify could not read the ledger.",
            [{"label": "Results", "open": {"tab": "results"}}],
        )
    if results["used"] and "events" in account:
        latest = latest_recorded(ledger)
        failing = [f for f in account.get("files", []) if f["state"] in RESULTS_FAILING]
        held = find_commits(
            project,
            {
                (f["path"], latest[f["path"]]["sha256"])
                for f in failing
                if f["path"] in latest and latest[f["path"]]["sha256"]
            },
            out_dir,
        )
        said = {
            "changed": (
                "changed after it was sealed",
                "files changed after they were sealed",
                "The file on disk is not the bytes the ledger recorded for it.",
            ),
            "missing": (
                "is missing; the ledger recorded it",
                "recorded files are missing",
                "The ledger recorded bytes at this path, and no file is there now.",
            ),
        }
        for state in RESULTS_FAILING:
            these = [f for f in failing if f["state"] == state]
            if not these:
                continue
            one, many, note = said.get(
                state,
                (
                    f"is {state}",
                    f"recorded files are {state}",
                    f"results verify reports it as {state}.",
                ),
            )
            items = []
            for f in these:
                rec = latest.get(f["path"], {})
                found = held.get((f["path"], rec.get("sha256"))) or {}
                diffable = state in said
                items.append(
                    {
                        "label": f["path"],
                        "open": {
                            "tab": "results",
                            "path": f["path"],
                            "run": rec.get("run"),
                            **({"diff": f"results-{state}"} if diffable else {}),
                        },
                        **(
                            {"diff": {"commit": found.get("commit"), "sha256": rec.get("sha256")}}
                            if diffable
                            else {}
                        ),
                    }
                )
            row(
                f"results-{state}",
                "results",
                f"{these[0]['path']} {one}" if len(these) == 1 else f"{len(these)} {many}",
                note,
                items,
            )
    unsealed = [
        r
        for r in tabs["results"]["runs"]
        if not r["sealed_before"] and not TEST_RUN.match(r["run_id"] or "")
    ]
    if unsealed:
        row(
            "results-unsealed",
            "results",
            f"{len(unsealed)} {plural_s(len(unsealed), 'run', 'runs')} with nothing sealed before "
            f"{plural_s(len(unsealed), 'it', 'them')}",
            "The ledger holds no seal before "
            + plural_s(len(unsealed), "this run", "these runs")
            + ", so nothing recorded the inputs in advance. A record made later cannot supply that.",
            [],
            fix=False,
        )

    citations = sections["citations"]
    sources = tabs["citations"]["sources"]
    if citations is not None and citations["used"]:
        if not citations["account"]:
            said_lines = [ln for ln in citations["output"].splitlines() if ln.strip()]
            row(
                "citations-unread",
                "citations",
                "the quotations could not be checked",
                said_lines[-1] if said_lines else "",
                [{"label": "Citations", "open": {"tab": "citations"}}],
            )
        missed = not_found_quotes(citations["output"], sources)
        n_missed = citations["account"].get("counts", {}).get("not found", 0) or len(missed)
        if n_missed:
            keys = list(dict.fromkeys(m["key"] for m in missed))
            row(
                "citations-not-found",
                "citations",
                f"{n_missed} {plural_s(n_missed, 'quotation', 'quotations')} not found in "
                f"{plural_s(n_missed, 'its source', 'their sources')}"
                + (f" ({', '.join(keys[:3])}{', …' if len(keys) > 3 else ''})" if keys else ""),
                "The quote, the pinned file or the reading may be wrong.",
                [
                    {
                        "label": m["label"],
                        "open": {
                            "tab": "citations",
                            **({"quote": m["quote"]} if m["quote"] else {}),
                        },
                    }
                    for m in missed
                ],
            )
        moved = broken_pins(citations["output"], sources)
        n_moved = citations["account"].get("broken_pins", 0) or len(moved)
        if n_moved:
            row(
                "citations-pin",
                "citations",
                f"{n_moved} {plural_s(n_moved, 'source', 'sources')} changed since "
                f"{plural_s(n_moved, 'it was', 'they were')} pinned"
                + (f" ({', '.join(m['key'] for m in moved[:3])})" if moved else ""),
                "The file on disk is not the bytes its claims file pinned.",
                [
                    {
                        "label": m["key"],
                        "open": {
                            "tab": "citations",
                            **({"source": m["file"]} if m["file"] else {}),
                        },
                    }
                    for m in moved
                ],
            )
    return rows


#: A commit as a freeze or the commit lookup names one: hexadecimal, nothing a shell or git
#: would read as an option.
COMMIT = re.compile(r"^[0-9a-f]{7,64}$")
#: The largest file either side of a diff is read at.
MAX_DIFF_BYTES = 2_000_000


class NotNamed(LookupError):
    """A diff asked for a path the records do not name."""


def issue_diff(project: pathlib.Path, graph_data: dict, issue: str, path: str) -> dict:
    """The recorded bytes of `path` against the file on disk, for an item of the issue `issue`.

    Only an item of the issues list in graph.json is served, by its exact path, and only a path
    inside the project. The recorded bytes come from `git show <commit>:<path>`, the commit the
    record names. A binary file, or one too large, gives each side's hash and size only."""
    row = next((r for r in graph_data.get("issues", []) if r["id"] == issue), None)
    if issue.startswith("step:"):
        step = next(
            (
                st
                for st in graph_data.get("tabs", {}).get("reproduce", {}).get("steps", [])
                if f"step:{st['id']}" == issue
            ),
            None,
        )
        row = {"tool": "repro", "items": step.get("diffs", [])} if step else None
    item = next(
        (
            i
            for i in (row or {}).get("items", [])
            if "diff" in i and i.get("open", {}).get("path") == path
        ),
        None,
    )
    if item is None or pathlib.PurePath(path).is_absolute():
        raise NotNamed(path)
    target = (project / path).resolve()
    if not target.is_relative_to(project):
        raise NotNamed(path)
    commit, recorded = item["diff"].get("commit"), item["diff"].get("sha256")
    tool_name = row["tool"]
    old, old_size = None, None
    if commit and COMMIT.match(commit):
        # The committed copy's size first, so a large one is never read into memory.
        sized = subprocess.run(
            ["git", "cat-file", "-s", f"{commit}:./{path}"],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        old_size = (
            int(sized.stdout) if sized.returncode == 0 and sized.stdout.strip().isdigit() else None
        )
        if old_size is not None and old_size <= MAX_DIFF_BYTES:
            shown = subprocess.run(
                ["git", "show", f"{commit}:./{path}"],
                cwd=project,
                capture_output=True,
                timeout=30,
                check=False,
            )
            old = shown.stdout if shown.returncode == 0 else None
    new = (
        target.read_bytes()
        if target.is_file() and target.stat().st_size <= MAX_DIFF_BYTES
        else None
    )
    old_too_big = old_size is not None and old_size > MAX_DIFF_BYTES
    too_big = (target.is_file() and new is None) or old_too_big

    def side(data: bytes | None) -> dict | None:
        return (
            None
            if data is None
            else {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        )

    notes = []
    if old is None and not old_too_big:
        notes.append(
            "No copy of the sealed bytes was kept: no commit holds them."
            if tool_name == "results"
            else "No copy of the bytes the last re-run saw was kept: no commit holds them."
            if tool_name == "repro"
            else "The freeze recorded no commit this repository holds, so there is no frozen copy to show."
            if not commit or not COMMIT.match(commit)
            else f"Commit {commit[:12]} does not hold {path}."
        )
    elif recorded and side(old)["sha256"] != recorded:
        notes.append(
            f"Commit {commit[:12]} holds other bytes than the ones recorded "
            f"({recorded[:12]}…); the diff is against that commit's copy."
        )
    if not target.is_file():
        notes.append("There is no file at this path now.")
    if too_big:
        notes.append("Too large to compare here; the hashes and sizes are shown.")
    texts = []
    for data in (old, new) if not too_big else ():
        try:
            texts.append(None if data is None else data.decode("utf-8"))
        except UnicodeDecodeError:
            texts.append(False)
    binary = any(t is False for t in texts) or any(b"\0" in d for d in (old, new) if d)
    diff = ""
    if not binary and old is not None and not too_big:
        # A last line with no newline is marked as git marks it, so it does not run into the next.
        diff = "".join(
            line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
            for line in difflib.unified_diff(
                (texts[0] or "").splitlines(keepends=True),
                (texts[1] or "").splitlines(keepends=True),
                fromfile=f"{path} @ {commit[:12]}",
                tofile=f"{path} (now)",
            )
        )
    return {
        "ok": True,
        "path": path,
        "commit": commit,
        "old": (
            {"sha256": recorded if recorded else None, "size": old_size}
            if old_too_big
            else side(old)
        ),
        "new": side(new)
        if new is not None
        else ({"sha256": None, "size": target.stat().st_size} if too_big else None),
        "binary": binary or too_big,
        "diff": diff,
        "note": " ".join(notes),
    }


#: How many numbers with no claim graph.json lists; the count is always whole.
UNBOUND_SHOWN = 200


def presubmit_findings(
    project: pathlib.Path, out_dir: pathlib.Path, tabs: dict, run: bool
) -> dict | None:
    """What the Pre-submit check flags beyond `repro verify`: numbers the manuscript prints that
    no claim accounts for (from `repro numbers`, run with `run` and kept beside graph.json),
    sources whose claims file pins no sha256, and runs with nothing sealed before them. None until
    a Pre-submit check has run."""
    kept = out_dir / "presubmit.json"
    if run:
        said = run_text(
            [tool("repro"), "numbers", "--format", "json", str(project / "repro.yaml")],
            project,
            300,
        )
        try:
            counted = json.loads(said or "")
        except ValueError:
            counted = None
        unbound = [
            {
                "path": t.get("path", ""),
                "line": n.get("line"),
                "text": n.get("text", ""),
                "context": n.get("context", ""),
            }
            for t in (counted or {}).get("texts", [])
            for n in t.get("numbers", [])
            if n.get("standing") == "unbound"
        ]
        out_dir.mkdir(parents=True, exist_ok=True)
        kept.write_text(
            json.dumps(
                {
                    "checked_at": datetime.datetime.now(datetime.UTC).isoformat(),
                    "numbers_read": counted is not None,
                    "unbound": unbound,
                }
            )
        )
    if not kept.exists():
        return None
    found = json.loads(kept.read_text())
    return {
        "checked_at": found["checked_at"],
        "numbers_read": found["numbers_read"],
        "unbound_count": len(found["unbound"]),
        "unbound": found["unbound"][:UNBOUND_SHOWN],
        "unpinned": [s["citation"] for s in tabs["citations"]["sources"] if not s["sha256"]],
        "unsealed": [
            r["run_id"]
            for r in tabs["results"]["runs"]
            if not r["sealed_before"] and not TEST_RUN.match(r["run_id"] or "")
        ],
    }


#: What `repro stale` reports for a project that declares no rebuild step. It prints a sentence
#: rather than JSON then, so the page is built from this instead of from its output.
NOTHING_STALE = {
    "findings": [],
    "regenerations": [],
    "artifacts": [],
    "claims": [],
    "reruns": 0,
}


def build(
    project: pathlib.Path,
    out_path: pathlib.Path,
    groups_file: pathlib.Path | None = None,
    check: bool = True,
    fetch: bool = True,
    presubmit: bool = False,
) -> str:
    """Write graph.json for `project` to `out_path` and return a one-line summary.

    With `presubmit` (which needs `check`), also runs `repro numbers`, which reads the texts the
    claims read and writes nothing, and keeps the numbers no claim accounts for beside graph.json
    for the Pre-submit check.

    With `check`, runs `repro verify`, which records the check in the project's history. Without
    it, reuses the report of the last check (kept beside graph.json) and re-reads everything else,
    so nothing is written to the project. With `fetch`, the landing page of each DOI not yet in
    the cache is looked up over the network; without it nothing is."""
    project = project.resolve()

    manifest = yaml.safe_load((project / "repro.yaml").read_text())
    cache = out_path.with_name("verify-report.json")
    ledger_path = project / ".results" / "ledger.jsonl"
    ledger = (
        [json.loads(x) for x in ledger_path.read_text().splitlines() if x.strip()]
        if ledger_path.exists()
        else []
    )
    if check or not cache.exists():
        verify = repro_json(project, "verify")
        report = verify["report"]
        sections = read_sections(verify, project, manifest, {})
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json.dumps(
                {
                    "checked_at": datetime.datetime.now(datetime.UTC).isoformat(),
                    "report": report,
                    "citations": sections["citations"],
                }
            )
        )
    else:
        cached = json.loads(cache.read_text())
        report = cached["report"]
        sections = read_sections(None, project, manifest, cached)
    checked_at = json.loads(cache.read_text())["checked_at"]
    staleness = sections["staleness"]
    checks = read_checks(project)

    artifacts = {x["id"]: x for x in manifest["artifacts"]}
    is_code = {aid for aid, x in artifacts.items() if x.get("media_type") == "text/x-python"}
    claim_decl = {c["id"]: c for c in manifest["claims"]}
    labels, captions = read_labels(project, artifacts.get("manuscript", {}).get("path"))
    tex_paths = [
        x["path"] for x in artifacts.values() if x.get("media_type") == "application/x-tex"
    ]
    for num, body in table_texts(project, tex_paths, labels).items():
        captions[num] = captions.get(num, "") + " " + body
    fixed_tables = correct_tables(manifest["claims"], labels, captions)
    readers: dict[str, set[str]] = collections.defaultdict(set)
    places: dict[str, set[str]] = collections.defaultdict(set)
    for c in manifest["claims"]:
        for ev in c.get("evidence", []):
            if ev.get("artifact"):
                readers[ev["artifact"]].add(c["id"])
                places[ev["artifact"]].add(resolve_where(c.get("where", ""), labels, fixed_tables))
    overrides = yaml.safe_load(groups_file.read_text()) if groups_file else []
    group_of = auto_groups(
        {k: v for k, v in artifacts.items() if k not in is_code},
        manifest.get("regenerations", []),
        readers,
        places,
        overrides,
    )

    last_run: dict[str, dict] = {}
    for e in ledger:
        if e.get("event") == "run":
            for o in e.get("outputs", []):
                last_run[o["path"]] = {
                    "run_id": e["run_id"],
                    "timestamp": e["timestamp"],
                    "sha256": o["sha256"],
                    "note": e.get("note", ""),
                }

    regen_of = {r["output"]["artifact"]: r for r in manifest.get("regenerations", [])}
    stale_art = {x["id"]: x for x in staleness["artifacts"]}
    stale_regen = {r["artifact"]: r for r in staleness["regenerations"]}
    stale_claim = {c["id"]: c for c in staleness["claims"]}
    causes_by_regen = collections.defaultdict(list)
    for f in staleness["findings"]:
        causes_by_regen[f["regeneration"]].append({"cause": f["cause"], "artifact": f["artifact"]})

    # History: per claim, one point per check that recorded it, with the worst outcome among its
    # assertions in that check. Per file, when a check last read it.
    history = collections.defaultdict(list)
    last_checked: dict[str, str] = {}
    for e in checks:
        by_claim = collections.defaultdict(list)
        for x in e.get("assertions", []):
            if x["claim_id"] in claim_decl:
                by_claim[x["claim_id"]].append(x["outcome"])
                for aid in x.get("digests", {}):
                    last_checked[aid] = e["timestamp"]
        for cid, outs in by_claim.items():
            history[cid].append({"t": e["timestamp"], "outcome": worst(outs)})

    per_art = collections.defaultdict(lambda: {"ok": 0, "fail": 0, "stale": 0, "claims": []})
    per_sec = collections.defaultdict(lambda: {"ok": 0, "fail": 0, "stale": 0, "claims": []})
    edge_counts = collections.Counter()
    for c in report["claims"]:
        decl = claim_decl.get(c["claim_id"], {})
        declared = decl.get("where", "unplaced")
        where = resolve_where(declared, labels, fixed_tables)
        sec = section_of(where)
        st = stale_claim.get(c["claim_id"], {})
        st_assert = st.get("assertions", [])
        rows = []
        for i, dcs in enumerate(c["decisions"]):
            rows.append(
                {
                    "kind": dcs["kind"],
                    "artifact": dcs["artifact_id"],
                    "ok": dcs["execution"] == "completed" and dcs["comparison"] == "match",
                    "comparison": dcs["comparison"],
                    "reason": dcs["reason"],
                    "detail": dcs["detail"],
                    "extracted": dcs["extracted"],
                    "warnings": dcs["warnings"],
                    "stale": st_assert[i]["state"] if i < len(st_assert) else None,
                }
            )
        row = {
            "id": c["claim_id"],
            "where": where,
            "declared_where": declared,
            "section": sec,
            "text": decl.get("text", ""),
            "ok": all(r["ok"] for r in rows),
            "stale": st.get("state"),
            "history": history.get(c["claim_id"], []),
        }
        row["assertions"] = rows
        per_sec[sec]["claims"].append(row)
        per_sec[sec]["ok" if row["ok"] else "fail"] += 1
        per_sec[sec]["stale"] += row["stale"] == "stale"
        for art in {r["artifact"] for r in rows}:
            mine = [r for r in rows if r["artifact"] == art]
            per_art[art]["claims"].append(row)
            per_art[art]["ok" if all(r["ok"] for r in mine) else "fail"] += 1
            per_art[art]["stale"] += any(r["stale"] == "stale" for r in mine)
            if art not in MANUSCRIPT_IDS:
                edge_counts[(art, sec)] += 1

    nodes, groups = [], {}
    for aid, art in artifacts.items():
        if aid in is_code:
            continue
        path = art["path"]
        run = last_run.get(path)
        current = sha256(project / path)
        pinned = art.get("digest", {}).get("value")
        group = group_of[aid]
        groups.setdefault(group, {"id": group, "kind": "files"})
        regen = regen_of.get(aid)
        sr = stale_regen.get(aid)
        nodes.append(
            {
                "id": aid,
                "type": "artifact",
                "group": group,
                "path": path,
                "media_type": art.get("media_type"),
                "pinned": pinned,
                "current": current,
                "state": "missing"
                if current is None
                else ("changed" if pinned and current != pinned else "pinned"),
                "run": run and {**run, "fresh": run["sha256"] == current},
                "regenerated_by": regen and " ".join(regen["command"]),
                "code": [
                    artifacts[i["artifact"]]["path"]
                    for i in (regen or {}).get("inputs", [])
                    if i["artifact"] in is_code
                ],
                "freshness": stale_art.get(aid, {}).get("state"),
                "rerun_at": sr and sr.get("rerun_at"),
                "causes": causes_by_regen.get(aid, []),
                "last_checked": last_checked.get(aid),
                "ok": per_art[aid]["ok"],
                "fail": per_art[aid]["fail"],
                "stale": per_art[aid]["stale"],
                "claims": per_art[aid]["claims"],
            }
        )

    def sec_key(s: str) -> tuple:
        order = {"Section": 0, "Table": 1, "Appendix": 2}
        head, _, rest = s.partition(" ")
        nums = tuple(int(x) if x.isdigit() else x for x in re.split(r"[.\s]", rest))
        return (
            order.get(head, 3),
            tuple((0, x) if isinstance(x, int) else (1, x) for x in nums),
        )

    for g in PAPER_GROUPS.values():
        groups[g] = {"id": g, "kind": "sections"}
    for sec in sorted(per_sec, key=sec_key):
        v = per_sec[sec]
        nodes.append(
            {
                "id": f"sec:{sec}",
                "type": "section",
                "group": PAPER_GROUPS.get(sec.split()[0], "Paper: body"),
                "label": sec,
                "ok": v["ok"],
                "fail": v["fail"],
                "stale": v["stale"],
                "claims": v["claims"],
            }
        )

    edges = []
    for r in manifest.get("regenerations", []):
        for i in r["inputs"]:
            if i["artifact"] in is_code:
                continue
            if i["artifact"] in artifacts and r["output"]["artifact"] in artifacts:
                edges.append(
                    {
                        "source": i["artifact"],
                        "target": r["output"]["artifact"],
                        "kind": "regenerates",
                    }
                )
    for (art, sec), n in edge_counts.items():
        edges.append({"source": art, "target": f"sec:{sec}", "kind": "supports", "count": n})

    # The re-runs `repro reproduce` recorded: how many, and what the last one found.
    rr_path = project / ".repro" / "reproductions.jsonl"
    reruns = (
        [json.loads(x) for x in rr_path.read_text().splitlines() if x.strip()]
        if rr_path.exists()
        else []
    )
    last_rerun = reruns[-1] if reruns else None
    reproduce = {
        "runs": len(reruns),
        "declared": len(manifest.get("regenerations", [])),
        "last_at": last_rerun and last_rerun.get("ended_at"),
        "last": dict(collections.Counter(r.get("state") for r in last_rerun["regenerations"]))
        if last_rerun
        else {},
        "last_steps": len(last_rerun["regenerations"]) if last_rerun else 0,
    }

    # A claim is backed by a run when a file it reads a number from was written by a run the
    # ledger recorded. Derived from the files, so no sentence has to be bound by hand.
    by_id = {n["id"]: n for n in nodes if n["type"] == "artifact"}
    run_backed = sum(
        1
        for c in report["claims"]
        if any(
            by_id.get(d["artifact_id"], {}).get("run")
            for d in c["decisions"]
            if d["kind"] != "quote"
        )
    )
    tabs = record_tabs(project, manifest, ledger, sections, out_path.parent, fetch)
    out = {
        "project": report["project"],
        "built_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "checked_at": checked_at,
        "project_dir": str(project),
        "status": status_lines(project, report, sections, ledger, reruns),
        "reproduce": reproduce,
        "project_name": project.name,
        "remote": remote_of(project),
        "manuscript_path": artifacts.get("manuscript", {}).get("path"),
        "tabs": tabs,
        "issues": issues(project, sections, ledger, tabs, out_path.parent),
        "presubmit": presubmit_findings(project, out_path.parent, tabs, presubmit),
        "manifest_digest": report["manifest_digest"],
        "totals": {
            "claims": len(report["claims"]),
            "assertions": sum(len(c["decisions"]) for c in report["claims"]),
            "artifacts": len(artifacts),
            "failing": sum(1 for c in per_sec.values() for r in c["claims"] if not r["ok"]),
            "reruns": int(staleness.get("reruns") or 0),
            "stale_steps": sum(1 for r in staleness["regenerations"] if r["state"] == "stale"),
            "checks": len(checks),
            "run_backed": run_backed,
            "relabelled_tables": fixed_tables,
            "last_check": checks[-1]["timestamp"] if checks else None,
        },
        "groups": list(groups.values()),
        "nodes": nodes,
        "edges": edges,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Written beside and renamed over, so the server never reads half a file.
    partial = out_path.with_name(out_path.name + ".partial")
    partial.write_text(json.dumps(out, indent=1))
    partial.replace(out_path)
    return f"{len(nodes)} nodes, {len(edges)} edges, {len(groups)} groups -> {out_path}"
