"""`repro audit`: clone a repository at a pinned commit and record what the four tools say.

The command a reviewer runs on somebody else's repository. It clones into a cache directory,
never into the audited repository and never inside another one, runs `prereg check`,
`results verify --files`, `citations verify`, `citations audit` and `repro verify` over the
clone, and writes one record of what each established and what it could not.

Three things are kept apart in every row, because a report that merges them is the defect the
audited tools exist to catch: a check that **failed**, a check that **could not** be made (a
source that is not on this machine, a registry that did not answer), and a check with
**nothing to read** (the repository keeps no ledger). Only the first is a finding about the
repository.

A count under `declared` is read from the repository's own files and only where the layout
names where to find it. A repository with no ledger gets no `ledger_events` key and not a zero:
nothing was examined, which is a different fact from nothing being there.

The record is the format `paper/audit/*_audit.json` already has, with three keys added to each
step (`outcome`, `found`, `could_not`) and one beside them (`skipped`).
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.metadata
import io
import json
import os
import pathlib
import re
import textwrap
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime

import yaml
from provenance_core import gitref, hint, sha256_of_text
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from repro.delegate import BY_NAME
from repro.exceptions import ReproError
from repro.manifest import DEFAULT_NAME

#: A clone or a fetch of a large repository over a slow link.
TIMEOUT = 600

PASSED = "passed"
FAILED = "failed"
COULD_NOT = "could not check"
NOTHING = "nothing to read"

#: How each tool opens its report when the project keeps nothing for it to read. All exit 2.
NOTHING_MARKERS = (
    "no PREREG.md here",
    "no .results/ in",
    "nothing to check.",
    f"no {DEFAULT_NAME} here",
)

#: Per command, the parts of its report that say what it measured, and the parts that count
#: what it did not measure. Matched against each line with runs of spaces collapsed.
READS: dict[tuple[str, str], tuple[str, str]] = {
    ("prereg", "check"): (
        r"^\d+ (?:plans|commit-pinned): .*",
        r"\b[1-9]\d* (?:not frozen|pending|unknown commit)",
    ),
    ("results", "verify"): (r"^chain .*|^\d+ file\(s\) .*|^all checks passed\.", r"(?!)"),
    ("citations", "verify"): (
        r"^(?:found|not found) [\d,]+|^\d+ sources? .*",
        r"^(?:unchecked|indeterminate|ambiguous) [\d,]+.*",
    ),
    ("citations", "audit"): (
        r"^(?:checked|agree|disagree) [\d,]+",
        r"^(?:unresolved|no id) [\d,]+.*",
    ),
    ("repro", "verify"): (
        r"^\d+ \w+(?:, \d+ \w+)*$|^policy .*",
        r"\b[1-9]\d* (?:unchecked|error|not_offered)\b",
    ),
}

#: How `citations verify` heads its warning that git tracks sources it read. The heading opens
#: with `git` so that `N sources ...` above does not take the sentence whole; the count goes
#: into what the step found under a name of its own, and changes no outcome.
TRACKED = re.compile(r"^git tracks ([\d,]+) sources? read here\b")

#: The distribution each command ships in.
DISTRIBUTIONS = {
    "citations": "citations",
    "results": "results-cli",
    "prereg": "prereg",
    "repro": "reproducible-science",
}

#: Files and directories a tool walks upwards for. A clone below one of these binds to it, and
#: the audit then reports another project's records as the audited repository's.
WALKED_FOR = ("PREREG.md", ".results", DEFAULT_NAME)

REGISTRIES = "reaches Crossref, DataCite and PubMed"

Entry = Callable[[Sequence[str]], int]


class AuditError(ReproError):
    """The audit could not be run as asked: no repository, an unreadable target, a failed clone."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Layout(_Strict):
    """Where the repository keeps what is worth counting. What a target leaves out is detected."""

    claims: str | None = None
    manifest: str | None = None
    ledger: str | None = None
    tags: str | None = None
    bibliographies: dict[str, str] | None = None
    globs: dict[str, str | list[str]] = Field(default_factory=dict)


class StepSpec(_Strict):
    name: str
    argv: list[str | int]
    network: bool = False
    note: str = ""


class Target(_Strict):
    """An optional file naming the repository, the pin, unusual paths, and further steps."""

    repository: str | None = None
    commit: str | None = None
    tree: str | None = None
    layout: Layout = Field(default_factory=Layout)
    steps: list[StepSpec] = Field(default_factory=list)


def load_target(path: pathlib.Path) -> Target:
    try:
        return Target.model_validate(yaml.safe_load(path.read_text()) or {})
    except (OSError, yaml.YAMLError, ValidationError) as e:
        raise AuditError(f"{path}: {e}") from e


def checkout(
    repository: str, commit: str | None, cache: pathlib.Path, offline: bool
) -> pathlib.Path:
    """The repository at `commit` (default: the remote's HEAD), cloned under `cache`.

    `repro verify`, `prereg check` and `results verify` walk upwards for a manifest, a plan and
    a ledger, so a clone placed below another project's is refused. A cached clone is fetched
    again and cleaned, so every audit starts from the bytes the commit names: the tools leave
    lock files beside what they read, and a clone carrying an earlier run's is `dirty`.
    """
    into = cache / "checkout"
    for above in into.resolve().parents:
        for marker in WALKED_FOR:
            if (above / marker).exists():
                raise AuditError(
                    f"{above / marker} is above the cache directory {cache}, and the tools "
                    "would read it as the audited repository's. Name another --cache."
                )
    cache.mkdir(parents=True, exist_ok=True)
    try:
        if not (into / ".git").is_dir():
            gitref.run("clone", "--quiet", repository, str(into), cwd=cache, timeout=TIMEOUT)
        else:
            try:
                gitref.run("fetch", "--quiet", "--tags", "origin", cwd=into, timeout=TIMEOUT)
                gitref.run("remote", "set-head", "origin", "--auto", cwd=into, timeout=TIMEOUT)
            except gitref.GitError:
                # Offline, a clone already in the cache is audited as it stands.
                if not offline:
                    raise
        gitref.run("checkout", "--quiet", "--force", "--detach", commit or "origin/HEAD", cwd=into)
        gitref.run("clean", "-fdxq", cwd=into)
    except gitref.GitError as e:
        raise AuditError(str(e)) from e
    return into


def detect(root: pathlib.Path, layout: Layout) -> Layout:
    """`layout` with every path it does not name filled in from what the clone holds."""
    claims = BY_NAME["citations"].data_dir(root)
    found = {
        "claims": claims.relative_to(root).as_posix() if claims else "claims",
        "manifest": DEFAULT_NAME,
        "ledger": ".results/ledger.jsonl",
        "bibliographies": {
            re.sub(r"\W", "_", rel): rel
            for rel in gitref.run("ls-files", "*.bib", cwd=root).splitlines()
        },
    }
    return layout.model_copy(update={k: v for k, v in found.items() if getattr(layout, k) is None})


def default_steps(root: pathlib.Path, layout: Layout) -> list[StepSpec]:
    """One check per kind of record, each pointed at where the layout says the record is."""
    bibs = layout.bibliographies or {}
    manifest = [layout.manifest] if layout.manifest and (root / layout.manifest).is_file() else []
    claims = layout.claims or "claims"
    return [
        StepSpec(name="prereg.check", argv=["prereg", "check"]),
        StepSpec(name="results.verify", argv=["results", "verify", "--files"]),
        StepSpec(name="citations.verify", argv=["citations", "verify", "--claims", claims]),
        *(
            StepSpec(
                name="citations.audit" if len(bibs) == 1 else f"citations.audit.{name}",
                argv=["citations", "audit", "--bib", rel, "--cache", "{cache}"],
                network=True,
                note=REGISTRIES,
            )
            for name, rel in bibs.items()
        ),
        StepSpec(name="repro.verify", argv=["repro", "verify", *manifest]),
    ]


@contextlib.contextmanager
def _inside(root: pathlib.Path) -> Iterator[None]:
    """Be in `root`, with nothing in the environment naming another repository.

    The tools run in this process and ask git about the working directory. A git hook exports
    `GIT_DIR`, so an audit started from one would otherwise check the hook's repository.
    """
    saved = {k: os.environ.pop(k) for k in gitref.REDIRECTS if k in os.environ}
    try:
        with contextlib.chdir(root):
            yield
    finally:
        os.environ.update(saved)


def run_step(argv: list[str], root: pathlib.Path, entry: Entry) -> tuple[int, str]:
    """One command run in the clone: its exit code, and stdout then stderr as it printed them."""
    out, err = io.StringIO(), io.StringIO()
    with _inside(root), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = int(entry(argv[1:]) or 0)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else int(e.code is not None)
        except Exception as e:
            # A crash is a check that did not run, which is what each tool's own 2 means.
            code = 2
            print(f"{type(e).__name__}: {e}", file=err)
    return code, (out.getvalue() + err.getvalue()).rstrip("\n")


def read(argv: list[str], code: int, output: str, root: pathlib.Path) -> tuple[str, str, str]:
    """The outcome word, what the command found, and what it could not establish."""
    text = output.replace(f"{root}/", "").replace(str(root), ".")
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    first = lines[0] if lines else ""
    if code == 2 and (nothing := next((x for x in lines if x.startswith(NOTHING_MARKERS)), "")):
        return NOTHING, nothing, ""

    measured, unmeasured = READS.get(
        (argv[0], argv[1] if len(argv) > 1 else ""), (r"(?!)", r"(?!)")
    )
    items = [m.group() for line in lines for m in re.finditer(measured, line)]
    if argv[:2] == ["citations", "verify"]:
        items += [
            f"{m[1]} source{'' if m[1] == '1' else 's'} tracked by git"
            for m in map(TRACKED.match, lines)
            if m
        ]
    found = "; ".join(items)
    could_not = "; ".join(m.group() for line in lines for m in re.finditer(unmeasured, line))

    # `citations verify --strict` exits 1 over a quotation it could not read, and `citations
    # audit` exits 0 over an entry that disagrees. Neither exit code is the outcome.
    unread = re.search(r"^nothing (?:was measured|failed|disagreed)\.", text, re.M)
    if (code == 1 and not unread) or re.search(r"^ +disagree +[1-9]", text, re.M):
        return FAILED, found or first, could_not
    if could_not or code != 0:
        return COULD_NOT, found, could_not or first
    return PASSED, found or first, ""


def bib_entries(bib: pathlib.Path) -> int:
    text = bib.read_text(errors="replace")
    return text.count("\n@") + int(text.startswith("@"))


def declared(root: pathlib.Path, layout: Layout) -> dict:
    """What the repository offers for checking, counted from its own files.

    Read here and not taken from any tool's summary: a count derived from a verification report
    cannot tell a declaration nothing examined from one that was examined and passed.
    """
    out: dict = {
        "tracked_files": len(gitref.run("ls-files", cwd=root).splitlines()),
        "registered_plans": len(list(root.glob("**/PREREG.md"))),
        "evidence_manifests": len(list(root.glob(f"**/{DEFAULT_NAME}"))),
        "results_ledgers": len(list(root.glob("**/.results/ledger.jsonl"))),
    }

    if layout.claims and (root / layout.claims).is_dir():
        # `citations restore` writes its derived claims to `<name>.restored.yaml` beside the
        # file they came from. Each is the source's own passage, written by a tool, and a
        # count of what the authors declared that included them would count the same
        # quotation twice. They are counted apart.
        every = sorted((root / layout.claims).glob("*.yaml"))
        files = [f for f in every if not f.name.endswith(".restored.yaml")]
        claims = quotes = 0
        sources: dict[str, str] = {}
        for f in files:
            doc = yaml.safe_load(f.read_text()) or {}
            src = doc.get("source", {}) or {}
            sources[src.get("local", "")] = src.get("sha256", "") or ""
            for claim in (doc.get("claims", {}) or {}).values():
                claims += 1
                quotes += len(claim.get("quotes", []) or [])
        out |= {
            "claim_records": len(files),
            "claims": claims,
            "quotations": quotes,
            "pinned_sources": len(sources),
            "sources_carrying_a_digest": sum(1 for v in sources.values() if v),
        }
        if restored := [f for f in every if f not in files]:
            out["restored_claim_records"] = len(restored)
            out["restored_quotations"] = sum(
                len((claim or {}).get("quotes", []) or [])
                for f in restored
                for claim in (
                    (yaml.safe_load(f.read_text()) or {}).get("claims", {}) or {}
                ).values()
            )

    for name, rel in (layout.bibliographies or {}).items():
        if (root / rel).is_file():
            out[f"bibliography_entries_{name}"] = bib_entries(root / rel)

    if layout.manifest and (root / layout.manifest).is_file():
        manifest = yaml.safe_load((root / layout.manifest).read_text()) or {}
        evidence = [e for c in manifest.get("claims") or [] for e in c.get("evidence") or []]
        out |= {
            "manifest_artifacts": len(manifest.get("artifacts") or []),
            "manifest_claims": len(manifest.get("claims") or []),
            "manifest_assertions": len(evidence),
            "manifest_assertions_by_kind": {
                k: sum(1 for e in evidence if e["kind"] == k)
                for k in sorted({e["kind"] for e in evidence})
            },
            "manifest_regenerations": len(manifest.get("regenerations") or []),
        }

    if layout.tags and (root / layout.tags).is_file():
        tags = json.loads((root / layout.tags).read_text())
        out["unresolved_manuscript_tags"] = tags["count"]
        out["unresolved_manuscript_tags_by_kind"] = {
            kind: sum(1 for t in tags["tags"] if t["kind"] == kind)
            for kind in sorted({t["kind"] for t in tags["tags"]})
        }

    if layout.ledger and (root / layout.ledger).is_file():
        events = [
            json.loads(line)
            for line in (root / layout.ledger).read_text().splitlines()
            if line.strip()
        ]
        digests = {f["path"] for e in events for f in (e.get("files", []) + e.get("outputs", []))}
        out |= {
            "ledger_events": len(events),
            "runs": len({e["run_id"] for e in events if "run_id" in e}),
            "file_digests_recorded": len(digests),
            "manuscript_claims_bound": sum(1 for e in events if e["event"] == "claim"),
            "confirmatory_claims": sum(
                1 for e in events if e["event"] == "claim" and e.get("confirmatory")
            ),
        }

    # A name may take several patterns: "manuscripts" is `.tex` plus the drafts beside them.
    for name, patterns in layout.globs.items():
        out[name] = sum(
            len(list(root.glob(p))) for p in ([patterns] if isinstance(patterns, str) else patterns)
        )
    return out


def table(steps: dict[str, dict], skipped: dict[str, dict]) -> str:
    """One row per check: command, exit, outcome, what it found, what it could not establish."""
    rows = [("command", "exit", "outcome", "what it found", "what it could not establish")]
    rows += [
        (name, str(s["exit"]), s["outcome"], s["found"] or "-", s["could_not"] or "-")
        for name, s in steps.items()
    ]
    rows += [(name, "-", "not run", "-", s["reason"]) for name, s in skipped.items()]
    widths = (max(len(r[0]) for r in rows), 4, len(COULD_NOT), 44, 40)
    lines = []
    for row in rows:
        cells = [
            textwrap.wrap(cell, width) or [""] for cell, width in zip(row, widths, strict=True)
        ]
        for i in range(max(len(c) for c in cells)):
            lines.append(
                "  ".join(
                    (c[i] if i < len(c) else "").ljust(w)
                    for c, w in zip(cells, widths, strict=True)
                ).rstrip()
            )
    return "\n".join(lines)


def exit_code(steps: dict[str, dict]) -> int:
    """1 when a check failed; 2 when one could not be made or nothing was established; else 0."""
    outcomes = [s["outcome"] for s in steps.values()]
    if FAILED in outcomes:
        return 1
    return 2 if COULD_NOT in outcomes or PASSED not in outcomes else 0


def audit(
    repository: str | None,
    entries: dict[str, Entry],
    *,
    commit: str | None = None,
    target_path: pathlib.Path | None = None,
    offline: bool = False,
    cache: pathlib.Path | None = None,
    out: pathlib.Path | None = None,
) -> int:
    """Audit one repository, write `<name>_audit.json` and `.log` under `out`, print the table."""
    target = load_target(target_path) if target_path else Target()
    repository = repository or target.repository
    if not repository:
        raise AuditError("name a repository: a URL, a path, or a --target file that gives one")
    if (local := pathlib.Path(repository).expanduser()).exists():
        repository = str(local.resolve())

    stem = pathlib.PurePosixPath(repository.rstrip("/")).name.removesuffix(".git")
    if target_path:
        stem = target_path.stem.removesuffix("_target") or target_path.stem
        stem = "repo" if stem in ("target", "repo") else stem
    stem = re.sub(r"\W", "_", stem)
    cache = cache or hint.cache_root() / "audit" / f"{stem}-{sha256_of_text(repository)[:8]}"

    root = checkout(repository, commit or target.commit, cache, offline)
    head = gitref.run("rev-parse", "HEAD", cwd=root)
    tree = gitref.run("rev-parse", "HEAD^{tree}", cwd=root)
    pin = {
        "commit": head,
        "tree": tree,
        "dirty": gitref.is_dirty(root),
        "commit_matches_pin": head == (target.commit or head),
        # A tree nobody pinned is not one that failed to match.
        "tree_matches_pin": tree == target.tree if target.tree else None,
    }

    layout = detect(root, target.layout)
    named = {s.name for s in target.steps}
    specs = [*target.steps, *(s for s in default_steps(root, layout) if s.name not in named)]
    for spec in specs:
        if str(spec.argv[0]) not in entries:
            raise AuditError(
                f"step {spec.name} runs {spec.argv[0]!r}; a step runs one of "
                f"{', '.join(sorted(entries))}"
            )
    target = target.model_copy(
        update={
            "repository": repository,
            "commit": target.commit or head,
            "layout": layout,
            "steps": specs,
        }
    )
    # Counted before any step runs: the tools leave lock files in the clone.
    counts = declared(root, layout)

    steps: dict[str, dict] = {}
    skipped: dict[str, dict] = {}
    if not layout.bibliographies and not any(s.argv[:2] == ["citations", "audit"] for s in specs):
        skipped["citations.audit"] = {"command": "", "reason": "no .bib file in the repository"}
    for spec in specs:
        argv = [str(a).replace("{cache}", str(cache / "audit-cache")) for a in spec.argv]
        if spec.network and offline:
            skipped[spec.name] = {"command": " ".join(argv), "reason": f"offline: {spec.note}"}
            continue
        code, output = run_step(argv, root, entries[argv[0]])
        outcome, found, could_not = read(argv, code, output, root)
        steps[spec.name] = {
            "command": " ".join(argv),
            "exit": code,
            "note": spec.note,
            "output": output,
            "outcome": outcome,
            "found": found,
            "could_not": could_not,
        }

    record = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "target": target.model_dump(exclude_unset=True),
        "pin": pin,
        "tool_versions": {d: importlib.metadata.version(d) for d in DISTRIBUTIONS.values()},
        "declared": counts,
        "steps": steps,
        "skipped": skipped,
    }
    out = out or pathlib.Path.cwd()
    out.mkdir(parents=True, exist_ok=True)
    record_path, log_path = out / f"{stem}_audit.json", out / f"{stem}_audit.log"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")

    log = [
        f"# audit of {repository}, {record['generated']}",
        f"# commit {head}",
        f"# tree   {tree}  matches pin: {pin['tree_matches_pin']}  dirty: {pin['dirty']}",
        "",
    ]
    for s in steps.values():
        log += [f"$ {s['command']}", s["output"], f"[exit {s['exit']}]", ""]
    log_path.write_text("\n".join(log))

    print(f"{repository}\ncommit {head}\ntree   {tree}")
    if pin["tree_matches_pin"] is False or not pin["commit_matches_pin"]:
        print(f"  the target pins commit {target.commit}, tree {target.tree}: not what was audited")
    print(f"\n{table(steps, skipped)}\n\nwrote {record_path} and {log_path}")
    return exit_code(steps)


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = sub.add_parser(
        "audit",
        help="clone a repository at a pinned commit and run every tool over the clone",
        description=(
            "Clone a repository into a cache directory at a commit, run prereg check, results "
            "verify --files, citations verify, citations audit on each .bib file and repro "
            "verify over the clone, and write <name>_audit.json and <name>_audit.log. Nothing "
            "is written into the audited repository. A check that could not be made, and a "
            "check with nothing to read, are reported apart from one that failed. Exits 1 "
            "when a check failed, 2 when one could not be made or nothing was established, "
            "and 0 otherwise."
        ),
    )
    p.add_argument("repository", nargs="?", help="a URL or a path (default: the target file's)")
    p.add_argument(
        "--commit", help="the revision to audit (default: the target's, else the remote's HEAD)"
    )
    p.add_argument(
        "--target",
        type=pathlib.Path,
        help="a YAML file adding steps, naming unusual paths, or pinning a commit and tree",
    )
    p.add_argument("--offline", action="store_true", help="skip the steps that reach a registry")
    p.add_argument("--cache", type=pathlib.Path, help="where the clone goes (default: user cache)")
    p.add_argument(
        "--out", type=pathlib.Path, help="where the record and log are written (default: .)"
    )
    return p


def command(args: argparse.Namespace, entries: dict[str, Entry]) -> int:
    return audit(
        args.repository,
        entries,
        commit=args.commit,
        target_path=args.target,
        offline=args.offline,
        cache=args.cache,
        out=args.out,
    )
