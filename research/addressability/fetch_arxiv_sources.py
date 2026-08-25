"""Fetch LaTeX source for a set of papers, to test the citation heuristic outside one author.

The `\\cite`-on-the-line rule marks a number as belonging to the work cited. It was calibrated
on a single meta-analysis, where it separated quoted odds ratios from the author's own
counts. A meta-analysis is the friendliest possible case: it tabulates other people's numbers
on purpose. An ML paper cites in prose beside its own accuracies, and the rule should be
expected to over-attribute there.

Titles are resolved through the arXiv API rather than written from memory, because an
identifier typed from recall resolves to a real and unrelated paper often enough to matter.
Source is fetched from the e-print endpoint, which serves the submitted LaTeX.
"""

from __future__ import annotations

import io
import json
import pathlib
import re
import ssl
import tarfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree

HERE = pathlib.Path(__file__).parent
CORPUS = HERE / "arxiv_corpus"
INDEX = CORPUS / "resolved.json"

USER_AGENT = "addressability-sample/1.0 (research; contact elliot@elliottower.ai)"

#: arXiv asks for one request every three seconds and will throttle otherwise. A corpus
#: assembled while rate-limited is a corpus whose composition depends on when it ran.
DELAY_SECONDS = 3.0

ATOM = "{http://www.w3.org/2005/Atom}"

#: Titles to resolve. Chosen to span the cases the rule should handle differently: papers
#: that report their own benchmark numbers beside heavy related-work citation, papers whose
#: tables compare against prior published figures, and papers that are mostly derivation.
TITLES = [
    "Attention Is All You Need",
    "Interpretability in the Wild: a Circuit for Indirect Object Identification in GPT-2 small",
    "Towards Automated Circuit Discovery for Mechanistic Interpretability",
    "Sparse Autoencoders Find Highly Interpretable Features in Language Models",
    "Locating and Editing Factual Associations in GPT",
    "Causal Abstraction: A Theoretical Foundation for Mechanistic Interpretability",
    "RAVEL: Evaluating Interpretability Methods on Disentangling Language Model Representations",
    "Deep Residual Learning for Image Recognition",
    "Adam: A Method for Stochastic Optimization",
    "Batch Normalization: Accelerating Deep Network Training by Reducing Internal Covariate Shift",
    "Training Compute-Optimal Large Language Models",
    "Language Models are Few-Shot Learners",
    "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
    "LLaMA: Open and Efficient Foundation Language Models",
    "Denoising Diffusion Probabilistic Models",
    "An Image is Worth 16x16 Words: Transformers for Image Recognition at Scale",
    "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models",
    "Toy Models of Superposition",
    "Scaling Laws for Neural Language Models",
    "Emergent Abilities of Large Language Models",
]


def context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


CONTEXT = context()


def get(url: str, timeout: int = 60) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=CONTEXT) as response:
            return response.read()
    except Exception:
        return None


def resolve(title: str) -> dict | None:
    """The arXiv entry whose title matches, or None.

    Matched on the returned title rather than trusting rank alone: a search for a well-known
    title returns papers that cite it as well as the paper itself.
    """
    query = urllib.parse.urlencode(
        {"search_query": f'ti:"{title}"', "max_results": 5, "sortBy": "relevance"}
    )
    payload = get(f"http://export.arxiv.org/api/query?{query}")
    if not payload:
        return None
    try:
        feed = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        return None

    def normal(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

    for entry in feed.iter(f"{ATOM}entry"):
        found = (entry.findtext(f"{ATOM}title") or "").strip()
        if normal(found).startswith(normal(title)[:48]):
            identifier = (entry.findtext(f"{ATOM}id") or "").rsplit("/", 1)[-1]
            return {
                "title": found,
                "arxiv_id": identifier,
                "published": (entry.findtext(f"{ATOM}published") or "")[:10],
            }
    return None


def fetch_source(arxiv_id: str, into: pathlib.Path) -> list[pathlib.Path]:
    """Extract the submission's `.tex` files, keeping the directory structure.

    The structure is what makes `\\input{sections/results}` resolvable. Flattening every file
    into one directory silently breaks every include: four of twenty papers then reported no
    numbers at all, and the paper with eighteen includes reported none of them.

    Members are written only inside the target directory, since a tar archive may name a
    path that climbs out of it.
    """
    into.mkdir(parents=True, exist_ok=True)
    existing = sorted(into.rglob("*.tex"))
    if existing:
        return existing
    payload = get(f"https://arxiv.org/e-print/{arxiv_id}")
    if not payload:
        return []
    root = into.resolve()
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
            for member in archive.getmembers():
                if not member.isfile() or not member.name.endswith(".tex"):
                    continue
                target = (into / member.name).resolve()
                if not str(target).startswith(str(root)):
                    continue
                handle = archive.extractfile(member)
                if handle is not None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(handle.read())
    except (tarfile.TarError, OSError, ValueError):
        return []
    return sorted(into.rglob("*.tex"))


def main() -> int:
    CORPUS.mkdir(exist_ok=True)
    resolved = json.loads(INDEX.read_text()) if INDEX.exists() else {}

    for title in TITLES:
        if title in resolved and resolved[title].get("tex_files"):
            continue
        entry = resolved.get(title) or resolve(title)
        time.sleep(DELAY_SECONDS)
        if not entry:
            resolved[title] = {"status": "not resolved"}
            print(f"  {title[:56]:<58} not resolved", flush=True)
            continue
        files = fetch_source(entry["arxiv_id"], CORPUS / entry["arxiv_id"].replace("/", "_"))
        entry["tex_files"] = [str(f.relative_to(CORPUS)) for f in files]
        entry["status"] = "source" if files else "no latex source served"
        resolved[title] = entry
        INDEX.write_text(json.dumps(resolved, indent=2) + "\n")
        print(f"  {title[:56]:<58} {entry['arxiv_id']:<12} {len(files)} .tex", flush=True)
        time.sleep(DELAY_SECONDS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
