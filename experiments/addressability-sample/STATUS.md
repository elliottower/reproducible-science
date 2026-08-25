# Where the scan stands

Three development articles, end to end: extract the paper, enumerate its numbers, resolve
its artifact, look for each number in the artifact, report what was settled and where.

## What the pipeline confirms

Load-bearing values are those with four or more constraining digits. Matches on one- and
two-digit integers are reported apart and never pooled into a rate: `3` occurs somewhere in
any repository, so finding it is not evidence.

| article | artifact | results view | load-bearing | confirmed |
|---|---|---:|---:|---:|
| Broman:2020 | 58 data, 46 opaque | 28 | 1 | 0 |
| Kim:2021 | 2 data, 12 opaque | 1106 | 28 | 0 |
| Obadage:2025 | 13 data, 1 xlsx, 11 opaque | 380 | 351 | **125 (36%)** |

Broman's integer counts confirm at 15 of 15. Obadage's table cells confirm at 125 of 351.
Kim confirms nothing, because its repository holds sixteen Python files and two data files
and every result it reports lives in twelve pickles.

## What the three articles say about the instrument

**Reading one more format is worth more than any matching heuristic.** Obadage went from 12
per cent to 40 per cent when `results/rep_values.xlsx` became readable, which took one
stdlib zip reader. Every result that article reports sits in that file. Before it, the scan
called 356 of 362 table cells not found.

**Rounding is not the obstacle.** Of 392 unconfirmed values in Obadage, six were a
precision mismatch against a longer stored value. The rest are not in the readable artifact
in any form.

**Values quoted from another paper do not confirm, and should not.** Obadage's tables pair
each reproduced value with the original study's, and the reproduced half confirms while the
original half does not. The pattern the codebook called eligibility reappears here as a
property of the output rather than a judgment a coder has to make.

## How `absent` is separated from `unchecked`

A miss is `absent` only where every machine-readable record in the artifact was read to the
end. One unread record makes every miss `unchecked`, because the value may sit in it and
"not found" would state a limit of this tool as a disagreement between a paper and its data.

Renderings are excluded from that test on purpose. A number legible only inside a plot image
is not machine-addressable, which is a property of the artifact rather than of the reader,
so a directory of PNGs does not make an artifact unaskable. Their count is printed beside
every verdict.

The rule changes what the three articles report. Broman leaves nine records unread — five
`.xls` workbooks, a zip of figures — so its misses are `unchecked`. Kim's twelve pickles are
now read, nothing in its repository is unread, and its misses are `absent`: the paper states
1,106 values carrying a decimal point and the repository holds 333 distinct numbers in total.

## Reading binary artifacts without executing them

Two formats worth reading execute code when opened the ordinary way. `pickle.load` imports
the modules a stream names and calls `__reduce__`; a pickle is a program. R's serialization
carries promises and closures, and `Rscript -e 'readRDS(...)'` pointed at an untrusted file
is a remote code execution primitive.

Neither is opened that way. `pickletools.genops` walks the opcode stream and yields each
opcode with its literal argument, resolving no names and calling nothing, so a stream whose
`__reduce__` invokes `os.system` yields the strings and runs neither. R serialization is
parsed directly: a documented header, then objects whose flags word carries a type, whose
real vectors are a length and that many big-endian doubles. No function, promise, closure or
environment type is modelled, so nothing in the parser can evaluate. Both readers report
whether they understood the whole file, and a partial read makes a miss `unchecked`.

`tests/test_artifact_readers.py` guards these properties, including a pickle whose
`__reduce__` runs a shell command: the test asserts the command did not run.

| format | files | status |
|---|---:|---|
| `.pkl` | 12 | read from the opcode stream; concatenated pickles walked to the end |
| `.RData` / `.rds` | 4 | parsed directly; all four read completely |
| `.gz` | 12 | unwrapped and re-dispatched on the inner extension, including `RData.gz` |
| `.xlsx` | 1 | read as a zip of XML |
| `.xls` | 8 | unread — pre-2007 Excel is a different container; forces `unchecked` |
