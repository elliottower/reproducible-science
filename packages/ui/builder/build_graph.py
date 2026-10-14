"""Build graph.json, the data behind the lineage view, for one project.

Reads the project's repro.yaml, runs `repro verify --format json` and `repro stale --format json`
(both read-only apart from the check history `repro verify` already keeps), and reads the
results ledger and the local record of checks. Writes one JSON file the web app loads.

    uv run --no-project --with pyyaml==6.0.2 python builder/build_graph.py <project> web/public/graph.json
"""

import argparse
import collections
import datetime
import hashlib
import json
import pathlib
import re
import subprocess
import urllib.error
import urllib.request

import yaml

PAPER_GROUPS = {"Section": "Paper: body", "Table": "Paper: tables", "Appendix": "Paper: appendices"}
MANUSCRIPT_IDS = {"manuscript", "manuscript-text", "appendix", "appendix-text"}
# Worst first, for collapsing several assertions into one outcome per check.
OUTCOME_RANK = ["mismatch", "not_found", "error", "unchecked", "verified"]


def sha256(path: pathlib.Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def repro_json(project: pathlib.Path, command: str) -> dict:
    out = subprocess.run(
        ["repro", command, "--format", "json", str(project / "repro.yaml")],
        cwd=project, capture_output=True, text=True, check=False,
    )
    if not out.stdout.strip():
        raise RuntimeError(f"repro {command} wrote nothing: {out.stderr.strip()[:500]}")
    return json.loads(out.stdout)


def section_of(where: str) -> str:
    first = where.split(",")[0].strip()
    m = re.match(r"Section (\d+)", first)
    return f"Section {m.group(1)}" if m else first


def auto_groups(artifacts: dict, regenerations: list, readers: dict[str, set[str]], places: dict[str, set[str]],
                overrides: list[dict]) -> dict[str, str]:
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
    rendered = {r["output"]["artifact"] for r in regenerations if any(i["artifact"] in tex for i in r["inputs"])}
    manuscript = (tex | rendered) - set(fixed)

    outdeg = collections.Counter(i["artifact"] for r in regenerations for i in r["inputs"])
    for r in regenerations:
        out = r["output"]["artifact"]
        for i in r["inputs"]:
            src = i["artifact"]
            if src in parent and out in parent and not {src, out} & (manuscript | set(fixed)) and outdeg[src] <= 2:
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
        names[root] = word if n > 1 or len(members) == 1 else max(members, key=lambda m: len(readers.get(m, ())))
    group = {a: names[find(a)] for a in ids if a not in manuscript and a not in fixed}
    group.update({a: "manuscript" for a in manuscript})
    group.update(fixed)
    return group


def read_labels(project: pathlib.Path, manuscript_path: str | None) -> tuple[dict[str, str], dict[str, str]]:
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


def table_texts(project: pathlib.Path, tex_paths: list[str], labels: dict[str, str]) -> dict[str, str]:
    """Table number -> normalized text of the whole table environment (caption and cells), from
    every .tex file the manifest pins. Cells are joined with ` | `, as a text rendering prints them."""
    out: dict[str, str] = {}
    for rel in tex_paths:
        f = project / rel
        if not f.is_file():
            continue
        src = f.read_text(errors="replace")
        for block in re.findall(r"\\begin\{table\*?\}(.*?)\\end\{table\*?\}", src, flags=re.S):
            m = re.search(r"\\label\{(tab:[^}]+)\}", block)
            if m and m.group(1) in labels:
                out[labels[m.group(1)]] = out.get(labels[m.group(1)], "") + " " + normalize(block.replace("&", " | "))
    return out


def normalize(tex: str) -> str:
    s = tex.replace("{,}", ",").replace("~", " ").replace("\\relax", "").replace("\\\\", " ")
    s = re.sub(r"\\[a-zA-Z]+\s*", "", s)
    s = re.sub(r"[{}$^]", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def correct_tables(claims: list[dict], labels: dict[str, str], captions: dict[str, str]) -> dict[str, str]:
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
        num, n = v.most_common(1)[0]
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
        prefix = {"Table": "tab:", "Figure": "fig:", "Section": "sec:", "Appendix": "sec:"}[m.group(1)]
        num = labels.get(prefix + m.group(2))
        return f"{m.group(1)} {num}" if num else part.strip()
    return ", ".join(one(p) for p in where.split(","))


def worst(outcomes: list[str]) -> str:
    return min(outcomes, key=lambda o: OUTCOME_RANK.index(o) if o in OUTCOME_RANK else 0)


def read_checks(project: pathlib.Path) -> list[dict]:
    git_dir = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=project, capture_output=True, text=True)
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
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def status_lines(project: pathlib.Path, report: dict) -> dict:
    """The four fields the repro mod draws above the prompt, computed the same way: `prereg check`,
    `results verify` and the ledger, a count of pinned quotations, and the repro counts. Each field
    is a short text plus `ok`: True, False (something is wrong) or None (nothing there to check).
    Read-only: none of these commands writes."""
    fields: dict[str, dict] = {}

    plans = run_text(["prereg", "check"], project)
    counts = collections.Counter()
    for line in (plans or "").splitlines():
        pinned = re.match(r"^(unchanged|appended|CHANGED|pending|unknown commit)\s{2,}[^/\s]", line)
        m = re.match(r"^([A-Za-z][A-Za-z ]*?)\s{2,}/", line)
        label = (m.group(1).lower() if m else None) or (
            {"unchanged": "unchanged", "appended": "unchanged", "CHANGED": "changed"}.get(pinned.group(1), "not frozen") if pinned else None)
        if label and label != "log":
            counts[label] += 1
    total, frozen = sum(counts.values()), counts["unchanged"]
    broken = total - frozen - counts["not frozen"]
    fields["prereg"] = (
        {"text": "not read (timed out)", "ok": False} if plans is None
        else {"text": "none drafted", "ok": None, "next": "prereg new"} if total == 0
        else {"text": f"{broken} changed", "ok": False} if broken
        else {"text": f"{frozen}/{total} frozen", "ok": True})

    ledger = project / ".results" / "ledger.jsonl"
    if ledger.exists():
        verified = run_text(["results", "verify"], project) or ""
        head = verified.split("\n")[0]
        if re.search(r"chain intact: \d+ events", head):
            events = [json.loads(x) for x in ledger.read_text().splitlines() if x.strip()]
            is_test = lambda rid: bool(re.match(r"^(smoke|prefreeze|test|dryrun)[_-]", rid or ""))
            claims = [e for e in events if e.get("event") == "claim"]
            has_seal, runs, sealed = False, 0, 0
            for e in events:
                if e.get("event") == "seal":
                    has_seal = True
                elif e.get("event") == "run" and not is_test(e.get("run_id")):
                    runs += 1
                    sealed += has_seal
            changed = len(re.findall(r"^\s+(CHANGED|MISSING)\s", verified, flags=re.M))
            fields["results"] = {
                "text": (f"{changed} changed, " if changed else "") + (f"{sealed}/{runs} runs sealed" if runs else "0 runs")
                + f", {plural(len(claims), 'claim')} bound",
                "ok": not changed and sealed == runs,
                "counts": {"runs": runs, "sealed": sealed, "bound": len(claims), "changed": changed},
            }
        else:
            m = re.match(r"^(?:CHAIN|NO)\s+(\w+)", head)
            fields["results"] = {"text": (m.group(1).lower() if m else "unreadable"), "ok": False}
    else:
        fields["results"] = {"text": "no ledger", "ok": None, "next": "results init"}

    folders = [d for d in project.rglob("claims") if d.is_dir() and ".git" not in d.parts and "node_modules" not in d.parts
               and len(d.relative_to(project).parts) <= 4]
    pinned_n = 0
    for d in folders:
        for f in d.rglob("*"):
            if f.is_file():
                pinned_n += len(re.findall(r"^[ \t]*-?[ \t]*exact:", f.read_text(errors="replace"), flags=re.M))
    fields["citations"] = ({"text": f"{pinned_n:,} pinned, not verified", "ok": None, "counts": {"pinned": pinned_n}} if folders
                           else {"text": "none pinned", "ok": None, "next": "citations pin"})

    outcomes = collections.Counter("verified" if d["comparison"] == "match" and d["execution"] == "completed" else d["comparison"]
                                   for c in report["claims"] for d in c["decisions"])
    n = sum(outcomes.values())
    fields["repro"] = ({"text": "no claims declared", "ok": None} if n == 0
                       else {"text": f"{outcomes['verified']:,}/{n:,} checks verified", "ok": outcomes["verified"] == n})
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
        sections = [(m.start(), re.sub(r"\\[a-zA-Z]+\{?|[{}]", "", m.group(2)).strip())
                    for m in re.finditer(r"\\(section|subsection)\*?\{([^}]*)\}", src)]
        for m in cite.finditer(src):
            start = max(src.rfind(". ", 0, m.start()), src.rfind("\n\n", 0, m.start()), src.rfind("}.", 0, m.start()))
            end_dot = src.find(". ", m.end())
            end_par = src.find("\n\n", m.end())
            end = min(x for x in (end_dot, end_par, len(src)) if x != -1)
            raw = src[start + 2 if start >= 0 else 0:end + 1]
            text = cite.sub(lambda c: "[" + c.group(1) + "]", raw)
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
            body, fields = src[m.end():i - 1], {"type": m.group(1).lower()}
            for f in re.finditer(r"(\w+)\s*=\s*", body):
                j = f.end()
                if j < len(body) and body[j] == "{":
                    k, d = j + 1, 1
                    while k < len(body) and d:
                        d += {"{": 1, "}": -1}.get(body[k], 0)
                        k += 1
                    value = body[j + 1:k - 1]
                elif j < len(body) and body[j] == '"':
                    k = body.find('"', j + 1)
                    value = body[j + 1:k]
                else:
                    value = re.match(r"[^,\n]*", body[j:]).group(0)
                value = re.sub(r"\\[a-zA-Z]+\s*", "", value).replace("{", "").replace("}", "").replace("--", "–")
                fields[f.group(1).lower()] = re.sub(r"\s+", " ", value).strip()
            out[m.group(2)] = fields
    return out


def landing_url(url: str, doi: str, cache: dict[str, str]) -> str:
    """The page a reader lands on: a doi.org address is resolved once to the publisher's page and
    cached, because a doi.org link says nothing about where it goes. Unresolvable: left as given."""
    target = url or (f"https://doi.org/{doi}" if doi else "")
    if not target or "doi.org/" not in target:
        return target
    if target in cache and "doi.org/" not in cache[target]:
        return cache[target]
    # HEAD first; a publisher that refuses it (ACM, OUP, BMC…) often still redirects a GET, of which
    # only the final address is read. A failure is not cached, so the next build tries again.
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(target, method=method, headers={"User-Agent": "reproducible-science-graph"})
            with urllib.request.urlopen(req, timeout=8) as r:
                cache[target] = r.geturl()
                return cache[target]
        except urllib.error.HTTPError as e:  # a 403 after the redirect still names the landing page
            if e.url and "doi.org/" not in e.url:
                cache[target] = e.url
                return cache[target]
        except Exception:  # timeout, refused connection: try the next method
            continue
    return target


def record_tabs(project: pathlib.Path, manifest: dict, ledger: list[dict], staleness: dict, out_dir: pathlib.Path) -> dict:
    """What the Prereg, Results, Citations and Reproduce tabs list, read from the records themselves."""
    # prereg: what `prereg check` printed, one line per plan.
    plans = [ln for ln in (run_text(["prereg", "check"], project) or "").splitlines() if ln.strip()]

    # results: every run, whether a seal came before it, and the sentences bound with `results claim`.
    runs, sealed_yet, seals = [], False, 0
    for e in ledger:
        if e.get("event") == "seal":
            sealed_yet = True
            seals += 1
        elif e.get("event") == "run":
            runs.append({"run_id": e.get("run_id"), "timestamp": e.get("timestamp"), "note": e.get("note", ""),
                         "outputs": [o["path"] for o in e.get("outputs", [])], "sealed_before": sealed_yet})
    bound = [{"run_id": e.get("run_id"), "timestamp": e.get("timestamp"), "claim": e.get("claim", ""),
              "location": e.get("location", "")} for e in ledger if e.get("event") == "claim"]

    # citations: every claims file under a `claims` folder, with its source and quotations, and
    # the sentences of the manuscript that cite it.
    tex_paths = [x["path"] for x in manifest["artifacts"] if x.get("media_type") == "application/x-tex"]
    cited_in = citing_sentences(project, tex_paths)
    main_tex = next((project / x["path"] for x in manifest["artifacts"] if x["id"] == "manuscript"), None)
    bib_names = re.findall(r"\\bibliography\{([^}]*)\}", main_tex.read_text(errors="replace")) if main_tex and main_tex.is_file() else []
    bib = parse_bib([main_tex.parent / f"{n.strip()}.bib" for names in bib_names for n in names.split(",")]) if main_tex else {}
    cache_path = out_dir / "landing_urls.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    sources = []
    for d in sorted(project.rglob("claims")):
        if not d.is_dir() or ".git" in d.parts or "node_modules" in d.parts or len(d.relative_to(project).parts) > 4:
            continue
        for f in sorted(d.glob("*.y*ml")):
            try:
                doc = yaml.safe_load(f.read_text()) or {}
            except yaml.YAMLError:
                continue
            src = doc.get("source", {}) or {}
            statements = []
            for sid, c in (doc.get("claims", {}) or {}).items():
                quotes = [{"exact": q.get("exact", ""), "section": q.get("section", "")} for q in (c or {}).get("quotes", []) or [] if isinstance(q, dict)]
                statements.append({"id": sid, "statement": (c or {}).get("statement", ""), "quotes": quotes,
                                   "notes": (c or {}).get("notes", "")})
            sources.append({"file": str(f.relative_to(project)), "citation": src.get("citation", f.stem),
                            "url": src.get("url", ""), "local": src.get("local", ""), "sha256": src.get("sha256", ""),
                            "cited_in": cited_in.get(src.get("citation", f.stem), []),
                            "bib": bib.get(src.get("citation", f.stem), {}),
                            "link": landing_url(src.get("url", ""), bib.get(src.get("citation", f.stem), {}).get("doi", ""), cache),
                            # The DOI's own landing page, which is the publisher's record; the link above
                            # is the copy that was pinned and may be a preprint elsewhere.
                            "doi_link": landing_url("", bib.get(src.get("citation", f.stem), {}).get("doi", "")
                                                    or (re.search(r"doi\.org/(10\.[^\s?#]+)", src.get("url", "")) or [None, ""])[1], cache),
                            "pinned": sum(len(s["quotes"]) for s in statements), "statements": statements})

    # reproduce: every declared rebuild step with its state, and every recorded re-run.
    causes = collections.defaultdict(list)
    for f in staleness["findings"]:
        causes[f["regeneration"]].append({"cause": f["cause"], "artifact": f["artifact"]})
    regen = {r["id"]: r for r in manifest.get("regenerations", [])}
    steps = [{"id": r["id"], "artifact": r["artifact"], "state": r["state"], "rerun_at": r.get("rerun_at"),
              "command": " ".join(regen.get(r["id"], {}).get("command", [])), "causes": causes.get(r["id"], [])}
             for r in staleness["regenerations"]]
    rr_path = project / ".repro" / "reproductions.jsonl"
    reruns = []
    if rr_path.exists():
        for line in rr_path.read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                reruns.append({"started_at": e.get("started_at"), "ended_at": e.get("ended_at"), "tool_version": e.get("tool_version"),
                               "counts": dict(collections.Counter(r.get("state") for r in e.get("regenerations", []))),
                               "steps": len(e.get("regenerations", []))})
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=1))
    return {"prereg": {"lines": plans}, "results": {"runs": runs, "seals": seals, "bound": bound},
            "citations": {"sources": sources}, "reproduce": {"steps": steps, "reruns": reruns}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", type=pathlib.Path)
    ap.add_argument("out", type=pathlib.Path)
    ap.add_argument("--groups", type=pathlib.Path,
                    help="optional YAML list of {group, match}: a file whose id matches the regex goes to that group")
    a = ap.parse_args()
    print(build(a.project, a.out, a.groups))


def build(project: pathlib.Path, out_path: pathlib.Path, groups_file: pathlib.Path | None = None,
          check: bool = True) -> str:
    """Write graph.json for `project` to `out_path` and return a one-line summary.

    With `check`, runs `repro verify`, which records the check in the project's history. Without
    it, reuses the report of the last check (kept beside graph.json) and re-reads everything else,
    so nothing is written to the project."""
    project = project.resolve()

    manifest = yaml.safe_load((project / "repro.yaml").read_text())
    cache = out_path.with_name("verify-report.json")
    if check or not cache.exists():
        report = repro_json(project, "verify")["report"]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "report": report}))
    else:
        report = json.loads(cache.read_text())["report"]
    checked_at = json.loads(cache.read_text())["checked_at"]
    staleness = repro_json(project, "stale")["staleness"]
    ledger_path = project / ".results" / "ledger.jsonl"
    ledger = [json.loads(x) for x in ledger_path.read_text().splitlines()] if ledger_path.exists() else []
    checks = read_checks(project)

    artifacts = {x["id"]: x for x in manifest["artifacts"]}
    is_code = {aid for aid, x in artifacts.items() if x.get("media_type") == "text/x-python"}
    claim_decl = {c["id"]: c for c in manifest["claims"]}
    labels, captions = read_labels(project, artifacts.get("manuscript", {}).get("path"))
    tex_paths = [x["path"] for x in artifacts.values() if x.get("media_type") == "application/x-tex"]
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
    group_of = auto_groups({k: v for k, v in artifacts.items() if k not in is_code},
                           manifest.get("regenerations", []), readers, places, overrides)

    last_run: dict[str, dict] = {}
    for e in ledger:
        if e.get("event") == "run":
            for o in e.get("outputs", []):
                last_run[o["path"]] = {"run_id": e["run_id"], "timestamp": e["timestamp"], "sha256": o["sha256"], "note": e.get("note", "")}

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
            rows.append({
                "kind": dcs["kind"], "artifact": dcs["artifact_id"],
                "ok": dcs["execution"] == "completed" and dcs["comparison"] == "match",
                "comparison": dcs["comparison"], "reason": dcs["reason"], "detail": dcs["detail"],
                "extracted": dcs["extracted"], "warnings": dcs["warnings"],
                "stale": st_assert[i]["state"] if i < len(st_assert) else None,
            })
        row = {
            "id": c["claim_id"], "where": where, "declared_where": declared, "section": sec, "text": decl.get("text", ""),
            "ok": all(r["ok"] for r in rows), "stale": st.get("state"),
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
        nodes.append({
            "id": aid, "type": "artifact", "group": group, "path": path,
            "media_type": art.get("media_type"),
            "pinned": pinned, "current": current,
            "state": "missing" if current is None else ("changed" if pinned and current != pinned else "pinned"),
            "run": run and {**run, "fresh": run["sha256"] == current},
            "regenerated_by": regen and " ".join(regen["command"]),
            "code": [artifacts[i["artifact"]]["path"] for i in (regen or {}).get("inputs", []) if i["artifact"] in is_code],
            "freshness": stale_art.get(aid, {}).get("state"),
            "rerun_at": sr and sr.get("rerun_at"),
            "causes": causes_by_regen.get(aid, []),
            "last_checked": last_checked.get(aid),
            "ok": per_art[aid]["ok"], "fail": per_art[aid]["fail"], "stale": per_art[aid]["stale"],
            "claims": per_art[aid]["claims"],
        })

    def sec_key(s: str) -> tuple:
        order = {"Section": 0, "Table": 1, "Appendix": 2}
        head, _, rest = s.partition(" ")
        nums = tuple(int(x) if x.isdigit() else x for x in re.split(r"[.\s]", rest))
        return (order.get(head, 3), tuple((0, x) if isinstance(x, int) else (1, x) for x in nums))

    for g in PAPER_GROUPS.values():
        groups[g] = {"id": g, "kind": "sections"}
    for sec in sorted(per_sec, key=sec_key):
        v = per_sec[sec]
        nodes.append({"id": f"sec:{sec}", "type": "section", "group": PAPER_GROUPS.get(sec.split()[0], "Paper: body"),
                      "label": sec, "ok": v["ok"], "fail": v["fail"], "stale": v["stale"], "claims": v["claims"]})

    edges = []
    for r in manifest.get("regenerations", []):
        for i in r["inputs"]:
            if i["artifact"] in is_code:
                continue
            if i["artifact"] in artifacts and r["output"]["artifact"] in artifacts:
                edges.append({"source": i["artifact"], "target": r["output"]["artifact"], "kind": "regenerates"})
    for (art, sec), n in edge_counts.items():
        edges.append({"source": art, "target": f"sec:{sec}", "kind": "supports", "count": n})

    # The re-runs `repro reproduce` recorded: how many, and what the last one found.
    rr_path = project / ".repro" / "reproductions.jsonl"
    reruns = [json.loads(x) for x in rr_path.read_text().splitlines() if x.strip()] if rr_path.exists() else []
    last_rerun = reruns[-1] if reruns else None
    reproduce = {
        "runs": len(reruns),
        "declared": len(manifest.get("regenerations", [])),
        "last_at": last_rerun and last_rerun.get("ended_at"),
        "last": dict(collections.Counter(r.get("state") for r in last_rerun["regenerations"])) if last_rerun else {},
        "last_steps": len(last_rerun["regenerations"]) if last_rerun else 0,
    }

    # A claim is backed by a run when a file it reads a number from was written by a run the
    # ledger recorded. Derived from the files, so no sentence has to be bound by hand.
    by_id = {n["id"]: n for n in nodes if n["type"] == "artifact"}
    run_backed = sum(
        1 for c in report["claims"]
        if any(by_id.get(d["artifact_id"], {}).get("run") for d in c["decisions"] if d["kind"] != "quote"))
    out = {
        "project": report["project"],
        "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "checked_at": checked_at,
        "project_dir": str(project),
        "status": status_lines(project, report),
        "reproduce": reproduce,
        "project_name": project.name,
        "tabs": record_tabs(project, manifest, ledger, staleness, out_path.parent),
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
    out_path.write_text(json.dumps(out, indent=1))
    return f"{len(nodes)} nodes, {len(edges)} edges, {len(groups)} groups -> {out_path}"


if __name__ == "__main__":
    main()
