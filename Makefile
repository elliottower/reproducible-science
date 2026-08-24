# Quality ladder. Each rung is a superset of the one above, and the times are what they cost
# on this repository today. The point of the split is that a commit stays pleasant: anything
# that would make people bypass the hooks lives further down.
#
#   make format        ~5s     rewrite formatting and safe lint fixes
#   make check         ~20s    what runs on every commit
#   make test          ~50s    the whole workspace's tests
#   make qa            ~3m     what a pull request must pass
#   make qa-all        ~10m+   the deep pass; advisory tools included
#   make release-check ~2m     what a release must pass
#
# Everything runs through `uv run`, so contributors and CI invoke the same commands.

PY := uv run
PKG_SRC := packages/repro/src packages/citations/src packages/results/src packages/prereg/src

.PHONY: help format check test qa qa-all release-check types drift deps wheels imports notes check-lowest hooks

help:
	@grep -E '^#   make' Makefile | sed 's/^#   //'

# ---- rung 1: rewrite ---------------------------------------------------------------------
format:
	-$(PY) ruff check . --fix
	$(PY) ruff format .

# ---- rung 2: every commit ----------------------------------------------------------------
check:
	$(PY) ruff check .
	$(PY) ruff format --check .
	uv lock --check
	$(PY) repro verify paper/repro.yaml --policy strict

# ---- rung 3: tests -----------------------------------------------------------------------
test:
	$(PY) pytest -q

# ---- rung 4: a pull request --------------------------------------------------------------
# `types` is advisory here, not blocking: there are 32 outstanding type errors, and adopting
# a checker on an existing codebase is a ratchet. Drop the `-` once the count reaches zero.
qa: check test drift deps imports wheels
	-$(MAKE) types

types:
	$(PY) pyrefly check $(PKG_SRC)

drift:
	$(PY) python scripts/check_drift.py

deps:
	$(PY) python scripts/check_deps.py

imports:
	$(PY) lint-imports

notes:
	$(PY) towncrier check --compare-with origin/main || true

wheels:
	$(PY) python scripts/check_wheels.py

# ---- rung 5: the deep pass ---------------------------------------------------------------
# Advisory tools are marked with `-` so one noisy report does not stop the rest.
qa-all: qa check-lowest
	$(PY) pytest -q -m corpus
	$(PY) vulture
	-$(PY) complexipy packages --max-complexity 25
	-$(PY) pip-audit --skip-editable
	-$(PY) python scripts/check_drift.py

# Resolve every declared dependency at its floor. The workspace always installs the newest
# thing available, so a floor that is too low is invisible until a user hits it.
check-lowest:
	uv run --resolution lowest-direct --all-packages --group dev pytest -q

# ---- rung 6: a release -------------------------------------------------------------------
release-check: qa
	$(PY) python scripts/check_wheels.py
	rm -rf dist && mkdir -p dist
	for d in reproducible-science citations results-cli prereg; do uv build --package $$d --out-dir dist -q; done
	$(PY) twine check dist/*
	$(PY) check-wheel-contents dist/*.whl

# ---- setup -------------------------------------------------------------------------------
hooks:
	$(PY) pre-commit install --hook-type pre-commit --hook-type pre-push
