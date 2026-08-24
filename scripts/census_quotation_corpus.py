"""Exact quotation-corpus figures, regenerated."""
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path.home() / "Documents/GitHub/citations/src"))
from citations import verify as V
from citations.exceptions import ClaimFileError
from citations.models import load_claim_file

gh = pathlib.Path.home() / "Documents/GitHub"
files = sorted(gh.glob("*/claims/*.yaml"))
projects, quotes, unparsed = set(), 0, 0
pins = collections.Counter()

for f in files:
    try:
        cf = load_claim_file(f)
    except ClaimFileError:
        unparsed += 1
        continue
    projects.add(f.parent.parent.name)
    quotes += sum(len(c.quotes) for c in cf.claims.values())
    pins[V.check_pin(cf.artifact(), cf.source.sha256).state] += 1

print(f"  claims files            : {len(files)}  ({unparsed} unparseable)")
print(f"  manuscripts             : {len(projects)}")
print(f"  quotation assertions    : {quotes:,}")
print(f"  source pin states       : {dict(pins)}")
