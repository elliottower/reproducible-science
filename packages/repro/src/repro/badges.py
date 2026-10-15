"""`repro badges`: one README badge per check, each reading a count from a run on this machine.

    repro badges            print one badge per check the project keeps a record for
    repro badges --readme   write them into README.md, between two marker lines
    repro badges --check    say whether README.md shows what the project gives now
    repro badges --record   check the quotations here and commit what was found, for CI
    repro badges init       write a workflow that keeps the badges current on GitHub

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

`repro badges init` writes the other kind: one workflow, `.github/workflows/repro.yml`, which on
each push to the default branch runs `repro ci endpoints`, writing one shields.io endpoint
file per check with the same label, count, colour and icon, and force-pushes those files as
the one commit of a `badges` branch. The README block then names the files on that branch, so
the counts follow the repository without a commit. shields.io reads the files from
raw.githubusercontent.com, which serves a public repository only. The citations badge in CI is
read from the record `repro badges --record` commits (`repro.citations_record`), since a clone
does not hold the sources.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import re
import urllib.parse

from provenance_core import atomic_write, atomic_write_bytes
from provenance_core.chain import ChainError, read_ledger
from provenance_core.gitref import try_run
from pydantic import BaseModel, ConfigDict

from repro import __version__, audit, ci, citations_record
from repro.citations_record import Standing
from repro.delegate import BY_NAME
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
#: The citations badge in CI where no record of a local check is committed.
NOT_RECORDED = "not verified locally"
#: The citations badge in CI where the claims files changed since the record.
REVERIFY = "re-verify locally"
REFRESH_RECORD = f"repro badges --record, then commit {citations_record.RECORD.as_posix()}"

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

#: A badge shields.io draws from a JSON file it fetches: https://shields.io/badges/endpoint-badge
ENDPOINT = "https://img.shields.io/endpoint"
#: The branch the workflow `init` writes force-pushes the endpoint files to. Never the default
#: branch: `init` refuses a repository whose default branch has this name.
BRANCH = "badges"
#: The workflow `init` writes, and the first line it is known by.
WORKFLOW_FILE = ci.WORKFLOWS / "repro.yml"
MARKER = "# Written by `repro badges init`."
#: Where the workflow writes the endpoint files before they are pushed.
OUT = "${{ runner.temp }}/badges"

WORKFLOW = """\
{marker} On a push to {branch}, it runs each check this repository
# keeps a record for and writes one shields.io endpoint file per check, then force-pushes
# those files as the only commit of the `{badges}` branch, which the README's badges read.
# It never pushes to {branch}: https://reproducible.science/tools/repro/#badges-that-update-themselves
name: repro badges

on:
  push:
    branches: [{branch}]
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: repro-badges
  cancel-in-progress: true

jobs:
  badges:
    runs-on: ubuntu-latest
    steps:
      - uses: {checkout}
        with:
          persist-credentials: false
      - uses: {setup_uv}
      - run: uvx --from {distribution}=={version} repro ci endpoints "$OUT"
        env:
          OUT: {out}
      - name: push the endpoint files to the {badges} branch
        env:
          OUT: {out}
          DEFAULT: ${{{{ github.event.repository.default_branch }}}}
          GH_TOKEN: ${{{{ github.token }}}}
        run: |
          test "$DEFAULT" != {badges}
          cd "$OUT"
          git init --quiet --initial-branch={badges}
          git add -- *.json
          git -c user.name="github-actions[bot]" \\
            -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \\
            commit --quiet --message="badges for $GITHUB_SHA"
          git push --force --quiet \\
            "https://x-access-token:$GH_TOKEN@github.com/$GITHUB_REPOSITORY.git" \\
            HEAD:refs/heads/{badges}
"""

_SHOWN = re.compile(r"\[!\[(?P<name>[^\]:]+): (?P<message>[^\]]*)\]\((?P<image>[^)\s]*)\)\]")


class BlockError(ReproError):
    """README.md opens a badge block it does not close."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        super().__init__(
            f"{path} holds `{START}` with no `{END}` after it; nothing was written. Close the "
            "block or remove the line."
        )


class WorkflowExistsError(ReproError):
    """A file is already where `init` would write its workflow. Nothing is overwritten."""

    def __init__(self, path: pathlib.Path, ours: bool) -> None:
        self.path = path
        super().__init__(
            f"{path} exists. `--force` replaces the workflow this command wrote; nothing was "
            "written."
            if ours
            else f"{path} exists and `repro badges init` did not write it; nothing was written."
        )


class NoGitHubError(ReproError):
    """`init` needs the GitHub repository the badges are read from."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"{detail}; nothing was written.")


class EndpointBlockError(ReproError):
    """`--readme` would replace the block `init` wrote, which the workflow keeps current."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        super().__init__(
            f"{path} holds the badges `repro badges init` wrote, which the workflow keeps "
            "current; nothing was written. `repro badges --record` refreshes the citations "
            "record, and `repro badges init --force` rewrites the block."
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

    @property
    def endpoint(self) -> dict[str, object]:
        """The badge as a shields.io endpoint file: the same label, message, colours and icon
        as `image`, with the icon as the SVG text the endpoint schema's `logoSvg` takes."""
        return {
            "schemaVersion": 1,
            "label": self.name,
            "message": self.message,
            "color": self.color,
            "labelColor": ci.LABEL_COLOR,
            "logoSvg": ci.icon(self.check),
        }


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
    # An inferred assertion that matched is a proposal that held, not a verified claim.
    verified = sum(
        decision.outcome is Outcome.VERIFIED and not decision.inferred
        for decision in report.decisions
    )
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


def recorded_citations_badge(compared: citations_record.Compared) -> Badge:
    """The citations badge read from the committed record of a run on the author's machine.

    Where the claims files are the ones the record covers, it is the badge that run gives,
    with `locally` said: `203/203 verified locally`. Where a claims file was added, removed or
    changed since, amber, `re-verify locally`. Where there is no record, gray.
    """
    if compared.standing is Standing.ABSENT or compared.record is None:
        return Badge(check="citations", message=NOT_RECORDED, color=GRAY)
    if compared.standing is Standing.STALE:
        return Badge(check="citations", message=REVERIFY, color=AMBER)
    made = citations_badge(compared.record.run)
    said = ", none read locally" if made.color == BLUE else " locally"
    return made.model_copy(update={"message": made.message + said})


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


def found(cwd: pathlib.Path, *, every: bool = False, recorded: bool = False) -> Found:
    """The badges for the project holding `cwd`. With `every`, a check the project keeps no
    record for has a gray badge; without, it is left out and said to be. With `recorded`, the
    citations badge is read from the committed record of a local check, and `citations
    verify` is not run: what a CI job does, where the sources are not."""
    root = project_root(cwd)
    made: dict[str, Badge] = {}
    why_not: dict[str, str] = {}

    for check in ci.TOOLS:
        if check == "citations" and recorded:
            if BY_NAME[check].used_by(root):
                made[check] = recorded_citations_badge(citations_record.compare(root))
            else:
                why_not[check] = ci.NO_RECORD[check]
            continue
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


# ---------------------------------------------------------------------- self-updating badges


def endpoint_line(checks: list[str], slug: str) -> str:
    """The README line for badges read from the endpoint files on the `badges` branch, each
    linked to the runs of the workflow that writes them."""
    runs = f"https://github.com/{slug}/actions/workflows/{WORKFLOW_FILE.name}"
    return " ".join(
        f"[![{ci.NAMES[check]}]({ENDPOINT}?url=https://raw.githubusercontent.com/{slug}/"
        f"{BRANCH}/{check}.json)]({runs})"
        for check in checks
    )


def is_endpoint_block(line: str) -> bool:
    """Whether a badge block holds the badges `init` wrote, which the workflow keeps current."""
    return f"{ENDPOINT}?" in line


def endpoints(cwd: pathlib.Path, directory: pathlib.Path) -> Found:
    """Write `<directory>/<check>.json` for every check, gray where the project keeps no
    record for it, with the citations badge read from the committed record."""
    now = found(cwd, every=True, recorded=True)
    directory.mkdir(parents=True, exist_ok=True)
    for badge in now.badges:
        atomic_write(
            directory / f"{badge.check}.json",
            json.dumps(badge.endpoint, indent=2, sort_keys=True) + "\n",
        )
    return now


def workflow_text(branch: str) -> str:
    """The workflow `init` writes, pinned to the installed version of this package."""
    if __version__ == "0+unknown":
        raise ci.VersionUnknownError
    return WORKFLOW.format(
        marker=MARKER,
        branch=ci._scalar(branch),
        badges=BRANCH,
        checkout=ci.CHECKOUT,
        setup_uv=ci.SETUP_UV,
        distribution=ci.DISTRIBUTION,
        version=__version__,
        out=OUT,
    )


def init(cwd: pathlib.Path, *, force: bool = False) -> int:
    """Write the workflow, the README block and the citations record, and print what is left
    to do."""
    root, path = ci.located(cwd)
    keeps = ci.kept(root, path)
    checks = [check for check in ci.CHECKS if keeps[check]]
    if not checks:
        raise ci.NothingToCheckError(root)
    slug = ci.repository(try_run("remote", "get-url", "origin", cwd=root) or "")
    if slug is None:
        raise NoGitHubError("`git remote get-url origin` names no GitHub repository")
    branch = ci.default_branch(root)
    if branch == BRANCH:
        raise NoGitHubError(
            f"the default branch is `{BRANCH}`, the branch the workflow force-pushes to"
        )
    target = root / WORKFLOW_FILE
    if target.exists():
        ours = target.read_text(encoding="utf-8").startswith(MARKER)
        if not (ours and force):
            raise WorkflowExistsError(target, ours)
    readme = root / README
    if not readme.is_file():
        raise ci.ReadmeError(f"no {README} at {root}")
    text = _read(readme)
    before = shown(text, readme)
    line = endpoint_line(checks, slug)
    flow = workflow_text(branch)

    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, flow)
    print(f"wrote {target}")
    print(f"  runs on a push to {branch}; pushes the badge files to the `{BRANCH}` branch only")
    if "citations" in checks:
        made = citations_record.write(root)
        print(f"wrote {root / citations_record.RECORD}")
        print(f"  citations: {citations_badge(made.run).message}, checked on this machine")
    for check in ci.CHECKS:
        if not keeps[check]:
            print(f"left out {check}: {ci.NO_RECORD[check]}")

    if before is not None and not force:
        print(f"\n{readme} already holds a badge block; it was left as it is.")
        if not is_endpoint_block(before):
            print("`repro badges init --force` replaces it with the badges the workflow updates.")
    else:
        atomic_write_bytes(readme, written(text, line, readme).encode("utf-8"))
        print(f"\nwrote the badge block in {readme}")
        for check in checks:
            print(f"  {ci.NAMES[check]}: {BRANCH}/{check}.json")

    print("\nnext:")
    print(f"  1. commit {WORKFLOW_FILE.as_posix()}, {README}", end="")
    print(f" and {citations_record.RECORD.as_posix()}" if "citations" in checks else "")
    print(f"  2. push to {branch}. The first run makes the `{BRANCH}` branch; until it has run,")
    print("     the badges draw as `resource not found`.")
    print("  3. if the run cannot push, allow GitHub Actions read and write permissions under")
    print("     Settings > Actions > General > Workflow permissions.")
    if "citations" in checks:
        print("  4. after changing a claims file, run `repro badges --record` and commit the")
        print(f"     record; until then the citations badge reads `{REVERIFY}`.")
    print(
        "\nshields.io reads the badge files from raw.githubusercontent.com, which serves a "
        "public repository\nonly: in a private one the badges do not draw. `repro badges "
        "--readme` writes static badges\nthat draw anywhere."
    )
    return 0


# --------------------------------------------------------------------------------- commands


def _read(path: pathlib.Path) -> str:
    """The README as its bytes spell it. Read as text, a line ending `\\r\\n` would come back
    as `\\n`, and writing that back would change every line outside the block."""
    return path.read_bytes().decode("utf-8")


def _note(text: str) -> None:
    """A line on standard error, so standard output holds only the badges."""
    os.write(2, f"{text}\n".encode())


def _check_record(root: pathlib.Path, path: pathlib.Path) -> int:
    """`--check` of a README holding the badges `init` wrote: the workflow keeps the counts
    current, so what can be out of date here is the citations record."""
    if not BY_NAME["citations"].used_by(root):
        print(f"{path}: the workflow keeps these badges current; nothing to compare here.")
        return 0
    compared = citations_record.compare(root)
    if compared.standing is Standing.CURRENT:
        print(f"{path}: the workflow keeps these badges current, and the citations record covers")
        print("each claims file as it is now.")
        return 0
    if compared.standing is Standing.ABSENT:
        print(f"no citations record at {root / citations_record.RECORD}. Write one:")
    else:
        print("the citations record does not cover the claims files as they are now:")
        print("\n".join(f"  {name}" for name in compared.differing))
        print("\nrefresh:")
    print(f"\n    {REFRESH_RECORD}")
    return 1


def command_record(root: pathlib.Path) -> int:
    made = citations_record.write(root)
    print(f"wrote {root / citations_record.RECORD}")
    print(f"  citations: {citations_badge(made.run).message}")
    print(f"  {len(made.claims)} claims files, checked with citations {made.citations}")
    return 0


def command(args: argparse.Namespace) -> int:
    root = project_root(pathlib.Path.cwd())
    if args.record:
        return command_record(root)
    path = root / README
    if (args.check or args.readme) and path.is_file():
        before = shown(_read(path), path)
        if before is not None and is_endpoint_block(before):
            if args.readme:
                raise EndpointBlockError(path)
            return _check_record(root, path)

    now = found(pathlib.Path.cwd(), every=args.every)
    for left in now.left_out:
        _note(f"left out {left.check}: {left.why}")
    if not now.badges:
        raise ci.NothingToCheckError(now.root)
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


def command_endpoints(args: argparse.Namespace) -> int:
    """`repro ci endpoints DIRECTORY`."""
    directory = pathlib.Path(args.directory)
    now = endpoints(pathlib.Path.cwd(), directory)
    for badge in now.badges:
        print(f"wrote {directory / f'{badge.check}.json'}: {badge.name} | {badge.message}")
    if any(b.check == "citations" and b.message == NOT_RECORDED for b in now.badges):
        print(f"\ncitations: no record of a local check is committed. Run\n\n    {REFRESH_RECORD}")
    elif any(b.check == "citations" and b.message == REVERIFY for b in now.badges):
        print(
            f"\ncitations: the claims files changed since the record. Run\n\n    {REFRESH_RECORD}"
        )
    return 0


def command_init(args: argparse.Namespace) -> int:
    return init(pathlib.Path.cwd(), force=args.force)


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
            "Reaches no network. `repro badges init` writes a workflow that keeps the same "
            "badges current on GitHub instead."
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
        f"project gives now, and 2 where there is no {README}. Where the block is the one "
        "`init` wrote, exit 1 where the citations record does not cover the claims files",
    )
    mode.add_argument(
        "--record",
        action="store_true",
        help="check the quotations on this machine and write what was found to "
        f"{citations_record.RECORD.as_posix()}, with the sha256 of each claims file, for the "
        "workflow `init` writes to read",
    )
    p.set_defaults(func=command)
    actions = p.add_subparsers(dest="action")
    p_init = actions.add_parser(
        "init",
        help="write a workflow that keeps the badges current on GitHub",
        description=(
            f"Write {WORKFLOW_FILE.as_posix()}, which on each push to the default branch runs "
            "each check the repository keeps a record for, writes one shields.io endpoint file "
            f"per check, and force-pushes them as the only commit of the `{BRANCH}` branch. "
            f"Put a badge block in {README} whose badges read those files, unless {README} "
            "already holds one. Where the project pins quotations, check them here and write "
            f"{citations_record.RECORD.as_posix()}, which the workflow reads in place of "
            "sources a clone does not hold. Prints what is left to do. The badges draw only "
            "for a public repository."
        ),
    )
    p_init.add_argument(
        "--force",
        action="store_true",
        help=f"replace the workflow this command wrote, and the badge block in {README}",
    )
    p_init.set_defaults(func=command_init)


__all__ = [
    "Badge",
    "Found",
    "add_parser",
    "citations_badge",
    "claims_badge",
    "endpoint_line",
    "endpoints",
    "found",
    "init",
    "prereg_badge",
    "recorded_citations_badge",
    "reruns_badge",
    "results_badge",
    "runs",
    "written",
]
