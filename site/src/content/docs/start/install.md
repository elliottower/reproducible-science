---
title: Installation
---


# Installation

Everything at once:

```bash
pip install reproducible-science
```

That installs the verifier and the three tools it works with. To install one alone:

```bash
pip install citations     # quotation checking only
pip install prereg        # preregistration only
pip install results-cli   # the run ledger only
```

Python 3.11 or newer. Every package carries the same version and is released the same day, so
`0.2.0` of one works with `0.2.0` of the others.

## Optional extras

Array locators need numpy:

```bash
pip install "reproducible-science[arrays]"
```

Quotation checking against PDFs needs `pdftotext` from poppler:

```bash
brew install poppler          # macOS
apt install poppler-utils     # Debian/Ubuntu
```

Without it, a PDF quotation is reported `unchecked` with the reason `extractor_missing`. It is
never reported as absent — a missing tool is a fact about your machine, not about the paper.
