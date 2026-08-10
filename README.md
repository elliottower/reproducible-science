# Citations

One record per cited work, shared across every paper. Organized by the source rather than by
the paper, so a single file answers what a work is and what each of my papers does with it.

```
records/<slug>.yaml
    slug        doi-… or arxiv-… — the identity, derived from the identifier
    title, authors, year, venue, url, doi, arxiv, sha256
    cited_by:
        mechanistic-validity:  {key: merullo2024circuit}
        mechanistic-reference: {key: merullo2024circuit}
        mechanistic-views:     {key: merullo2024}
```

Works are joined on DOI or arXiv id, **never on citation key**. Twenty works are cited under
divergent keys across these three papers, so the key identifies nothing.

## What it is for

A per-paper bibliography hides its own errors. Reading source-first exposes them: the same work
entered twice under different keys, the same paper dated 2021 in one bibliography and 2022 in
another, a url resolved for one paper and missing from the rest. Fix the record once and every
paper inherits it.

## Current state

484 distinct works from three papers. 31 are cited by more than one, and 20 of those under
divergent keys. 193 carry no DOI or arXiv id and are joined on title, which is the weakest link
in the design — a title match can conflate two papers by the same author.

## Rebuilding

```bash
python build.py --scan     # report contributions and collisions, write nothing
python build.py            # write records/
```

Source PDFs live in `pdfs/` and are gitignored; most are under copyright. Each record carries
the identifier and sha256 needed to refetch and verify the identical artifact.
