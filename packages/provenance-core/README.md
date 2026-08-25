# provenance-core

Primitives shared by the [reproducible-science](https://github.com/elliottower/reproducible-science)
tools. Not intended to be installed directly.

Two things lived in four copies each before this package existed: hashing a file or a string,
and asking git a question. The copies had drifted — one hashed in 64 KB blocks and another in
1 MB, one encoded a string implicitly and the others explicitly, and one reported a missing
`git` binary as success.

```python
from provenance_core import sha256_of_file, sha256_of_text
from provenance_core.gitref import commit, is_dirty, try_run
```

MIT licensed.
