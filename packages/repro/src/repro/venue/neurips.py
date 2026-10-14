"""`repro venue neurips`: the NeurIPS Paper Checklist, drafted from what the repository records.

The questions are those of `checklist.tex` in the NeurIPS formatting archive, stored in
`data/neurips_checklist.json` with the archive's address and the day it was read. Every
question asks about the paper, and no record can say what a paper discloses, so the answer
stays `\\answerTODO{}`, except open access (5): an archived copy or a code repository the
records name settles it as `\\answerYes{}`, marked DRAFT, for the authors to confirm the
repository is public. Where a record bears on a question, the
justification is a draft listing what that record says, for the authors to check against the
paper and rewrite; elsewhere it stays `\\justificationTODO{}`.
"""

from __future__ import annotations

import textwrap

from repro.venue.draft import (
    Answer,
    Draft,
    Settle,
    fill,
    latex_code,
    latex_escape,
    latex_findings,
    latex_marker,
    markdown,
    questionnaire,
)
from repro.venue.records import CONFIRM_PUBLIC, Project

NAME = "neurips_checklist"

#: For each question, by its number in the checklist, the readers whose findings bear on it.
READS: dict[str, tuple[str, ...]] = {
    "1": ("claims",),
    "4": ("regenerations", "reruns", "plans"),
    "5": ("archive", "origins", "regenerations", "environment", "license"),
    "8": ("rerun_time", "rerun_environment"),
    "12": ("origins",),
    "13": ("documentation", "license"),
}

#: The one question a record settles: open access to the code (5) is Yes where the records
#: name an archived copy or a code repository, for the authors to confirm the repository is
#: public. Every other question asks what the paper discloses, which no record can say.
SETTLES: dict[str, Settle] = {
    "5": Settle(choice="Yes", readers=("archive", "repository"), note=CONFIRM_PUBLIC),
}

CHOICE = "Answer: **TODO** (authors): Yes, No or NA, chosen by the authors."


def checklist(project: Project) -> Draft:
    return fill(questionnaire(NAME), READS, project, SETTLES)


def as_markdown(draft: Draft) -> str:
    return markdown(draft, choice=CHOICE)


def _answer(answer: Answer) -> str:
    """The answer: `\\answerYes{}` where a record settles it, followed by a mark that prints,
    naming the record, so the PDF shows the answer as a draft; `\\answerTODO{}` elsewhere."""
    if answer.choice == "Yes":
        named = ", ".join(latex_code(record) for record in answer.choice_from)
        note = f"; {latex_escape(answer.choice_note)}" if answer.choice_note else ""
        return rf"\answerYes{{}} \textbf{{(DRAFT: from {named}{note})}}"
    return r"\answerTODO{} % the authors choose \answerYes{}, \answerNo{} or \answerNA{}"


def latex(draft: Draft) -> str:
    """The checklist in the shape of `checklist.tex`, with the answer left `\\answerTODO{}`
    and each justification either drafted from a record or `\\justificationTODO{}`. The
    guidelines under each question are not reproduced: they stay as `checklist.tex` has them."""
    lines = [
        *(f"% {line}" for line in textwrap.wrap(draft.notice, 90)),
        f"% Questions copied from {draft.source.url}",
        f"% retrieved {draft.source.retrieved}. The guidelines under each question are left out:",
        "% keep them from checklist.tex.",
        r"\section*{NeurIPS Paper Checklist}",
        r"\textbf{" + latex_escape(draft.notice) + "}",
        r"\begin{enumerate}",
    ]
    for answer in draft.answers:
        question = answer.question
        justification = latex_marker(answer, with_choice=False)
        if answer.findings:
            justification += "\n" + latex_findings(answer)
        else:
            justification = r"\justificationTODO{} " + justification
        lines += [
            "",
            rf"\item {{\bf {latex_escape(question.title)}}}",
            rf"    \item[] Question: {latex_escape(question.text)}",
            f"    \\item[] Answer: {_answer(answer)}",
            rf"    \item[] Justification: {justification}",
        ]
    lines.append(r"\end{enumerate}")
    return "\n".join(lines) + "\n"


__all__ = ["READS", "as_markdown", "checklist", "latex"]
