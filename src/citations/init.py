"""Make a library.

Git is handled by detection rather than by asking, because each case has one right answer.
Inside an existing repository the library is just a directory the parent already tracks;
nesting a repository inside a repository is never what anyone wants. Standing alone it gets its
own repository, since the records are YAML precisely so that `git diff` shows what changed, and
an untracked library throws that away.

No remote is configured, and this tool never pushes.
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess

from citations import paths

GITIGNORE = """\
# artifacts, not records. Copyright usually forbids redistributing them
pdfs/

# secrets
.env

__pycache__/
*.pyc
.DS_Store
"""

README = """\
# Citation library

Records checked by [`citations`](https://pypi.org/project/citations/).

```
records/          one file per cited work, keyed by DOI or arXiv id
enrichment.yaml   facts resolved after a bibliography was written
pdfs/             the artifacts. Not committed
```

This holds verbatim passages from the sources you cite. Publishing it republishes that text.
"""


def _in_git_repo(d: pathlib.Path) -> bool:
    r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                       cwd=d, capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


def make(target: pathlib.Path, git: bool | None = None) -> tuple[pathlib.Path, str]:
    target.mkdir(parents=True, exist_ok=True)
    (target / "records").mkdir(exist_ok=True)
    if not (target / ".gitignore").exists():
        (target / ".gitignore").write_text(GITIGNORE)
    if not (target / "README.md").exists():
        (target / "README.md").write_text(README)

    tracked = _in_git_repo(target)
    if git is False or tracked:
        note = ("tracked by the repository above" if tracked
                else "not tracked — run `git init` here to keep a history of changes")
        return target, note
    subprocess.run(["git", "init", "--quiet"], cwd=target, capture_output=True)
    return target, "git initialised, no remote"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="citations init",
                                 description=__doc__.split("\n")[0])
    ap.add_argument("--user", action="store_true",
                    help="make the shared library instead of one here")
    ap.add_argument("--path", help="make it at this path")
    ap.add_argument("--no-git", action="store_true", help="do not initialise a repository")
    a = ap.parse_args(argv)

    if a.path:
        target = pathlib.Path(a.path).expanduser()
    elif a.user:
        target = paths.user_library()
    else:
        target = pathlib.Path.cwd() / paths.DIRNAME

    if (target / "records").is_dir():
        print(f"already a library: {target}")
        return 0

    target, note = make(target, git=False if a.no_git else None)
    print(f"created {target}")
    print(f"{note}\n")
    print("This library will hold verbatim passages from the sources you cite.")
    print("Publishing it republishes that text. citations commits here but never pushes.")
    if a.user or a.path:
        print(f"\nUse it from anywhere:\n    export CITATIONS_HOME={target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
