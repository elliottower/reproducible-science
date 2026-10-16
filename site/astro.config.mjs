// @ts-check
import starlight from "@astrojs/starlight";
import { defineConfig } from "astro/config";

export default defineConfig({
  // GitHub Pages serving the custom domain. DNS is on Cloudflare; the old
  // elliottower.github.io/reproducible-science address redirects here.
  site: "https://reproducible.science",
  redirects: {
    "/integrations/osf/": "/tools/prereg/#osf-integration",
    "/integrations/opentimestamps/": "/tools/results/#timestamp",
    "/integrations/zotero/": "/tools/citations/#a-bib-exported-from-zotero",
    "/integrations/adduce/": "/integrations/",
    "/integrations/open-items/": "/agents/open-items/",
    "/integrations/init-scaffold/": "/start/init-scaffold/",
    "/start/codex/": "/agents/codex-plugin/",
    "/start/claude-code/": "/agents/claude-code-plugin/",
  },
  integrations: [
    starlight({
      head: [
        {
          tag: "script",
          content: `
            document.addEventListener("click", (e) => {
              const button = e.target.closest(".nb-start");
              if (!button) return;
              const box = button.closest(".nb-embed");
              const frame = document.createElement("iframe");
              frame.src = "/jlite/lab/index.html?path=" +
                encodeURIComponent(box.dataset.nb);
              frame.title = "Live notebook";
              box.replaceChildren(frame);
            });
          `,
        },
      ],
      title: "Reproducible Science",
      description:
        "Freeze a plan before running it, bind every number in a paper to the run that produced it, and check that quoted passages appear in their sources.",
      customCss: ["./src/styles/custom.css"],
      components: { ThemeSelect: "./src/components/ThemeSelect.astro" },
      lastUpdated: false,
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: "https://github.com/elliottower/reproducible-science",
        },
      ],
      editLink: {
        baseUrl: "https://github.com/elliottower/reproducible-science/edit/main/site/",
      },
      expressiveCode: {
        themes: ["github-dark", "github-light"],
        styleOverrides: { borderRadius: "0.375rem" },
        // No window chrome. The three dots on a shell block are decoration pretending to be
        // a terminal, and they take a line of vertical space on every code sample.
        defaultProps: { frame: "none" },
      },
      sidebar: [
        { label: "Overview", link: "/" },
        // `demo/verify` is the TypeScript evidence-contract implementation. It still builds
        // and still passes the conformance cases; it is unlisted while the notebook is the
        // demo we are showing. Its history is in this branch if it comes back.
        // One page per tool, and each tool page carries its own notebook. What is left here is
        // the only demo that is not about a single tool.
        { label: "Live demo", link: "/demo/end-to-end/", attrs: { "data-tool": "repro" } },
        {
          label: "Get started",
          items: [
            { label: "Installation", link: "/start/install/" },
            { label: "Quick start", link: "/start/first-check/" },
            { label: "repro init scaffolding", link: "/start/init-scaffold/" },
          ],
        },
        {
          label: "Concepts",
          items: [
            { label: "Declaring evidence", link: "/concepts/evidence-contract/" },
            { label: "Outcomes and reasons", link: "/concepts/outcomes/" },
            { label: "Pinning", link: "/concepts/pinning/" },
            { label: "The check record", link: "/concepts/check-record/" },
          ],
        },
        {
          label: "Tools",
          items: [
            { label: "Prereg", link: "/tools/prereg/", attrs: { "data-tool": "prereg" } },
            { label: "Results", link: "/tools/results/", attrs: { "data-tool": "results" } },
            { label: "Citations", link: "/tools/citations/", attrs: { "data-tool": "citations" } },
            { label: "Repro", link: "/tools/repro/", attrs: { "data-tool": "repro" } },
            { label: "Claims", link: "/tools/claims/", attrs: { "data-tool": "claims" } },
            { label: "repro ui", link: "/tools/ui/" },
          ],
        },
        {
          label: "Reference",
          items: [
            { label: "Specification", link: "/reference/spec/" },
            { label: "Exports: JSON, SARIF, RO-Crate", link: "/reference/exports/" },
            { label: "Changelog", link: "/reference/changelog/" },
          ],
        },
        {
          label: "Agents",
          items: [
            { label: "Claude Code plugin", link: "/agents/claude-code-plugin/" },
            { label: "Claude Code mod", link: "/agents/claude-code-mod/" },
            { label: "Codex plugin", link: "/agents/codex-plugin/" },
            { label: "MCP server", link: "/agents/mcp/" },
            { label: "Open items", link: "/agents/open-items/" },
          ],
        },
        {
          label: "Automation",
          items: [
            { label: "GitHub CI", link: "/automation/github-ci/" },
            { label: "Pull-request bot", link: "/automation/pr-bot/" },
            { label: "Badges", link: "/tools/repro/#badges-with-counts" },
          ],
        },
        {
          label: "Integrations",
          collapsed: true,
          items: [
            { label: "CODECHECK", link: "/integrations/codecheck/" },
            { label: "CORE-Bench", link: "/integrations/core-bench/" },
            { label: "PaperDelta", link: "/integrations/paperdelta/" },
            { label: "ClawBio", link: "/integrations/clawbio/" },
          ],
        },
      ],
    }),
  ],
});
