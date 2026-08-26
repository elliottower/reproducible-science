Test helpers across `prereg` and `results` ran git with an inherited environment. Under
`pre-commit`, which exports `GIT_INDEX_FILE` while it stashes, their `git add -A` staged into
the *outer* worktree's index and left every tracked file there staged as deleted -- a wrecked
checkout produced by a passing test, with `pytest -n auto` workers racing on the one index.
They now build their environment with `gitref.clean_env()`.
