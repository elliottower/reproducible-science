<div align="center">

# reproducible-science

**Command-line tools and a Claude Code plugin that check whether a manuscript's claims match
its artifacts.**

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

Write down what your paper claims and where each claim comes from. `repro verify` checks
every one against the file it names and tells you which ones hold.

Quotations are matched against the sources they cite, page numbers included. Reported numbers
are compared against the value stored at an address you gave — never by searching a file for a
number that looks close enough.

```console
$ repro verify
  Table 2, "ICC = 0.42"          verified   results.json /icc = 0.42
  Section 3, "p < 0.05"          MISMATCH   the source reads p = 0.051
  Appendix B, "n = 60"           unchecked  results.json is not there
  1 of 3 assertions failed, 1 could not be checked.
```

When a check cannot run at all — a missing file, a PDF with no extractable text — it reports
that, and the run does not pass.

## The toolkit

- **[`repro`](packages/repro)** — verifies declared evidence against hash-pinned artifacts.
  `pip install reproducible-science`
- **[`citations`](packages/citations)** — checks that quotations resolve in the sources they
  cite, page numbers included. `pip install citations`
- **[`results`](packages/results)** — seals inputs, records outputs, binds manuscript claims to
  runs, in a hash-chained ledger. `pip install results-cli`
- **[`prereg`](packages/prereg)** — freezes a plan before running and records what changed
  after. `pip install prereg`

Each tool is its own distribution, so installing one brings only that one. Preregistration is
optional — you mark a claim confirmatory, exploratory, or not applicable, and only the first
kind needs a plan behind it.

## Getting started

```bash
pip install reproducible-science     # all four tools
repro init my-paper
```

```console
$ prereg freeze                                    # lock the plan; names a git commit
$ results seal analysis.py data.csv                # hash the inputs, before the run
$ results run output.json --run-id exp_001         # hash the outputs, after it
$ results claim "ICC = 0.42" --run-id exp_001 --location "Table 2"
$ repro verify
```

The [browser notebook](https://elliottower.github.io/reproducible-science/demo/) runs the
published packages with nothing installed.

## What it addresses

Values can be addressed inside JSON, YAML, CSV/TSV, SQLite, and NumPy `.npy`/`.npz` files.
Parquet, HDF5, NetCDF and XLSX aren't supported yet — point a manifest at one and you get
`format_unsupported` instead of a guess.

## Resources

- [Documentation](https://elliottower.github.io/reproducible-science/) — guides and reference
- [Specification](docs/SPEC.md) — what a decision means, and its limits
- [Development](DEVELOPMENT.md) — the workspace, the gates, the release procedure
- [Contributing](CONTRIBUTING.md) · [Code of conduct](CODE_OF_CONDUCT.md) · [Security](SECURITY.md)

## Claude Code

```
/plugin marketplace add elliottower/reproducible-science
```

MIT licensed.
