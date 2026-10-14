"""`repro badges`: one README badge per check, each reading a count from a run on this machine.

    repro badges            print one badge per check the project keeps a record for
    repro badges --readme   write them into README.md, between two marker lines
    repro badges --check    say whether README.md shows what the project gives now

Each count is what the matching `repro ci` command counts. `prereg`, `results` and `citations`
run the tool's own check through `repro.ci.tool` and read the JSON the tool writes with
`--json`. `claims` and `reproduced` read the run `repro.ci.claims` makes, which is
`repro.verify.verify` and `repro.stale.stale`. One count is reported by no check: how many of
the ledger's runs had inputs sealed before them. It is read from the ledger as the status band
of the Claude Code mod reads it.

A badge is a static shields.io image. Its address carries the label, the message and the
colour, so it draws for a private repository, and nothing here asks GitHub anything. A badge
written this way says what a run on the author's machine found, on the day it was written;
`repro ci init` writes the badges that say what GitHub's runner found. Reaches no network.
"""

from __future__ import annotations

import argparse
import collections
import os
import pathlib
import re
import urllib.parse

from provenance_core import atomic_write_bytes
from provenance_core.chain import ChainError, read_ledger
from pydantic import BaseModel, ConfigDict

from repro import audit, ci
from repro.exceptions import ReproError
from repro.manifest import find, load
from repro.models import Freshness, Outcome, StalenessReport, VerificationReport
from repro.policy import PUBLICATION
from repro.starter import project_root

#: A static badge: shields.io draws what the address says and reads nothing else.
STATIC = "https://img.shields.io/static/v1"

#: The colour of each kind of message, from the palette GitHub draws its own badges in, so a
#: badge reads beside the dark label `repro.ci.LABEL_COLOR` gives the icon.
GREEN = "2da44e"
"""Every item the check counts holds."""
RED = "cf222e"
"""The check failed: a value, a file or a plan is not what was recorded."""
AMBER = "bf8700"
"""Nothing failed and something was not established: a draft, an unchecked item, a re-run that
is not current."""
BLUE = "0969da"
"""Counted and not checked: quotations pinned to sources none of which is on this machine."""
GRAY = "6e7781"
"""No record of this kind is kept."""

NONE_DECLARED = "none declared"

#: The ledger `results` keeps, from the top of the project.
LEDGER = pathlib.Path(".results") / "ledger.jsonl"
#: A run named as a test is recorded before a plan is frozen, and nothing may be claimed from
#: it. The mod's band leaves it out of the count, and so does this.
TEST_RUN = re.compile(r"^(smoke|prefreeze|test|dryrun)[_-]")

#: The two lines that hold the badges in a README. Text between them is replaced; text
#: outside them is never touched.
START = "<!-- repro badges: start -->"
END = "<!-- repro badges: end -->"
README = "README.md"

_SHOWN = re.compile(r"\[!\[(?P<name>[^\]:]+): (?P<message>[^\]]*)\]\((?P<image>[^)\s]*)\)\]")


class BlockError(ReproError):
    """README.md opens a badge block it does not close."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        super().__init__(
            f"{path} holds `{START}` with no `{END}` after it; nothing was written. Close the "
            "block or remove the line."
        )


class Badge(BaseModel):
    """One check's badge: the count it reads and the colour that count is drawn in."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check: str
    """One of `repro.ci.CHECKS`."""
    message: str
    color: str

    @property
    def name(self) -> str:
        """The label: the name `repro ci init` gives the check's workflow."""
        return ci.NAMES[self.check]

    @property
    def image(self) -> str:
        query = urllib.parse.urlencode(
            {
                "label": self.name,
                "message": self.message,
                "color": self.color,
                "labelColor": ci.LABEL_COLOR,
                "logo": ci.logo(self.check),
            },
            quote_via=urllib.parse.quote,
        )
        return f"{STATIC}?{query}"

    @property
    def markdown(self) -> str:
        """The badge, linked to the section of the documentation that says what it counts."""
        return f"[![{self.name}: {self.message}]({self.image})]({ci.DOCS}#{ci.ANCHORS[self.check]})"


class LeftOut(BaseModel):
    """A check with no badge, and why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check: str
    why: str


class Found(BaseModel):
    """The badges for one project, in `repro.ci.CHECKS` order, and the checks left out."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    root: pathlib.Path
    badges: tuple[Badge, ...]
    left_out: tuple[LeftOut, ...] = ()

    @property
    def line(self) -> str:
        return " ".join(badge.markdown for badge in self.badges)


class Runs(BaseModel):
    """The ledger's runs, leaving out those named as tests, and how many had a seal before them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    runs: int = 0
    sealed: int = 0


# ------------------------------------------------------------------------------ each count


def runs(events: list[dict]) -> Runs:
    """A run counts as sealed where inputs were sealed before it was recorded, as the mod's band
    counts it in `packages/repro/mod/hooks/register.ts`."""
    seen, counted, sealed = False, 0, 0
    for event in events:
        if event.get("event") == "seal":
            seen = True
        elif event.get("event") == "run" and not TEST_RUN.match(str(event.get("run_id", ""))):
            counted += 1
            sealed += seen
    return Runs(runs=counted, sealed=sealed)


def prereg_badge(run: ci.ToolRun) -> Badge:
    """Plans frozen, from the JSON `prereg check --json` writes. A plan frozen by a commit line
    counts as the mod's band counts it; one superseded or withdrawn awaits no freeze."""
    plans = run.account.get("plans", [])
    pinned = [document["status"] for document in run.account.get("commit_pinned", [])]
    frozen = sum(plan["frozen"] for plan in plans) + sum(
        status in ("unchanged", "appended", "changed") for status in pinned
    )
    changed = sum(plan["frozen"] and plan["check"] == "changed" for plan in plans) + pinned.count(
        "changed"
    )
    drafts = sum(not plan["frozen"] for plan in plans) + sum(
        status in ("pending", "unknown commit") for status in pinned
    )
    if changed:
        return Badge(
            check="prereg",
            message=f"{changed} of {ci._count(frozen, 'frozen plan')} changed",
            color=RED,
        )
    if drafts:
        message = f"{frozen}/{frozen + drafts} plans frozen"
    else:
        message = f"{ci._count(frozen, 'plan')} frozen"
    return Badge(
        check="prereg", message=message, color=GREEN if run.outcome == audit.PASSED else AMBER
    )


def results_badge(run: ci.ToolRun, counted: Runs) -> Badge:
    """Runs sealed, of the ledger's runs. The colour reads what `results verify --files`
    reported and decides nothing of its own.

    Red where the chain did not verify: the account carries no event count, or the check
    failed with every recorded file in a state that passes (`ok`, `resealed`, `appended`,
    `ignored`, `retired`), which is a timestamp that contradicts the chain. Amber where the check failed
    over a recorded file in a state that fails, or not every run was sealed. Which file states
    fail is the tool's to say, and the badge follows its exit.
    """
    files = run.account.get("files", [])
    passing = ("ok", *ci.RESULTS_PASSING)
    if "events" not in run.account or (
        run.outcome == audit.FAILED and all(file["state"] in passing for file in files)
    ):
        color = RED
    elif run.outcome == audit.PASSED and counted.runs and counted.sealed == counted.runs:
        color = GREEN
    else:
        color = AMBER
    return Badge(
        check="results", message=f"{counted.sealed}/{counted.runs} runs sealed", color=color
    )


def claims_badge(report: VerificationReport) -> Badge:
    """Assertions verified, of every assertion `repro verify` decided. Red on a mismatch; amber
    where none mismatched and some were not found, not checked or could not be read."""
    outcomes = collections.Counter(decision.outcome for decision in report.decisions)
    total = len(report.decisions)
    verified = outcomes[Outcome.VERIFIED]
    if outcomes[Outcome.MISMATCH]:
        color = RED
    elif total and verified == total:
        color = GREEN
    else:
        color = AMBER
    return Badge(check="claims", message=f"{verified}/{total} verified", color=color)


def citations_badge(run: ci.ToolRun) -> Badge:
    """Quotations found, of every quotation pinned, where at least one source was read.

    Where none was, the quotations were counted and none was checked: `repro ci citations`
    calls that `could not check`, which is neither a pass nor a failure, and the badge says how
    many are pinned.
    """
    counts = run.account.get("counts", {})
    total = run.account.get("quotes", 0)
    found = counts.get("found", 0)
    if found + counts.get("not found", 0) == 0:
        return Badge(
            check="citations",
            message=f"{total} pinned",
            color=RED if run.outcome == audit.FAILED else BLUE,
        )
    if run.outcome == audit.FAILED:
        color = RED
    elif run.outcome == audit.PASSED and found == total:
        color = GREEN
    else:
        # A run `citations verify` exits 0 for, with quotations left unchecked, is amber.
        color = AMBER
    return Badge(check="citations", message=ci.verified(run), color=color)


def reruns_badge(report: StalenessReport) -> Badge:
    """Declared commands with a current re-run on record, of every declared command, as
    `repro stale` reports them under `regenerations`."""
    nodes = report.regenerations
    current = sum(node.state is Freshness.CURRENT for node in nodes)
    return Badge(
        check="reruns",
        message=f"{current}/{len(nodes)}",
        color=GREEN if current == len(nodes) else AMBER,
    )


# ---------------------------------------------------------------------------------- project


def _counted(ledger: pathlib.Path) -> Runs:
    """The ledger's runs, or none where a line of it is not an event."""
    try:
        return runs(read_ledger(ledger))
    except ChainError:
        return Runs()


def found(cwd: pathlib.Path, *, every: bool = False) -> Found:
    """The badges for the project holding `cwd`. With `every`, a check the project keeps no
    record for has a gray badge; without, it is left out and said to be."""
    root = project_root(cwd)
    made: dict[str, Badge] = {}
    why_not: dict[str, str] = {}

    for check in ci.TOOLS:
        run = ci.tool(check, root)
        if run.outcome == audit.NOTHING:
            why_not[check] = ci.NO_RECORD[check]
        elif check == "prereg":
            made[check] = prereg_badge(run)
        elif check == "citations":
            made[check] = citations_badge(run)
        else:
            made[check] = results_badge(run, _counted(root / LEDGER))

    path = find(cwd)
    if path is None:
        why_not["claims"] = why_not["reruns"] = ci.NO_RECORD["claims"]
    else:
        run = ci.claims(load(path), PUBLICATION)
        made["claims"] = claims_badge(run.verification)
        if run.staleness is None:
            why_not["reruns"] = ci.NO_RECORD["reruns"]
        else:
            made["reruns"] = reruns_badge(run.staleness)

    if every:
        made |= {check: Badge(check=check, message=NONE_DECLARED, color=GRAY) for check in why_not}
    return Found(
        root=root,
        badges=tuple(made[check] for check in ci.CHECKS if check in made),
        left_out=tuple(
            LeftOut(check=check, why=why_not[check])
            for check in ci.CHECKS
            if check in why_not and not every
        ),
    )


# ----------------------------------------------------------------------------------- README


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def written(readme: str, line: str, path: pathlib.Path) -> str:
    """The README with `line` in the badge block: in place of the block where there is one,
    and otherwise under the first heading, where `repro ci init --readme` puts its line.

    Only the block changes. A README that does not end on a line break gains one before a
    block is put after its last line, so the block's first line is a line of its own.
    """
    start = readme.find(START)
    if start >= 0:
        end = readme.find(END, start)
        if end < 0:
            raise BlockError(path)
        newline = "\r\n" if readme.startswith(START + "\r\n", start) else "\n"
        return readme[:start] + newline.join([START, line, END]) + readme[end + len(END) :]
    newline = _newline(readme)
    if readme and not readme.endswith(("\n", "\r")):
        readme += newline
    lines = ci.under_heading(
        readme.splitlines(keepends=True),
        [f"{text}{newline}" for text in (START, line, END)],
        blank=newline,
    )
    return "".join(lines)


def shown(readme: str, path: pathlib.Path) -> str | None:
    """The line the README's badge block holds, or None where it has no block."""
    start = readme.find(START)
    if start < 0:
        return None
    end = readme.find(END, start)
    if end < 0:
        raise BlockError(path)
    return readme[start + len(START) : end].strip()


def differences(before: str, now: Found) -> list[str]:
    """Each badge the README shows that the project does not give now, by check."""
    then = {match["name"]: (match["message"], match["image"]) for match in _SHOWN.finditer(before)}
    said = []
    for badge in now.badges:
        message, image = then.pop(badge.name, (None, None))
        if message is None:
            said.append(f"  {badge.name}: not in README.md; now `{badge.message}`")
        elif message != badge.message:
            said.append(f"  {badge.name}: README.md shows `{message}`; now `{badge.message}`")
        elif image != badge.image:
            said.append(f"  {badge.name}: `{badge.message}`, drawn in another colour than now")
    said += [
        f"  {name}: README.md shows `{message}`; no badge is given now"
        for name, (message, _) in then.items()
    ]
    return said or ["  the block's line is not the one the project gives now"]


# --------------------------------------------------------------------------------- commands


def _read(path: pathlib.Path) -> str:
    """The README as its bytes spell it. Read as text, a line ending `\\r\\n` would come back
    as `\\n`, and writing that back would change every line outside the block."""
    return path.read_bytes().decode("utf-8")


def _note(text: str) -> None:
    """A line on standard error, so standard output holds only the badges."""
    os.write(2, f"{text}\n".encode())


def command(args: argparse.Namespace) -> int:
    now = found(pathlib.Path.cwd(), every=args.every)
    for left in now.left_out:
        _note(f"left out {left.check}: {left.why}")
    if not now.badges:
        raise ci.NothingToCheckError(now.root)
    path = now.root / README
    refresh = "repro badges --readme" + (" --all" if args.every else "")

    if args.check:
        if not path.is_file():
            print(f"no {README} at {now.root}; nothing to compare.")
            return 2
        before = shown(_read(path), path)
        if before is None:
            print(f"{path} holds no badge block. Write one:\n\n    {refresh}")
            return 1
        if before == now.line:
            print(f"{path}: each badge is what the project gives now.")
            return 0
        print(f"{path}: the badges are not what the project gives now.")
        print("\n".join(differences(before, now)))
        print(f"\nrefresh:\n\n    {refresh}")
        return 1

    if args.readme:
        if not path.is_file():
            raise ci.ReadmeError(f"no {README} at {now.root}")
        readme = _read(path)
        text = written(readme, now.line, path)
        if text == readme:
            print(f"{path}: the badges are already these; nothing was written.")
            return 0
        atomic_write_bytes(path, text.encode("utf-8"))
        print(f"wrote the badge block in {path}")
        for badge in now.badges:
            print(f"  {badge.name}: {badge.message}")
        return 0

    print("\n".join(badge.markdown for badge in now.badges))
    return 0


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "badges",
        help="print a badge per check, each a count from a run on this machine",
        description=(
            "Run each check the project keeps a record for, as the matching `repro ci` command "
            "runs it, and print one shields.io badge per check whose message is what the check "
            "counted: plans frozen, runs sealed, assertions verified, quotations verified, "
            "declared commands with a current re-run. The badges are static images that carry "
            "their counts in their addresses, so they draw for a private repository. A check "
            "the project keeps no record for is left out, and standard error says which. "
            "Reaches no network."
        ),
    )
    p.add_argument(
        "--all",
        action="store_true",
        dest="every",
        help=f"give a check with no record a gray `{NONE_DECLARED}` badge instead of leaving it out",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--readme",
        action="store_true",
        help=f"write the badges into {README}, on one line between `{START}` and `{END}`, under "
        "the first heading; a second run replaces that block and nothing else",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help=f"write nothing; exit 1 where {README} has no block or its block is not what the "
        f"project gives now, and 2 where there is no {README}",
    )
    p.set_defaults(func=command)


__all__ = [
    "Badge",
    "Found",
    "add_parser",
    "citations_badge",
    "claims_badge",
    "found",
    "prereg_badge",
    "reruns_badge",
    "results_badge",
    "runs",
    "written",
]
