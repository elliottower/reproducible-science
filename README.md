# prereg

Freeze a plan before you run it, and record what changed after.

```bash
uv tool install prereg

prereg new V16_reliability_ceilings
# fill it in, commit
prereg freeze
prereg log "tolerance now derived from fixtures" --access "no results seen"
prereg check
```

## One file, one rule

```
V16_reliability_ceilings/
    PREREG.md      the plan, then a line, then an append-only log
    tests/  results/
```

**Never edit above the line. Only append below it.**

`prereg check` enforces it — the freeze records a hash of the plan, and any later edit to it
fails the check. Appending to the log does not.

## The log

```
2026-08-11  frozen at 9894e148e429              nothing run
2026-08-13  tolerance now from fixtures         no results seen
2026-08-14  ran                                 results not opened
2026-08-15  C5 failed at k=15: 6.6% vs 5%       results seen
```

The last column is what distinguishes an amendment from a deviation, so you never have to
decide which word to use. `nothing run`, `no results seen`, `results not opened`, `results
seen`. An entry logged before results is an amendment; one logged after is a deviation.

## The plan uses OSF's headings

Verbatim, so the document maps onto an [OSF registration](https://osf.io/prereg/) without being
rewritten. Two of the twenty-seven do the real work:

- **Foreknowledge of data or evidence** — what you have already seen. This is the field that
  catches an exploratory result being reused as though it were confirmatory.
- **Inference criteria** — the decision rule as a commitment, before the number exists.

A heading that does not apply is answered `N/A` with a reason, never deleted.

## What a freeze is

A commit and a hash. The commit is the evidence — it is in history, dated, and not yours to
revise quietly. The hash is the convenience that lets `prereg check` tell you in a second
whether the plan still says what it said.

Neither proves you did not run the experiment first. Nothing can: a timestamp bounds when
something existed, never when work began. If that matters, register the plan somewhere you do
not control.

## Freezing twice

`freeze` writes the status block whether the plan is a draft or already frozen, and it hashes the
plan *after* writing it. Two things follow.

**It is idempotent.** Re-freezing an unedited plan reproduces the same hash, because the commit,
the digest and the date sit on lines the hash skips. So `--force` on an unchanged plan is a no-op
you can run without thinking about it.

**A note on the status line survives.** Write `**Status:** DRAFT — not frozen. Third version; see
Log.` and the note moves onto its own line under the freeze date rather than being appended to it.

`--force` is for a plan that legitimately changed and was re-committed. It is not a way to clear a
`CHANGED` warning: that warning means the plan was edited after freezing, and the honest response
is `prereg log`, not a new hash.

## Writing the header by hand

Don't. `**Status:**`, `**Plan sha256:**` and `**Frozen:**` are output. A hand-written header
produces a document that reads as registered and cannot be verified, which is worse than one that
never claimed to be.

MIT licensed.
