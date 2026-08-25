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
      head: [
        {
          tag: "script",
          content: `
            document.addEventListener("click", (e) => {
              const button = e.target.closest(".nb-start");
              if (!button) return;
              const box = button.closest(".nb-embed");
              const frame = document.createElement("iframe");
              frame.src = "/reproducible-science/jlite/lab/index.html?path=" +
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
            { label: "Prereg", link: "/tools/prereg/", attrs: { "data-tool": "prereg" } },
            { label: "Results", link: "/tools/results/", attrs: { "data-tool": "results" } },
            { label: "Citations", link: "/tools/citations/", attrs: { "data-tool": "citations" } },
            { label: "Repro", link: "/tools/repro/", attrs: { "data-tool": "repro" } },
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
