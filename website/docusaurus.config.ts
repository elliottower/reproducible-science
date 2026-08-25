import type * as Preset from "@docusaurus/preset-classic";
import type { Config } from "@docusaurus/types";
import { themes as prismThemes } from "prism-react-renderer";

const config: Config = {
  title: "Reproducible Science",
  tagline: "Evidence that can be checked again",
  favicon: "img/favicon.ico",

  url: "https://mechanisticresearch.org",
  baseUrl: "/reproducible-science/",
  organizationName: "elliottower",
  projectName: "reproducible-science",

  // A broken link is a broken promise on a site about verification.
  onBrokenLinks: "throw",
  markdown: { hooks: { onBrokenMarkdownLinks: "throw" } },

  future: { v4: true },

  i18n: { defaultLocale: "en", locales: ["en"] },

  presets: [
    [
      "classic",
      {
        docs: {
          sidebarPath: "./sidebars.ts",
          editUrl:
            "https://github.com/elliottower/reproducible-science/tree/main/website/",
        },
        blog: false,
        theme: { customCss: "./src/css/custom.css" },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    image: "img/social-card.png",
    colorMode: { respectPrefersColorScheme: true },
    navbar: {
      title: "Reproducible Science",
      items: [
        { type: "docSidebar", sidebarId: "docs", position: "left", label: "Docs" },
        { to: "/lab", label: "Lab", position: "left" },
        {
          href: "https://github.com/elliottower/reproducible-science",
          label: "GitHub",
          position: "right",
        },
      ],
    },
    footer: {
      style: "light",
      links: [
        {
          title: "Tools",
          items: [
            { label: "prereg", to: "/docs/tools/prereg" },
            { label: "citations", to: "/docs/tools/citations" },
            { label: "results", to: "/docs/tools/results" },
            { label: "repro", to: "/docs/tools/repro" },
          ],
        },
        {
          title: "Reference",
          items: [
            { label: "Specification", to: "/docs/reference/spec" },
            { label: "Changelog", to: "/docs/reference/changelog" },
            { label: "Releasing", to: "/docs/reference/releasing" },
          ],
        },
        {
          title: "Project",
          items: [
            { label: "GitHub", href: "https://github.com/elliottower/reproducible-science" },
            { label: "PyPI", href: "https://pypi.org/project/reproducible-science/" },
          ],
        },
      ],
      copyright: `MIT licensed.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ["bash", "json", "yaml", "python"],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
