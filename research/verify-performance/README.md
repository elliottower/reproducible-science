# Where `citations verify` spends its time

The measurements behind three commits on `quote-selector`, kept because those commit messages
quote numbers from them and a number with no artifact behind it is the failure these tools
exist to catch.

| file | what it holds |
|---|---|
| `data/00_summary.json` | the ranked changes, each with its number and the key it came from |
| `data/01_baseline_profile.json.gz` | the current implementation, 15 of 16 claims files, 1292.6 s |
| `data/03_matrix.json.gz` | the prototype across 13 configurations: cold, warm, a worker sweep, and invalidation cases I–M |
| `data/04_spawn_and_page.json` | the process-spawn floor, poppler's load cost, one page against a whole document |

The two `.gz` files are compressed only for size; `gunzip -c` gives the JSON the harness wrote.

## What they establish

**95.07% of wall clock is the poppler subprocess.** OpenSSL sha256 is 4.64%, libyaml 0.17%, and
interpreted Python **0.13%** — which is what a rewrite in another language would be competing
for. A faster *reader* attacks the 95%; that question is answered next door in `pdf-readers/`,
and the answer there is that the fast readers resolve fewer passages.

**`functools.lru_cache` does not memoize exceptions.** `extract` raised on an unreadable source,
so the cache stored every reading it managed and none of the ones it could not, and a document
no extractor could open was re-attempted once per quotation. 2,210 poppler invocations for 14
unique artifacts, 158 times the work the corpus requires. Fixed in `a334122`; the same run is
now 14.6 seconds.

## The caveat this directory must not be read without

`01_baseline_profile.json.gz` measured a **broken configuration**. Its `match_calls` is 0: the
matcher never ran, because every source declared `extract_cmd: pdftotext -layout` on a
convention where an input and an output path are appended, and `citations` appends the input
alone and reads stdout — so the command wrote a file, printed nothing, and all 2,358 quotations
came back `unchecked`.

So `1292.6 s → 11.65 s` is *broken current implementation* against *working prototype*, and is
not a like-for-like speedup. `profile_baseline.py --healthy` would close that gap and has not
been run. The 95% figure survives the caveat — a working run also spends its time in
extraction, and adds matching on top — but the absolute seconds do not.

The prototype under `pipeline.py` and `rendition.py` is not proposed for merge as it stands. It
cross-validates against the independent gate in `mechanistic-validity-NEW2`, reaching the same
three failing quotations by name and the same count of normalized matches, which is the reason
to trust its verdicts rather than only its timings.
