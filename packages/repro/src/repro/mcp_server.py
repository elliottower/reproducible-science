"""`repro mcp`: the toolkit's checks as tools of an MCP server, over standard input and output.

Any agent that speaks MCP gets the same tools and the same rules, and the rules are the
server's to enforce rather than an instruction file's to ask for. Every tool calls the
toolkit in this process: the claims side through its functions, and `prereg`, `results` and
`citations` through the entry `repro check` uses, each told to write what it found as JSON.

Read-only: verify, why, stale, numbers, open_items, next_open_item, get_open_item, origins,
prereg_check, results_verify, citations_verify. They write nothing into the project: `verify`
here does not append to the record of checks, as `repro verify` does.

Two write: `propose_binding` appends one `basis: inferred` assertion to a draft manifest, and
`pin_quote` runs `citations pin`, which writes a quotation only where it resolves.

Nothing here freezes or registers a plan, seals or records a run, runs a declared command,
publishes anything or reaches the network. The instructions say to ask the human for those.

Every path an agent gives is resolved inside the project root, `--root` or the directory the
server starts in, and refused where it leaves it. The root is, in order: the folder
`set_project` named; the client's first `file://` MCP root; `--root`; and the nearest directory
at or above the working directory holding a project marker. Tool bodies run on the event loop, one at a
time: the tools reached through their command line read the working directory and print, so
each runs with the directory changed to the root and its output captured.
"""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from typing import Annotated, Any

from citations import pin as citations_pin
from claims.exceptions import ReproError
from claims.manifest import DEFAULT_NAME
from claims.models import Basis
from claims.numbers import numbers as run_numbers
from claims.open_items import tally
from claims.origins import origins as run_origins
from claims.policy import PROFILES
from claims.stale import stale as run_stale
from claims.verify import verify as run_verify
from claims.why import why as run_why
from mcp.server.mcpserver import Context, ListRoots, MCPServer, Resolve
from mcp.types import CallToolResult, ListRootsResult, TextContent, ToolAnnotations

from repro import __version__
from repro.delegate import BY_NAME
from repro.delegate import run as delegate_run
from repro.proposals import (
    MAX_NAME,
    MAX_TEXT,
    Refused,
    capped,
    inside,
    load_inside,
    packet,
    propose,
)

NAME = "reproducible-science"

#: What an agent reads on connecting: the open-items procedure of the plugin's `open-items`
#: skill, condensed, and what it has to ask a person to run.
INSTRUCTIONS = """\
Tools for the reproducible-science toolkit: check a manuscript's declared claims against the \
files they name, and fill the items a reader of another tool's files left open.

Every tool works inside one project folder, and every result names it as `root`. When unsure \
which project this is, call set_project with the project folder first. A tool that answers \
"no project: call set_project" found none.

The rule: you propose, the checks decide. Every assertion you write is basis: inferred, and \
propose_binding writes no other. An inferred assertion that matched is a proposal that held, \
never a verified claim: report it as "matched, inferred: not verified". It fails the \
publication and strict policies until an author accepts it, and accepting it is the author's.

Filling open items:
1. Count first: open_items on the open-items.json. Note the counts.
2. Take items one at a time: next_open_item gives the first open one, then pass its id as \
`after` for the next. get_open_item reads one by id. Each packet holds the claim, the value \
printed or stated, the sentence and its line, and each candidate's file, address, labels and \
stored value.
3. need value: propose one assertion that fetches the stated value from its address. Prefer an \
address that names the value (a tree pointer, a table locator with where) over a row position. \
A unique candidate is a lead, never an answer: propose it only after the sentence's or the \
question's words agree with the candidate's labels. Where they do not settle it (a column \
named score for a question about AUROC), leave the item open and say why.
4. need passage: the passage that makes the claim, quoted as the source prints it, never \
shortened. Where the project keeps a citations claims file, pin_quote with check=true first, \
then pin it. A passage that does not resolve is not written.
5. Leave an item open rather than guess. An open item is a result.
6. A proposal that does not match is not fixed by changing reported. Propose another address \
or leave the item open.
7. Count again with open_items, and report the counts as it gives them, each item left open \
with its reason, and that every filled item is inferred.

Never: edit open-items.json; delete a claim to close an item; write an assertion without \
basis: inferred, remove that line, or write reviewed; change reported, which is the value as \
the source states it; edit a pinned quotation (a wrong pin is replaced by a new one); change an \
artifact's digest or write repro.yaml; run anything in a capsule or bundle; call anything \
verified that a tool did not report verified, or any assertion you wrote verified at all.

Not offered here, so ask the human to run them: prereg freeze, prereg register, results seal, \
results run, repro reproduce and anything else that runs a declared command, anything that \
publishes or registers, and anything that fetches over the network (citations pin --url, \
claims origins --fetch, claims from-codecheck --fetch).
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITES = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)


def _result(data: dict[str, Any], summary: str, error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=summary)], structured_content=data, is_error=error
    )


def _inferred_said(account: dict[str, Any]) -> dict[str, Any]:
    """`why`'s account with each inferred assertion's match named `matched`, as `claims why`
    prints it, so no inferred assertion reads `verified` in what an agent is handed."""
    for assertion in account.get("assertions", ()):
        if (
            assertion.get("basis") == Basis.INFERRED.value
            and assertion.get("outcome") == "verified"
        ):
            assertion["outcome"] = "matched"
            assertion["said"] = "matched, inferred: not verified"
    if "verified" in account.get("inferred", {}):
        account["inferred"]["matched"] = account["inferred"].pop("verified")
    return account


def _delegated(root: pathlib.Path, tool: str, argv: Sequence[str]) -> dict[str, Any]:
    """One of the other tools' commands run in this process, as `repro check` runs it, with
    what it found written as JSON to a scratch file. `delegate.run` takes the code of a
    `SystemExit`, so no argument can end the server."""
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
    return {"exit": code, "found": written, "output": output.getvalue()}


def _file_root(uri: str) -> pathlib.Path | None:
    """The directory a `file://` root names, or None for any other root."""
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme != "file":
        return None
    path = pathlib.Path(urllib.request.url2pathname(parsed.path)).resolve()
    return path if path.is_dir() else None


def _asked_roots(ctx: Context) -> ListRoots | None:
    """Ask a client that offers roots for them, and nothing of one that does not. The SDK sends
    the request as the negotiated protocol has it: mid-call before 2026-07-28, as an input the
    client answers on retry after."""
    capabilities = ctx.client_capabilities
    return ListRoots() if capabilities is not None and capabilities.roots is not None else None


#: A tool parameter the SDK fills with the client's roots, and never one the agent supplies.
Roots = Annotated[ListRootsResult | None, Resolve(_asked_roots)]


#: What marks a directory as a project: a manifest or a reader's draft, a results ledger, a
#: record of frozen plans, or a folder of pinned quotations.
PROJECT_MARKERS = ("repro.yaml", "repro.draft.yaml", ".results", ".prereg", "claims")

#: What every tool answers where no project root could be settled.
NO_PROJECT = "no project: call set_project"


def is_project(directory: pathlib.Path) -> bool:
    return directory.is_dir() and any((directory / name).exists() for name in PROJECT_MARKERS)


def discover(start: pathlib.Path) -> pathlib.Path | None:
    """The nearest directory at or above `start` holding a project marker, as git finds
    `.git`; None where no directory up to the filesystem root does."""
    here = start.resolve()
    return next((d for d in (here, *here.parents) if is_project(d)), None)


def _client_root(
    listed: ListRootsResult | None, default: pathlib.Path | None
) -> pathlib.Path | None:
    """The client's first `file://` root that is a directory, which is how an agent that
    starts the server without `--root` names the project; otherwise `default`."""
    found = (_file_root(str(root.uri)) for root in (listed.roots if listed else ()))
    return next((path for path in found if path is not None), default)


Work = Callable[[pathlib.Path], tuple[dict[str, Any], str]]


def build(root: pathlib.Path | None = None) -> MCPServer:
    """The server, with every tool registered. The root of each call is, in order: the folder
    `set_project` named in this session; the client's first `file://` root, where it offers
    roots; `root` (`--root`); and the nearest directory at or above the working directory that
    holds a project marker. Where none is settled every tool answers `NO_PROJECT`."""
    default = root.resolve() if root is not None else discover(pathlib.Path.cwd())
    server = MCPServer(NAME, instructions=INSTRUCTIONS, version=__version__)
    chosen: list[pathlib.Path] = []

    def answer(roots: ListRootsResult | None, work: Work) -> CallToolResult:
        here = chosen[-1] if chosen else _client_root(roots, default)
        if here is None:
            return _result({"refused": "no_project", "detail": NO_PROJECT}, NO_PROJECT, True)
        # Run on the event loop, not a worker thread: the delegated tools change the working
        # directory and capture standard output, which two calls at once would cross.
        try:
            data, summary = work(here)
        except Refused as e:
            data, summary, error = {"refused": e.rule, "detail": e.detail}, str(e), True
        except ReproError as e:
            data, summary, error = {"error": type(e).__name__, "detail": str(e)}, str(e), True
        else:
            error = False
        return _result({**data, "root": here.as_posix()}, summary, error)

    @server.tool(annotations=WRITES)
    async def set_project(path: str, roots: Roots = None) -> CallToolResult:
        """Name the project folder for the rest of this session: an absolute path, or one
        relative to the current root. Accepted only where the folder holds repro.yaml,
        repro.draft.yaml, .results/, .prereg/ or claims/. Answers the root settled on, and
        every later path is confined to it."""
        current = chosen[-1] if chosen else _client_root(roots, default)
        given = pathlib.Path(path).expanduser()
        if not given.is_absolute():
            given = (current or pathlib.Path.cwd()) / given
        folder = given.resolve()
        if not folder.is_dir():
            reason = f"{path} resolves to {folder}, which is not a directory"
        elif not is_project(folder):
            reason = f"{folder} holds none of {', '.join(PROJECT_MARKERS)}"
        else:
            chosen.append(folder)
            return _result({"root": folder.as_posix()}, f"project root: {folder}")
        detail = f"not a project: {reason}"
        return _result({"refused": "not_a_project", "detail": detail}, detail, error=True)

    @server.tool(annotations=READ_ONLY)
    async def verify(
        manifest: str = DEFAULT_NAME, policy: str = "publication", roots: Roots = None
    ) -> CallToolResult:
        """Check every evidence assertion in the manifest, and assess it under a policy
        (exploratory, publication or strict). Writes no record of checks."""

        def work(here: pathlib.Path):
            if policy not in PROFILES:
                raise Refused("policy", f"policy is one of {', '.join(sorted(PROFILES))}")
            report = run_verify(load_inside(here, manifest))
            assessment = PROFILES[policy].assess(report)
            counts = ", ".join(f"{n} {k}" for k, n in sorted(report.counts.items()))
            said = f"{counts}; policy {policy}: {'passed' if assessment.passed else 'FAILED'}"
            # `counts` is a property of the report, so its dump leaves it out. It is the line
            # an agent reads first, and an inferred match is counted there as inferred_matched.
            return {
                "counts": dict(report.counts),
                "report": report.model_dump(mode="json"),
                "assessment": assessment.model_dump(mode="json"),
            }, said

        return answer(roots, work)

    @server.tool(annotations=READ_ONLY)
    async def why(claim: str, manifest: str = DEFAULT_NAME, roots: Roots = None) -> CallToolResult:
        """What the record establishes for one claim, and what it does not. An inferred
        assertion that matched reads `matched`, never `verified`."""

        def work(here: pathlib.Path):
            found = run_why(load_inside(here, manifest), claim)
            account = _inferred_said(found.model_dump(mode="json"))
            said = ", ".join(
                f"{a.get('kind')} {a.get('said') or a.get('outcome')}"
                for a in account["assertions"]
            )
            return account, f"{claim}: {said or 'no assertions'}"

        return answer(roots, work)

    @server.tool(annotations=READ_ONLY)
    async def stale(
        manifest: str = DEFAULT_NAME, policy: str = "publication", roots: Roots = None
    ) -> CallToolResult:
        """Which claims read a file changed since its recorded re-run. Executes nothing."""

        def work(here: pathlib.Path):
            if policy not in PROFILES:
                raise Refused("policy", f"policy is one of {', '.join(sorted(PROFILES))}")
            loaded = load_inside(here, manifest)
            if not loaded.regenerations:
                return {"regenerations": 0}, "no command is declared under regenerations"
            report = run_stale(loaded)
            assessment = PROFILES[policy].assess_staleness(report)
            states = ", ".join(f"{c.id} {c.state.value}" for c in report.claims)
            return {
                "staleness": report.model_dump(mode="json"),
                "assessment": assessment.model_dump(mode="json"),
            }, f"{states}; policy {policy}: {'passed' if assessment.passed else 'FAILED'}"

        return answer(roots, work)

    @server.tool(annotations=READ_ONLY)
    async def numbers(
        manifest: str = DEFAULT_NAME, texts: list[str] | None = None, roots: Roots = None
    ) -> CallToolResult:
        """Every number the manuscript prints, and whether a claim binds it."""

        def work(here: pathlib.Path):
            report = run_numbers(load_inside(here, manifest), only=tuple(texts or ()))
            counts = ", ".join(f"{n} {k.value}" for k, n in report.counts.items())
            data = report.model_dump(mode="json")
            data["counts"] = {k.value: n for k, n in report.counts.items()}
            return data, f"{len(report.numbers)} numbers: {counts}"

        return answer(roots, work)

    @server.tool(annotations=READ_ONLY)
    async def origins(manifest: str = DEFAULT_NAME, roots: Roots = None) -> CallToolResult:
        """Compare each artifact copied from another repository with its origin, from a local
        clone only: this server fetches nothing."""

        def work(here: pathlib.Path):
            report = run_origins(load_inside(here, manifest), {}, None)
            counts = ", ".join(f"{n} {k}" for k, n in report.counts.items())
            return {"origins": report.model_dump(mode="json")}, (
                f"{len(report.origins)} origins: {counts or 'none declared'}"
            )

        return answer(roots, work)

    @server.tool(annotations=READ_ONLY)
    async def open_items(open_items: str, roots: Roots = None) -> CallToolResult:
        """Count what a reader left open in a draft manifest and what is filled, with one line
        per item. An inferred match is counted as matched, never verified."""

        def work(here: pathlib.Path):
            found = tally(inside(here, open_items))
            data = found.model_dump(mode="json", exclude={"per_claim"})
            data["list"] = [
                {
                    "item": fill.id,
                    "claim": entry.claim,
                    "need": fill.need.value,
                    "filled": fill.filled,
                    "outcomes": list(fill.outcomes),
                    "unique": fill.unique,
                }
                for entry in found.per_claim
                for fill in entry.items
            ]
            claims = ", ".join(f"{n} {state}" for state, n in data["claims"].items())
            items = data["items"]
            return data, (
                f"{found.total} claims: {claims}; {items['total']} items, {items['open']} open, "
                f"{items['filled_by_inferred']} filled by an inferred assertion"
            )

        return answer(roots, work)

    @server.tool(annotations=READ_ONLY)
    async def next_open_item(
        open_items: str, after: str | None = None, roots: Roots = None
    ) -> CallToolResult:
        """The first open item after `after` (from the start where omitted), as one packet:
        the claim, the printed value, the sentence and its line, and each candidate's file,
        address, labels and stored value, with the counts of items in total and remaining."""

        def work(here: pathlib.Path):
            found = packet(here, open_items, None, after)
            return found.model_dump(mode="json"), (
                f"{found.item} ({found.need.value}), {found.remaining} of {found.total} open; "
                f"next {found.next_item or 'none'}"
            )

        return answer(roots, work)

    @server.tool(annotations=READ_ONLY)
    async def get_open_item(open_items: str, item: str, roots: Roots = None) -> CallToolResult:
        """One item of the open-items file by its id, as `next_open_item` gives it."""

        def work(here: pathlib.Path):
            found = packet(here, open_items, item, None)
            state = "filled" if found.filled else "open"
            return found.model_dump(mode="json"), (
                f"{found.item} ({found.need.value}, {state}), {found.remaining} of "
                f"{found.total} open"
            )

        return answer(roots, work)

    @server.tool(annotations=READ_ONLY)
    async def prereg_check(roots: Roots = None) -> CallToolResult:
        """Has any frozen plan in the project changed since its freeze? `prereg check`."""
        return answer(
            roots, lambda here: _said("prereg check", _delegated(here, "prereg", ["check"]))
        )

    @server.tool(annotations=READ_ONLY)
    async def results_verify(files: bool = False, roots: Roots = None) -> CallToolResult:
        """Check the results ledger's hash chain, and with `files` every recorded file's
        hash. `results verify`."""
        argv = ["verify", "--files"] if files else ["verify"]
        return answer(
            roots, lambda here: _said("results verify", _delegated(here, "results", argv))
        )

    @server.tool(annotations=READ_ONLY)
    async def citations_verify(claims: str = "claims", roots: Roots = None) -> CallToolResult:
        """Do the quotations in a claims directory resolve in their pinned sources?
        `citations verify --claims`."""

        def work(here: pathlib.Path):
            argv = ["verify", f"--claims={inside(here, claims)}"]
            return _said("citations verify", _delegated(here, "citations", argv))

        return answer(roots, work)

    @server.tool(annotations=WRITES)
    async def propose_binding(
        open_items: str,
        claim: str,
        assertion: dict[str, Any],
        item: str | None = None,
        basis: str | None = None,
        roots: Roots = None,
    ) -> CallToolResult:
        """Fill one open item: append `assertion` to the claim in the draft manifest the
        open-items file names, marked basis: inferred, and check it. The assertion is inserted
        as one line and no other byte of the draft changes. Refused: any basis but inferred,
        `reviewed`, a claim the file lists no item for or the draft lacks, a draft outside the
        project root, a kind that fills no open item, a `reported` that is missing or other
        than the value the source states, and an oversized field. A match is "matched,
        inferred: not verified"."""

        def work(here: pathlib.Path):
            done = propose(here, open_items, claim, assertion, item, basis)
            return done.model_dump(mode="json"), f"{done.item}: {done.said}"

        return answer(roots, work)

    @server.tool(annotations=WRITES)
    async def pin_quote(
        claims_file: str,
        id: str,
        quote: str,
        page: int | None = None,
        section: str | None = None,
        occurrence: int | None = None,
        check: bool = False,
        roots: Roots = None,
    ) -> CallToolResult:
        """`citations pin`: add a quotation to a claims file where it resolves in the pinned
        source, and write nothing where it does not. With `check`, resolve and write nothing.
        Never replaces a pinned quotation: an id the file already holds is refused."""

        def work(here: pathlib.Path):
            for field, value, cap in (
                ("id", id, MAX_NAME),
                ("quote", quote, MAX_TEXT),
                ("section", section, MAX_NAME),
            ):
                capped(field, value, cap)
            path = inside(here, claims_file)
            # Every value is attached to its flag with `=`, so a value beginning with `-` is
            # read as the value and never as another option, `--url` among them.
            argv = [str(path), f"--id={id}", f"--quote={quote}"]
            for flag, value in (("--page", page), ("--section", section)):
                if value is not None:
                    argv.append(f"{flag}={value}")
            if occurrence is not None:
                argv.append(f"--occurrence={occurrence}")
            if check:
                argv.append("--check")
            output = io.StringIO()
            with (
                contextlib.chdir(here),
                contextlib.redirect_stdout(output),
                contextlib.redirect_stderr(output),
            ):
                try:
                    code = citations_pin.main(argv)
                except citations_pin.PinRefused as e:
                    raise Refused("pin_refused", str(e)) from e
                except SystemExit as e:
                    # argparse ends the process on a usage error; here that is a refusal.
                    code = e.code if isinstance(e.code, int) else 2
            said = output.getvalue()
            if code != 0:
                raise Refused("pin_refused", said.strip() or f"citations pin exited {code}")
            data = {"claims_file": path.relative_to(here).as_posix(), "id": id}
            return {**data, "written": not check, "output": said}, said.strip()

        return answer(roots, work)

    return server


def _said(command: str, ran: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """A delegated command's findings, with its exit code as the command documents it."""
    last = next((line for line in reversed(ran["output"].splitlines()) if line.strip()), "")
    return {"command": command, **ran}, f"{command}: exit {ran['exit']}; {last.strip()}"


def serve(root: pathlib.Path | None) -> None:
    """Run the server over standard input and output until the client leaves. `root` is
    `--root`, or None to find the project above the working directory."""
    build(root).run("stdio")
