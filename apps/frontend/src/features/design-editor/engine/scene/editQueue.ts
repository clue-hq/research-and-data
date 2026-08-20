import type { Diagnostic, Operation, Scene } from "./contracts";

/**
 * Track E W3: the optimistic pipeline's server leg.
 *
 * Local edits apply instantly through the WASM engine; this queue persists
 * the same operation batches to the document API in order, carrying
 * `base_version` so concurrent writers are detected, and reconciles the
 * server's authoritative scene against the local optimistic scene whenever
 * the queue drains. Server authority is untouched: these are the exact
 * `/documents/{id}/operations` payload and envelope semantics Phase D
 * built. With the same engine on both sides, divergence is a bug signal —
 * it surfaces as a diagnostic and the local scene is replaced by the
 * server scene, never silently tolerated.
 */

export type ReconcileEventKind = "divergence" | "rejected" | "request_failed";

export interface ReconcileEvent {
  kind: ReconcileEventKind;
  /** Authoritative server scene to load locally, when one was recovered. */
  serverScene: Scene | null;
  serverVersion: number | null;
  diagnostic: Diagnostic;
}

export interface EnqueueOptions {
  /** Server-side checkpoint label stamped onto this batch's envelope
   * (checkpoint_label) — the anchor Compare/Revert points at. */
  checkpoint?: string;
}

export interface EditQueuePort {
  /** Queue a locally-applied operation batch for persistence. */
  enqueueOperations(operations: Operation[], options?: EnqueueOptions): void;
  /** Resolves when every queued batch has been processed. */
  idle(): Promise<void>;
  /** Number of batches accepted by the server since creation. */
  readonly persistedBatches: number;
  /** Re-sync after an external server-side write (e.g. a checkpoint revert):
   * the cached base_version is stale and the next batch would be rejected as
   * a concurrent write. Passing null re-fetches on the next batch. Also
   * clears a halted queue — the caller just adopted authoritative state. */
  resync(version: number | null): void;
}

export interface EditQueueOptions {
  apiBaseUrl: string;
  documentId: string;
  /** Current local optimistic scene, for the drain-time divergence check. */
  localScene: () => Scene;
  /** Receives divergence/rejection/failure events to apply + surface. */
  onReconcile: (event: ReconcileEvent) => void;
  fetchImpl?: typeof fetch;
}

export function createEditQueue(options: EditQueueOptions): EditQueuePort {
  return new ApiEditQueue(options);
}

class ApiEditQueue implements EditQueuePort {
  persistedBatches = 0;
  private chain: Promise<void> = Promise.resolve();
  private pending = 0;
  private baseVersion: number | null = null;
  private halted = false;
  private readonly fetchImpl: typeof fetch;

  constructor(private readonly options: EditQueueOptions) {
    // Wrap the global fetch instead of storing it bare: calling a class-field
    // `this.fetchImpl(...)` rebinds `this` to the queue instance, and browser
    // fetch throws "Illegal invocation" off its Window. Unit tests always
    // inject fetchImpl, so only the real browser ever hit this.
    // Workspace auth is the BFF's job — the browser never stamps headers.
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  enqueueOperations(operations: Operation[], options?: EnqueueOptions): void {
    if (operations.length === 0 || this.halted) {
      return;
    }
    this.pending += 1;
    this.chain = this.chain
      .then(() => this.persistBatch(operations, options))
      .catch((error: unknown) => {
        this.halted = true;
        this.options.onReconcile({
          kind: "request_failed",
          serverScene: null,
          serverVersion: null,
          diagnostic: requestFailedDiagnostic(error)
        });
      })
      .finally(() => {
        this.pending -= 1;
      });
  }

  idle(): Promise<void> {
    return this.chain.then(() => undefined);
  }

  resync(version: number | null): void {
    this.baseVersion = version;
    this.halted = false;
  }

  private async persistBatch(operations: Operation[], options?: EnqueueOptions): Promise<void> {
    if (this.halted) {
      return;
    }
    if (this.baseVersion === null) {
      this.baseVersion = await this.fetchCurrentVersion();
    }
    const response = await this.fetchImpl(
      `${this.options.apiBaseUrl}/documents/${encodeURIComponent(this.options.documentId)}/operations`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          operations,
          actor: { kind: "editor" },
          source: "editor",
          base_version: this.baseVersion,
          ...(options?.checkpoint ? { checkpoint: options.checkpoint } : {})
        })
      }
    );

    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      this.halted = true;
      const recovered = await this.fetchDocument().catch(() => null);
      this.options.onReconcile({
        kind: "rejected",
        serverScene: (recovered?.scene as Scene | undefined) ?? null,
        serverVersion: (recovered?.current_version as number | undefined) ?? null,
        diagnostic: {
          severity: "error",
          phase: "operation",
          code: "EDITOR_WASM_EDIT_REJECTED",
          message: `The server rejected a persisted edit batch (${response.status}): ${JSON.stringify(detail)}`,
          subject: { kind: "document" },
          hint: "The local scene has been replaced by the server's authoritative state."
        }
      });
      return;
    }

    const payload = (await response.json()) as {
      document?: { current_version?: number };
    };
    this.persistedBatches += 1;
    this.baseVersion = payload.document?.current_version ?? null;

    // Reconcile only at drain (pending === 1 means this batch is the last
    // queued): comparing mid-flight would race optimistic batches the
    // server has not seen yet.
    if (this.pending === 1) {
      await this.reconcile();
    }
  }

  private async reconcile(): Promise<void> {
    const document = await this.fetchDocument();
    const serverScene = document.scene as Scene;
    const serverVersion = (document.current_version as number | undefined) ?? null;
    const localScene = this.options.localScene();
    // Compare authoritative state only. `computed` geometry is a derived
    // cache: the server computes it under Skia, the local engine under the
    // heuristic, so they legitimately differ. Including it here would flag a
    // false divergence on every reconcile and replace the coherent local
    // scene with server geometry (jumping text). True divergence is a
    // disagreement in the authored fields.
    if (deepEqual(withoutComputed(serverScene), withoutComputed(localScene))) {
      return;
    }
    this.options.onReconcile({
      kind: "divergence",
      serverScene,
      serverVersion,
      diagnostic: {
        severity: "error",
        phase: "operation",
        code: "EDITOR_WASM_RECONCILE_DIVERGENCE",
        message:
          "Optimistic scene diverged from the server after reconciliation. The local scene has been replaced by the server's authoritative state.",
        subject: { kind: "document" },
        hint:
          "With the same engine on both sides this should never happen outside concurrent edits — report it as an engine bug."
      }
    });
  }

  private async fetchCurrentVersion(): Promise<number | null> {
    const document = await this.fetchDocument();
    return (document.current_version as number | undefined) ?? null;
  }

  private async fetchDocument(): Promise<Record<string, unknown>> {
    const response = await this.fetchImpl(
      `${this.options.apiBaseUrl}/documents/${encodeURIComponent(this.options.documentId)}`
    );
    if (!response.ok) {
      throw new Error(`document fetch failed (${response.status})`);
    }
    return (await response.json()) as Record<string, unknown>;
  }
}

function requestFailedDiagnostic(error: unknown): Diagnostic {
  return {
    severity: "error",
    phase: "operation",
    code: "EDITOR_WASM_EDIT_PERSIST_FAILED",
    message:
      error instanceof Error
        ? `Persisting edits to the server failed: ${error.message}`
        : "Persisting edits to the server failed.",
    subject: { kind: "document" },
    hint:
      "Local optimistic edits continue, but they are not persisted. Check the API connection and reload the document."
  };
}

/** Structural deep equality: object key order must not matter (the server
 * serializes from BTreeMaps; the local snapshot preserves insertion order). */
/**
 * Deep clone with every `computed` geometry field removed, so reconcile
 * compares authoritative authored state only (the server recomputes
 * geometry canonically under Skia; the local engine uses the heuristic).
 */
function withoutComputed<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.map((entry) => withoutComputed(entry)) as unknown as T;
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
      if (key === "computed") {
        continue;
      }
      out[key] = withoutComputed(entry);
    }
    return out as T;
  }
  return value;
}

function deepEqual(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) {
    return true;
  }
  if (Array.isArray(left) || Array.isArray(right)) {
    if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) {
      return false;
    }
    return left.every((entry, index) => deepEqual(entry, right[index]));
  }
  if (
    typeof left !== "object" ||
    typeof right !== "object" ||
    left === null ||
    right === null
  ) {
    return false;
  }
  const leftEntries = Object.entries(left as Record<string, unknown>);
  const rightRecord = right as Record<string, unknown>;
  if (leftEntries.length !== Object.keys(rightRecord).length) {
    return false;
  }
  return leftEntries.every(
    ([key, value]) => key in rightRecord && deepEqual(value, rightRecord[key])
  );
}
