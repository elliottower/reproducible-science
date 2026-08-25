#!/usr/bin/env bash
# Build the in-browser JupyterLab into the site's static assets.
#
# Not committed: the output is ~21 MB across ~526 files, which is build output rather than
# source. CI runs this before the site build; locally, run it once.
#
# Source maps are deleted afterwards. They are 48 MB of the 69 MB JupyterLite emits, and they
# exist so somebody can debug JupyterLab's own internals in a browser devtools pane. Nobody is
# doing that from a documentation site, and 48 MB is most of a Cloudflare Pages budget.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="$here/../site/public/jlite"

rm -rf "$out"
uvx --with jupyterlite-core --with jupyterlite-pyodide-kernel --with jupyter-server \
  jupyter lite build \
    --contents "$here/end-to-end.ipynb" \
    --contents "$here/prereg.ipynb" \
    --contents "$here/results.ipynb" \
    --contents "$here/citations.ipynb" \
    --contents "$here/paper.pdf" \
    --output-dir "$out"

before=$(du -sh "$out" | cut -f1)
find "$out" -name '*.map' -delete
echo "jlite: $before -> $(du -sh "$out" | cut -f1), $(find "$out" -type f | wc -l | tr -d ' ') files"
