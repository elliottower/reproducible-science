"""`repro mcp`: the toolkit's checks as tools of an MCP server, over standard input and output.

Every tool calls the toolkit in this process: the claims side through its functions, and
`prereg`, `results` and `citations` through the entry `repro check` uses, each told to write
what it found as JSON. Nothing here freezes or registers a plan, seals or records a run, runs a
declared command or publishes, and only `citations_audit` reads over the network, from
registries; the instructions say to ask the human for the rest.

Each call works in one project, found from its path: the nearest folder at or above it holding
a marker (`PROJECT_MARKERS`). A call with no path takes its `project` argument, else the
project of the last call, else `--root`, else the project above the working directory. Every
path is kept inside its project. Tool bodies run on the event loop, one at a time, because the
delegated tools change the working directory and print.
"""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import re
import tempfile
from collections.abc import Callable, Sequence
from typing import Any

from citations import audit as citations_audit_module
from citations import pin as citations_pin
from claims.exceptions import ReproError
from claims.manifest import DEFAULT_NAME
from claims.models import Basis
from claims.numbers import numbers as run_numbers
from claims.origins import origins as run_origins
from claims.policy import PROFILES
from claims.stale import stale as run_stale
from claims.verify import verify as run_verify
from claims.why import why as run_why
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from repro import __version__
from repro.delegate import BY_NAME
from repro.delegate import run as delegate_run
from repro.proposals import (
    MAX_NAME,
    MAX_TEXT,
    PROJECT_MARKERS,
    Refused,
    capped,
    inside,
    load_inside,
    packet,
    project_of,
    propose,
)
from repro.proposals import add_artifact as add_artifact_to
from repro.proposals import mark_reviewed as record_review

NAME = "reproducible-science"

NO_PROJECT = "no project: pass a path or a project"

#: What an agent reads on connecting: the open-items procedure of the plugin's `open-items`
#: skill, condensed, and what it has to ask a person to run.
INSTRUCTIONS = """\
Tools for the reproducible-science toolkit: check a manuscript's declared claims against the \
files they name, and fill the items a reader of another tool's files left open.

Pass absolute paths, or a `project` folder to a tool that takes no path. The server follows \
them: each call works in the project holding its path, and every result names it as `root`.

The rule: you propose, the checks decide. Every assertion you write is basis: inferred. An \
inferred assertion that matched is "matched, inferred: not verified", never verified, and \
fails the publication and strict policies until a person accepts it.

Filling open items:
1. next_open_item gives the first open item of an open-items.json; pass its id as `after` for \
the next. Each holds the claim, the printed value, the sentence and its line, and each \
candidate's file, address, labels and stored value.
2. need value: propose_binding one assertion fetching the stated value from its address, \
preferring one that names the value (a tree pointer, a table locator with where). Propose a \
unique candidate only after the sentence's words agree with its labels; where they do not \
settle it, leave the item open and say why.
3. need passage: add_artifact the paper where the draft lacks it, then propose_binding a quote \
of the passage as the source prints it. Where the project keeps a citations claims file, \
pin_quote with check=true first. A passage that does not resolve is not written.
4. A proposal that does not match is not fixed by changing reported: propose another address \
(it replaces your failed one) or leave the item open. An open item is a result.
5. Report each item left open with its reason, and that every filled item is inferred.

A paper's references, without its sources: citations_audit checks each entry of a .bib \
against the registries, ten at a time.

Reviews: list the matched items to the user first, and call mark_reviewed only for the items \
the user has explicitly approved in this conversation.

Never: edit open-items.json; delete a claim to close an item; write reviewed yourself; change \
reported; edit a pinned quotation; change a digest or write repro.yaml; run anything in a \
capsule or bundle; call anything verified that a tool did not report verified.

Not offered here, so ask the human to run them: prereg freeze, prereg register, results seal, \
results run, repro reproduce and anything else that runs a declared command, anything that \
publishes or registers, and any network fetch but citations_audit's registry lookups.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
LOOKS_UP = ToolAnnotations(read_only_hint=True, open_world_hint=True)

#: How many bibliography entries one `citations_audit` call checks. `start` pages past it.
MAX_AUDIT_ENTRIES = 10

#: Each `citations audit` verdict, as the four answers an agent reports, and why the last.
AUDITED = {
    "ok": ("agrees", ""),
    "mismatch": ("disagrees", ""),
    "not found": ("not_found", ""),
    "unresolved": (
        "could_not_check",
        "the registry or every search service did not answer: throttled, offline, or not "
        "registered there",
    ),
    "no identifier": ("could_not_check", "no DOI or PMID, and the title search is off"),
    "found": ("could_not_check", "the title search found an id with no DOI to compare against"),
}

#: The field a `citations audit` disagreement names, at the start of its message.
FIELD = re.compile(r"^(title|year|volume|pages|author list|author \d+)")
WRITES = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)

Work = Callable[[pathlib.Path], tuple[dict[str, Any], str]]


def _result(data: dict[str, Any], summary: str, error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=summary)], structured_content=data, is_error=error
    )


def _inferred_said(account: dict[str, Any]) -> dict[str, Any]:
    """`why`'s account with each inferred match named `matched`, never `verified`."""
    for assertion in account.get("assertions", ()):
        if assertion.get("basis") == Basis.INFERRED.value and assertion["outcome"] == "verified":
            assertion["outcome"] = "matched"
            assertion["said"] = "matched, inferred: not verified"
    if "verified" in account.get("inferred", {}):
        account["inferred"]["matched"] = account["inferred"].pop("verified")
    return account


def _delegated(root: pathlib.Path, tool: str, argv: Sequence[str]) -> tuple[dict[str, Any], str]:
    """One of the other tools' commands run in this process, with what it found written as
    JSON to a scratch file. `delegate.run` takes the code of a `SystemExit`."""
    output = io.StringIO()
    with (
        tempfile.TemporaryDirectory() as scratch,
        contextlib.chdir(root),
        contextlib.redirect_stdout(output),
        contextlib.redirect_stderr(output),
    ):
        found = pathlib.Path(scratch) / "found.json"
        code = delegate_run(BY_NAME[tool], [*argv, "--json", str(found)])
        written = json.loads(found.read_text()) if found.exists() else None
    last = next((line for line in reversed(output.getvalue().splitlines()) if line.strip()), "")
    command = f"{tool} {argv[0]}"
    data = {"command": command, "exit": code, "found": written, "output": output.getvalue()}
    return data, f"{command}: exit {code}; {last.strip()}"


def _audited(path: pathlib.Path, strict: bool, search: bool, start: int) -> tuple[dict, str]:
    """`citations audit --bib` over one page of entries: the registry's verdict per entry, and
    apart from it what a title search found. Reads registries; writes only the cache
    `citations audit` keeps beside the bibliography."""
    if not path.is_file():
        raise Refused("not_a_file", f"no bibliography at {path}")
    if start < 0:
        raise Refused("start", "start counts entries from 0")
    entries = citations_audit_module.entries_from_bib(path)
    page = entries[start : start + MAX_AUDIT_ENTRIES]
    with contextlib.redirect_stdout(io.StringIO()):
        report = citations_audit_module.audit(
            page, path.parent / ".audit-cache", str(path), search=search
        )
    rows: list[dict[str, Any]] = []
    for key, verdict in report.entries.items():
        result, why_not = AUDITED.get(verdict.status, ("could_not_check", verdict.status))
        fields = [m.group(1) for p in verdict.problems if (m := FIELD.match(p))]
        rows.append(
            {
                "key": key,
                "registry": {
                    "result": result,
                    "why_not": why_not,
                    "checked_against": verdict.checked_against,
                    "fields": fields,
                    "problems": verdict.problems,
                    "doi": verdict.doi,
                    "pmid": verdict.pmid,
                },
                "search": {
                    "found_kind": verdict.found_kind,
                    "found_id": verdict.found_id,
                    "found_by": verdict.found_by,
                    "searched": verdict.searched,
                },
            }
        )
    counts = {
        word: sum(r["registry"]["result"] == word for r in rows)
        for word in ("agrees", "disagrees", "not_found", "could_not_check")
    }
    failed = counts["disagrees"] + (counts["could_not_check"] if strict else 0)
    following = start + len(page)
    data = {
        "entries": rows,
        "counts": counts,
        "strict": strict,
        "passed": not failed and bool(rows),
        "total": len(entries),
        "next_start": following if following < len(entries) else None,
    }
    said = ", ".join(f"{n} {word.replace('_', ' ')}" for word, n in counts.items())
    return data, f"entries {start + 1}-{following} of {len(entries)}: {said}"


def _client(ctx: Context) -> str:
    params = ctx.session.client_params
    info = getattr(params, "client_info", None)
    return getattr(info, "name", None) or "an MCP client"


def build(root: pathlib.Path | None = None) -> MCPServer:
    """The server, with every tool registered. `root` is `--root`: the project of a call with
    no path and no `project`, until a call names another."""
    fallback = root.resolve() if root is not None else None
    server = MCPServer(NAME, instructions=INSTRUCTIONS, version=__version__)
    last: list[pathlib.Path] = []

    def base() -> pathlib.Path:
        return last[-1] if last else fallback or pathlib.Path.cwd()

    def absolute(path: str) -> pathlib.Path:
        given = pathlib.Path(path).expanduser()
        return given if given.is_absolute() else base() / given

    def here(path: str | None, project: str | None) -> pathlib.Path:
        if path is not None or project is not None:
            return project_of(absolute(path if path is not None else project or ""))
        if last or fallback:
            return base()
        try:
            return project_of(pathlib.Path.cwd())
        except Refused as e:
            raise Refused("no_project", NO_PROJECT) from e

    def answer(work: Work, path: str | None = None, project: str | None = None) -> CallToolResult:
        try:
            found = here(path, project)
        except Refused as e:
            return _result({"refused": e.rule, "detail": e.detail}, str(e), True)
        last.append(found)
        try:
            data, summary = work(found)
        except Refused as e:
            data, summary, error = {"refused": e.rule, "detail": e.detail}, str(e), True
        except ReproError as e:
            data, summary, error = {"error": type(e).__name__, "detail": str(e)}, str(e), True
        else:
            error = False
        return _result({**data, "root": found.as_posix()}, summary, error)

    def manifest_at(at: pathlib.Path, manifest: str | None):
        return load_inside(at, absolute(manifest) if manifest else at / DEFAULT_NAME)

    def policy_of(policy: str):
        if policy not in PROFILES:
            raise Refused("policy", f"policy is one of {', '.join(sorted(PROFILES))}")
        return PROFILES[policy]

    @server.tool(annotations=READ_ONLY)
    async def verify(
        manifest: str | None = None, project: str | None = None, policy: str = "publication"
    ) -> CallToolResult:
        """Check every assertion in a manifest (default: repro.yaml of the project) under a
        policy: exploratory, publication or strict. Writes no record of checks."""

        def work(at: pathlib.Path):
            report = run_verify(manifest_at(at, manifest))
            assessment = policy_of(policy).assess(report)
            counts = ", ".join(f"{n} {k}" for k, n in sorted(report.counts.items()))
            return {
                "counts": dict(report.counts),
                "report": report.model_dump(mode="json"),
                "assessment": assessment.model_dump(mode="json"),
            }, f"{counts}; policy {policy}: {'passed' if assessment.passed else 'FAILED'}"

        return answer(work, manifest, project)

    @server.tool(annotations=READ_ONLY)
    async def why(
        claim: str, manifest: str | None = None, project: str | None = None
    ) -> CallToolResult:
        """What the record establishes for one claim, and what it does not."""

        def work(at: pathlib.Path):
            account = _inferred_said(
                run_why(manifest_at(at, manifest), claim).model_dump(mode="json")
            )
            said = ", ".join(
                f"{a['kind']} {a.get('said') or a['outcome']}" for a in account["assertions"]
            )
            return account, f"{claim}: {said or 'no assertions'}"

        return answer(work, manifest, project)

    @server.tool(annotations=READ_ONLY)
    async def stale(
        manifest: str | None = None, project: str | None = None, policy: str = "publication"
    ) -> CallToolResult:
        """Which claims read a file changed since its recorded re-run. Executes nothing."""

        def work(at: pathlib.Path):
            loaded = manifest_at(at, manifest)
            if not loaded.regenerations:
                return {"regenerations": 0}, "no command is declared under regenerations"
            report = run_stale(loaded)
            assessment = policy_of(policy).assess_staleness(report)
            return {
                "staleness": report.model_dump(mode="json"),
                "assessment": assessment.model_dump(mode="json"),
            }, ", ".join(f"{c.id} {c.state.value}" for c in report.claims)

        return answer(work, manifest, project)

    @server.tool(annotations=READ_ONLY)
    async def numbers(
        manifest: str | None = None, project: str | None = None, texts: list[str] | None = None
    ) -> CallToolResult:
        """Every number the manuscript prints, and whether a claim binds it."""

        def work(at: pathlib.Path):
            report = run_numbers(manifest_at(at, manifest), only=tuple(texts or ()))
            counts = {k.value: n for k, n in report.counts.items()}
            data = {**report.model_dump(mode="json"), "counts": counts}
            return data, f"{len(report.numbers)} numbers: {counts}"

        return answer(work, manifest, project)

    @server.tool(annotations=READ_ONLY)
    async def origins(manifest: str | None = None, project: str | None = None) -> CallToolResult:
        """Compare each artifact copied from another repository with its origin, from a local
        clone only: this server fetches nothing."""

        def work(at: pathlib.Path):
            report = run_origins(manifest_at(at, manifest), {}, None)
            return {"origins": report.model_dump(mode="json")}, f"{len(report.origins)} origins"

        return answer(work, manifest, project)

    @server.tool(annotations=READ_ONLY)
    async def prereg_check(project: str | None = None) -> CallToolResult:
        """`prereg check`: has any frozen plan in the project changed since its freeze?"""
        return answer(lambda at: _delegated(at, "prereg", ["check"]), None, project)

    @server.tool(annotations=READ_ONLY)
    async def results_verify(files: bool = False, project: str | None = None) -> CallToolResult:
        """`results verify`, with `files` checking every recorded file's hash."""
        argv = ["verify", "--files"] if files else ["verify"]
        return answer(lambda at: _delegated(at, "results", argv), None, project)

    @server.tool(annotations=READ_ONLY)
    async def citations_verify(
        claims: str | None = None, project: str | None = None
    ) -> CallToolResult:
        """`citations verify --claims` over a claims folder (default: claims/ of the project)."""

        def work(at: pathlib.Path):
            folder = inside(at, absolute(claims)) if claims else at / "claims"
            return _delegated(at, "citations", ["verify", f"--claims={folder}"])

        return answer(work, claims, project)

    @server.tool(annotations=LOOKS_UP)
    async def citations_audit(
        bib: str, strict: bool = False, no_search: bool = False, start: int = 0
    ) -> CallToolResult:
        """`citations audit --bib`: does each entry's title, authors, year, volume and pages
        agree with the registry record its DOI or PMID resolves to, or that a title search
        finds? Per entry: agrees, disagrees (with the fields named), not found, or could not
        check, which is what a throttled or silent service gives. Ten entries a call; pass
        `next_start` as `start` for more. The only tool that reaches the network, and only to
        read registries; it writes no .bib, record or claims file."""
        return answer(
            lambda at: _audited(inside(at, absolute(bib)), strict, not no_search, start), bib
        )

    @server.tool(annotations=READ_ONLY)
    async def next_open_item(open_items: str, after: str | None = None) -> CallToolResult:
        """The first open item after `after` (from the start where omitted), as one packet,
        with the counts of items in total and remaining."""

        def work(at: pathlib.Path):
            found = packet(at, str(absolute(open_items)), None, after)
            return found.model_dump(mode="json"), (
                f"{found.item}: {found.remaining} of {found.total} open; next {found.next_item}"
            )

        return answer(work, open_items)

    @server.tool(annotations=READ_ONLY)
    async def get_open_item(open_items: str, item: str) -> CallToolResult:
        """One item of the open-items file by its id, as `next_open_item` gives it."""

        def work(at: pathlib.Path):
            found = packet(at, str(absolute(open_items)), item, None)
            return found.model_dump(mode="json"), f"{found.item}: filled {found.filled}"

        return answer(work, open_items)

    @server.tool(annotations=WRITES)
    async def propose_binding(
        open_items: str,
        claim: str,
        assertion: dict[str, Any],
        item: str | None = None,
        basis: str | None = None,
    ) -> CallToolResult:
        """Fill one open item: insert `assertion`, basis: inferred, into the claim in the
        draft the open-items file names, as one line, and check it. It replaces your last
        proposal for the item where that did not match, and never a matched, declared or
        reviewed one. Refused: another basis, `reviewed`, a claim not in the file or the
        draft, a kind that fills no open item, a missing or changed `reported`, an undeclared
        artifact, an oversized field. From the sixth attempt the result carries a warning."""

        def work(at: pathlib.Path):
            done = propose(at, str(absolute(open_items)), claim, assertion, item, basis)
            return done.model_dump(mode="json"), f"{done.item}: {done.said} {done.warning}"

        return answer(work, open_items)

    @server.tool(annotations=WRITES)
    async def add_artifact(
        open_items: str, path: str, media_type: str | None = None, id: str | None = None
    ) -> CallToolResult:
        """Declare a file in the draft the open-items file names, pinned by its sha256 and
        basis: inferred, so whatever reads it counts as inferred until a person accepts it.
        Refused: a path outside the project, a directory, a Git LFS pointer, a file over the
        size cap, a file or id already declared."""

        def work(at: pathlib.Path):
            done = add_artifact_to(
                at, str(absolute(open_items)), str(absolute(path)), media_type, id
            )
            return done.model_dump(mode="json"), f"added {done.artifact['id']}, inferred"

        return answer(work, open_items)

    @server.tool(annotations=WRITES)
    async def mark_reviewed(
        ctx: Context,
        open_items: str,
        items: list[str] | None = None,
        artifacts: list[str] | None = None,
        note: str = "",
    ) -> CallToolResult:
        """Record that the user approved, in this conversation, the inferred assertion filling
        each item and each inferred artifact: reviewed {who (git user), when, how, digest}.
        Call it only after listing the items and the user's explicit approval. A review lapses
        when what it accepted changes."""
        how = f"approved in chat via {_client(ctx)}" + (f": {note}" if note else "")

        def work(at: pathlib.Path):
            done = record_review(
                at, str(absolute(open_items)), list(items or ()), list(artifacts or ()), how
            )
            named = [*done.assertions, *done.artifacts]
            return done.model_dump(mode="json"), f"reviewed {', '.join(named)}: {how}"

        return answer(work, open_items)

    @server.tool(annotations=WRITES)
    async def pin_quote(
        claims_file: str,
        id: str,
        quote: str,
        page: int | None = None,
        section: str | None = None,
        occurrence: int | None = None,
        check: bool = False,
    ) -> CallToolResult:
        """`citations pin`: add a quotation to a claims file where it resolves in the pinned
        source, and write nothing where it does not. With `check`, write nothing. An id the
        file already holds is refused, so a pinned quotation is never replaced."""

        def work(at: pathlib.Path):
            for field, value, cap in (
                ("id", id, MAX_NAME),
                ("quote", quote, MAX_TEXT),
                ("section", section, MAX_NAME),
            ):
                capped(field, value, cap)
            path = inside(at, absolute(claims_file))
            # Each value is attached to its flag with `=`, so one beginning with `-` is read
            # as the value and never as another option.
            argv = [str(path), f"--id={id}", f"--quote={quote}"]
            for flag, value in (
                ("--page", page),
                ("--section", section),
                ("--occurrence", occurrence),
            ):
                if value is not None:
                    argv.append(f"{flag}={value}")
            argv += ["--check"] if check else []
            output = io.StringIO()
            with (
                contextlib.chdir(at),
                contextlib.redirect_stdout(output),
                contextlib.redirect_stderr(output),
            ):
                try:
                    code = citations_pin.main(argv)
                except citations_pin.PinRefused as e:
                    raise Refused("pin_refused", str(e)) from e
                except SystemExit as e:
                    code = e.code if isinstance(e.code, int) else 2
            said = output.getvalue()
            if code != 0:
                raise Refused("pin_refused", said.strip() or f"citations pin exited {code}")
            data = {"claims_file": path.relative_to(at).as_posix(), "id": id}
            return {**data, "written": not check, "output": said}, said.strip()

        return answer(work, claims_file)

    return server


def serve(root: pathlib.Path | None) -> None:
    """Run the server over standard input and output until the client leaves."""
    build(root).run("stdio")


__all__ = ["INSTRUCTIONS", "NAME", "NO_PROJECT", "PROJECT_MARKERS", "build", "serve"]
