# A one-record library

Enough to see the shape of a record and to run the tool against something.

```bash
CITATIONS_HOME=example citations verify
```

That exits non-zero, on purpose: the record names no artifact on disk, so nothing can be
checked. A verifier that reported success here would be passing by examining nothing, which
is the failure the whole tool exists to prevent.
