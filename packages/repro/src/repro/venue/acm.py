"""`repro venue acm`: an Artifact Appendix drafted from what the repository records.

The questions are the headings and fields of the Unified Artifact Appendix template that ACM
conferences running artifact evaluation ask authors to fill in (`data/acm_appendix.json`, with
the commit of the template it was copied from). `READS` says which records bear on which
field. A field a record answers is a draft naming that record; every other field is left for
the authors, marked TODO.

The LaTeX rendering follows the template's own layout, so it can be pasted where the template
goes, and every field in it still carries its marker.
"""

from __future__ import annotations

import textwrap

from repro.venue.draft import (
    Draft,
    Settle,
    Status,
    fill,
    latex_escape,
    latex_findings,
    latex_marker,
    questionnaire,
)
from repro.venue.records import CONFIRM_PUBLIC, Project

NAME = "acm_appendix"

#: The checklist section, whose fields the template sets as one itemized list.
CHECKLIST = "Artifact check-list (meta-information)"

#: For each field, the readers whose findings bear on it. A field not named is left to do.
READS: dict[str, tuple[str, ...]] = {
    "run-time-environment": ("environment", "rerun_environment"),
    "hardware": ("rerun_environment",),
    "execution": ("rerun_time",),
    "output": ("claims",),
    "experiments": ("regenerations",),
    "time-to-complete": ("rerun_time",),
    "code-licenses": ("license",),
    "workflow-framework": ("regenerations",),
    "archived": ("archive",),
    "how-to-access": ("remote", "archive", "repository"),
    "software-dependencies": ("environment",),
    "experiment-workflow": ("regenerations", "plans", "ledger"),
    "evaluation": ("claims", "reruns", "origins"),
}


#: Fields a record settles with no judgment involved. An archived copy is a DOI or a Software
#: Heritage ID; a repository address is public only if the authors say so, and GitHub or GitLab
#: alone is not an archive. A declared command is run by `repro reproduce`.
SETTLES: dict[str, Settle] = {
    "archived": Settle(
        choice="Yes",
        readers=("archive",),
        unsettled=(
            "no record here names an archived copy: a DOI in CITATION.cff or codemeta.json, or "
            "a Software Heritage ID (swh:1:...) in either or in the README. A GitHub or GitLab "
            "URL alone is not an archive."
        ),
    ),
    "publicly-available": Settle(
        choice="Yes", readers=("archive", "repository"), note=CONFIRM_PUBLIC
    ),
    "workflow-framework": Settle(choice="Yes", readers=("regenerations",)),
}


def appendix(project: Project) -> Draft:
    return fill(questionnaire(NAME), READS, project, SETTLES)


def latex(draft: Draft) -> str:
    """The draft in the template's layout: the checklist as one list, every other field under
    its own heading, each with its marker."""
    notice = "\n".join(f"% {line}" for line in textwrap.wrap(draft.notice, 90))
    lines = [
        notice,
        f"% Questions copied from {draft.source.url}",
        f"% retrieved {draft.source.retrieved}.",
        r"\section{Artifact Appendix}",
        r"\textbf{" + latex_escape(draft.notice) + "}",
    ]
    section = None
    in_list = False
    for answer in draft.answers:
        question = answer.question
        if question.section == CHECKLIST:
            if not in_list:
                lines += [rf"\subsection{{{latex_escape(CHECKLIST)}}}", r"\begin{itemize}"]
                in_list = True
            body = latex_marker(answer)
            if answer.status is Status.DRAFT:
                body += "\n" + latex_findings(answer)
            lines.append(rf"\item {{\bf {latex_escape(question.title)}: }} {body}")
            section = CHECKLIST
            continue
        if in_list:
            lines.append(r"\end{itemize}")
            in_list = False
        if not question.section:
            lines.append(rf"\subsection{{{latex_escape(question.title)}}}")
            section = None
        else:
            if question.section != section:
                lines.append(rf"\subsection{{{latex_escape(question.section)}}}")
                section = question.section
            lines.append(rf"\subsubsection{{{latex_escape(question.title)}}}")
        if question.text:
            lines.append(r"{\em " + latex_escape(question.text) + "}\n")
        lines.append(latex_marker(answer))
        if answer.findings:
            lines.append(latex_findings(answer))
    if in_list:
        lines.append(r"\end{itemize}")
    return "\n".join(lines) + "\n"


__all__ = ["READS", "appendix", "latex"]
