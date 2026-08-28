The corpus size behind `readers.PREFERRED` is the one the measurement recorded. The README and
`readers.py` justified preferring pypdf over pdfplumber with "1,792 passage checks", a number
that appears in no artifact: `research/pdf-readers/results.json` records 1,593 checks over 80
documents for the quotations corpus and 458 over 132 for the sampled one, and `verify.py` cited
1,593 for the sibling claim in the same commit. Both now read 1,593, and both carry the
agreement rates the artifact holds -- 92.7% against 90.2% -- so the sentence can be checked
rather than believed.

The preference itself was correct and is unchanged. What was wrong was the evidence cited for
it, which is the failure these tools exist to catch.
