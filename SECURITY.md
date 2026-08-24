# Security

## Reporting

Report a vulnerability privately through GitHub's advisory form on this repository, or by
email to <elliot@elliottower.ai>. Please do not open a public issue first.

Expect an acknowledgement within a week. There is no bounty.

## What is in scope

These tools read files a user points them at, run declared commands when explicitly asked, and
publish reports. The interesting boundaries are:

- **Manifest parsing.** A manifest is untrusted input. A crafted `repro.yaml` should never
  cause anything to execute.
- **`repro verify --regenerate`.** This runs commands named in a manifest. It is off by
  default for that reason, runs only what the manifest declares, and runs it in a sandbox
  holding only the declared inputs. Commands are argv, never shell strings.
- **Artifact reading.** Extractors handle files from arbitrary sources. A malformed PDF, CSV
  or database should produce an error, not a crash or an escape.
- **Locator resolution.** Database identifiers are checked against the schema before being
  quoted; values are always bound as parameters.

A verification tool that can be made to report `verified` for evidence that is not there is a
security problem, not merely a bug. Report it as one.

## What is not

Running `--regenerate` on a manifest you have not read is equivalent to running a script you
have not read. The flag is opt-in and documented as executing what the manifest names.
