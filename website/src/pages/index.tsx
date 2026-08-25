import Link from "@docusaurus/Link";
import Layout from "@theme/Layout";
import React from "react";
import styles from "./index.module.css";

const TOOLS = [
  ["prereg", "prereg", "freezes a plan before running, records what changed after"],
  ["citations", "citations", "checks that quotations resolve in the sources they cite"],
  ["results", "results-cli", "seals inputs, records outputs, binds claims to runs"],
  ["repro", "reproducible-science", "verifies declared evidence against pinned artifacts"],
];

export default function Home(): React.ReactElement {
  return (
    <Layout description="Evidence that can be checked again">
      <main className={styles.main}>
        <section className={styles.hero}>
          <h1>Evidence that can be checked again.</h1>
          <p className={styles.lede}>
            A number in a manuscript names a claim. The claim names a run. The run names its
            outputs, hashed when they were recorded. The inputs were hashed before the run
            started.
          </p>
          <div className={styles.actions}>
            <Link className={styles.primary} to="/docs/start/install">
              Get started
            </Link>
            <Link className={styles.secondary} to="/lab">
              Open the Lab
            </Link>
          </div>
        </section>

        <section className={styles.band}>
          <h2>Did the source really say that?</h2>
          <div className={styles.compare}>
            <div>
              <p className={styles.label}>The manuscript</p>
              <code>The effect was significant, p &lt; 0.05.</code>
            </div>
            <div>
              <p className={styles.label}>The source</p>
              <code>p = 0.05</code>
            </div>
          </div>
          <p className={styles.result}>
            Ordinary text matching finds the passage. The evidence contract records{" "}
            <strong>mismatch</strong>, because the declared strict inequality is false.
          </p>
        </section>

        <section className={styles.tools}>
          <h2>Four focused tools</h2>
          <div className={styles.toolGrid}>
            {TOOLS.map(([name, dist, what]) => (
              <Link key={name} className={styles.tool} to={`/docs/tools/${name}`}>
                <strong>{name}</strong>
                <code>pip install {dist}</code>
                <span>{what}</span>
              </Link>
            ))}
          </div>
          <p className={styles.note}>
            Each is an independent distribution, so installing citation verification never
            drags in a preregistration tool.
          </p>
        </section>
      </main>
    </Layout>
  );
}
