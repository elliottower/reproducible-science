"""Report whether PyPI still accepts a release from each publish workflow.

Step 5 of `docs/RELEASING.md` was five settings pages in a browser, because PyPI binds a
trusted publisher to a repository, a workflow *filename* and an environment, and none of that
is visible from a checkout. A check with no command is a check that gets skipped, and the one
it guards is the expensive one: a wholly rejected release is recoverable, a partial one is
not, because re-pushing the tag hits `File already exists` on whatever succeeded.

Each publish workflow now answers the question itself, in a `binding` job that exchanges an
OIDC claim for a short-lived upload token and throws it away. This reads those runs.

    uv run python scripts/check_publishers.py

Exits non-zero when any binding last failed, or has never been verified. A verification older
than `STALE_DAYS` is reported rather than failed: it means nothing has run lately, not that
anything is wrong.
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys

#: Distribution name to the workflow PyPI is bound to. Both halves matter: the binding names
#: the filename, so a workflow renamed without reconfiguring PyPI fails at the upload.
WORKFLOWS = {
    "citations": "publish-citations.yml",
    "prereg": "publish-prereg.yml",
    "results-cli": "publish-results.yml",
    "reproducible-science": "publish-repro.yml",
    "provenance-core": "publish-provenance-core.yml",
}

#: How old a verification may be before it is worth mentioning. The schedule is weekly.
STALE_DAYS = 10


#: The job that performs the exchange. Read by name, because a run's overall conclusion is
#: not the answer: a release run that published proves the binding held then, while a run
#: with no such job proves only that this check did not exist yet. Reading the run's
#: conclusion as the binding's reported `ok` for five workflows that had verified nothing.
JOB = "binding"


def latest(workflow: str) -> dict | None:
    """The most recent completed run of `workflow`, with what its binding job concluded."""
    out = subprocess.run(
        [
            "gh",
            "run",
            "list",
            "--workflow",
            workflow,
            "--limit",
            "20",
            "--json",
            "databaseId,conclusion,status,createdAt,url",
        ],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        return None
    for run in json.loads(out.stdout or "[]"):
        if run.get("status") != "completed":
            continue
        jobs = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{{owner}}/{{repo}}/actions/runs/{run['databaseId']}/jobs",
                "--jq",
                f'.jobs[] | select(.name | startswith("{JOB}")) | .conclusion',
            ],
            capture_output=True,
            text=True,
        )
        verdict = (jobs.stdout or "").strip().splitlines()
        run["binding"] = verdict[0] if verdict else None
        return run
    return None


def age_days(stamp: str) -> float:
    when = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return (datetime.datetime.now(datetime.UTC) - when).total_seconds() / 86400


def main() -> int:
    print(f"  {'distribution':<24}{'binding':<12}{'checked':<12}workflow")
    bad = []
    for dist, workflow in WORKFLOWS.items():
        run = latest(workflow)
        if run is None:
            state, when = "never run", "-"
            bad.append(f"{dist}: no completed run of {workflow}")
        else:
            days = age_days(run["createdAt"])
            when = "today" if days < 1 else f"{days:.0f}d ago"
            if run["binding"] == "success":
                state = "ok"
                if days > STALE_DAYS:
                    when += " (stale)"
            elif run["binding"] is None and run["conclusion"] == "success":
                # A release that uploaded proves PyPI accepted this workflow at the time.
                state = "released ok"
            elif run["binding"] is None:
                state = "not verified"
                bad.append(f"{dist}: no {JOB} job has run — {run['url']}")
            else:
                state = run["binding"]
                bad.append(f"{dist}: {JOB} job {state} — {run['url']}")
        print(f"  {dist:<24}{state:<12}{when:<12}{workflow}")

    if not bad:
        print("\nevery distribution can be published from this repository.")
        return 0
    print(f"\n{len(bad)} binding(s) a release would fail on:")
    for line in bad:
        print(f"  {line}")
    print("\n  Run one to see why:  gh workflow run <workflow>")
    print("  A partial release cannot be repeated; the version is spent on whatever uploaded.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
