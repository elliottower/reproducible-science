# reproducible-science-pr-bot

A pull-request bot for [reproducible-science](https://github.com/elliottower/reproducible-science). On a pull request it comments once for each claim in `repro.yaml` that fails or went stale, and records the answer someone with write access gives in reply:

1. Yes, the paper should say the file's value
2. No, the result file is wrong
3. Ignore this one
4. Not a claim

Answers 3 and 4 commit a `set_aside` entry to the pull request's branch, naming who answered and when. Answers 1 and 2 are recorded in the comment and change no file, except that a 1 or 2 after a 3 or 4 removes the entry the bot wrote for it. The manuscript is never edited.

It runs from GitHub Actions workflows in your own repository, with its own token. Nothing is hosted, and no model reads or writes anything. `repro ci init --pr-bot` writes the two short caller workflows; the commands they run are this package's:

```bash
reproducible-science-pr-bot check   # on the pull request, read-only
reproducible-science-pr-bot post    # after the check: comments; checks out nothing
reproducible-science-pr-bot reply   # on a reply: records the answer; checks out nothing
```

Documentation: <https://reproducible.science/tools/repro/#a-bot-on-pull-requests>
