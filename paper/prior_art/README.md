# Prior art

The sources the paper's related-work section is checked against.

| file | what it holds |
|---|---|
| `references.bib` | 17 entries, the bibliography the draft cites |
| `prior_art_dois.json` | DOI, title, and authors for each entry, resolved from Crossref |
| `prior_art_arxiv.json` | arXiv identifiers, resolved from the arXiv API |
| `claims/` | quotation records, verified by `citations verify` |
| `reference/` | the PDFs themselves — **not committed** |

`reference/` and `.audit-cache/` are gitignored. The PDFs are publisher copies and this
repository is public, so they stay on disk; `prior_art_dois.json` carries the identifier for
each one, which is enough to fetch them again.

Every identifier here was resolved by title and author against Crossref or DataCite rather
than constructed. Two DOIs guessed during an early draft resolved to real but unrelated
papers, which is the failure this repository's own tooling exists to catch.

## Registered with the citations CLI

```console
citations verify --claims paper/prior_art/claims --only reproducible-science
```

`--only` scopes the check to records this paper's bibliography cites. The project's bib and
claims paths are registered under `reproducible-science` in `$CITATIONS_HOME/papers.yaml`,
which is what `citations build` reads.
