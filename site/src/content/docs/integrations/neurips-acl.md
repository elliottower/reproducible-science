---
title: NeurIPS and ACL checklists
description: repro venue neurips and repro venue acl draft the two checklists from the records.
---

`repro venue neurips` drafts the NeurIPS Paper Checklist, and `repro venue acl` drafts the ACL
Responsible NLP Research checklist. The question text is stored verbatim in the package with its
source and retrieval date: the sixteen questions of `checklist.tex` in the NeurIPS 2026
formatting archive, and the questions of the ARR checklist page.

## Reads

The same records as [`repro venue acm`](/integrations/acm-artifact-appendix/): claims, declared
commands and their re-runs, frozen plans, the DOI, origins, lockfiles, the license and the
documentation. `--plan` names one preregistration in place of every plan `prereg check` finds.

## Writes

- NeurIPS: Markdown, LaTeX in the shape of `checklist.tex`, or JSON.
- ACL: Markdown or JSON.

Where a record bears on a question, the justification is a draft marked DRAFT with the record
named. Every other question is left TODO.

## Command

```bash
repro venue neurips --format latex -o checklist.tex
repro venue acl --format markdown -o responsible-nlp-checklist.md
```

## Refuses or never does

- Every NeurIPS answer stays `\answerTODO{}`, because each question asks what the paper
  discloses, except open access (5). That one is `\answerYes{}` where the project's own DOI,
  Software Heritage ID or code repository is recorded, followed by
  `(DRAFT: from CITATION.cff; author: confirm this repository is public)`.
- No ACL answer is chosen, and a public repository settles none.
- A recorded re-run does not settle whether computational experiments were run, or answer the
  NeurIPS compute question.
- An origin alone does not answer open access.
- ACL has no LaTeX output.
- Never writes over the `--output` file without `--force`, and reaches no network.

## Does not claim

The drafts are not completed checklists and not answers on the authors' behalf. Each question
stays the authors' to answer.

## The other project

The [NeurIPS Paper Checklist guidelines](https://neurips.cc/public/guides/PaperChecklist), and
the [ACL Responsible NLP Research checklist](https://aclrollingreview.org/responsibleNLPresearch/).

Not affiliated with or endorsed by NeurIPS or ACL.
