"""One version across every package, and a gate that fails when they drift.

Lockstep versioning is the dagster/opentelemetry pattern: every package carries the same
number and every package publishes on the same day. It removes two recurring errors. The
first is deciding per package whether a change "earned" a bump, which is a judgement call
made under time pressure and reliably wrong. The second is the hand-maintained floor: this
repository shipped `pyyaml>=6` and `pydantic>=2` for months, both too low to install, and
nothing noticed because no gate resolved the declared minimum.

So the version lives in one place as far as a human is concerned -- `bump` writes it to every
manifest and rewrites the cross-package ranges to match -- and `check` refuses a tree
where they disagree. A rule with no gate is a comment.

    python scripts/versions.py check
    python scripts/versions.py bump 0.4.0
    python scripts/versions.py bump 0.6.0rc1     # a release candidate, PEP 440
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
    "claims-cli": PROJECT_ROOT / "packages" / "claims" / "pyproject.toml",
    "provenance-core": PROJECT_ROOT / "packages" / "provenance-core" / "pyproject.toml",
}

#: The plugin manifests, for Claude Code and for Codex, which carry the same release version
#: and were not written by anything. They sat at 0.2.0 through two releases: nothing read them,
#: so nothing could say they were stale, and a reader comparing the plugin to PyPI found a
#: mismatch.
#: `site/.vscode/launch.json` also carries `"version": "0.2.0"` and is not one of these -- that
#: is VS Code's schema version and has nothing to do with this project.
PLUGIN_MANIFESTS = (
    PROJECT_ROOT / ".claude-plugin" / "marketplace.json",
    PROJECT_ROOT / "packages" / "citations" / "plugin" / ".claude-plugin" / "plugin.json",
    PROJECT_ROOT / "packages" / "prereg" / "plugin" / ".claude-plugin" / "plugin.json",
    PROJECT_ROOT / "packages" / "results" / "plugin" / ".claude-plugin" / "plugin.json",
    PROJECT_ROOT / "packages" / "repro" / "plugin" / ".claude-plugin" / "plugin.json",
    PROJECT_ROOT / "packages" / "repro" / "mod" / ".claude-plugin" / "plugin.json",
    # The Codex manifest for the same bundle. Codex names the installed copy by this version
    # (`plugins/cache/<marketplace>/<plugin>/<version>/`), so a stale one installs as an old
    # release.
    PROJECT_ROOT / "packages" / "repro" / "plugin" / ".codex-plugin" / "plugin.json",
)

#: The citation record, which carries the release version too and was owned by nothing. It
#: read 0.2.0 while the distributions were at 0.4.0 -- three releases -- and the anonymized
#: artifact drop is what surfaced it, because that is the file a reviewer cites from.
CITATION = PROJECT_ROOT / "CITATION.cff"

#: The install snippet in `.pre-commit-hooks.yaml`, which pins a tag for anyone copying it. It
#: said `repro-v0.3.0` while the release was 0.4.0, so following the documentation pinned a
#: version behind. Owned here for the same reason the plugin manifests and the citation record
#: are: a version string in prose that nothing writes is a version string that goes stale.
HOOKS = PROJECT_ROOT / ".pre-commit-hooks.yaml"

HOOK_REV = re.compile(r"^(?P<head>#\s+rev:\s*)v(?P<version>[0-9][^\s]*)", re.M)

#: The same snippet where a reader meets it first, in the README PyPI renders. It read `v0.4.0`
#: at 0.5.5: the copy in `.pre-commit-hooks.yaml` was written at each release and this one was
#: owned by nothing.
HOOK_README = PROJECT_ROOT / "packages" / "repro" / "README.md"

README_REV = re.compile(r"^(?P<head>\s+rev:\s*)v(?P<version>[0-9][^\s]*)", re.M)

CFF_VERSION = re.compile(r'^(?P<head>version:\s*")(?P<version>[^"]+)(?P<tail>")', re.M)
CFF_DATE = re.compile(r'^(?P<head>date-released:\s*")(?P<date>[^"]+)(?P<tail>")', re.M)

VERSION_LINE = re.compile(r'^version = "([^"]+)"$', re.M)
JSON_VERSION = re.compile(r'(?P<head>"version":\s*")(?P<version>[^"]+)(?P<tail>")')
SEMVER = re.compile(r"^\d+\.\d+\.\d+([ab]\d+|rc\d+)?$")

#: A version this scheme writes, in its parts: the release and an optional PEP 440 pre-release.
VERSION_PARTS = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?$")

#: How a pre-release sorts against the others of its release, and against the release itself,
#: which comes after every one of them.
PRE_RANK = {"a": 0, "b": 1, "rc": 2, None: 3}


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


def hook_rev() -> str | None:
    """The version the published pre-commit snippet tells people to pin, or None."""
    if not HOOKS.exists():
        return None
    m = HOOK_REV.search(HOOKS.read_text())
    return m.group("version") if m else None


def readme_rev() -> str | None:
    """The version the README's pre-commit snippet tells people to pin, or None."""
    if not HOOK_README.exists():
        return None
    m = README_REV.search(HOOK_README.read_text())
    return m.group("version") if m else None


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
    """Numeric comparison. `"0.10.0" < "0.9.0"` is true as strings and false as versions.

    The release's three numbers, then where a pre-release sorts: `0.6.0rc1` before `0.6.0`,
    which is how PEP 440 orders them, and `0.6.0rc1` after every 0.5.
    """
    m = VERSION_PARTS.match(version)
    if not m:
        raise VersionError(f"{version!r} is not a version this scheme writes (want 1.2.3)")
    major, minor, patch, pre, number = m.groups()
    return (int(major), int(minor), int(patch), PRE_RANK[pre], int(number or 0))


def release(version: str) -> tuple[int, int, int]:
    """The three numbers of a version, without any pre-release: `0.6.0` for `0.6.0rc1`."""
    major, minor, patch, *_ = parts(version)
    return major, minor, patch


#: The first version a release cut from this tree may carry, and the last one published before
#: it. `reproducible-science` and `results-cli` import `provenance_core.chain`, which no
#: `provenance-core` up to 0.5.6 holds. A sibling range names a series and not a patch, so a
#: 0.5.7 of either would declare `provenance-core>=0.5,<0.6` and install beside a core that
#: lacks the module. Opening a new series is what makes the range exclude those.
SERIES_FLOOR = "0.6.0"
LAST_BEFORE_FLOOR = "0.5.6"


def below_floor(version: str) -> str | None:
    """Why a release may not carry this version, or None where it may.

    The version already published stays valid, because the tree sits at it between releases.
    """
    # A candidate of the floor is in its series: `0.6.0rc1` opens 0.6 as `0.6.0` does.
    if version == LAST_BEFORE_FLOOR or release(version) >= release(SERIES_FLOOR):
        return None
    return (
        f"{version} is below {SERIES_FLOOR}: this tree imports `provenance_core.chain`, which "
        f"no provenance-core up to {LAST_BEFORE_FLOOR} has, and a sibling range of "
        f"{series(version)} would accept one. The next release opens {SERIES_FLOOR}"
    )


def series(version: str) -> str:
    """The range a lockstep release pins its siblings to: `>=0.4,<0.5`.

    A range rather than an exact `==`, following langchain rather than opentelemetry: an
    exact pin makes any hand-run release that publishes packages seconds apart briefly
    uninstallable, and this release is run by hand.

    A candidate pins its siblings from itself: `>=0.6rc1,<0.7`. A specifier admits a
    pre-release only where it names one, so `>=0.6,<0.7` would refuse the candidate the six
    packages are released as together, and the set would not install. The final release goes
    back to `>=0.6,<0.7`, which admits 0.6.0 and every patch after it.

    The candidate's bound is written with trailing zeros dropped from its release numbers,
    `0.6rc1` for `0.6.0rc1`, because that is how `pyproject-fmt` rewrites it on commit; written
    as the version, the hook changed every range and `check` then refused what it wrote.
    """
    major, minor, patch, pre, _number = parts(version)
    upper = f"<{major}.{minor + 1}"
    if pre == PRE_RANK[None]:
        return f">={major}.{minor},{upper}"
    numbers = [major, minor, patch]
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers.pop()
    suffix = version[VERSION_PARTS.match(version).start(4) :]
    return f">={'.'.join(map(str, numbers))}{suffix},{upper}"


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

#: An optional extras list after a sibling's name, kept through a bump. Without it the pattern
#: matched no dependency carrying an extra, so `check` passed it unread and `bump` left its range
#: behind the release.
EXTRAS = r'(\[[^\]"]*\])?'


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
        # An extra sits between the name and the range: "provenance-core[anchor]>=0.4,<0.5".
        m = re.search(rf'"{re.escape(name)}{EXTRAS}((?:[><=!~][^"]*)?)"', body)
        if m:
            found[name] = m.group(2)
    return found


def check() -> list[str]:
    problems: list[str] = []
    versions = declared()
    if len(set(versions.values())) > 1:
        listed = ", ".join(f"{n}={v}" for n, v in sorted(versions.items()))
        problems.append(f"versions are not in lockstep: {listed}")
    version = max(versions.values(), key=parts)
    want = series(version)
    if (refused := below_floor(version)) is not None:
        problems.append(refused)

    for name, path in PACKAGES.items():
        for dep, spec in cross_refs(path.read_text()).items():
            if dep == name:
                continue
            if spec != want:
                problems.append(
                    f"{path.relative_to(PROJECT_ROOT)}: depends on {dep}{spec}, "
                    f"but lockstep {version} wants {dep}{want}"
                )

    pinned = hook_rev()
    if pinned is not None and pinned != version:
        problems.append(
            f".pre-commit-hooks.yaml: the install snippet pins v{pinned}, "
            f"but the release is {version}"
        )

    shown = readme_rev()
    if shown is not None and shown != version:
        problems.append(
            f"{HOOK_README.relative_to(PROJECT_ROOT)}: the pre-commit snippet pins v{shown}, "
            f"but the release is {version}"
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
    if (refused := below_floor(version)) is not None:
        raise VersionError(refused)
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
                body = re.sub(
                    rf'"{re.escape(dep)}{EXTRAS}(?:[><=!~][^"]*)?"',
                    lambda m, dep=dep: f'"{dep}{m.group(1) or ""}{want}"',
                    body,
                )
            text = text[: span[0]] + body + text[span[1] :]
        if text != original:
            path.write_text(text)
            touched.append(str(path.relative_to(PROJECT_ROOT)))

    # The citation record carries the release version and the date it went out. The version is
    # checked; the date is written and not checked, because there is nothing to check it
    # against -- a bump run a few days before the tag leaves it a few days early, which is a
    # great deal better than the three releases stale it was.
    if HOOKS.exists():
        text = original = HOOKS.read_text()
        text = HOOK_REV.sub(rf"\g<head>v{version}", text, count=1)
        if text != original:
            HOOKS.write_text(text)
            touched.append(HOOKS.name)

    if HOOK_README.exists():
        text = original = HOOK_README.read_text()
        text = README_REV.sub(rf"\g<head>v{version}", text, count=1)
        if text != original:
            HOOK_README.write_text(text)
            touched.append(str(HOOK_README.relative_to(PROJECT_ROOT)))

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
