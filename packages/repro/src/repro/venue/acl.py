"""`repro venue acl`: the ACL Responsible NLP Research checklist, drafted from the records.

The questions are those of the ARR Responsible NLP Research checklist page, stored in
`data/acl_checklist.json` with its address and the day it was read. The checklist is filled
in on the submission form, so the draft is Markdown or JSON. No question is answered yes or
no: none asks whether code or data were released, and every other question needs the authors'
judgment, including whether a file a claim reads is a scientific artifact in ACL's sense.
Where a record bears on a question, the section reference or justification the form asks for
is a draft listing what the record says, and elsewhere it is left TODO.
"""

from __future__ import annotations

from repro.venue.draft import Draft, fill, markdown, questionnaire
from repro.venue.records import Project

NAME = "acl_checklist"

#: For each question, by its label on the form, the readers whose findings bear on it.
READS: dict[str, tuple[str, ...]] = {
    "B": ("artifacts",),
    "B1": ("origins",),
    "B2": ("license",),
    "B5": ("documentation",),
    "C1": ("rerun_time", "rerun_environment"),
    "C4": ("environment",),
}

CHOICE = "Answer: **TODO** (authors): Yes or No, chosen by the authors."


def checklist(project: Project) -> Draft:
    return fill(questionnaire(NAME), READS, project)


def as_markdown(draft: Draft) -> str:
    return markdown(draft, choice=CHOICE)


__all__ = ["READS", "as_markdown", "checklist"]
