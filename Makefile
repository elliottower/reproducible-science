# Quality ladder. Each rung is a superset of the one above, and the times are what they cost
# on this repository today. The point of the split is that a commit stays pleasant: anything
# that would make people bypass the hooks lives further down.
#
#   make format        ~5s     rewrite formatting and safe lint fixes
#   make check         ~1s     what runs on every commit
#   make test          ~50s    the whole workspace's tests
#   make coverage      ~2m     the same tests, measured, with a floor
#   make qa            ~3m     what a pull request must pass
#   make qa-all        ~10m+   the deep pass; advisory tools included
#   make interop       ~15s    is the adduce adapter still true of the latest adduce?
#   make release-check ~2m     what a release must pass
#
# Everything runs through `uv run`, so contributors and CI invoke the same commands.

PY := uv run
PKG_SRC := packages/repro/src packages/citations/src packages/results/src packages/prereg/src

.PHONY: help format check test coverage versions publishable interop qa qa-all release-check types deps imports dead notes check-lowest hooks

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

# ---- rung 3: tests -----------------------------------------------------------------------
test:
	$(PY) pytest -q

# Three variables, all required, all absolute. Most of these suites drive a CLI in a real
# subprocess, and coverage measures only the process it starts: without the hook the four
# `cli.py` modules reported 0-18% while their tests passed, and a floor on that would have
# been a floor on a fiction. COVERAGE_FILE must be absolute because a child runs in a
# tmp_path and would otherwise write its data where the test then deletes it.
COV_ENV := COVERAGE_FILE=$(CURDIR)/.coverage \
           COVERAGE_PROCESS_START=$(CURDIR)/pyproject.toml \
           PYTHONPATH=$(CURDIR)/scripts/coverage_hook

coverage:
	@rm -f .coverage .coverage.*
	# `-n auto` because the suites spawn a great many subprocesses and the tracer runs in
	# every one of them, which is what makes this six times slower than the same tests
	# uninstrumented. The xdist workers are subprocesses like any other, so
	# COVERAGE_PROCESS_START measures them and `coverage combine` below gathers them.
	# Measured: 193.7s serial against 53.6s here, reporting the identical 5953/1390/1788/185.
	$(COV_ENV) $(PY) coverage run -m pytest -q -p no:randomly -n auto
	COVERAGE_FILE=$(CURDIR)/.coverage $(PY) coverage combine
	COVERAGE_FILE=$(CURDIR)/.coverage $(PY) coverage xml -o coverage.xml
	COVERAGE_FILE=$(CURDIR)/.coverage $(PY) coverage report --fail-under=70

# ---- rung 4: a pull request --------------------------------------------------------------
# Exactly what CI requires, so a green `make qa` really does mean a green pull request.
qa: check test coverage types versions publishable deps imports wheels dead

types:
	$(PY) pyrefly check $(PKG_SRC)

# Every package carries one version and pins its siblings to that series. Enforced rather
# than documented: the floors this repository shipped for months were wrong precisely
# because nothing checked them.
versions:
	$(PY) python scripts/versions.py check

# A workspace path resolves a sibling during development and does not survive into a wheel.
# A published package depending on an unpublished one installs for nobody.
publishable:
	$(PY) python scripts/check_publishable.py

# The adduce rule is a claim about someone else's package, on someone else's schedule. A new
# release of theirs is a prompt on an ordinary push and a blocker at a release, because a
# release is when the claim in SPEC.md and the paper goes out with a version number on it.
interop:
	$(PY) python scripts/check_interop.py --advisory

interop-strict:
	$(PY) python scripts/check_interop.py

dead:
	$(PY) vulture

deps:
	$(PY) python scripts/check_deps.py

imports:
	$(PY) lint-imports

notes:
	-$(PY) towncrier check --compare-with origin/main

wheels:
	$(PY) python scripts/check_wheels.py

# ---- rung 5: the deep pass ---------------------------------------------------------------
# Advisory tools are marked with `-` so one noisy report does not stop the rest.
qa-all: qa check-lowest
	-$(PY) complexipy packages --max-complexity 25
	-$(PY) pip-audit --skip-editable

# Resolve every declared dependency at its floor. The workspace always installs the newest
# thing available, so a floor that is too low is invisible until a user hits it.
check-lowest:
	uv run --resolution lowest-direct --all-packages --group dev pytest -q

# ---- rung 6: a release -------------------------------------------------------------------
release-check: qa interop-strict
	$(PY) python scripts/check_wheels.py
	rm -rf dist && mkdir -p dist
# provenance-core included: every other package declares it, so a release that omits it
# leaves the other four uninstallable from PyPI. It was absent here while its publish
# workflow shipped it, so twine and check-wheel-contents never saw the artifact.
	for d in reproducible-science citations results-cli prereg provenance-core; do uv build --package $$d --out-dir dist -q; done
	$(PY) twine check dist/*
	$(PY) check-wheel-contents dist/*.whl

# ---- setup -------------------------------------------------------------------------------
hooks:
	# No --hook-type flags: passing them overrides `default_install_hook_types` in the config,
	# which silently left the commit-msg hook uninstalled for anyone following the docs.
	$(PY) pre-commit install --install-hooks
