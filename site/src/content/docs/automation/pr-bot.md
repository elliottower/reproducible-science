---
title: Pull-request bot
description: A bot that comments on each claim a pull request breaks or leaves stale, and records the answer given in reply.
---

On a pull request, the bot comments once for each claim in `repro.yaml` that fails or went
stale, and records the answer someone with write access gives in reply:

1. Yes, the paper should say the file's value
2. No, the result file is wrong
3. Ignore this one
4. Not a claim

Answers 3 and 4 commit a `set_aside` entry to the pull request's branch, naming who answered and
when. Answers 1 and 2 are recorded in the comment and change no file, except that a 1 or 2 after
a 3 or 4 removes the entry the bot wrote for it. The manuscript is never edited.

It runs from GitHub Actions workflows in your own repository, with its own token. Nothing is
hosted, and no model reads or writes anything. It ships in 0.7.0.

## Setup

```bash
repro ci init --pr-bot
```

This writes two caller workflows. `repro-pr-bot.yml` runs on `pull_request` with
`contents: read`, and `repro-pr-bot-respond.yml` runs after it and on new comments. Both call the
reusable workflow `elliottower/reproducible-science/.github/workflows/pr-bot.yml` and grant
nothing at their top. A file the command did not write is never replaced; `--force` replaces the
two it wrote.

The workflows run the commands of the `reproducible-science-pr-bot` package:

```bash
reproducible-science-pr-bot check   # on the pull request, read-only
reproducible-science-pr-bot post    # after the check: comments; checks out nothing
reproducible-science-pr-bot reply   # on a reply: records the answer; checks out nothing
```

## Refuses or never does

- `post` and `reply` check out nothing, and refuse findings that do not belong to the pull
  request, commit and branch the run checked, or that name a file other than the manifest.
- Each comment carries a hidden marker. A later run edits it, marks it fixed and resolves its
  thread when the claim passes, and never posts it twice.
- On a pull request from a fork it comments and commits nothing.
- A reply naming two numbers or a time, such as `1-2` or `1:30`, gives no answer. An edited
  reply is read again as what it now says.
- After a commit it starts the checks again, so a required check runs on the new head.
