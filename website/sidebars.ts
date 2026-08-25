import type { SidebarsConfig } from "@docusaurus/plugin-content-docs";

const sidebars: SidebarsConfig = {
  docs: [
    { type: "doc", id: "index", label: "Overview" },
    {
      type: "category",
      label: "Get started",
      collapsed: false,
      items: ["start/install", "start/first-check"],
    },
    {
      type: "category",
      label: "Concepts",
      items: ["concepts/evidence-contract", "concepts/outcomes", "concepts/pinning"],
    },
    {
      type: "category",
      label: "Tools",
      items: ["tools/prereg", "tools/citations", "tools/results", "tools/repro"],
    },
    {
      type: "category",
      label: "Reference",
      items: ["reference/spec", "reference/releasing", "reference/changelog"],
    },
  ],
};

export default sidebars;
