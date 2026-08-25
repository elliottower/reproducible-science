import React, { useCallback, useEffect, useState } from "react";
import { type Decision, sha256Hex, verify } from "../contract/verify";
import styles from "./Lab.module.css";

const BASELINE = `{
  "primary": {
    "p": 0.031,
    "n": 147
  }
}`;

interface Mutation {
  label: string;
  hint: string;
  apply: (s: State) => Partial<State>;
}

interface State {
  artifact: string;
  pointer: string;
  reported: string;
  pinned: string;
}

const MUTATIONS: Mutation[] = [
  {
    label: "Change the stored value",
    hint: "the artifact was read and disagrees",
    apply: (s) => ({ artifact: s.artifact.replace(/"p":\s*[0-9.]+/, '"p": 0.051') }),
  },
  {
    label: "Delete the addressed key",
    hint: "nothing was compared, so nothing disagreed",
    apply: (s) => ({ artifact: s.artifact.replace(/\s*"p":\s*[0-9.]+,?\n/, "\n") }),
  },
  {
    label: "Address a container",
    hint: "a section is not a value",
    apply: () => ({ pointer: "/primary" }),
  },
  {
    label: "Set the value to null",
    hint: "null is an absent value, not a value",
    apply: (s) => ({ artifact: s.artifact.replace(/"p":\s*[0-9.]+/, '"p": null') }),
  },
  {
    label: "Corrupt the pin",
    hint: "every number agrees — with a document nobody pinned",
    apply: () => ({ pinned: "de".repeat(32) }),
  },
];

const OUTCOME_CLASS: Record<string, string> = {
  verified: styles.verified,
  mismatch: styles.mismatch,
  not_found: styles.notFound,
  unchecked: styles.unchecked,
  error: styles.error,
  not_offered: styles.unchecked,
};

export default function Lab(): React.ReactElement {
  const [state, setState] = useState<State>({
    artifact: BASELINE,
    pointer: "/primary/p",
    reported: "0.031",
    pinned: "",
  });
  const [decision, setDecision] = useState<Decision | null>(null);

  const run = useCallback(async (s: State) => {
    setDecision(await verify({ ...s, pinned: s.pinned || undefined }));
  }, []);

  useEffect(() => {
    void run(state);
  }, [state, run]);

  const pin = async () => {
    setState((s) => ({ ...s }));
    const digest = await sha256Hex(state.artifact);
    setState((s) => ({ ...s, pinned: digest }));
  };

  const reset = () =>
    setState({ artifact: BASELINE, pointer: "/primary/p", reported: "0.031", pinned: "" });

  return (
    <div className={styles.lab}>
      <p className={styles.note}>
        Everything below runs in your browser. Nothing is uploaded.
      </p>

      <div className={styles.grid}>
        <section>
          <h3>Artifact</h3>
          <p className={styles.caption}>results.json</p>
          <textarea
            className={styles.editor}
            value={state.artifact}
            spellCheck={false}
            rows={9}
            onChange={(e) => setState((s) => ({ ...s, artifact: e.target.value }))}
          />
          <div className={styles.pinRow}>
            <button className={styles.smallButton} onClick={pin} type="button">
              Pin this artifact
            </button>
            <code className={styles.digest}>
              {state.pinned ? `${state.pinned.slice(0, 24)}…` : "no digest recorded"}
            </code>
          </div>
        </section>

        <section>
          <h3>Evidence</h3>
          <p className={styles.caption}>what the manuscript claims</p>
          <label className={styles.field}>
            <span>JSON Pointer (RFC 6901)</span>
            <input
              value={state.pointer}
              spellCheck={false}
              onChange={(e) => setState((s) => ({ ...s, pointer: e.target.value }))}
            />
          </label>
          <label className={styles.field}>
            <span>Value printed in the paper</span>
            <input
              value={state.reported}
              spellCheck={false}
              onChange={(e) => setState((s) => ({ ...s, reported: e.target.value }))}
            />
          </label>
          <button className={styles.reset} onClick={reset} type="button">
            Reset to the baseline
          </button>
        </section>
      </div>

      {decision && (
        <div className={`${styles.decision} ${OUTCOME_CLASS[decision.outcome]}`}>
          <div className={styles.verdict}>
            <strong>{decision.outcome.replace("_", " ").toUpperCase()}</strong>
            <span className={styles.codes}>
              reason <code>{decision.reason}</code> · validity{" "}
              <code>{decision.validity}</code>
            </span>
          </div>
          <p className={styles.detail}>{decision.detail}</p>
          <ol className={styles.trace}>
            {decision.trace.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ol>
        </div>
      )}

      <h3>Break it</h3>
      <div className={styles.mutations}>
        {MUTATIONS.map((m) => (
          <button
            key={m.label}
            className={styles.mutation}
            type="button"
            onClick={() => setState((s) => ({ ...s, ...m.apply(s) }))}
          >
            <strong>{m.label}</strong>
            <span>{m.hint}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
