"""The page as one read-only .html file: the built page's script and styles inlined, and the
project's graph.json embedded, so it opens in any browser with nothing installed.

The page reads the embedded data instead of fetching graph.json, and every button that needs the
local server says so and names the command to run instead. The server's launch token is never
in the file: it is built from the built page, not from the page the server serves.
"""

from __future__ import annotations

import html
import pathlib
import re

#: Marks the page as an export; the page reads it to know it has no server.
STATIC_META = '<meta name="repro-ui-static" content="1" />'
SCRIPT = re.compile(r'<script type="module" crossorigin src="\./(assets/[^"]+\.js)"></script>')
STYLE = re.compile(r'<link rel="stylesheet" crossorigin href="\./(assets/[^"]+\.css)">')


def embedded_json(data: bytes) -> str:
    """JSON safe inside a <script> element: every `<` written as its escape, so no `</script>`
    or `<!--` inside a string can end the element. Still the same JSON once parsed."""
    return data.decode("utf-8").replace("<", "\\u003c")


def export_html(static: pathlib.Path, graph: bytes, title: str) -> str:
    """The single file: `static`'s index.html with its assets inlined and `graph` embedded."""
    page = (static / "index.html").read_text()

    def script(m: re.Match) -> str:
        code = (static / m.group(1)).read_text().replace("</script", "<\\/script")
        return f'<script type="module">{code}</script>'

    def style(m: re.Match) -> str:
        css = (static / m.group(1)).read_text().replace("</style", "<\\/style")
        return f"<style>{css}</style>"

    page = SCRIPT.sub(script, page)
    page = STYLE.sub(style, page)
    data = f'<script type="application/json" id="repro-graph">{embedded_json(graph)}</script>'
    page = page.replace("<head>", f"<head>\n    {STATIC_META}", 1)
    named = f"<title>{html.escape(title)}</title>"
    page = re.sub(r"<title>[^<]*</title>", lambda _: named, page, count=1)
    for end in ("</body>", "</html>"):
        if end in page:
            return page.replace(end, f"{data}\n{end}", 1)
    return page + data
