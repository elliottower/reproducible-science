An extractor that writes a file *beside* the source is reported. The existing check hashes the
artifact before and after, which catches a renderer that overwrites the file it was given and
cannot see one that writes a sibling -- the commoner shape, since `pdftotext -layout X.pdf` with
no trailing `-` writes `X.txt` and prints nothing.

Thirty-two such files accumulated in one audited repository over three weeks, unnoticed because
the directory is gitignored. Nothing was corrupted there, but a `.txt` pinned as a source beside
a same-stem PDF would have been silently replaced by this tool's own output, and every quotation
would then have resolved against text the checker wrote.

Narrowed to files sharing the source's stem rather than watching the whole directory, so an
unrelated process writing there cannot trip it. Nothing is deleted: the file is named in the
report and left where it is.
