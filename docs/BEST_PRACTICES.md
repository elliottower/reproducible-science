# Best practices

How to run a study so the claims survive scrutiny. Written for work where an AI assistant does
much of the drafting, coding and analysis, because that raises the stakes on everything below
without changing what any of it means.

The test throughout: **can a stranger check this without trusting me?**

---

## One file per experiment

```
experiments/<ID>_<short name>/
    PREREG.md      the plan, then a horizontal rule, then an append-only log
    run.py
    tests/
    results/
```

`PREREG.md` is the only thing you maintain by hand.

**The rule, and it is the whole system: never edit above the line. Only append below it.**

```markdown
[... the plan ...]

---
## Log

2026-08-11  frozen at abc1234              nothing run
2026-08-13  tolerance now from fixtures    no results seen
2026-08-14  ran                            results not opened
2026-08-15  C5 failed at k=15: 6.6% vs 5%  results seen
```

The last column carries the entire epistemic content. Four values: `nothing run`,
`no results seen`, `results not opened`, `results seen`. An entry logged before results is an
amendment; one logged after is a deviation. You never have to remember which word to use,
because the column already says it.

Nothing else is needed. Git already hashes every file, so there is no manifest. The log is the
timeline. Separate `AMENDMENTS/` and `DEVIATIONS.md` directories are the same information filed
twice.

## Use the OSF headings

Write the plan under [OSF Preregistration](https://osf.io/prereg/) question titles verbatim.
It costs nothing, a reader recognizes the structure without OSF, and submitting later becomes
mechanical rather than a rewrite.

Two of the headings do real work and are the reason to bother:

- **Foreknowledge of data or evidence.** Forces you to declare what you have already seen.
  This is the field that catches an exploratory result being reused as if it were confirmatory.
- **Inference criteria.** Forces the decision rule to be a commitment rather than a description.
  "Any ceiling below 0.50 blocks the measure" is an inference criterion. "We expect reliability
  to be high" is not.

Answer every heading. A question that does not apply is answered **N/A** with the reason, never
deleted — a deleted heading and an inapplicable one look identical in markdown and very
different to a reviewer.

## Three platforms, three jobs

| | what it is for | blindable |
|---|---|---|
| **GitHub** | the code, continuously | private until acceptance |
| **OSF registration** | the frozen plan and a snapshot of the code, DOI minted automatically | yes — embargo |
| **Zenodo** | a DOI for a thing: preprint, dataset, code release | no, always public |

Register on OSF only for experiments whose results you will defend under challenge. A tolerance
sweep does not need a DOI. Go back to OSF only when a hypothesis, primary outcome or decision
rule changes; everything smaller is a log line.

**The embargo is the piece that makes this work with blind review.** You register at freeze —
dated, immutable, third-party held — and it stays invisible until you lift it. Anonymity intact,
attestation already banked. Public release at acceptance would be too late to prove anything.

**On Zenodo and preprint servers.** arXiv and bioRxiv are community reading lists, and posting
there imposes a cost on everyone in the field. Zenodo is an archive; depositing imposes on
nobody. For exploratory or AI-heavy work that wants a citable, dated, scoop-resistant record
without claiming a field's attention, Zenodo is the honest choice.

Know that a published Zenodo deposit is **permanent**. You cannot delete it; files cannot be
edited, only superseded by a new version, and the old version stays resolvable. That permanence
is not a drawback — a timestamp you can revise establishes nothing.

## What timestamps do and do not prove

A cryptographic timestamp proves a **lower bound**: this existed by time T. It can never prove
an **upper bound** — that the work did not start earlier. You cannot prove a negative about your
own private activity, and no amount of hashing changes that.

So continuous stamping of scripts and data is a genuine provenance record and a real deterrent.
It is **not** proof that you did not peek. The literature names this failure — preregistering
after results are known — and reaches for third-party registration rather than cryptography,
because the value is that someone else holds a dated copy you cannot revise.

Claim the first. Never claim the second.

## Separate what a source says from what you concluded

```
claims/     the extraction: verbatim quotations with section and page, the pinned
            artifact and its sha256, the claim as stated. Checkable by anyone.
audits/     the judgment: statuses, verdicts, reasoning. Ours, and contestable.
```

An audit record points at its claim record; a claim record never mentions a verdict. Someone who
rejects every verdict can still use the extraction. Merging them makes that impossible, and a
paper arguing that a field conflates evidence with assessment cannot ship them conflated.

Pre-registrations belong in `experiments/`, never in `paper/` or `submission/<venue>/`. A venue
folder is temporary, and a frozen document filed under temporary metadata becomes deletable-looking
the moment the submission is abandoned.

## Verify quotations against the artifact

Every quotation resolves against a source pinned by sha256, checked by a gate that runs in CI.
What this catches is fabrication. What it cannot catch is misinterpretation — a real, resolving
quotation attached to a claim it does not support.

**And it can be defeated by truncation.** A pinned substring that ends before a qualifying clause
verifies a claim its source contradicts. A real instance: `"We trained 50"` resolves cleanly while
the source continues `"...each for 2, 4, and 8 layered variants and 5 refits each for 12 layered
(GPT2-small)"`. The claim recorded fifty refits; the true number was five.

Require quotations long enough to carry their own qualifiers, and check that they do not end
mid-sentence.

## Failure modes that recur

Every one of these produced a confident wrong answer in practice.

**A check that passes by examining nothing.** A linter whose tool could not find its input
reported zero issues. A quote gate whose source was missing reported success. Any check must
distinguish *passed*, *failed*, and *could not run*, and must refuse to report success for the
third.

**Confusing "refused" with "absent".** A batch of sixty lookups reported sixty works as
unfindable when the API had started rate-limiting after the first few. Error handling that
collapses those two will delete information and look confident doing it.

**Comparing the wrong thing.** Two files reported as unique because the comparison was on
filename rather than content. Compare hashes.

**Same surname, similar year, different paper.** This happened five times in one project. Verify
title *and* author list *and* identifier together, never two of the three.

**A term count is not a finding.** Concluding a source lacks a concept because a phrase is absent
produces false negatives, because authors name things differently. Read the section that would
contain it.

## Where the AI assistance goes

One accurate statement in methods:

> Generative AI tools assisted with literature triage, study design, pre-registration drafting,
> code generation, execution orchestration and manuscript editing. The author reviewed and
> approved the registered hypotheses, decision rules, code, analyses and interpretations, and
> assumes responsibility for the work.

No chat logs, no contribution graph, no `.claude` directory in the repository. What a reader
needs is responsibility and reproducibility, not a transcript.

Do not advertise the pre-registration either. One sentence in methods, never in the discussion,
never framed as a virtue. A paper that markets its own rigor invites an audit of the rigor
instead of the result.

## The two-minute test

A reader should be able to answer these from the repository alone:

1. What was planned, and when was it frozen?
2. What was already known at that point?
3. What changed, and was it before or after the results were seen?
4. Which registered analysis produced this claim?
5. Does every quotation resolve in the source it cites?

If the answer to all five is yes, stop building. Anything further is provenance theater.
