// Copy the canonical Markdown into the docs tree with the front matter Starlight needs.
// The source of truth stays where it is -- SPEC.md next to the code it specifies, package
// READMEs where PyPI renders them from -- so the site cannot show a version the repository
// does not hold.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..", "..");
const DOCS = resolve(HERE, "..", "src", "content", "docs");

// Fourth element is the demo page for that tool, linked directly under the slogan. A reader
// who lands on a tool page from a search result has no reason to know a runnable version
// exists, and the sidebar group is not an answer -- it is a different section.
const SYNCED = [
  ["docs/SPEC.md", "reference/spec.md", "Specification"],
  ["docs/RELEASING.md", "reference/releasing.md", "Releasing"],
  ["CHANGELOG.md", "reference/changelog.md", "Changelog"],
  ["packages/prereg/README.md", "tools/prereg.md", "Prereg", "prereg"],
  ["packages/citations/README.md", "tools/citations.md", "Citations", "citations"],
  ["packages/results/README.md", "tools/results.md", "Results", "results"],
  ["packages/repro/README.md", "tools/repro.md", "Repro", "end-to-end"],
];

/** Insert a line after the slogan -- the first paragraph of the README body. */
function afterSlogan(body, line) {
  const end = body.indexOf("\n\n");
  if (end < 0) return `${body}\n\n${line}\n`;
  return `${body.slice(0, end)}\n\n${line}${body.slice(end)}`;
}

let written = 0;
for (const [source, target, title, demo] of SYNCED) {
  let body;
  try {
    body = readFileSync(join(REPO, source), "utf8");
  } catch {
    console.error(`  MISSING  ${source}`);
    process.exitCode = 1;
    continue;
  }
  body = body.replace(/^#\s+.*\n+/, "");
  if (demo) {
    body = afterSlogan(
      body,
      `**[Run it in your browser](/reproducible-science/demo/${demo}/)** — every command on this page, ` +
        `in a live notebook. No install.`,
    );
  }
  const out = join(DOCS, target);
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(
    out,
    `---\ntitle: ${title}\ndescription: ${title} — Reproducible Science\n---\n\n` +
      `<!-- Generated from ${source}. Edit that file, not this one. -->\n\n${body}`,
  );
  written += 1;
  console.log(`  ${source}  ->  ${target}`);
}
console.log(`\n  synced ${written}/${SYNCED.length}`);
