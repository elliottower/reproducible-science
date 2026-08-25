<div align="center">

# reproducible-science

**Check that a paper says what its artifacts contain.**

[![CI](https://img.shields.io/github/actions/workflow/status/elliottower/reproducible-science/ci.yml?branch=main&logo=github&label=CI)](https://github.com/elliottower/reproducible-science/actions?query=branch%3Amain+workflow%3ACI)
[![docs](https://img.shields.io/badge/docs-live-blue)](https://elliottower.github.io/reproducible-science/)
[![pypi](https://img.shields.io/pypi/v/reproducible-science?label=%20)](https://pypi.org/project/reproducible-science/)
[![python](https://img.shields.io/pypi/pyversions/reproducible-science)](https://pypi.org/project/reproducible-science/)
[![license](https://img.shields.io/pypi/l/reproducible-science)](LICENSE)

[Documentation](https://elliottower.github.io/reproducible-science/) ·
[Specification](docs/SPEC.md) ·
[Try it in the browser](https://elliottower.github.io/reproducible-science/demo/)

</div>

---

A number in a manuscript names a claim. The claim names a run. The run names its outputs,
hashed when they were recorded, and its inputs, hashed before it started.

Nothing here searches a document for a printed number, because a search finds that number
wherever it appears and calls it verification. Every check resolves a typed address in a
hash-pinned artifact, and reports what it found.

```console
$ repro verify
  Table 2, "ICC = 0.42"          verified   results.json /icc = 0.42
  Section 3, "p < 0.05"          MISMATCH   the source reads p = 0.051
  Appendix B, "n = 60"           unchecked  results.json is not there
  1 of 3 assertions failed, 1 could not be checked.
```

Three outcomes, not two. A check that could not run is reported as such rather than counted
as a pass — which is the failure this project exists to prevent.

## The toolkit

- **[`repro`](packages/repro)** — verifies declared evidence against hash-pinned artifacts.
  `pip install reproducible-science`
- **[`citations`](packages/citations)** — checks that quotations resolve in the sources they
  cite, page numbers included. `pip install citations`
- **[`results`](packages/results)** — seals inputs, records outputs, binds manuscript claims to
  runs, in a hash-chained ledger. `pip install results-cli`
- **[`prereg`](packages/prereg)** — freezes a plan before running and records what changed
  after. `pip install prereg`

Installing one never drags in the others. Preregistration is optional: a claim is confirmatory,
exploratory, or not applicable, and only the first needs a plan.

## Getting started

```bash
pip install reproducible-science     # all four tools
repro init my-paper
```

Then follow the [quickstart](https://elliottower.github.io/reproducible-science/), or run the
[browser notebook](https://elliottower.github.io/reproducible-science/demo/) — it executes the
published packages with no install at all.

## Resources

- [Documentation](https://elliottower.github.io/reproducible-science/) — guides and reference
- [Specification](docs/SPEC.md) — what a decision means, and what it deliberately does not
- [Development](DEVELOPMENT.md) — the workspace, the gates, the release procedure
- [Contributing](CONTRIBUTING.md) · [Code of conduct](CODE_OF_CONDUCT.md) · [Security](SECURITY.md)

## Claude Code

```
/plugin marketplace add elliottower/reproducible-science
```

MIT licensed.
