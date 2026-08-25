# provenance-core

[![pypi](https://img.shields.io/pypi/v/provenance-core)](https://pypi.org/project/provenance-core/)
[![python](https://img.shields.io/pypi/pyversions/provenance-core)](https://pypi.org/project/provenance-core/)
[![license](https://img.shields.io/pypi/l/provenance-core)](https://github.com/elliottower/reproducible-science/blob/main/LICENSE)
[![docs](https://img.shields.io/badge/docs-live-blue)](https://elliottower.github.io/reproducible-science/)

Content digests and git references, shared by the reproducible-science tools.

Internal to [reproducible-science](https://github.com/elliottower/reproducible-science). Nothing installs it directly; the tools that need it depend on it.

Two things lived in four copies each before this package existed: hashing a file or a string,
and asking git a question. The copies had drifted — one hashed in 64 KB blocks and another in
1 MB, one encoded a string implicitly and the others explicitly, and one reported a missing
`git` binary as success.

```python
from provenance_core import sha256_of_file, sha256_of_text
from provenance_core.gitref import commit, is_dirty, try_run
```

MIT licensed.
