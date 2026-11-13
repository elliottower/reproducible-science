---
title: Pull-request bot
description: A bot that comments on each claim a pull request breaks or leaves stale, and records the answer given in reply.
---

On a pull request, the bot comments once for each claim in `repro.yaml` that fails or went
stale, and records the answer someone with write access gives in reply:

1. Yes, the paper should change. The comment words it for the claim: "Yes, the paper should
   say" the file's value where the two differ, and "Yes, run the command again and update the
   paper" where the claim is stale.
2. No, the result file is wrong
3. Ignore this one
4. Not a claim

Answers 3 and 4 commit a `set_aside` entry to the pull request's branch where the claim quotes a
passage of the manuscript. The entry names the passage, the reason, who answered and when, and
`reviewed.via: reproducible-science-pr-bot`, which is how the bot knows the entries it may
remove. Where the claim quotes no passage, the reply says that no entry was written. Answers 1
and 2 are recorded in the comment and change no file, except that a 1 or 2 after a 3 or 4
removes the entry the bot wrote for it. The manuscript is never edited.

It runs from GitHub Actions workflows in your own repository, with the workflow's
`GITHUB_TOKEN`; there is no app and no secret. Nothing is hosted, and no model reads or writes
anything. The workflows install `reproducible-science-pr-bot` from PyPI with `uvx`, pinned to
the release, so the bot runs once 0.7.0 is on PyPI.

## Setup

```bash
repro ci init --pr-bot
```

This writes two caller workflows, and refuses where the repository has no `repro.yaml`.
`repro-pr-bot.yml` runs on `pull_request` and on `workflow_dispatch`, with `contents: read`.
`repro-pr-bot-respond.yml` runs after it, and on new and edited comments (`issue_comment` and
`pull_request_review_comment`); its job grants `actions`, `contents`, `issues` and
`pull-requests` write. Both call the reusable workflow
`elliottower/reproducible-science/.github/workflows/pr-bot.yml` and grant nothing at their top.
A file the command did not write is never replaced; `--force` replaces the two it wrote.

Merge the two files into the default branch before expecting a comment: GitHub runs
`workflow_run` and `issue_comment` workflows only from the default branch.

The workflows run the commands of the `reproducible-science-pr-bot` package:

```bash
reproducible-science-pr-bot check   # on the pull request, read-only
reproducible-science-pr-bot post    # after the check: comments; checks out nothing
reproducible-science-pr-bot reply   # on a reply: records the answer; checks out nothing
```

## Limits

- `post` refuses findings that do not belong to the pull request, commit and branch the run
  checked, or that name a file other than the manifest. `post` and `reply` check out nothing.
- Each comment carries a hidden marker. A later run edits it, marks it fixed and resolves its
  thread when the claim passes, and never posts it twice.
- On a pull request from a fork it comments only in the conversation and commits nothing.
- A reply naming two numbers or a time, such as `1-2` or `1:30`, gives no answer. An edited
  reply is read again as what it now says.
- After a commit it starts its own check again, and the workflows `repro ci init` wrote with a
  `workflow_dispatch` trigger, since a commit by the bot starts no workflow by itself.
