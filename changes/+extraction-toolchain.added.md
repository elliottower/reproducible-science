- **[repro] Every decision records the extraction toolchain and the digest of what it
  produced.** `backend_version` is a protocol string naming a backend's interface, so a
  `pdftotext` upgrade that resolved a ligature differently changed an extracted passage while
  the artifact's digest held and the report read `backend_version: "1"` on both sides of it.
  A decision now carries `tool` and `tool_version` — the binary's version as it prints it, or
  the installed distribution's for the format adapters — and `extraction_digest`, the sha256
  of the whole extracted text for a quotation and of the extracted value for a number. The
  version says why a reading changed; the digest catches a change from any cause, including a
  rebuilt binary reporting the same version. A version or digest that was sought and not
  obtained is recorded as `unknown`, so it stays distinguishable from one never sought. The
  fields are provenance: no outcome moves, and whether a changed toolchain should break a pin
  is left to policy.
