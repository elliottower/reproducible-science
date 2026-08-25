# 2. Diagnostic — automated verification is bounded by addressability, not by checker quality

## Claim

Agentic auditors plateau because the numbers they are asked to check are not addressable,
not because the agents reason poorly. The bottleneck is documentation practice.

## The evidence that makes this available, and it is surprising

From HAL's published CORE-Bench results, decrypted with `hal-decrypt` (password `hal1234`,
hardcoded in the public source — the encryption is a contamination guard, not access
control):

```
Claude Code + Opus 4.5, corebench_hard, 2025-12-01
  accuracy          0.778
  written_accuracy  0.722    numeric questions
  vision_accuracy   0.853    figure questions
  total_cost        $87.16 over 45 tasks
  35 succeeded / 10 failed

Core Agent + Gemini 3 Pro, 2025-11-22
  accuracy          0.400
  written_accuracy  0.444
  vision_accuracy   0.412
```

**The agent is better at reading charts than at reporting numbers.** 85.3% on "what is the
orange line labeled" against 72.2% on "report the test accuracy of NB with ngram on the
combined corpus."

That is backwards from every intuition about model capability, and the explanation is the
claim: reading a chart label is one visual lookup, while reporting a number requires
running code, locating the right section among 21 structurally identical ones, and reading
the right label from an unnamed stdout stream. The numbers are harder than the pictures
because the numbers have no names.

`written_accuracy` and `vision_accuracy` are HAL's own published fields, so the split is
not something this paper has to argue for.

## What is not claimed

- Not that agents are bad. One scores 77.8% and the benchmark is reported solved.
- Not a competing system. There is nothing to be state of the art against — every entry on
  that leaderboard is an LLM agent, and no deterministic system is present.
- Not a leaderboard entry. CORE-Bench scores a `report.json` with one answer per question
  and has no abstention channel, so a deliberately abstaining system reads as low accuracy.

## What must be registered before analysis

The comparison targets have already been inspected. 72.2%, 85.3%, $87.16 were read before
any plan was frozen. That is declarable foreknowledge under the same rule position 1
applies to itself, and it is only survivable if declared in advance of the analysis rather
than discovered in review.

Registration must fix: which runs are analyzed, how coverage is defined for a deterministic
comparator, what result would falsify the bottleneck claim, and whether cost is reported at
all given the unresolved discrepancy below.

## Open problems

**The cost fields do not reconcile.** Opus reports $87.16 over 45 tasks; the Gemini run
reports $0.01366 against 39M prompt tokens. Those differ by orders of magnitude and at
least one means something other than what it appears to. Do not quote either until
resolved.

**The 95% "solved" figure was not found.** The Claude Code + Opus 4.5 run in the published
traces reads 77.8%. The saturation claim likely refers to a different scaffold or a later
run and must be located before being cited.

**Selective prediction is the right framing** — a predictor paired with a selection
function that abstains, reported on a risk-coverage curve, summarized by AURC, with AUGRC
(NeurIPS 2024) correcting known reporting flaws. One operating point on such a curve is a
recognized evaluation mode rather than a self-selected subset.

But a deterministic contract's abstention is **not tunable** — it abstains exactly when the
locator fails to resolve. A full risk-coverage curve requires a threshold there is no
principled way to vary, so the report is a single point and the framing has to survive
that.

## The objection most likely to kill it

**"You are explaining a capability gap with a documentation story you happen to have a tool
for."** The written/vision inversion is consistent with the claim but does not establish
it — an alternative explanation is that written questions require successful code execution
and figure questions do not, which is an execution-difficulty account with nothing to do
with addressability.

Distinguishing them is the experiment: among tasks where execution succeeded, does written
accuracy still trail vision accuracy? `successful_tasks` and `failed_tasks` are in the
results, so this is answerable from data already in hand — and it should be registered as
the discriminating test before it is run.

## Venue

Wherever position 1 lands, or an ICML-style position track. Weaker alone; strong as the
mechanism behind position 1's rate.

## Next actions

1. Pull the remaining eight Opus runs — results-only archives are ~4 KB, so this is minutes.
2. Locate the 95% claim.
3. Resolve the cost fields.
4. Register the execution-conditioned test before running it.
