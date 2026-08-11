# Where pre-registrations go

One convention, all repositories, going forward. Existing documents stay where they are — the
point is that new ones stop scattering, not that fifty files get moved and re-verified.

## The layout

```
experiments/
    <CRITERION_or_ID>_<short name>/
        PREREG.md        frozen before anything ran
        run.py           the code it governs
        tests/
        results/
preregistrations/
    README.md            the freeze registry: commit + SHA-256 per document
```

The pre-registration sits beside the code it governs so the two move together. The registry at
the root records what was frozen and when, so a reader can check the document predates the
result without trusting anyone's word for it.

## Never

- **`paper/`** — that directory is about presentation, and a frozen document is evidence.
- **`submission/<venue>/`** — a venue is temporary. Two pre-registrations sat in
  `msms-subspace-collapse/submission/plosone/` after the paper moved to JASMS, and the obviously
  correct cleanup of that stale folder would have looked like it was destroying them. They turned
  out to be duplicates, but the layout is what made the question frightening.
- **`docs/`** — where `epistatic-circuits` keeps six of them. Documentation is describable;
  a registration is attestable.
- **the repository root** — where `msms-subspace-collapse` keeps eight and
  `knockout-epistasis-dynamics` keeps twenty-two, with no indication of which experiment each
  governs or whether it is frozen.

## Moving one does not break its freeze

A freeze is a commit plus a content hash. Neither depends on the path.

```bash
git show <freeze-sha>:<old/path/PREREG.md> | shasum -a 256   # resolves forever
```

`mechanistic-validity` moved five frozen documents into per-experiment folders and re-hashed
them afterwards; all five were byte-identical and the attestation held. Record the old path
alongside the new one in the registry and nothing is lost.

## The registry

`preregistrations/README.md` carries a SHA-256 per document, taken at freeze. Check it with
`shasum -a 256 *.md`. A test should assert those hashes rather than reading them from the same
file it is checking — a test that takes its expectations from the file under test passes
regardless of what that file says.

## Amendments

Never edit a prediction. Append a dated deviation recording what was predicted, what happened,
and why they differ. `msms-subspace-collapse/PREREGISTRATION.md` does this correctly: its only
changes since freeze are a provenance line and a section recording that a preregistered
criterion **failed** at k=15, with the number that failed it. That is the mechanism working.

## Draft is not frozen

`PREREGISTRATION_V2_SPEC.md` in that repository reads `Status: DRAFT — freeze with SHA before
running any confirmatory computation`. A draft spec is a plan; only a frozen document with a
commit behind it is a registration, and the two should never be cited the same way.

## Current state, for reference

51 distinct pre-registration documents across seven repositories. Only `mechanistic-views-NEW`
and `mechanistic-validity-NEW2` follow the layout above. `neural-geometry-reliability` is close,
keeping them flat under `experiments/`. The rest are at repository roots or in `docs/`.
