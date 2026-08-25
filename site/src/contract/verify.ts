// A second implementation of the evidence contract, in TypeScript.
//
// This exists so the browser demo runs the real rules rather than a mock, and so the
// specification has two implementations that can be checked against the same fixtures.
// It deliberately mirrors the Python engine's vocabulary: six outcomes, a separate reason,
// and validity as its own axis. A demo that invented friendlier names would be demonstrating
// something the tool does not do.

export type Outcome =
  | "verified"
  | "mismatch"
  | "not_found"
  | "unchecked"
  | "error"
  | "not_offered";

export type Reason =
  | "value_match"
  | "value_mismatch"
  | "pointer_absent"
  | "selector_not_scalar"
  | "value_not_numeric"
  | "format_unsupported"
  | "artifact_missing"
  | "artifact_unreadable"
  | "backend_defect";

export type Validity =
  | "authoritative"
  | "unpinned_artifact"
  | "broken_pin"
  | "artifact_absent";

export interface Decision {
  outcome: Outcome;
  reason: Reason;
  validity: Validity;
  detail: string;
  extracted: string | null;
  trace: string[];
}

/** RFC 6901 JSON Pointer resolution. `undefined` means the pointer addresses nothing. */
export function resolvePointer(document: unknown, pointer: string): unknown {
  if (pointer === "") return document;
  if (!pointer.startsWith("/")) throw new Error(`JSON Pointer must start with "/": ${pointer}`);
  let node: unknown = document;
  for (const raw of pointer.slice(1).split("/")) {
    const token = raw.replace(/~1/g, "/").replace(/~0/g, "~");
    if (Array.isArray(node)) {
      // RFC 6901 array indices carry no leading zeros, so "01" addresses nothing and is
      // never silently read as 1.
      if (!/^(0|[1-9][0-9]*)$/.test(token)) return undefined;
      const index = Number(token);
      if (index >= node.length) return undefined;
      node = node[index];
    } else if (node !== null && typeof node === "object") {
      if (!(token in (node as Record<string, unknown>))) return undefined;
      node = (node as Record<string, unknown>)[token];
    } else {
      return undefined;
    }
  }
  return node;
}

export async function sha256Hex(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** Compare at the precision the manuscript printed, so 0.031 does not fail against 0.0310. */
function agrees(stored: number, reported: string): boolean {
  const dot = reported.indexOf(".");
  const places = dot < 0 ? 0 : reported.length - dot - 1;
  return stored.toFixed(places) === Number(reported).toFixed(places);
}

export interface Input {
  artifact: string;
  pointer: string;
  reported: string;
  /** The digest the manifest recorded. Empty means the artifact was never pinned. */
  pinned?: string;
}

export async function verify(input: Input): Promise<Decision> {
  const trace: string[] = [];
  const actual = await sha256Hex(input.artifact);
  trace.push(`sha256(artifact) = ${actual.slice(0, 16)}…`);

  let validity: Validity = "unpinned_artifact";
  if (input.pinned) {
    validity = input.pinned === actual ? "authoritative" : "broken_pin";
    trace.push(
      validity === "authoritative"
        ? "digest matches the pin"
        : `digest does NOT match the pin (${input.pinned.slice(0, 16)}…)`,
    );
  } else {
    trace.push("no digest recorded — the file read may not be the file meant");
  }

  let document: unknown;
  try {
    document = JSON.parse(input.artifact);
  } catch (e) {
    return {
      outcome: "unchecked",
      reason: "artifact_unreadable",
      validity,
      detail: `not valid JSON: ${(e as Error).message}`,
      extracted: null,
      trace,
    };
  }

  let node: unknown;
  try {
    node = resolvePointer(document, input.pointer);
  } catch (e) {
    return {
      outcome: "error",
      reason: "backend_defect",
      validity,
      detail: (e as Error).message,
      extracted: null,
      trace,
    };
  }

  if (node === undefined) {
    trace.push(`${input.pointer} resolves to nothing`);
    return {
      outcome: "not_found",
      reason: "pointer_absent",
      validity,
      detail: `${input.pointer} does not resolve`,
      extracted: null,
      trace,
    };
  }
  if (node === null) {
    // `String(null)` is "null", which compares. A null is an absent value, not a value.
    trace.push(`${input.pointer} holds null`);
    return {
      outcome: "not_found",
      reason: "pointer_absent",
      validity,
      detail: `${input.pointer} holds null`,
      extracted: null,
      trace,
    };
  }
  if (typeof node === "object") {
    trace.push(`${input.pointer} holds a ${Array.isArray(node) ? "list" : "object"}`);
    return {
      outcome: "not_found",
      reason: "selector_not_scalar",
      validity,
      detail: `${input.pointer} holds a container, not a value`,
      extracted: null,
      trace,
    };
  }

  const extracted = String(node);
  trace.push(`extracted ${extracted}`);

  if (typeof node !== "number" || !Number.isFinite(node) || !Number.isFinite(Number(input.reported))) {
    return {
      outcome: "not_found",
      reason: "value_not_numeric",
      validity,
      detail: `${extracted} is not a quantity to compare`,
      extracted,
      trace,
    };
  }

  const ok = agrees(node, input.reported);
  trace.push(`compared ${extracted} against ${input.reported} at printed precision → ${ok}`);
  return {
    outcome: ok ? "verified" : "mismatch",
    reason: ok ? "value_match" : "value_mismatch",
    validity,
    detail: ok
      ? `manuscript prints ${input.reported}, artifact holds ${extracted}`
      : `manuscript prints ${input.reported}, artifact holds ${extracted}`,
    extracted,
    trace,
  };
}
