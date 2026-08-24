# Figure-generating scripts

Every number in `paper/DRAFT_v2.md` is produced by a script here or by the conformance suite.
A figure without a script that regenerates it does not go in the paper.

| script | figures it produces | section |
|---|---|---|
| `census_quotation_corpus.py` | assertions, manuscripts, pin states, unparseable files | §6.2 |
| `census_resolver_identifiers.py` | resolver-written identifiers and the checkable denominator | §6.4 |
| `../packages/repro/tests/conformance/` | fixture count and assertion count | §6.1 |

Both census scripts read the citation library at `$CITATIONS_HOME` and are therefore specific
to that corpus. They print counts and write nothing.
