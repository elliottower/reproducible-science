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

const SYNCED = [
  ["docs/SPEC.md", "reference/spec.md", "Specification"],
  ["docs/RELEASING.md", "reference/releasing.md", "Releasing"],
  ["CHANGELOG.md", "reference/changelog.md", "Changelog"],
  ["packages/prereg/README.md", "tools/prereg.md", "prereg"],
  ["packages/citations/README.md", "tools/citations.md", "citations"],
  ["packages/results/README.md", "tools/results.md", "results"],
  ["packages/repro/README.md", "tools/repro.md", "repro"],
];

let written = 0;
for (const [source, target, title] of SYNCED) {
  let body;
  try {
    body = readFileSync(join(REPO, source), "utf8");
  } catch {
    console.error(`  MISSING  ${source}`);
    process.exitCode = 1;
    continue;
  }
  body = body.replace(/^#\s+.*\n+/, "");
  const out = join(DOCS, target);
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(
    out,
    `---\ntitle: ${title}\ndescription: ${title} — Reproducible Science\n---\n\n` +
      `{/* Generated from ${source}. Edit that file, not this one. */}\n\n${body}`,
  );
  written += 1;
  console.log(`  ${source}  ->  ${target}`);
}
console.log(`\n  synced ${written}/${SYNCED.length}`);
