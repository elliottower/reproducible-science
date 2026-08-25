// @ts-check
import starlight from "@astrojs/starlight";
import { defineConfig } from "astro/config";

export default defineConfig({
  // GitHub Pages, matching mechanistic-views. Nobody looks twice at a github.io docs URL,
  // and it needs no DNS. A domain can be pointed here later with a Cloudflare-proxied CNAME,
  // which is what makes analytics count requests server-side instead of relying on a beacon
  // an ad blocker can drop. Changing that is this one line plus a rebuild.
  site: "https://elliottower.github.io",
  base: "/reproducible-science",
  integrations: [
    starlight({
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
        {
          label: "Demo",
          // `data-tool` is spread onto the anchor by SidebarSublist and rendered as a code-styled
          // suffix in custom.css. The label itself is escaped text, so a backtick in it would
          // show up as a literal backtick -- this is the way to get the package name set in mono
          // without copying Starlight's sidebar internals.
          // Workflow order: freeze the plan, record the run, check the quotations, and verify
          // the lot. The end-to-end notebook runs that chain, so it comes first.
          items: [
            { label: "End to end", link: "/demo/end-to-end/", attrs: { "data-tool": "repro" } },
            { label: "Freeze a plan", link: "/demo/prereg/", attrs: { "data-tool": "prereg" } },
            { label: "Record a run", link: "/demo/results/", attrs: { "data-tool": "results" } },
            { label: "Check a quotation", link: "/demo/citations/", attrs: { "data-tool": "citations" } },
          ],
        },
        {
          label: "Get started",
          items: [
            { label: "Installation", link: "/start/install/" },
            { label: "Your first check", link: "/start/first-check/" },
          ],
        },
        {
          label: "Concepts",
          items: [
            { label: "The evidence contract", link: "/concepts/evidence-contract/" },
            { label: "Outcomes and reasons", link: "/concepts/outcomes/" },
            { label: "Pinning", link: "/concepts/pinning/" },
          ],
        },
        {
          label: "Tools",
          items: [
            { label: "prereg", link: "/tools/prereg/" },
            { label: "citations", link: "/tools/citations/" },
            { label: "results", link: "/tools/results/" },
            { label: "repro", link: "/tools/repro/" },
          ],
        },
        {
          label: "Reference",
          collapsed: true,
          items: [
            { label: "Specification", link: "/reference/spec/" },
            { label: "Releasing", link: "/reference/releasing/" },
            { label: "Changelog", link: "/reference/changelog/" },
          ],
        },
      ],
    }),
  ],
});
