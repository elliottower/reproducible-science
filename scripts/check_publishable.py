"""Every cross-package dependency must be publishable, not merely resolvable locally.

`[tool.uv.sources] { workspace = true }` resolves a sibling from its path, which is what makes
development work. It does not survive into a wheel: the built artifact declares
`Requires-Dist: provenance-core>=0.2,<0.3`, and a user installing from PyPI gets that from
PyPI or not at all.

So a workspace member that other published packages depend on has to be published too, and
the failure mode is silent -- the whole test suite passes, `make wheels` passes because it
installs from `dist/`, and the break appears only for the first person who runs `pip install`
after a release that left the dependency behind.

This checks that every sibling named in a manifest either exists on PyPI at a version the
range accepts, or has a publish workflow that a release tag will fire.

    python scripts/check_publishable.py
"""

from __future__ import annotations

import json
import pathlib
import re
import tomllib
import urllib.error
import urllib.request

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"


def members() -> dict[str, pathlib.Path]:
    out = {}
    for manifest in sorted((PROJECT_ROOT / "packages").glob("*/pyproject.toml")):
        out[tomllib.loads(manifest.read_text())["project"]["name"]] = manifest
    return out


def on_pypi(name: str) -> bool:
    try:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=20) as r:
            json.loads(r.read().decode("utf-8", "replace"), strict=False)
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return True


def publishes(name: str) -> pathlib.Path | None:
    """The workflow whose `uv build --package <name>` ships this distribution."""
    for wf in sorted(WORKFLOWS.glob("publish-*.yml")):
        if re.search(rf"--package {re.escape(name)}\b", wf.read_text()):
            return wf
    return None


def main() -> int:
    pkgs = members()
    problems: list[str] = []
    for name, manifest in pkgs.items():
        data = tomllib.loads(manifest.read_text())
        deps = data["project"].get("dependencies", [])
        for dep in deps:
            target = re.split(r"[<>=!~\[ ]", dep, maxsplit=1)[0]
            if target not in pkgs or target == name:
                continue
            wf = publishes(target)
            live = on_pypi(target)
            if not live and wf is None:
                problems.append(
                    f"{name} depends on {target}, which is neither on PyPI nor built by any "
                    f"publish workflow. A release would ship a wheel nobody can install."
                )
            elif not live:
                print(f"  note  {name} -> {target}: not yet on PyPI, but {wf.name} will ship it")
            else:
                print(f"  ok    {name} -> {target}")
    for p in problems:
        print(f"  FAIL  {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
