---
name: prereg-style
description: One author's opinionated style for writing a preregistration, none of it required by the tool. Covers what a plan has to register, how to lay out hypotheses, inference criteria and void conditions, what to cut, and what to check before freezing. Use when drafting or revising a PREREG.md, when a plan reads as too long or too thin, or when asked whether a plan is ready to freeze.
---

# prereg-style

**This is one author's opinionated style. Nothing in it is required by `prereg`.** The tool
freezes whatever file it is given, and `prereg check` reads a plan written any other way
exactly as it reads one written this way. Take what is useful and ignore the rest.

The only layout the tool itself cares about is the one `prereg new` scaffolds: OSF's 27 question
titles as headings, each answered or marked `N/A`. The `prereg` skill covers freezing, and the
`osf-registration` skill covers what OSF's form will and will not accept.

## The rule that matters

**Coverage, not length.** A plan is the right length when every claim the results section and
the abstract will make has a hypothesis, a criterion and a test behind it, and nothing else is
in the file. There is no word count to aim at.

Claims hide in places that do not look like hypotheses. Each of these is a claim, and each is
either registered or reported as exploratory:

- a taxonomy or set of categories the results will be sorted into
- the rule that selected the sample, and the unit of analysis
- the test statistic and its null
- the full list of exclusions
- every data column a stratified or sensitivity analysis will need

A plan can fix its main rule and threshold precisely and still leave most of the paper outside
the registration, because the categories and the sample were never written down.

## Before freezing

1. **Write a "Maximum claim under this registration" paragraph.** State everything the paper
   could say as confirmatory if every hypothesis held. Whatever falls outside the paragraph will
   be labeled exploratory. Read it against the abstract you expect to write, and register more
   if the two do not match. Never trade coverage for brevity.
2. **Get an outside read.** Give the plan to someone, or something, that did not write it, and
   ask what the plan leaves undecided. The author knows what the plan means and cannot see what
   it fails to say.
3. **Then commit and freeze.** After the freeze a change is an amendment.

## Form

**The title is a question.** "Does caching reduce median latency?", not "Latency under a cache".

**Hypotheses are `**H1.**` to `**Hn.**`, one sentence each.** Fold the rationale into the
sentence where it is not obvious, and leave it out where it is. Follow them with one line
naming the hypothesis that carries the design.

**Inference criteria is a table**, `| hypothesis | holds when |`, with a numeric condition in
every row. Any prose reading of the outcomes is a short paragraph under the table.

**Void and gate conditions are bold one-liners.** "**All hypotheses are void if H3 fails.**"

**`N/A` gets one clause, never a second sentence.** `N/A — no treatment; the data are fixed.`

An invented study, in this register:

```markdown
# Does caching reduce median latency?

## Research questions or hypotheses

**H1.** Median request latency is lower with the cache enabled than with it disabled.

**H2.** The reduction is larger for read requests than for write requests, because only reads
are served from the cache.

**H3.** With the cache enabled and its capacity set to zero, median latency does not differ
from the cache-disabled condition.

H3 carries the design. Without it, H1 is consistent with the two builds differing in something
other than the cache.

## Inference criteria

| hypothesis | holds when |
|---|---|
| H1 | the 95% interval for the difference in medians, disabled minus enabled, lies above 0 ms |
| H2 | the read reduction exceeds the write reduction by at least 5 ms |
| H3 | the 95% interval for the difference lies within ±2 ms |

**H1 and H2 are void if H3 fails.**
```

## Design habits

- **At least one control that can fail.** A check that passes whatever the system does shows
  only that nothing was applied. H3 above is a control: a zero-capacity cache that still
  changed latency would void the rest.
- **At least one registered outcome that would favor whatever is under examination**, named as
  such in the file. A design that can only embarrass its target is a bad design.
- **Foreknowledge stated as fact.** Say what was already seen, including anything read that
  anchors a prediction. If a published number was seen before a threshold was chosen, say so:
  the threshold is then informed by that number, and meeting it is weaker evidence than meeting
  a threshold chosen blind.

## Which headings earn prose

Four of the 27 headings are worth paragraphs. The other 23 are one line each.

| earns paragraphs | what goes there |
|---|---|
| Research questions or hypotheses | the hypotheses, and which one carries the design |
| Foreknowledge of data or evidence | what was already seen, stated plainly |
| Inference criteria | the decision table |
| Sample size | n, and what it can and cannot resolve |

On OSF, "Foreknowledge of data or evidence" is multiple choice, so the paragraph goes under
"Explanation of foreknowledge and managing unintended influences".

## What to cut

- **A reasoning column on every prediction.** Justify the predictions that are not obvious. A
  threshold that is arithmetic on two numbers already in the plan needs no rationale.
- **Sections that argue for their own existence.** Write the answer, not the answer plus why it
  is the answer. A sentence that defends the design instead of stating it comes out.
- **Context repeated across sibling registrations.** Foreknowledge, published numbers and
  standing principles shared by several plans go in one `CONTEXT.md` that each plan points at.
  Attach it to the OSF draft with `prereg freeze --osf --attach`.
- **A "what this cannot show" section in every file.** State a limit once, where it arises.

Too much. The prediction is fine, and the paragraph after it is the plan appraising its own
method:

```markdown
**Prediction:** the median falls by at least 10 ms in 4 of the 5 services.

**Why medians:** Medians are robust to the long tail of slow requests, which would otherwise
dominate a mean. They are also easier to interpret, and intervals from a bootstrap quantify
the uncertainty directly without distributional assumptions.
```

Too little. The rule is exact, and the plan stops there:

```markdown
## Inference criteria

The cache helps if median latency falls by at least 10 ms.
```

It does not say which services are measured or how they were chosen, whether the unit is a
request or a service, which requests are excluded, or how "read" and "write" are told apart.
A results section that reports any of those is reporting something the plan never fixed.

## When to reach for this

- While drafting a PREREG.md, before the first commit of it
- When a plan has grown long without registering more
- When a plan is short and the paper it supports is not
- Before `prereg freeze`, for the maximum-claim paragraph and the outside read

## What it will not do

It does not make a design sound. A plan can follow every habit here and still test the wrong
thing. It is also not a standard: another field, another group or another study may have good
reasons to write a plan differently, and `prereg` will freeze that plan just the same.
