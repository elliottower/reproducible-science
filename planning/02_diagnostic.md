# 2. Diagnostic — automated verification is bounded by addressability, not by checker quality

## Claim

Agentic auditors plateau because the numbers they are asked to check are not addressable,
not because the agents reason poorly. The bottleneck is documentation practice.

## The evidence, across four model generations

From HAL's published CORE-Bench results, decrypted with `hal-decrypt` (password `hal1234`,
hardcoded in the public source — the encryption is a contamination guard, not access
control). All Claude Code scaffold, `corebench_hard`, 45 tasks each:

```
model                     acc    written   vision    w-v      cost
claude-opus-4-1         0.422    0.389    0.500    -0.111   $331.79
claude-opus-4-5         0.778    0.722    0.853    -0.131    $87.16
claude-sonnet-4         0.467    0.500    0.500     0.000    $65.58
claude-sonnet-4-5       0.622    0.611    0.706    -0.095    $68.33
claude-3-7-sonnet       0.000    0.000    0.000     0.000     $0.16   failed run, excluded
```

**Written accuracy is never above vision accuracy.** Reading a label off a plot beats
reporting a number from an artifact, in every run where either is non-zero.

**And the gap does not close with capability.** Opus 4.5 is nearly twice as accurate
overall as Opus 4.1 and carries the *largest* gap. If locating a number in a results file
were a capability limitation, stronger models would narrow it. Four generations say
otherwise, which is the observation the whole position rests on.

`written_accuracy` and `vision_accuracy` are HAL's own published fields, so the split is
not something this paper has to argue for.

### Qualifiers that must travel with the table

- **Scaffold-dependent.** One Core Agent + Gemini 3 Pro run inverts the ordering (0.444
  written, 0.412 vision). HAL report that a scaffold swap can double a model's accuracy, so
  this is evidence about the Claude Code scaffold, not about agents generally.
- **One run per configuration.** The pattern is across models, not within-model variance.
  Four points with a consistent sign is stronger than one point, and is still not an
  interval.
- **Denominators unstated.** Question counts behind each rate, and whether they are
  per-question or per-task, are not given in the results and must not be assumed.

### Cost, separately

Opus 4.1 spent $331.79 to reach 0.422; Opus 4.5 spent $87.16 to reach 0.778. Four times the
cost for roughly half the accuracy, one generation apart. Reportable on its own, and
independent of the addressability claim.

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
