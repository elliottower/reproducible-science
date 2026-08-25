# reproducible-science

[![CI](https://img.shields.io/github/actions/workflow/status/elliottower/reproducible-science/ci.yml?branch=main&logo=github&label=CI)](https://github.com/elliottower/reproducible-science/actions?query=branch%3Amain+workflow%3ACI)
[![coverage](https://img.shields.io/codecov/c/github/elliottower/reproducible-science?logo=codecov&logoColor=white)](https://codecov.io/gh/elliottower/reproducible-science)
[![pypi](https://img.shields.io/pypi/v/reproducible-science)](https://pypi.org/project/reproducible-science/)
[![python](https://img.shields.io/pypi/pyversions/reproducible-science)](https://pypi.org/project/reproducible-science/)
[![license](https://img.shields.io/pypi/l/reproducible-science)](LICENSE)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![DOI](https://zenodo.org/badge/1337959942.svg)](https://doi.org/10.5281/zenodo.22100272)

Command-line tools that check whether a paper's claims match its artifacts.

1. **Three outcomes kept apart**: a value that disagrees, a value the artifact is silent on,
   and a check that never ran. A pass/fail report collapses them, and their remedies differ.
2. **Deterministic and offline.** A check is a digest comparison and a decimal comparison, so
   it runs on every commit rather than once before submission.
3. **Facts separated from verdict.** The engine computes no verdict; a policy maps outcomes to
   severity, so an unchecked citation is acceptable in a draft and disqualifying in a submission.
4. **One contract over all three kinds of evidence** — a quotation in a source, a value at a
   location in a machine-readable file, a cell in a table — through one engine and one report.

```bash
pip install reproducible-science
```

See our [Claude Code plugin](https://elliottower.github.io/reproducible-science/start/claude-code/),
which traces results at the time of experimentation.

```text
/plugin marketplace add elliottower/reproducible-science
```

**Required dependency:** poppler (`pdftotext`), for reading PDF sources.

```bash
brew install poppler              # macOS
sudo apt install poppler-utils    # Debian/Ubuntu
```

## Documentation

**[elliottower.github.io/reproducible-science](https://elliottower.github.io/reproducible-science/)**

The docs include a notebook that runs the published packages in your browser, with nothing to
install.

## Install

| tool | what it checks |
|---|---|
| [`prereg`](packages/prereg) | that the plan you ran is the plan you froze, against a commit and a content hash |
| [`results`](packages/results) | that a reported number came from a recorded run over sealed inputs |
| [`citations`](packages/citations) | that a quoted passage occurs in the source cited for it |
| [`repro`](packages/repro) | that every declared claim holds against its pinned artifact, and which ones do not |

`pip install reproducible-science` brings all four. Each is also its own distribution —
`prereg`, `citations`, `results-cli` — so installing one brings only that one.

## Getting started

Write down what your paper claims and where each claim comes from. `repro verify` checks every
one against the file it names and tells you which ones hold.

```console
$ prereg freeze                                    # lock the plan; names a git commit
$ results seal analysis.py data.csv                # hash the inputs, before the run
$ results run output.json --run-id exp_001         # hash the outputs, after it
$ results claim "ICC = 0.42" --run-id exp_001 --location "Table 2"
$ repro verify
repro.yaml

  ok    icc          metric   /icc = 0.42
  MISS  pvalue       metric   p: manuscript prints 0.031, results.json holds 0.051
  GONE  n            metric   /n does not resolve in results.json

  1 mismatch, 1 not_found, 1 verified
  policy publication: FAILED  (2 errors, 0 warnings)
    error   evidence.mismatch          pvalue/metric: p: manuscript prints 0.031, results.js
    error   evidence.not_found         n/metric: /n does not resolve in results.json
```

`ok` holds, `MISS` disagrees with the artifact, `GONE` names an address that no longer
resolves. Three further outcomes appear in longer runs: `--` for a check that could not run,
`none` for a claim offering no evidence, and `ERR` for a source that could not be read.

Quotations are matched against the sources they cite, page numbers included. Reported numbers
are compared against the value stored at an address you gave — never by searching a file for a
number that looks close enough. When a check cannot run at all, it reports that, and the run
does not pass.

Preregistration is optional — you mark a claim confirmatory, exploratory, or not applicable,
and only the first kind needs a plan behind it.

## Contributing

[Contributing](CONTRIBUTING.md) to get started, [Development](DEVELOPMENT.md) for the workspace
and release machinery, and [docs/SPEC.md](docs/SPEC.md) for what a decision means. Security
issues: [SECURITY.md](SECURITY.md).

MIT licensed.
