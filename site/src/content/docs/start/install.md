---
title: Installation
---

Everything at once:

```bash
pip install reproducible-science
```

That installs the verifier and the three tools it works with. To install one alone:

```bash
pip install citations     # quotation checking only
pip install prereg        # preregistration only
pip install results-cli   # the run ledger only
pip install claims-cli    # claims checking only
```

`claims-cli` is the code behind `repro verify`, `stale`, `why`, `numbers`, `export` and
`origins`, under the command `claims`. It runs no command a manifest names, so it suits a
machine that should only read a project's files.

Python 3.11 or newer. Every package carries the same version and is released the same day, so
`0.2.0` of one works with `0.2.0` of the others.

## Coding agent plugins

The skills, hooks and commands that run the tools from inside a coding agent install as a
plugin: for [Claude Code](/start/claude-code/) or for [Codex](/start/codex/).

## Optional extras

Array locators need numpy:

```bash
pip install "reproducible-science[arrays]"
```

Quotation checking against PDFs needs `pdftotext` from poppler:

On macOS:

```bash
brew install poppler
```

On Debian or Ubuntu:

```bash
sudo apt install poppler-utils
```

Without it, a PDF quotation is reported `unchecked` with the reason `extractor_missing`. It is
never reported as absent — a missing tool is a fact about your machine, not about the paper.
