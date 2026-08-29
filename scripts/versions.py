"""One version across every package, and a gate that fails when they drift.

Lockstep versioning is the dagster/opentelemetry pattern: every package carries the same
number and every package publishes on the same day. It removes two recurring errors. The
first is deciding per package whether a change "earned" a bump, which is a judgement call
made under time pressure and reliably wrong. The second is the hand-maintained floor: this
repository shipped `pyyaml>=6` and `pydantic>=2` for months, both too low to install, and
nothing noticed because no gate resolved the declared minimum.

So the version lives in one place as far as a human is concerned -- `bump` writes it to all
four manifests and rewrites the cross-package ranges to match -- and `check` refuses a tree
where they disagree. A rule with no gate is a comment.

    python scripts/versions.py check
    python scripts/versions.py bump 0.4.0
"""

from __future__ import annotations

import argparse
import datetime
import pathlib
import re

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Distribution name -> its manifest. The import name differs from the distribution name for
#: two of these, which is why the mapping is written out rather than derived from the path.
PACKAGES = {
    "citations": PROJECT_ROOT / "packages" / "citations" / "pyproject.toml",
    "prereg": PROJECT_ROOT / "packages" / "prereg" / "pyproject.toml",
    "results-cli": PROJECT_ROOT / "packages" / "results" / "pyproject.toml",
    "reproducible-science": PROJECT_ROOT / "packages" / "repro" / "pyproject.toml",
    "provenance-core": PROJECT_ROOT / "packages" / "provenance-core" / "pyproject.toml",
}

#: The Claude Code plugin manifests, which carry the same release version and were not
#: written by anything. They sat at 0.2.0 through two releases: nothing read them, so nothing
#: could say they were stale, and a reader comparing the plugin to PyPI found a mismatch.
#: `site/.vscode/launch.json` also carries `"version": "0.2.0"` and is not one of these -- that
#: is VS Code's schema version and has nothing to do with this project.
PLUGIN_MANIFESTS = (
    PROJECT_ROOT / ".claude-plugin" / "marketplace.json",
    PROJECT_ROOT / "packages" / "citations" / "plugin" / ".claude-plugin" / "plugin.json",
    PROJECT_ROOT / "packages" / "prereg" / "plugin" / ".claude-plugin" / "plugin.json",
    PROJECT_ROOT / "packages" / "results" / "plugin" / ".claude-plugin" / "plugin.json",
    PROJECT_ROOT / "packages" / "repro" / "plugin" / ".claude-plugin" / "plugin.json",
)

#: The citation record, which carries the release version too and was owned by nothing. It
#: read 0.2.0 while the distributions were at 0.4.0 -- three releases -- and the anonymized
#: artifact drop is what surfaced it, because that is the file a reviewer cites from.
CITATION = PROJECT_ROOT / "CITATION.cff"

CFF_VERSION = re.compile(r'^(?P<head>version:\s*")(?P<version>[^"]+)(?P<tail>")', re.M)
CFF_DATE = re.compile(r'^(?P<head>date-released:\s*")(?P<date>[^"]+)(?P<tail>")', re.M)

VERSION_LINE = re.compile(r'^version = "([^"]+)"$', re.M)
JSON_VERSION = re.compile(r'(?P<head>"version":\s*")(?P<version>[^"]+)(?P<tail>")')
SEMVER = re.compile(r"^\d+\.\d+\.\d+([ab]\d+|rc\d+)?$")


class VersionError(Exception):
    """The declared versions disagree, or a version is not one this scheme can write."""


def declared() -> dict[str, str]:
    out: dict[str, str] = {}
    for name, path in PACKAGES.items():
        m = VERSION_LINE.search(path.read_text())
        if not m:
            raise VersionError(f'{path.relative_to(PROJECT_ROOT)}: no `version = "..."` line')
        out[name] = m.group(1)
    return out


def citation_version() -> str | None:
    """What `CITATION.cff` says the release is, or None where there is no such file."""
    if not CITATION.exists():
        return None
    m = CFF_VERSION.search(CITATION.read_text())
    if not m:
        raise VersionError(f"{CITATION.name}: no `version:` line")
    return m.group("version")


def plugin_versions() -> dict[pathlib.Path, str]:
    """What each plugin manifest declares, by path."""
    out: dict[pathlib.Path, str] = {}
    for path in PLUGIN_MANIFESTS:
        if not path.exists():
            continue
        m = JSON_VERSION.search(path.read_text())
        if not m:
            raise VersionError(f'{path.relative_to(PROJECT_ROOT)}: no `"version"` field')
        out[path] = m.group("version")
    return out


def parts(version: str) -> tuple[int, ...]:
    """Numeric comparison. `"0.10.0" < "0.9.0"` is true as strings and false as versions."""
    return tuple(int(n) for n in version.split(".")[:3])


def series(version: str) -> str:
    """The range a lockstep release pins its siblings to: `>=0.4,<0.5`.

    A range rather than an exact `==`, following langchain rather than opentelemetry: an
    exact pin makes any hand-run release that publishes packages seconds apart briefly
    uninstallable, and this release is run by hand.
    """
    major, minor, *_ = version.split(".")
    return f">={major}.{minor},<{major}.{int(minor) + 1}"


#: The start of the dependencies array. Its end is found by balancing brackets rather than by
#: a pattern, because the array is written both ways in this workspace:
#:
#:     dependencies = [ "provenance-core>=0.3,<0.4" ]      # prereg, results, citations
#:     dependencies = [                                     # repro
#:       "citations>=0.3,<0.4",
#:     ]
#:
#: A pattern ending at `^]` matches neither the first form nor, when one is followed by an
#: unrelated multi-line array, only the intended text: it ran from `dependencies = [` past the
#: closing bracket to the `]` of `classifiers`, and in `prereg`, which has no later array, it
#: did not match at all. `bump` therefore left prereg pinned to the previous series while every
#: other package moved, and `check` could not see the disagreement because it reads the same
#: way. The wheels refused to install together, which is where it was caught.
DEPENDENCIES_START = re.compile(r"^dependencies = \[", re.M)


def dependencies_span(text: str) -> tuple[int, int] | None:
    """The offsets of the dependencies array's body, or None where there is no array.

    Returned as offsets rather than a match so the read and the write paths agree on exactly
    which characters are the array.
    """
    start = DEPENDENCIES_START.search(text)
    if not start:
        return None
    depth, i = 1, start.end()
    while i < len(text) and depth:
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
        i += 1
    return (start.end(), i - 1) if depth == 0 else None


def cross_refs(text: str) -> dict[str, str]:
    """Declared dependencies on sibling packages, as {distribution: specifier}.

    Scoped to the `dependencies` array. `keywords` legitimately lists "citations" and
    "provenance" as bare strings, and matching the whole file read those as unpinned
    dependencies -- a false report that would have taught the reader to ignore this check.
    """
    span = dependencies_span(text)
    if span is None:
        return {}
    body = text[span[0] : span[1]]
    found = {}
    for name in PACKAGES:
        m = re.search(rf'"{re.escape(name)}((?:[><=!~][^"]*)?)"', body)
        if m:
            found[name] = m.group(1)
    return found


def check() -> list[str]:
    problems: list[str] = []
    versions = declared()
    if len(set(versions.values())) > 1:
        listed = ", ".join(f"{n}={v}" for n, v in sorted(versions.items()))
        problems.append(f"versions are not in lockstep: {listed}")
    version = max(versions.values(), key=parts)
    want = series(version)

    for name, path in PACKAGES.items():
        for dep, spec in cross_refs(path.read_text()).items():
            if dep == name:
                continue
            if spec != want:
                problems.append(
                    f"{path.relative_to(PROJECT_ROOT)}: depends on {dep}{spec}, "
                    f"but lockstep {version} wants {dep}{want}"
                )

    cited = citation_version()
    if cited is not None and cited != version:
        problems.append(f"CITATION.cff: version {cited}, but the release is {version}")

    for path, declared_version in plugin_versions().items():
        if declared_version != version:
            problems.append(
                f"{path.relative_to(PROJECT_ROOT)}: plugin version {declared_version}, "
                f"but the release is {version}"
            )
    return problems


def bump(version: str, realign: bool = False) -> list[str]:
    if not SEMVER.match(version):
        raise VersionError(f"{version!r} is not a version this scheme writes (want 1.2.3)")
    # Aligning is not advancing. The first lockstep release sets every package to the highest
    # version already declared, so packages that are already there do not move; refusing an
    # equal version would make that first alignment impossible. What is refused is any package
    # going backwards, which PyPI would reject at upload and which loses history in the tree.
    behind = {n: v for n, v in declared().items() if parts(version) < parts(v)}
    if behind and not realign:
        listed = ", ".join(f"{n}={v}" for n, v in sorted(behind.items()))
        raise VersionError(
            f"{version} is below {listed}; a version may not go backwards. "
            f"If those versions were never published, pass --realign."
        )

    want = series(version)
    touched = []
    for name, path in PACKAGES.items():
        text = original = path.read_text()
        text = VERSION_LINE.sub(f'version = "{version}"', text, count=1)

        # Confined to the dependencies array, for the same reason the read path is: a bare
        # "prereg" also appears in `keywords` and in deptry's DEP002 ignore list, and
        # rewriting those turned a keyword into "citations>=0.3,<0.4" and silently disabled
        # the ignore rule. `make deps` caught it; a narrower substitution stops it happening.
        if (span := dependencies_span(text)) is not None:
            body = text[span[0] : span[1]]
            for dep in PACKAGES:
                if dep == name:
                    continue
                body = re.sub(rf'"{re.escape(dep)}(?:[><=!~][^"]*)?"', f'"{dep}{want}"', body)
            text = text[: span[0]] + body + text[span[1] :]
        if text != original:
            path.write_text(text)
            touched.append(str(path.relative_to(PROJECT_ROOT)))

    # The citation record carries the release version and the date it went out. The version is
    # checked; the date is written and not checked, because there is nothing to check it
    # against -- a bump run a few days before the tag leaves it a few days early, which is a
    # great deal better than the three releases stale it was.
    if CITATION.exists():
        text = original = CITATION.read_text()
        text = CFF_VERSION.sub(rf"\g<head>{version}\g<tail>", text, count=1)
        text = CFF_DATE.sub(rf"\g<head>{datetime.date.today().isoformat()}\g<tail>", text, count=1)
        if text != original:
            CITATION.write_text(text)
            touched.append(CITATION.name)

    # The plugin manifests carry the same release version. Written here rather than by hand,
    # because by hand is what left them at 0.2.0 across two releases.
    for path in PLUGIN_MANIFESTS:
        if not path.exists():
            continue
        text = original = path.read_text()
        text = JSON_VERSION.sub(rf"\g<head>{version}\g<tail>", text, count=1)
        if text != original:
            path.write_text(text)
            touched.append(str(path.relative_to(PROJECT_ROOT)))
    return touched


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="versions", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="fail if the packages are not in lockstep")
    b = sub.add_parser("bump", help="set every package to one version")
    b.add_argument("version")
    b.add_argument(
        "--realign",
        action="store_true",
        help="allow a version below one already declared, for a first lockstep release "
        "where the higher number was never published",
    )
    a = ap.parse_args(argv)

    if a.cmd == "bump":
        for path in bump(a.version, realign=a.realign):
            print(f"  {path}")
        print(f"all packages at {a.version}, siblings pinned {series(a.version)}")
        return 0

    problems = check()
    for p in problems:
        print(f"  {p}")
    if problems:
        print("\nlockstep versioning is broken. run: python scripts/versions.py bump <version>")
        return 1
    print(f"lockstep: every package at {max(declared().values(), key=parts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
