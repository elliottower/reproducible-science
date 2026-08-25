# Four positions, four artifacts

One body of work supports four distinct claims. They are not alternatives and they do not
merge — different subjects, different evidence, different audiences. Merging any two
produces a study that cannot fail cleanly.

| # | Position | Subject | Artifact | Status |
|---|---|---|---|---|
| 1 | [Descriptive](01_descriptive.md) | the literature | `experiments/addressability-sample/` | **preregistered, draft, nothing run** |
| 2 | [Diagnostic](02_diagnostic.md) | claim-auditing systems | HAL trace analysis | data in hand, unregistered |
| 3 | [Instrument](03_instrument.md) | the specification | conformance suite + 2nd implementation | partially built |
| 4 | [Normative](04_normative.md) | practice | position paper + LessWrong post | argued, unwritten |

## The dependency, which is not a merger

If addressability is 20%, every automated auditor is capped at 20% coverage regardless of
how good it is. Position 1 bounds position 2's usefulness. That is a citation between two
studies, not one study.

## The commitment that runs through all four

**Addressability is relational, not a property of artifacts.** A claim is addressable
*under a locator grammar*. The existing preregistration already takes this position —
values are addressable "at a nameable position under the frozen locator grammar," with the
grammar pinned by digest.

The consequence has to be carried everywhere: **H1's rate is a statement about a grammar,
not about science.** A richer grammar raises it. The CORE-Bench pilot demonstrated exactly
this — stdout output unaddressable under the current grammar, perfectly addressable under a
section-plus-label one.

Position 4 is the exception, and it is why it needed reframing twice. The normative claim
is that **a format should declare its own addressing scheme** — grammar-independent, and
format-level rather than file-level. CSV declares it via the header row; JSON declares it
via keys; plain text declares nothing.

The intermediate attempt, "artifacts should be self-describing," failed against its own
motivating example: the CORE-Bench log *contains* both `test_accuracy:` and its section
header, so the names are present. What is absent is any declaration of how those names
compose into an address.

## Workflow

```
spec  ->  critique  ->  revise  ->  run
```

Currently at **spec**. Nothing runs until 1's preregistration is frozen and 2 has a
registration of its own.

Each spec states what it claims, what evidence exists versus what is missing, its venue,
and the objection most likely to kill it. They are written to be attacked.

## What must not happen

- Position 4 concluding with "adopt this package." It concludes with the property; the
  specification is a footnote demonstrating the property is checkable.
- Position 2 running before it is registered — the comparison targets have already been
  inspected (72.2% written, 85.3% vision), which is declarable foreknowledge, not a
  disqualifier, but only if declared before the analysis.
- Position 1 being restated anywhere. It exists. Everything else cites it.
