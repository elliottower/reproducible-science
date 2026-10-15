---
title: Zotero
description: There is no Zotero plugin. citations reads the .bib that Better BibTeX exports like any other.
---

There is no Zotero plugin. With the Better BibTeX add-on, a Zotero collection or library can be
exported to a `.bib` with "Keep updated" checked, which registers the export for automation:
according to Better BibTeX's documentation, "any changes to the collection or library will
trigger an automatic re-export to update the file"
([Better BibTeX: automatic export](https://retorque.re/zotero-better-bibtex/exporting/auto/)).
`citations` reads that `.bib` as it reads any other.

The commands that take a `.bib`:

| command | does |
|---|---|
| `citations audit --bib refs.bib` | checks each entry's metadata against the record its identifier resolves to |
| `citations lint --bib refs.bib` | reports repeated keys and author lists written without given names |
| `citations lint --authors refs.bib` | reads each entry's author list back against the registry its DOI or arXiv id names |
| `citations add refs.bib --doi 10.1145/3287560.3287596` | appends one entry, refusing a key the file already has |
| `citations build` | rebuilds a library's records from the `bib:` path each paper lists in its `papers.yaml` |

`audit` and `lint` read the file. `add` is the one command that writes into a `.bib`; on a file
Better BibTeX keeps updated, add the entry in Zotero instead, so the library and the file hold
the same entries.

Not affiliated with or endorsed by Zotero or Better BibTeX.
