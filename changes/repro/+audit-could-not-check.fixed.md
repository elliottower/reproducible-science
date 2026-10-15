**`repro audit` counts `citations audit`'s `could not check` row under what the step could not establish**, as it counted the `unresolved` row that row replaces.

**The MCP server's `citations_audit` says why an entry could not be checked.** `why_not` names the services that did not answer (throttled, refused or offline: ask again later) and those that rejected the query as malformed (asking again changes nothing), read from the entry's `refused` and `rejected`, where it had been the bare status `could not check`.
