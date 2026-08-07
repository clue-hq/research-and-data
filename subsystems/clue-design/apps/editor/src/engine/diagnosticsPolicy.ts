import type { Diagnostic } from "./contracts";

/**
 * Persistence-class diagnostics are STICKY: the editor's diagnostics state is
 * a single slot that many flows overwrite wholesale (export preview,
 * validation resets, agent turns — last writer wins), and a "your edits are
 * not being saved" error must never lose that race silently. A sticky
 * diagnostic survives writes that don't concern it; a new write carrying the
 * SAME code supersedes it (fresher signal), and the flow that resolves the
 * condition clears it explicitly (e.g. successful document adoption clears
 * the create-failure).
 */
export const STICKY_DIAGNOSTIC_CODES: ReadonlySet<string> = new Set([
  "EDITOR_DOCUMENT_CREATE_FAILED",
  "EDITOR_WASM_EDIT_PERSIST_FAILED",
  "EDITOR_WASM_EDIT_REJECTED",
  "EDITOR_WASM_RECONCILE_DIVERGENCE",
  "EDITOR_REVERT_FAILED"
]);

/** Merge policy for every diagnostics write: carry forward current sticky
 * entries unless the incoming write itself carries that code. */
export function mergeStickyDiagnostics(
  current: Diagnostic[],
  next: Diagnostic[]
): Diagnostic[] {
  const nextCodes = new Set(next.map((diagnostic) => diagnostic.code));
  const carried = current.filter(
    (diagnostic) =>
      STICKY_DIAGNOSTIC_CODES.has(diagnostic.code) && !nextCodes.has(diagnostic.code)
  );
  return carried.length > 0 ? [...carried, ...next] : next;
}
