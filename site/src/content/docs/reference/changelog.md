---
title: Changelog
description: Changelog — Reproducible Science
---

{/* Generated from CHANGELOG.md. Edit that file, not this one. */}

Every package in this workspace carries the same version and is released on the same day, so
one file covers all four. Entries are scoped with a `[package]` prefix; unprefixed entries
apply to the workspace as a whole.

## 0.2.0 — 2026-08-24

First release from the monorepo. The four packages previously released separately from their
own repositories; they now share one version, one lockfile and one release.

Several entries below are corrections to results the tools reported. They are listed first
because a verifier that reports a clean run it did not earn is worse than one that fails.

### Fixed

- **[citations] A quotation matched a source that contradicted it.** The fallback used when a
  verbatim match fails stripped every non-alphanumeric character, so `p < 0.05` resolved
  against a source reading `p = 0.05`, and `-0.42` against `0.42`. It now removes whitespace
  and nothing else, which is what a PDF extractor actually mangles.
- **[citations] A source edited after being pinned still passed.** Every quotation was checked
  against the file on disk and nothing compared it to the recorded digest, so a changed source
  produced a clean run. A broken pin now fails the run and is reported before the quotation
  results, because it changes how they should be read.
- **[citations] `--strict` did not fail on unresolved quotations.** A deleted source, an
  unpinned one, an unparseable claims file and a missing `pdftotext` all left a build green
  while nothing had been verified.
- **[citations] BibTeX entries were split with a regex** that dropped or merged entries
  containing nested braces. Entries are now separated by counting braces.
- **[results] The ledger could be extended after being tampered with.** `append_event` built
  on a chain already reported as edited and re-anchored over the evidence, so a damaged
  ledger verified clean from the next ordinary command onward. It now refuses.
- **[results] Truncating the ledger and re-anchoring was a two-command clean bill of health.**
  `reanchor` now refuses a chain reported as truncated, which is the cheapest tampering there
  is: no line has to be forged, so the hash chain stays intact and only the count disagrees.
- **[results] `verify --files` reported a deleted sealed file as `ok`**, and reported a path
  sealed under several different hashes as `ok` when the file matched any one of them.
- **[prereg] `freeze` proceeded when there was no commit to name.** `git()` returns empty on
  any non-zero exit, so a missing binary, a locked index and a directory outside a repository
  all read as success, and a freeze recorded a commit-shaped string in place of a commit.
- **[prereg] The log was editable after freezing.** The plan hash deliberately stops at the
  log, which left the only record of what changed after registration freely deletable while
  `check` still reported the plan unchanged. Entries are now chained, with an anchor
  recording the length so a removal from the end is visible.
- **[prereg] `check` passed at a repository root when a plan below it was never frozen**, so
  whether an unfrozen registration passed CI depended on which directory it ran from.
- **[repro] A structured array element resolved as a single value.** A two-field record
  stringified as `(0.91, 0.02)` and was reported as one extracted value, so a manuscript
  reporting `0.91` could verify against a record rather than a number.
- **[repro] A passage found on the wrong page reported as verified.** The page was recorded as
  a warning, and no policy reads decision warnings, so the assertion was unenforceable.
- **[repro] Duplicate artifact and claim ids silently kept the last declaration**, which could
  drop a broken pin from the report entirely and leave the strict policy passing with no
  violations at all.
- **[repro] Duplicate keys in JSON resolved to whichever came last**, so one artifact could
  hold two values for one quantity and address one of them with nothing said about the other.

### Added

- **[repro] Conformance fixtures now pin the reason and the artifact validity**, not only the
  outcome. Four cases share the outcome `unchecked` and three share `not_found`; without the
  reason, a defect in the tool and a fact about the manuscript were indistinguishable.
- **[repro] A `broken_pin` conformance case**, which the fixture set named in its skip list
  but never contained.
- **Coverage is measured and gated at 70%.** Most suites drive a CLI in a real subprocess,
  which coverage does not follow by default, so the CLI modules reported 0–18% while their
  tests passed.
- **Dependency floors are resolved in CI** (`--resolution lowest-direct`), which found two
  declared minimums that could not be installed at all.
- **Lockstep versioning is enforced** by `make versions`: every package carries one version
  and pins its siblings to that series.

### Changed

- **Restructured as a uv workspace.** One lockfile, four packages, one release.
- **Python 3.11 is now required.**
- **[citations] [repro] Raised `pyyaml` to `>=6.0.2` and `pydantic` to `>=2.9`.** The previous
  floors resolved to versions that fail to build on current Python.
