# Number categories

Every numeric token in an extracted article receives one category. The scan does not ask
whether a number is a finding — that judgment is what made three coders disagree in the
pilot, and it is not needed. It asks whether an artifact could hold a counterpart.

Categories fall in three groups, and the groups are reported separately rather than
collapsed to two.

## Traceable — goes to the verifier

| category | what it is | why an artifact could hold it |
|---|---|---|
| `table_cell` | a cell in an aligned table row | a results table is the paper's most direct restatement of what a run produced |
| `measurement` | a quantity stated in prose about the work | the run that produced it wrote it somewhere |
| `parameter` | a value bound to a named symbol — `d = 128`, `p, q are set to 1` | a config file or a call site sets it, and a paper stating 128 where the code sets 256 is the mismatch an audit exists to surface |
| `equation_content` | a number inside a display equation | the equation is implemented or it is not |

## Untraceable — nothing in an artifact corresponds

| category | what it is |
|---|---|
| `bibliographic` | inside a DOI, URL, SWHID, ISBN, a bracketed reference index, a page number, a publication year |
| `structural` | a section number, an equation label, an affiliation marker, a cross-reference (`according to (3)`), an inline enumeration marker, a running header or footer |

## Reported separately — a limit of the instrument, not a property of the article

Folding any of these into either group above would publish a fact about the scanner as a
fact about the paper.

| category | what it is |
|---|---|
| `figure_axis` | inside an aligned block the caption names as a figure; tick labels, with no row to attach them to |
| `dense_line` | four or more numbers on a line matching none of the known layouts |
| `orphan` | the line holds the number and nothing else, so there is no label to match on |
| `bounded` | qualified by a bound or approximation (`at most 10 minutes`, `~0.9`), so it states no single quantity and no comparison can succeed or fail |
| `extraction_failed` | a flattened formula or a superscript pushed onto the baseline; the article was not read at that position |

## Nine development articles

All outside the sampled 60, per `DEV_LOG.md`.

| article | tokens | traceable | table_cell | measurement | untraceable | separate |
|---|---:|---:|---:|---:|---:|---:|
| Boraud:2021 | 412 | 69% | 192 | 74 | 103 | 23 |
| Broman:2020 | 442 | 59% | 192 | 70 | 130 | 50 |
| Eglen:2021 | 246 | 37% | 12 | 66 | 82 | 73 |
| Kim:2021 | 1986 | 81% | 1325 | 282 | 245 | 123 |
| Livernoche:2023 | 433 | 36% | 59 | 96 | 209 | 66 |
| Moalla:2023 | 822 | 61% | 347 | 147 | 238 | 84 |
| Moens:2023 | 496 | 40% | 0 | 182 | 142 | 155 |
| Obadage:2025 | 1054 | 62% | 396 | 241 | 249 | 154 |
| Wallrich:2022 | 248 | 40% | 42 | 56 | 96 | 52 |
| **all nine** | **6139** | **63%** | **2565** | **1214** | **1494 (24%)** | **781 (13%)** |

`Moens:2023` returns zero table cells, which is correct: it prints no tables and reports
every result as a figure. Its 73 `figure_axis` and 41 `orphan` are where those results went.

## Layout decisions the scan makes

Three properties are not visible in a line on its own, so a document pre-pass supplies them.

**Running headers.** A line recurring three or more times once its digits are blanked and
its whitespace collapsed is printed by the page template. Whitespace collapses as well as
digits because a footer sets its page number in a fixed column: the number changes width
from page 9 to page 10 and the padding before it changes to compensate.

**Tables against figures.** A run of three or more consecutive lines, each carrying two or
more numbers, whose numeric tokens land at two or more stable character offsets, is an
aligned block. Alignment alone cannot say which kind: tick labels on stacked panels align as
readily as columns do. The caption decides, and a table caption anywhere in a twenty-line
window wins over a figure caption rather than the nearer of the two winning — extraction
order does not preserve which caption a block sits under, and the two errors do not cost the
same. Reading a table as a figure discards the paper's most checkable numbers; reading tick
labels as cells sends a few values to a verifier, which reports them unmatched.

**Prose against layout.** A block averaging more than 1.5 words of three or more letters per
number is prose. Consecutive sentences naming `VGG-16`, `PreAct-18` and `DenseNet-121` align
as readily as columns do; they run 2.0 to 3.0 by this measure and a table row runs 0.0.
