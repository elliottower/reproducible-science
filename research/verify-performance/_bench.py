"""Shared measurement scaffolding for the `citations verify` performance study.

Every script here writes its whole result structure to `data/<name>.json` before printing
anything, so a number quoted anywhere has a file behind it. The envelope records the machine,
the corpus, the git state of the tree that produced it, and the exact command, because a timing
without those is not comparable with the next one.

Nothing in this directory is imported by `citations`. These are prototypes; the production
change is a separate, reviewed piece of work.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import pathlib
import platform
import shutil
import subprocess
import time

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE / "data"
SCHEMA = 1

#: The corpus every measurement in this study runs against.
CORPUS_ROOT = pathlib.Path(os.environ.get("CORPUS_ROOT", "corpus")).expanduser()
CLAIMS_DIR = CORPUS_ROOT / "claims"
REFERENCE_DIR = CORPUS_ROOT / "reference"

#: The tree whose behaviour is being measured.
REPO_ROOT = HERE.parent.parent


def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def git_state() -> dict:
    return {
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(_git("status", "--porcelain")),
        "verify_py_sha256": sha256_of(REPO_ROOT / "packages/citations/src/citations/verify.py"),
    }


def machine() -> dict:
    def sysctl(key: str) -> str:
        try:
            r = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return r.stdout.strip() if r.returncode == 0 else ""

    return {
        "os": f"{platform.system()} {platform.release()}",
        "os_version": platform.mac_ver()[0] or platform.version(),
        "arch": platform.machine(),
        "cpu": sysctl("machdep.cpu.brand_string"),
        "logical_cpus": os.cpu_count(),
        "physical_cpus": int(sysctl("hw.physicalcpu") or 0) or None,
        "memory_bytes": int(sysctl("hw.memsize") or 0) or None,
        "python": platform.python_version(),
        "pdftotext": pdftotext_version(),
        "user": getpass.getuser(),
    }


def pdftotext_version() -> str:
    """The exact string poppler prints. Part of extractor identity, not decoration."""
    exe = shutil.which("pdftotext")
    if not exe:
        return ""
    r = subprocess.run([exe, "-v"], capture_output=True, text=True, timeout=30)
    first = (r.stderr or r.stdout or "").strip().splitlines()
    return first[0] if first else ""


def sha256_of(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def corpus() -> dict:
    """What is being measured, hashed so a later run can tell it apart from a changed one."""
    pdfs = sorted(REFERENCE_DIR.glob("*.pdf"))
    claims = sorted(CLAIMS_DIR.glob("*.yaml"))
    manifest = hashlib.sha256()
    total = 0
    for p in pdfs:
        size = p.stat().st_size
        total += size
        manifest.update(f"{p.name}:{size}\n".encode())
    return {
        "root": str(CORPUS_ROOT),
        "claims_dir": str(CLAIMS_DIR),
        "claims_files": len(claims),
        "reference_pdfs": len(pdfs),
        "reference_bytes": total,
        "reference_manifest_sha256": manifest.hexdigest(),
    }


def envelope(name: str, command: list[str], **extra) -> dict:
    return {
        "schema": SCHEMA,
        "experiment": name,
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git": git_state(),
        "machine": machine(),
        "corpus": corpus(),
        "command": command,
        **extra,
    }


def write(name: str, payload: dict) -> pathlib.Path:
    """Write the whole result structure. Called before anything is printed."""
    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / f"{name}.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=False, default=str))
    tmp.replace(out)
    return out


def results_digest(rows: list) -> str:
    """A canonical hash of the verdicts, so two configurations can be compared for semantic
    equivalence. Timings are deliberately excluded: a faster run that decides differently is
    not a faster run of the same check."""
    canon = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode()).hexdigest()
