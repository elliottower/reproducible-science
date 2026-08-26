# One printed word, three encodings

`pdftotext` renders an accented letter as a spacing accent followed by a dotless i —
`na¨ıve` for `naïve` — and the other extractors produce their own variants. `verify.fold`
normalizes NFKC, which composes a combining mark onto the letter *before* it and does nothing
for an accent that arrives before its letter: NFKC expands the spacing accent into a space plus
a combining mark, welding a space into the middle of the word. The manuscript is right, the
extraction is legible to a human, and the quotation does not resolve.

This is not a reader problem, and triangulation correctly declines to solve it: every extractor
produces its own mangling, all of them agree the passage is absent, and the agreement is
unanimous.

`results.json` holds the measurement. Two candidates:

| candidate | what it does |
|---|---|
| `broad` | strip spacing accents, map dotless i, NFKD, drop every combining mark |
| `narrow` | map dotless i, move a spacing accent onto the letter it precedes, NFKC |

Both reduce the four encodings of one word to one string. They differ in what else they change:
`broad` makes `résumé` equal `resume`, `Kästner` equal `Kastner`, and `naïve` equal `naive`;
`narrow` conflates nothing. Neither touches `p < 0.05` against `p = 0.05` or `-0.42` against
`0.42`, which is the failure the `skeleton` docstring records.

Over the claims corpora — 3,250 passage checks across 324 pinned sources — neither candidate
changed a single outcome, because that corpus has no unresolved quotation for either to
resolve. The zero is evidence about the risk and none about the benefit, and a corpus that
carries the case is what would measure it.

```console
uv run python research/normalization/diacritic_ab.py \
    --claims-root ~/Documents/GitHub --out research/normalization/results.json
```

Omit `--claims-root` to run the two checks that need no corpus.
