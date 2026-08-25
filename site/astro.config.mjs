// @ts-check
import starlight from "@astrojs/starlight";
import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://mechanisticresearch.org",
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
        { label: "Demo", link: "/demo/jupyterlite/" },
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
