import Layout from "@theme/Layout";
import React from "react";
import Lab from "../components/Lab";

export default function LabPage(): React.ReactElement {
  return (
    <Layout
      title="Lab"
      description="Verify a claim against an artifact, in the browser"
    >
      <main>
        <div style={{ maxWidth: "60rem", margin: "0 auto", padding: "2.5rem 1rem 0" }}>
          <h1>Verify a claim</h1>
          <p>
            A manuscript prints a number. An artifact holds one. This runs the evidence
            contract over both and reports what it established — and, just as importantly,
            what it could not.
          </p>
        </div>
        <Lab />
      </main>
    </Layout>
  );
}
