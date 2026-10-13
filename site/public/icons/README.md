# Icons

One icon per check `repro ci` runs, each cut out of one circle.

| file | depicts |
|---|---|
| `prereg.svg` | a lock: the plan frozen before the run |
| `results.svg` | two links side by side: the ledger's chain |
| `claims.svg` | a document with lines: the manuscript's printed values |
| `citations.svg` | quotation marks: the quoted passages |
| `reruns.svg` | a three-quarter circular arrow: a command run again |

These are dark on a light ground, for documents. The white-on-dark forms a badge's label
carries are in `packages/repro/src/repro/icons/`, one file per check, where `repro ci init`
reads them. Replacing a file there is the whole change to a badge's icon.
