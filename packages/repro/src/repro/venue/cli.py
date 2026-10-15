"""`repro venue`: the commands that draft what a venue asks for from the records.

    repro venue acm           an Artifact Appendix, in Markdown, LaTeX or JSON
    repro venue acm-evidence  the records bearing on each ACM badging criterion, in HTML or JSON

Each writes to standard output, or to `--output`, which is never overwritten without
`--force`: a draft the authors have started editing is theirs, and regenerating over it would
put generated text back where they had replaced it.
"""

from __future__ import annotations

import argparse
import pathlib
from collections.abc import Callable

from provenance_core import atomic_write

from repro.exceptions import ReproError
from repro.venue import acm, acm_evidence
from repro.venue.draft import Draft, Status, as_json, markdown
from repro.venue.records import Project


class OutputExistsError(ReproError):
    """`--output` names a file that is there. Nothing is written over it without `--force`."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        super().__init__(
            f"{path} exists; nothing was written. The authors may have edited it: pass --force "
            "to replace it with a new draft."
        )


def emit(text: str, output: str | None, force: bool) -> int:
    """Print `text`, or write it to `output` and say so."""
    if output is None:
        print(text, end="")
        return 0
    path = pathlib.Path(output)
    if path.exists() and not force:
        raise OutputExistsError(path)
    atomic_write(path, text)
    print(f"wrote {path}")
    return 0


def summary(draft: Draft) -> str:
    drafted = sum(answer.status is Status.DRAFT for answer in draft.answers)
    return (
        f"{drafted} of {len(draft.answers)} drafted from records, "
        f"{len(draft.answers) - drafted} left TODO"
    )


ACM_FORMATS: dict[str, Callable[[Draft], str]] = {
    "markdown": markdown,
    "latex": acm.latex,
    "json": as_json,
}


def command_acm(args: argparse.Namespace) -> int:
    draft = acm.appendix(Project.at(pathlib.Path.cwd(), plan=args.plan))
    code = emit(ACM_FORMATS[args.format](draft), args.output, args.force)
    if args.output is not None:
        print(f"  {summary(draft)}")
    return code


EVIDENCE_FORMATS: dict[str, Callable[[acm_evidence.EvidenceMap], str]] = {
    "html": acm_evidence.as_html,
    "json": acm_evidence.as_json,
}


def command_acm_evidence(args: argparse.Namespace) -> int:
    made = acm_evidence.evidence_map(Project.at(pathlib.Path.cwd()))
    code = emit(EVIDENCE_FORMATS[args.format](made), args.output, args.force)
    if args.output is not None:
        print(f"  {acm_evidence.LABEL}")
        for mapped in made.criteria:
            print(f"  {mapped.criterion.id}: {mapped.standing.value}")
    return code


def _output_options(parser: argparse.ArgumentParser, formats: list[str], plan: bool = True) -> None:
    parser.add_argument("--format", choices=formats, default=formats[0])
    parser.add_argument("--output", "-o", metavar="FILE", help="write here instead of printing")
    parser.add_argument(
        "--force", action="store_true", help="replace the file --output names where it exists"
    )
    if plan:
        parser.add_argument(
            "--plan",
            type=pathlib.Path,
            metavar="PATH",
            help="the preregistration to read, in place of every PREREG.md `prereg check` finds "
            "outside folders of tests, fixtures and examples",
        )


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "venue",
        help="draft a venue's appendix or checklist from the records, every answer marked",
        description=(
            "Fill what a venue asks for from what this repository records: the manifest, the "
            "record of re-runs, the ledger, the frozen plans, CITATION.cff and the files at "
            "the top of the project. Every answer drawn from a record is marked DRAFT and "
            "names that record; every question no record answers is marked TODO and left "
            "for the authors. A yes or no is filled in only where a record settles it with "
            "no judgment, and is marked DRAFT with that record named; every other yes or no "
            "is left to the authors. Reaches no network."
        ),
    )
    venues = p.add_subparsers(dest="venue", required=True)
    p_acm = venues.add_parser(
        "acm",
        help="an Artifact Appendix, from the Unified Artifact Appendix template",
        description=(
            "Draft an Artifact Appendix in the layout of the Unified Artifact Appendix "
            "template ACM conferences use for artifact evaluation. The field labels are the "
            "template's, copied with the commit they were read at. Three fields are answered "
            "Yes where a record settles them: Archived, from a DOI or Software Heritage ID "
            "among the project's own identifiers; Publicly available, from those or the "
            "project's own code repository, for the authors to confirm it is public; and "
            "Workflow automation framework used, from a declared command."
        ),
    )
    _output_options(p_acm, list(ACM_FORMATS))
    p_acm.set_defaults(func=command_acm)
    p_evidence = venues.add_parser(
        "acm-evidence",
        help="the records bearing on each criterion of ACM Artifact Review and Badging v1.1",
        description=(
            f"{acm_evidence.LABEL} For each criterion of the policy, list the records in this "
            "repository that bear on it, with the policy's own text for the criterion. Whether "
            "a criterion is met is not said: evaluators decide that. The two criteria about "
            "results obtained by others are not determinable by this tool."
        ),
    )
    _output_options(p_evidence, list(EVIDENCE_FORMATS), plan=False)
    p_evidence.set_defaults(func=command_acm_evidence)


__all__ = ["OutputExistsError", "add_parser", "emit"]
