---
title: ACM badging evidence map
description: repro venue acm-evidence lists the records bearing on each criterion of ACM Artifact Review and Badging v1.1.
---

`repro venue acm-evidence` lists, for each criterion of ACM Artifact Review and Badging v1.1,
the records in the repository that bear on it, under the policy's own text for the criterion.
Every format carries the label "Evidence mapped to ACM Artifact Review and Badging v1.1
criteria; not an ACM badge."

## Reads

The same records as [`repro venue acm`](/integrations/acm-artifact-appendix/), and the policy
text stored in the package. The policy page was saved from a browser, because acm.org refuses
scripted requests; each quoted criterion is stored with the page's address, the retrieval date,
its line in the saved text, and its sha256.

## Writes

HTML or JSON, to standard output or to `--output`. Each criterion's standing is one of
`records listed`, `no record found`, or `not determinable by this tool`.

- Archival availability: a DOI or Software Heritage ID among the project's own identifiers.
- An exercisable artifact: the declared commands, their last re-runs, the claims, and the
  documentation.
- Reuse: those, with the license and the lockfiles.

## Command

```bash
repro venue acm-evidence --format html -o acm-evidence.html
```

## Refuses or never does

- Never says a criterion is met: evaluators decide that.
- The two criteria about results obtained by others are always `not determinable by this tool`.
- Uses no badge name or image as a label or status outside the quoted policy text.
- Never lists the origin of a copied file as the project's archival record.
- Never writes over the `--output` file without `--force`, and reaches no network.

## Does not claim

The output is not an ACM badge, does not award one, and does not predict one.

## The other project

ACM's [Artifact Review and Badging](https://www.acm.org/publications/policies/artifact-review-and-badging-current)
policy.

Not affiliated with or endorsed by ACM.
